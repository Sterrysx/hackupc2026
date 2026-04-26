"""Cost and availability metrics derived from event booleans.

The objective function follows ai-context/CONTEXT.md §10:
    minimize  E[per-printer annual cost]
    subject to availability >= 95%
"""
from __future__ import annotations

from typing import Mapping

import pandas as pd

from backend.simulator.schema import COMPONENT_IDS

DAYS_PER_YEAR = 365.25


def _components(components_cfg: Mapping) -> Mapping:
    return components_cfg["components"]


def compute_costs(
    events_df: pd.DataFrame,
    components_cfg: Mapping,
) -> dict:
    """Sum preventive and corrective event costs per component and overall.

    Returns per-printer annual cost so fleets of any size are comparable.
    """
    components = _components(components_cfg)
    n_days = int(events_df["day"].max() - events_df["day"].min() + 1)
    n_printers = int(events_df["printer_id"].nunique())
    years = n_days / DAYS_PER_YEAR
    norm = max(n_printers * years, 1e-9)

    preventive_total = 0.0
    corrective_total = 0.0
    n_preventive: dict[str, int] = {}
    n_corrective: dict[str, int] = {}
    for component_id in COMPONENT_IDS:
        spec = components[component_id]
        n_pm = int(events_df[f"maint_{component_id}"].sum())
        n_cm = int(events_df[f"failure_{component_id}"].sum())
        preventive_total += n_pm * float(spec["cost_preventive_eur"])
        corrective_total += n_cm * float(spec["cost_corrective_eur"])
        n_preventive[component_id] = n_pm
        n_corrective[component_id] = n_cm

    return {
        "annual_cost": (preventive_total + corrective_total) / norm,
        "preventive_cost": preventive_total / norm,
        "corrective_cost": corrective_total / norm,
        "n_preventive_per_component": n_preventive,
        "n_corrective_per_component": n_corrective,
        "horizon_days": n_days,
        "horizon_years": years,
        "n_printers": n_printers,
    }


def compute_availability(
    events_df: pd.DataFrame,
    components_cfg: Mapping,
) -> float:
    """Fleet-mean availability over the simulated horizon."""
    components = _components(components_cfg)
    n_printers = int(events_df["printer_id"].nunique())
    n_days = int(events_df["day"].max() - events_df["day"].min() + 1)
    total_days = n_days * n_printers
    if total_days <= 0:
        return 1.0

    downtime_days = 0.0
    for component_id in COMPONENT_IDS:
        spec = components[component_id]
        n_pm = int(events_df[f"maint_{component_id}"].sum())
        n_cm = int(events_df[f"failure_{component_id}"].sum())
        downtime_days += n_pm * float(spec["downtime_preventive_d"])
        downtime_days += n_cm * float(spec["downtime_corrective_d"])

    raw = (total_days - downtime_days) / total_days
    return float(min(1.0, max(0.0, raw)))


# Any infeasible trial returns a value above this floor; any feasible trial
# returns a value below it. Real per-printer annual costs are 1e5..1e7 €,
# so 1e9 keeps the two regimes strictly separated regardless of cost shape.
INFEASIBLE_FLOOR: float = 1e9


def scalar_objective(
    events_df: pd.DataFrame,
    components_cfg: Mapping,
    *,
    availability_threshold: float = 0.95,
    lambda_pen: float = 1e10,
) -> dict:
    """Single-scalar objective ready for Optuna's minimisation.

    Hard constraint: any trial below `availability_threshold` is rebased above
    `INFEASIBLE_FLOOR` so it cannot beat any feasible trial. The deficit-scaled
    penalty term still gives TPE a gradient back toward feasibility.
    """
    costs = compute_costs(events_df, components_cfg)
    availability = compute_availability(events_df, components_cfg)
    deficit = max(0.0, availability_threshold - availability)

    if deficit > 0.0:
        value = INFEASIBLE_FLOOR + lambda_pen * deficit
    else:
        value = costs["annual_cost"]

    return {
        "value": value,
        "annual_cost": costs["annual_cost"],
        "availability": availability,
        "preventive_cost": costs["preventive_cost"],
        "corrective_cost": costs["corrective_cost"],
        "deficit": deficit,
        "horizon_days": costs["horizon_days"],
        "n_printers": costs["n_printers"],
    }
