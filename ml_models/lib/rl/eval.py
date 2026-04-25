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

from ml_models.lib.env_runner import default_dates, run_with_tau
from ml_models.lib.objective import INFEASIBLE_FLOOR, scalar_objective
from sdg.generate import load_configs
from sdg.schema import COMPONENT_IDS

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
