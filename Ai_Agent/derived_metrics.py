"""Per-component display metrics surfaced to the UI.

The Stage 1 parquet only carries generic per-component stats (`H`, `lambda`,
`tau`, `L`, `maint`, `failure`) — there are no physical sensor channels per
part (no nozzle temp, no motor vibration, no resistance reading). To make
each of the 6 components show three *visually distinctive* metrics in the
operator UI, we mix:

  • **REAL** values pulled straight from the parquet row, and
  • **DERIVED** values computed *deterministically* from the same row via
    physically-plausible formulas. They move with the live health and
    drivers — not random — so a degrading part actually looks like it is
    degrading on every metric, while still keeping the demo punch of
    component-specific units (µm, A, g, Ω, kW…).

`forecast.py` calls `compute_metrics(..., h_override=h_next)` so the 45-min
forecast tile shows the projected metric value, not the current one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

import pandas as pd

# Health bands — keep in sync with `forecast.H_*`.
_H_FULL = 1.0


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str
    # (row, sim_id, h) -> float. `h` is the health to evaluate at — current
    # for the live snapshot, projected for the 45-min forecast.
    fn: Callable[[pd.Series, str, float], float]


# ---------------------------------------------------------- value computers
#
# Each computer takes (row, sim_id, h) and returns a single float. They are
# pure functions of the row + a health override so forecast projections
# reuse the exact same arithmetic.


def _real(col: str) -> Callable[[pd.Series, str, float], float]:
    """Read a global column straight from the row (drivers, jobs)."""
    return lambda row, _sid, _h: float(row[col])


def _real_per_comp(prefix: str) -> Callable[[pd.Series, str, float], float]:
    """Read a per-component column like `lambda_C1`, `tau_C2`."""
    return lambda row, sid, _h: float(row[f"{prefix}_{sid}"])


def _blade_wear_um(row: pd.Series, _sid: str, h: float) -> float:
    # New blade ≈ 0 µm wear; failed blade ≈ 60 µm + dust amplifier.
    dust = float(row["dust_concentration"])
    return 60.0 * (_H_FULL - h) + 8.0 * dust


def _motor_current_a(row: pd.Series, _sid: str, h: float) -> float:
    # Idle ~2.4 A, climbs with load and as bearings wear.
    jobs = float(row["jobs_today"])
    return 2.4 + 0.04 * jobs + 1.5 * (_H_FULL - h)


def _vibration_g(_row: pd.Series, _sid: str, h: float) -> float:
    # Healthy spindle ~0.06 g RMS; failure ~0.6 g.
    return 0.06 + 0.55 * (_H_FULL - h)


def _nozzle_temp_c(row: pd.Series, _sid: str, h: float) -> float:
    # Setpoint ~180 °C, drifts up as plate ages and ambient rises.
    ambient = float(row["ambient_temp_c"])
    return 175.0 + 0.5 * ambient + 22.0 * (_H_FULL - h)


def _dropout_ppm(row: pd.Series, _sid: str, h: float) -> float:
    # Jet dropouts climb fast as the plate degrades; dust makes it worse.
    dust = float(row["dust_concentration"])
    return 50.0 + 1500.0 * (_H_FULL - h) + 200.0 * dust


def _resistance_ohms(_row: pd.Series, _sid: str, h: float) -> float:
    # Nominal resistor ~12 Ω; ages high as element decays.
    return 12.0 + 6.0 * (_H_FULL - h)


def _surface_temp_c(row: pd.Series, _sid: str, h: float) -> float:
    # Setpoint ~320 °C, runs hotter at high Q and as element fails.
    q = float(row["Q_demand"])
    return 320.0 + 25.0 * (_H_FULL - h) + 0.3 * q


def _power_kw(row: pd.Series, _sid: str, h: float) -> float:
    # Nominal 2.4 kW under unit Q; rises with demand and as efficiency drops.
    q = float(row["Q_demand"])
    return 2.4 + 0.6 * q + 0.4 * (_H_FULL - h)


def _skin_temp_c(row: pd.Series, _sid: str, h: float) -> float:
    # Outer skin runs ~60 °C nominal; rises as insulation degrades + ambient.
    ambient = float(row["ambient_temp_c"])
    return 60.0 + 15.0 * (_H_FULL - h) + 0.4 * (ambient - 18.0)


# ------------------------------------------------------- per-component spec
#
# Three metrics per part. `primaryMetricKey` (the headline tile) is the
# *first* entry so each component leads with its most distinctive signal.

_METRICS: Mapping[str, tuple[MetricSpec, MetricSpec, MetricSpec]] = {
    "C1": (  # recoater_blade
        MetricSpec("blade_wear_um", "Blade edge wear", "µm",   _blade_wear_um),
        MetricSpec("lambda",        "Hazard rate",     "1/h",  _real_per_comp("lambda")),
        MetricSpec("tau",           "Hours since service", "h", _real_per_comp("tau")),
    ),
    "C2": (  # recoater_motor
        MetricSpec("vibration_g",     "Vibration RMS",  "g",    _vibration_g),
        MetricSpec("motor_current_a", "Motor current",  "A",    _motor_current_a),
        MetricSpec("lambda",          "Hazard rate",    "1/h",  _real_per_comp("lambda")),
    ),
    "C3": (  # nozzle_plate
        MetricSpec("nozzle_temp_c", "Nozzle plate temp", "°C",  _nozzle_temp_c),
        MetricSpec("dropout_ppm",   "Jet dropouts",      "ppm", _dropout_ppm),
        MetricSpec("lambda",        "Hazard rate",       "1/h", _real_per_comp("lambda")),
    ),
    "C4": (  # thermal_resistor
        MetricSpec("resistance_ohms", "Element resistance", "Ω",  _resistance_ohms),
        MetricSpec("lambda",          "Hazard rate",        "1/h", _real_per_comp("lambda")),
        MetricSpec("tau",             "Hours since service", "h",  _real_per_comp("tau")),
    ),
    "C5": (  # heating_element
        MetricSpec("surface_temp_c", "Surface temp",  "°C",   _surface_temp_c),
        MetricSpec("power_kw",       "Power draw",    "kW",   _power_kw),
        MetricSpec("lambda",         "Hazard rate",   "1/h",  _real_per_comp("lambda")),
    ),
    "C6": (  # insulation_panel
        MetricSpec("skin_temp_c",  "Outer skin temp", "°C",   _skin_temp_c),
        MetricSpec("humidity_pct", "Ambient humidity", "%",   _real("humidity_pct")),
        MetricSpec("lambda",       "Hazard rate",     "1/h",  _real_per_comp("lambda")),
    ),
}


def primary_metric_key(sim_id: str) -> str:
    """Headline metric for a component — first slot in its spec."""
    return _METRICS[sim_id][0].key


def compute_metrics(
    row: pd.Series,
    sim_id: str,
    *,
    h_override: float | None = None,
) -> list[dict[str, Any]]:
    """Return three `{key,label,value,unit}` dicts for one component.

    `h_override` lets the forecast layer reuse this exact arithmetic with the
    projected health value, so the forecast tile and live tile stay in sync.
    """
    h = float(row[f"H_{sim_id}"]) if h_override is None else float(h_override)
    return [
        {
            "key":   spec.key,
            "label": spec.label,
            "value": float(spec.fn(row, sim_id, h)),
            "unit":  spec.unit,
        }
        for spec in _METRICS[sim_id]
    ]


def predicted_metrics(
    row: pd.Series,
    sim_id: str,
    h_next: float,
) -> list[dict[str, Any]]:
    """Forecast-side projection — same keys, evaluated at projected health."""
    return [
        {"key": spec.key, "value": float(spec.fn(row, sim_id, h_next))}
        for spec in _METRICS[sim_id]
    ]
