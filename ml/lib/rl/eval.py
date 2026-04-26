"""Test-set evaluation for Stage 03 and apples-to-apples comparison vs Stages 01 & 02.

All three stages are scored with the SAME ``scalar_objective`` on the SAME
test printers, so the resulting numbers are directly comparable. Stage 03's
edge is per-printer τ — its ``per_printer_tau_test.csv`` will show a
6-column τ matrix that varies row-to-row, while Stages 01 and 02 produce a
single τ replicated across rows.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from stable_baselines3 import PPO

from ml.lib.env_runner import default_dates, run_with_tau
from ml.lib.objective import INFEASIBLE_FLOOR, scalar_objective
from backend.simulator.generate import load_configs
from backend.simulator.schema import COMPONENT_IDS

from .encoder_loader import SSLEncoderBundle, load_ssl_encoder
from .gym_env import MaintenanceBanditEnv, action_to_tau


def _ensure_configs(
    components_cfg: Mapping[str, Any] | None,
    couplings_cfg: Mapping[str, Any] | None,
    cities_cfg: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    if components_cfg is None or couplings_cfg is None or cities_cfg is None:
        c, k, ci = load_configs()
        components_cfg = components_cfg or c
        couplings_cfg = couplings_cfg or k
        cities_cfg = cities_cfg or ci
    return components_cfg, couplings_cfg, cities_cfg


def evaluate_constant_tau(
    tau_vector: Mapping[str, float],
    *,
    printer_ids: Sequence[int],
    dates: list[date] | None = None,
    components_cfg: Mapping[str, Any] | None = None,
    couplings_cfg: Mapping[str, Any] | None = None,
    cities_cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Score a single fleet-wide τ on a printer set — matches Stage 01/02 protocol."""
    components_cfg, couplings_cfg, cities_cfg = _ensure_configs(
        components_cfg, couplings_cfg, cities_cfg
    )
    if dates is None:
        dates = default_dates()
    events = run_with_tau(
        tau_vector,
        printer_ids=list(printer_ids),
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
    )
    return dict(scalar_objective(events, components_cfg))


def evaluate_per_printer_policy(
    model: PPO,
    *,
    printer_ids: Sequence[int],
    encoder_bundle: SSLEncoderBundle | None = None,
    dates: list[date] | None = None,
    components_cfg: Mapping[str, Any] | None = None,
    couplings_cfg: Mapping[str, Any] | None = None,
    cities_cfg: Mapping[str, Any] | None = None,
    deterministic: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run an SB3 policy on each printer to get per-printer τ + fleet KPIs.

    The fleet KPI is computed by running ALL chosen-τ vectors through the
    simulator in one shot (one printer per τ via ``run_with_tau``), so the
    resulting ``annual_cost`` is normalised exactly like Stages 01 and 02.

    Returns
    -------
    per_printer_df, fleet_kpis
        ``per_printer_df`` has one row per printer with columns:
        ``printer_id, tau_C1..tau_C6, annual_cost, availability, deficit, value``.
        ``fleet_kpis`` has the standard ``scalar_objective`` keys computed
        over the concatenated event log.
    """
    components_cfg, couplings_cfg, cities_cfg = _ensure_configs(
        components_cfg, couplings_cfg, cities_cfg
    )
    if dates is None:
        dates = default_dates()
    if encoder_bundle is None:
        encoder_bundle = load_ssl_encoder()

    env = MaintenanceBanditEnv(
        printer_ids=list(printer_ids),
        encoder_bundle=encoder_bundle,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
        dates=dates,
    )

    rows: list[dict[str, Any]] = []
    fleet_event_frames: list[pd.DataFrame] = []
    for printer_id in env.printer_ids:
        obs = env.get_observation_for(printer_id)
        action, _ = model.predict(obs, deterministic=deterministic)
        tau_vector = action_to_tau(np.asarray(action, dtype=np.float32))
        events = run_with_tau(
            tau_vector,
            printer_ids=[printer_id],
            dates=dates,
            components_cfg=components_cfg,
            couplings_cfg=couplings_cfg,
            cities_cfg=cities_cfg,
        )
        per_score = scalar_objective(events, components_cfg)
        row: dict[str, Any] = {"printer_id": int(printer_id)}
        for component_id in COMPONENT_IDS:
            row[f"tau_{component_id}"] = float(tau_vector[component_id])
        row["annual_cost"] = float(per_score["annual_cost"])
        row["availability"] = float(per_score["availability"])
        row["deficit"] = float(per_score["deficit"])
        row["value"] = float(per_score["value"])
        rows.append(row)
        fleet_event_frames.append(events)

    per_printer_df = pd.DataFrame(rows)
    fleet_events = pd.concat(fleet_event_frames, ignore_index=True)
    fleet_kpis = dict(scalar_objective(fleet_events, components_cfg))
    return per_printer_df, fleet_kpis


def kpi_comparison_table(
    *,
    test_printers: Sequence[int],
    stage_definitions: Iterable[tuple[str, dict[str, float] | None, str]],
    per_printer_dfs: Mapping[str, pd.DataFrame],
    fleet_kpis: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """Format a side-by-side table of stage KPIs for the report.

    Parameters
    ----------
    test_printers
        Identifies the eval printer set in the table caption.
    stage_definitions
        Iterable of ``(stage_name, optional_constant_tau, description)``.
    per_printer_dfs
        Map ``stage_name -> per_printer DataFrame`` (output of
        ``evaluate_per_printer_policy`` for stage 03; built per-row from a
        constant τ for stages 01/02).
    fleet_kpis
        Map ``stage_name -> fleet KPI dict`` from ``scalar_objective``.
    """
    rows = []
    for stage_name, constant_tau, description in stage_definitions:
        kpi = fleet_kpis[stage_name]
        per_df = per_printer_dfs[stage_name]
        feasible_pct = 100.0 * (per_df["availability"] >= 0.95).mean()
        rows.append(
            {
                "stage": stage_name,
                "policy_class": "constant τ" if constant_tau is not None else "per-printer τ",
                "description": description,
                "fleet_value": float(kpi["value"]),
                "fleet_annual_cost": float(kpi["annual_cost"]),
                "fleet_availability": float(kpi["availability"]),
                "fleet_deficit": float(kpi["deficit"]),
                "feasible_printer_pct": feasible_pct,
                "infeasible_floor_breached": bool(float(kpi["value"]) >= INFEASIBLE_FLOOR),
                "n_test_printers": len(test_printers),
            }
        )
    return pd.DataFrame(rows)


def per_printer_table_for_constant_tau(
    tau_vector: Mapping[str, float],
    *,
    printer_ids: Sequence[int],
    dates: list[date] | None = None,
    components_cfg: Mapping[str, Any] | None = None,
    couplings_cfg: Mapping[str, Any] | None = None,
    cities_cfg: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Build a per-printer KPI DataFrame for Stages 01/02's constant-τ output."""
    components_cfg, couplings_cfg, cities_cfg = _ensure_configs(
        components_cfg, couplings_cfg, cities_cfg
    )
    if dates is None:
        dates = default_dates()
    rows = []
    for printer_id in printer_ids:
        events = run_with_tau(
            tau_vector,
            printer_ids=[printer_id],
            dates=dates,
            components_cfg=components_cfg,
            couplings_cfg=couplings_cfg,
            cities_cfg=cities_cfg,
        )
        score = scalar_objective(events, components_cfg)
        row: dict[str, Any] = {"printer_id": int(printer_id)}
        for component_id in COMPONENT_IDS:
            row[f"tau_{component_id}"] = float(tau_vector[component_id])
        row["annual_cost"] = float(score["annual_cost"])
        row["availability"] = float(score["availability"])
        row["deficit"] = float(score["deficit"])
        row["value"] = float(score["value"])
        rows.append(row)
    return pd.DataFrame(rows)


def load_ppo(model_path: str | Path) -> PPO:
    """Load a saved SB3 PPO model from disk (zip)."""
    return PPO.load(str(model_path))


def bootstrap_fleet_ci(
    per_printer_df: pd.DataFrame,
    *,
    metric: str = "annual_cost",
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    rng_seed: int = 0,
    availability_threshold: float = 0.95,
) -> dict[str, float]:
    """Bootstrap CI on a fleet-level metric by resampling printers.

    Test sets at the printer level are tiny (15 printers); the
    point-estimate of fleet ``annual_cost`` or ``availability`` carries
    real sampling noise. This function resamples printers with replacement
    ``n_resamples`` times and returns the empirical CI on:

    - ``metric ∈ {"annual_cost", "availability"}`` directly.
    - ``"value"`` — the Stage 01/02 scalar objective (uses ``INFEASIBLE_FLOOR``
      when bootstrap availability < threshold, otherwise the bootstrap mean cost).

    Parameters
    ----------
    per_printer_df
        DataFrame with at least ``annual_cost`` and ``availability`` columns,
        one row per printer (output of ``evaluate_per_printer_policy``).
    metric
        ``"annual_cost"``, ``"availability"``, or ``"value"``.
    n_resamples
        Number of bootstrap resamples (10k is plenty for 15-row tables).
    confidence
        e.g. 0.95 for a 95 % CI.
    rng_seed
        For reproducibility.

    Returns
    -------
    dict with keys ``mean``, ``lo``, ``hi``, ``se``, ``n_printers``,
    ``n_resamples``, ``metric``, ``confidence``.
    """
    if metric not in {"annual_cost", "availability", "value"}:
        raise ValueError(f"unsupported metric: {metric}")
    if "annual_cost" not in per_printer_df or "availability" not in per_printer_df:
        raise KeyError("per_printer_df must have annual_cost and availability columns")
    n = int(len(per_printer_df))
    if n == 0:
        raise ValueError("per_printer_df is empty")
    rng = np.random.default_rng(int(rng_seed))
    cost_arr = per_printer_df["annual_cost"].to_numpy(dtype=np.float64)
    avail_arr = per_printer_df["availability"].to_numpy(dtype=np.float64)

    samples = np.empty(int(n_resamples), dtype=np.float64)
    for i in range(int(n_resamples)):
        idx = rng.integers(0, n, size=n)
        c = float(cost_arr[idx].mean())
        a = float(avail_arr[idx].mean())
        if metric == "annual_cost":
            samples[i] = c
        elif metric == "availability":
            samples[i] = a
        else:  # value
            deficit = max(0.0, float(availability_threshold) - a)
            samples[i] = (INFEASIBLE_FLOOR + 1e10 * deficit) if deficit > 0 else c

    alpha = (1.0 - float(confidence)) / 2.0
    lo = float(np.quantile(samples, alpha))
    hi = float(np.quantile(samples, 1.0 - alpha))
    return {
        "mean": float(samples.mean()),
        "lo": lo,
        "hi": hi,
        "se": float(samples.std(ddof=1)) if len(samples) > 1 else 0.0,
        "n_printers": n,
        "n_resamples": int(n_resamples),
        "metric": metric,
        "confidence": float(confidence),
    }


def kpi_comparison_table_with_ci(
    *,
    test_printers: Sequence[int],
    stage_definitions: Iterable[tuple[str, dict[str, float] | None, str]],
    per_printer_dfs: Mapping[str, pd.DataFrame],
    fleet_kpis: Mapping[str, Mapping[str, Any]],
    n_resamples: int = 10_000,
    confidence: float = 0.95,
    rng_seed: int = 0,
) -> pd.DataFrame:
    """``kpi_comparison_table`` extended with bootstrap CIs on cost and value.

    Adds ``annual_cost_lo``, ``annual_cost_hi``, ``value_lo``, ``value_hi``
    columns so claims like "Stage 03 strictly beats Stage 02" can be backed
    by non-overlapping CIs rather than naked point estimates.
    """
    base = kpi_comparison_table(
        test_printers=test_printers,
        stage_definitions=stage_definitions,
        per_printer_dfs=per_printer_dfs,
        fleet_kpis=fleet_kpis,
    )
    cost_lo, cost_hi = [], []
    value_lo, value_hi = [], []
    avail_lo, avail_hi = [], []
    for _, row in base.iterrows():
        per_df = per_printer_dfs[row["stage"]]
        ci_cost = bootstrap_fleet_ci(per_df, metric="annual_cost",
                                     n_resamples=n_resamples, confidence=confidence,
                                     rng_seed=rng_seed)
        ci_value = bootstrap_fleet_ci(per_df, metric="value",
                                      n_resamples=n_resamples, confidence=confidence,
                                      rng_seed=rng_seed)
        ci_avail = bootstrap_fleet_ci(per_df, metric="availability",
                                      n_resamples=n_resamples, confidence=confidence,
                                      rng_seed=rng_seed)
        cost_lo.append(ci_cost["lo"]); cost_hi.append(ci_cost["hi"])
        value_lo.append(ci_value["lo"]); value_hi.append(ci_value["hi"])
        avail_lo.append(ci_avail["lo"]); avail_hi.append(ci_avail["hi"])
    base["annual_cost_lo"] = cost_lo
    base["annual_cost_hi"] = cost_hi
    base["fleet_value_lo"] = value_lo
    base["fleet_value_hi"] = value_hi
    base["fleet_availability_lo"] = avail_lo
    base["fleet_availability_hi"] = avail_hi
    return base


def evaluate_per_tick_per_printer(
    model_or_ensemble,
    *,
    printer_ids: Sequence[int],
    dates: list[date] | None = None,
    components_cfg: Mapping[str, Any] | None = None,
    couplings_cfg: Mapping[str, Any] | None = None,
    cities_cfg: Mapping[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Per-printer evaluation for a per-tick policy (or ensemble).

    ``model_or_ensemble`` must implement ``.predict(obs, deterministic=True)``
    returning ``(action, _)`` — both ``stable_baselines3.PPO`` and the
    ``EnsemblePolicy`` from ``recurrent_trainer.py`` qualify.

    Returns a per-printer DataFrame matching the schema produced by
    ``evaluate_per_printer_policy`` (sans constant τ columns since per-tick
    policies don't emit a fixed τ — they emit one decision per day per
    component).
    """
    from .per_tick_env import MaintenancePerTickEnv

    components_cfg, couplings_cfg, cities_cfg = _ensure_configs(
        components_cfg, couplings_cfg, cities_cfg
    )
    if dates is None:
        dates = default_dates()
    rows: list[dict[str, Any]] = []
    env = MaintenancePerTickEnv(
        printer_ids=list(printer_ids),
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
        dates=dates,
    )
    n_pm_per_component: dict[int, dict[str, int]] = {}
    n_cm_per_component: dict[int, dict[str, int]] = {}
    for printer_id in printer_ids:
        obs, _ = env.reset(seed=int(printer_id), options={"printer_id": int(printer_id)})
        terminated = False
        truncated = False
        info: dict[str, Any] = {}
        n_pm = {c: 0 for c in COMPONENT_IDS}
        n_cm = {c: 0 for c in COMPONENT_IDS}
        while not (terminated or truncated):
            action, _ = model_or_ensemble.predict(obs, deterministic=True)
            obs, _r, terminated, truncated, info = env.step(action)
            row = info.get("row", {})
            for component_id in COMPONENT_IDS:
                if bool(row.get(f"maint_{component_id}", False)):
                    n_pm[component_id] += 1
                if bool(row.get(f"failure_{component_id}", False)):
                    n_cm[component_id] += 1
        summary = info.get("episode_summary", {})
        rows.append(
            {
                "printer_id": int(printer_id),
                "annual_cost": float(summary.get("annual_cost", float("nan"))),
                "availability": float(summary.get("availability", float("nan"))),
                "deficit": float(summary.get("deficit", 0.0)),
                "n_preventive": int(summary.get("n_preventive", 0)),
                "n_corrective": int(summary.get("n_corrective", 0)),
                **{f"n_pm_{c}": int(n_pm[c]) for c in COMPONENT_IDS},
                **{f"n_cm_{c}": int(n_cm[c]) for c in COMPONENT_IDS},
            }
        )
        n_pm_per_component[int(printer_id)] = n_pm
        n_cm_per_component[int(printer_id)] = n_cm
    per_df = pd.DataFrame(rows)
    annual_cost = float(per_df["annual_cost"].mean())
    availability = float(per_df["availability"].mean())
    deficit = max(0.0, 0.95 - availability)
    if deficit > 0.0:
        value = float(INFEASIBLE_FLOOR + 1e10 * deficit)
    else:
        value = float(annual_cost)
    fleet = {
        "value": value,
        "annual_cost": annual_cost,
        "availability": availability,
        "deficit": deficit,
        "horizon_days": int(len(dates)),
        "n_printers": int(len(per_df)),
    }
    return per_df, fleet
