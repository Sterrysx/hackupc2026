"""Empirical diagnostic for the SDG simulator (Phase 0 / Phase 4 verification).

Drives the per-day inner loop with FIXED drivers (no weather noise, no Poisson
jobs) so the result is reproducible and only depends on the YAML calibration.
For each component, reports:

  - day of first corrective failure (H crossed 0.1)
  - mean lambda over the run
  - peak factor (which of f_ext / f_M / f_L / f_cross dominated)

Usage::

    uv run python scripts/diagnose_lifespans.py             # nominal drivers
    uv run python scripts/diagnose_lifespans.py --bad       # stress drivers
    uv run python scripts/diagnose_lifespans.py --no-maint  # disable preventive

This script is read-only against the codebase (no edits, no parquet writes).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml

from backend.simulator.core.component import Component
from backend.simulator.core.degradation import (
    compute_cross_factors,
    compute_lambda,
    validate_components_config,
    _maintenance_factor,
    _life_factor,
    _variable_product,
)
from backend.simulator.schema import COMPONENT_IDS

# --- knobs -----------------------------------------------------------------

NOMINAL_DRIVERS = {
    "T": 25.0,
    "H": 40.0,
    "c_p": 50.0,
    "Q": 1.0,
    "T_fab": 25.0,
    "T_set": 180.0,
    "T_max": 180.0,
    "v": 150.0,
    "f_d": 20.0,
    "E_d": 3.0,
    "P_B": 0.0,
    "phi_R": 0.20,
    "layer_thickness_um": 50.0,
}

BAD_DRIVERS = {
    **NOMINAL_DRIVERS,
    "T": 35.0,
    "H": 70.0,
    "c_p": 150.0,
    "Q": 1.5,
    "T_fab": 30.0,
    "T_set": 200.0,
    "T_max": 200.0,
}

HOURS_PER_DAY = 4.0  # mean of Gamma(2, 2) used by the simulator

MAX_DH_PER_DAY = 1.2


# --- helpers ---------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@dataclass
class CompTrace:
    component_id: str
    first_failure_day: int | None = None
    lambda_samples: list[float] = field(default_factory=list)
    f_ext_peak: float = 1.0
    f_M_peak: float = 1.0
    f_L_peak: float = 1.0
    f_cross_peak: float = 1.0
    f_int_vars_peak: float = 1.0


def _factor_breakdown(comp: Component, drivers: dict[str, float], f_cross: float) -> dict[str, float]:
    spec = comp.spec
    f_ext = _variable_product(spec.get("ext_vars", ()), drivers)
    f_M = _maintenance_factor(comp)
    f_L = _life_factor(comp)
    f_int_vars = _variable_product(spec.get("int_vars", ()), drivers)
    return {
        "f_ext": f_ext,
        "f_M": f_M,
        "f_L": f_L,
        "f_int_vars": f_int_vars,
        "f_cross": float(f_cross),
    }


def run_diagnostic(
    drivers_in: dict[str, float],
    *,
    days: int = 365,
    enable_maintenance: bool = True,
    enable_cross_cascade: bool = True,
    enable_safety_pair: bool = True,
) -> dict[str, CompTrace]:
    components_cfg = _load_yaml(REPO_ROOT / "sdg" / "config" / "components.yaml")
    couplings_cfg = _load_yaml(REPO_ROOT / "sdg" / "config" / "couplings.yaml")
    validate_components_config(components_cfg)

    process = components_cfg["process_constants"]
    counters: dict[str, int] = {"N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0}
    components = {
        cid: Component(
            id=cid,
            spec=components_cfg["components"][cid],
            counters=counters,
            alpha=1.0,
        )
        for cid in COMPONENT_IDS
    }
    traces = {cid: CompTrace(component_id=cid) for cid in COMPONENT_IDS}

    for day in range(days):
        # (1) Counters: deterministic accumulation matching simulator's mean rate.
        hours = HOURS_PER_DAY  # deterministic, matches Gamma(2,2) mean
        counters["N_f"] += int(hours * float(process["fires_per_hour"]))
        counters["N_c"] += int(hours * float(process["layers_per_hour"]))
        counters["N_TC"] += int(hours / float(process["hours_per_job"]))
        counters["N_on"] += max(1, int(round(hours * 0.05)))

        # (2) Cross-cascades (optionally disabled to isolate per-comp degradation).
        if enable_cross_cascade:
            c1_h = max(0.0, min(1.0, components["C1"].H))
            c6_h = max(0.0, min(1.0, components["C6"].H))
            c_p = float(drivers_in["c_p"]) * (1.0 + (1.0 - c1_h) ** 2)
            q_demand = float(drivers_in["Q"]) * (1.0 + (1.0 - c6_h) ** 2)
        else:
            c_p = float(drivers_in["c_p"])
            q_demand = float(drivers_in["Q"])

        drivers = {
            **drivers_in,
            "c_p": c_p,
            "Q": q_demand,
            "N_f": float(counters["N_f"]),
            "N_c": float(counters["N_c"]),
            "N_iv": float(counters["N_c"]),
            "N_TC": float(counters["N_TC"]),
            "N_on": float(counters["N_on"]),
        }

        cross_factors = (
            compute_cross_factors(components, couplings_cfg)
            if enable_cross_cascade
            else {cid: 1.0 for cid in COMPONENT_IDS}
        )

        for cid in COMPONENT_IDS:
            comp = components[cid]
            lam = compute_lambda(comp, drivers, cross_factors[cid])
            traces[cid].lambda_samples.append(lam)
            br = _factor_breakdown(comp, drivers, cross_factors[cid])
            traces[cid].f_ext_peak = max(traces[cid].f_ext_peak, br["f_ext"])
            traces[cid].f_M_peak = max(traces[cid].f_M_peak, br["f_M"])
            traces[cid].f_L_peak = max(traces[cid].f_L_peak, br["f_L"])
            traces[cid].f_cross_peak = max(traces[cid].f_cross_peak, br["f_cross"])
            traces[cid].f_int_vars_peak = max(traces[cid].f_int_vars_peak, br["f_int_vars"])

            comp.apply_degradation(min(lam, MAX_DH_PER_DAY))

        # (3) Maintenance + corrective + safety-pair, all optional.
        for cid in COMPONENT_IDS:
            comp = components[cid]
            if enable_maintenance and comp.tau_mant_d >= float(comp.spec["tau_nom_d"]):
                comp.apply_preventive()
            if comp.H <= 0.1:
                if traces[cid].first_failure_day is None:
                    traces[cid].first_failure_day = day
                comp.apply_corrective()

        if enable_safety_pair and components["C5"].H < 0.4 and components["C6"].H < 0.4:
            target = "C5" if components["C5"].H <= components["C6"].H else "C6"
            if traces[target].first_failure_day is None:
                traces[target].first_failure_day = day
            components[target].apply_corrective()

        for comp in components.values():
            comp.advance_time(1.0)

    return traces


def _l_nom_days(components_cfg: dict, cid: str) -> float:
    return float(components_cfg["components"][cid]["L_nom_d"])


def report(traces: dict[str, CompTrace], scenario_name: str) -> None:
    components_cfg = _load_yaml(REPO_ROOT / "sdg" / "config" / "components.yaml")
    name_map = {
        "C1": "Recoater blade",
        "C2": "Recoater motor",
        "C3": "Nozzle plate (printhead)",
        "C4": "Thermal resistor",
        "C5": "Heating element",
        "C6": "Insulation panel",
    }

    print(f"\n=== Diagnostic: {scenario_name} ===")
    print(
        f"{'cid':<4} {'name':<28} {'L_nom (d)':>10} {'1st fail (d)':>12} "
        f"{'mean lam/d':>11} {'f_ext':>7} {'f_M':>7} {'f_L':>7} {'f_int_v':>9} {'f_cross':>8}"
    )
    print("-" * 116)
    for cid in COMPONENT_IDS:
        t = traces[cid]
        l_nom = _l_nom_days(components_cfg, cid)
        first = t.first_failure_day if t.first_failure_day is not None else -1
        mean_lam = sum(t.lambda_samples) / max(1, len(t.lambda_samples))
        print(
            f"{cid:<4} {name_map[cid]:<28} {l_nom:>10.1f} "
            f"{first:>12} {mean_lam:>11.4g} "
            f"{t.f_ext_peak:>7.2f} {t.f_M_peak:>7.2f} {t.f_L_peak:>7.2f} "
            f"{t.f_int_vars_peak:>9.2f} {t.f_cross_peak:>8.2f}"
        )

    # Health summary at end
    healthy = [cid for cid in COMPONENT_IDS if traces[cid].first_failure_day is None]
    print(f"\nNo failures within window: {', '.join(healthy) if healthy else '(none)'}")

    # Calibration check: how close is each first-failure day to the YAML target?
    print("\nCalibration vs first_failure_target_d (under nominal drivers, target should match):")
    for cid in COMPONENT_IDS:
        target = components_cfg["components"][cid].get("first_failure_target_d")
        actual = traces[cid].first_failure_day
        if target is None:
            note = "n/a (no target)"
        elif actual is None:
            note = f"target={target:.1f}, actual=NEVER (window too short or drivers too soft)"
        else:
            note = f"target={target:.1f}, actual={actual}, ratio={actual / float(target):.2f}"
        print(f"  {cid}: {note}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose component lifespans.")
    parser.add_argument("--bad", action="store_true", help="Use stress drivers")
    parser.add_argument("--no-maint", action="store_true", help="Disable preventive maintenance")
    parser.add_argument("--no-cascade", action="store_true", help="Disable cross-coupling cascades")
    parser.add_argument("--no-safety", action="store_true", help="Disable C5/C6 forced safety rule")
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()

    drivers = BAD_DRIVERS if args.bad else NOMINAL_DRIVERS
    scenario = "BAD drivers (T=35, H=70, c_p=150, Q=1.5)" if args.bad else "NOMINAL drivers (T=25, H=40, c_p=50, Q=1)"

    flags = []
    if args.no_maint: flags.append("no-maint")
    if args.no_cascade: flags.append("no-cascade")
    if args.no_safety: flags.append("no-safety")
    if flags:
        scenario += f"  [flags: {', '.join(flags)}]"

    traces = run_diagnostic(
        drivers,
        days=args.days,
        enable_maintenance=not args.no_maint,
        enable_cross_cascade=not args.no_cascade,
        enable_safety_pair=not args.no_safety,
    )
    report(traces, scenario)


if __name__ == "__main__":
    main()
