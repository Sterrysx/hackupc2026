"""Run sdg.simulator.run_printer with a custom maintenance-interval vector.

Used both by Stage 01 (direct search) and by Stage 02 to generate labelled
training data under varied τ schedules. Determinism per printer is preserved
by reusing the np.random.default_rng(printer_id) pattern from sdg.generate.
"""
from __future__ import annotations

import copy
from datetime import date
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from sdg.core.degradation import validate_components_config
from sdg.core.simulator import PrinterStepper, run_printer
from sdg.generate import (
    END_DATE,
    START_DATE,
    build_printer_city_map,
    load_configs,
)
from sdg.schema import COMPONENT_IDS


def default_dates() -> list[date]:
    return list(pd.date_range(START_DATE, END_DATE, freq="D").date)


def override_tau(
    components_cfg: Mapping[str, Any],
    tau_vector: Mapping[str, float],
) -> dict[str, Any]:
    """Return a deep copy of components_cfg with tau_nom_d overridden per component."""
    cfg = copy.deepcopy(components_cfg)
    components = cfg["components"]
    for component_id in COMPONENT_IDS:
        if component_id not in tau_vector:
            raise KeyError(f"tau_vector missing component {component_id}")
        components[component_id]["tau_nom_d"] = float(tau_vector[component_id])
    validate_components_config(cfg)
    return cfg


def run_with_tau(
    tau_vector: Mapping[str, float],
    *,
    printer_ids: Iterable[int],
    dates: list[date] | None = None,
    components_cfg: Mapping[str, Any] | None = None,
    couplings_cfg: Mapping[str, Any] | None = None,
    cities_cfg: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Simulate the requested printers under a custom τ vector and return rows."""
    if components_cfg is None or couplings_cfg is None or cities_cfg is None:
        c_cfg, k_cfg, city_cfg = load_configs()
        components_cfg = components_cfg or c_cfg
        couplings_cfg = couplings_cfg or k_cfg
        cities_cfg = cities_cfg or city_cfg

    cfg = override_tau(components_cfg, tau_vector)
    if dates is None:
        dates = default_dates()
    cities = list(cities_cfg["cities"])
    printer_city_map = build_printer_city_map(cities)

    rows: list[dict] = []
    for printer_id in printer_ids:
        pid = int(printer_id)
        rng = np.random.default_rng(pid)
        monthly_jobs = float(rng.uniform(8.0, 15.0))
        alpha_values = rng.uniform(0.7, 1.3, size=len(COMPONENT_IDS))
        alphas = dict(zip(COMPONENT_IDS, alpha_values, strict=True))
        rows.extend(
            run_printer(
                printer_id=pid,
                city_profile=printer_city_map[pid],
                dates=dates,
                components_cfg=cfg,
                couplings_cfg=couplings_cfg,
                rng=rng,
                monthly_jobs=monthly_jobs,
                alphas=alphas,
            )
        )

    # Skip the Arrow schema round-trip here; trial loops only read a handful of
    # columns and consumers that need a validated parquet (e.g. policy_runs
    # generation) call sdg.schema.table_from_dataframe themselves.
    return pd.DataFrame.from_records(rows)


def make_printer_stepper(
    printer_id: int,
    *,
    components_cfg: Mapping[str, Any] | None = None,
    couplings_cfg: Mapping[str, Any] | None = None,
    cities_cfg: Mapping[str, Any] | None = None,
    tau_vector: Mapping[str, float] | None = None,
) -> PrinterStepper:
    """Build a :class:`PrinterStepper` matching ``run_with_tau`` semantics.

    Mirrors the per-printer RNG / monthly_jobs / alpha sampling used in
    ``run_with_tau`` so a stepper-driven rollout is reproducible and
    comparable to the batch interface (apart from the agent's actions).

    If ``tau_vector`` is supplied the underlying ``components_cfg`` has its
    ``tau_nom_d`` per component overridden — useful when you want the
    fallback tau-rule (when the agent passes ``agent_action=None``) to match a
    specific schedule. For the per-tick RL env, ``agent_action`` is always
    provided so ``tau_vector`` only affects the tau-based feature on the row
    output (``tau_Ci``), not policy decisions.
    """
    if components_cfg is None or couplings_cfg is None or cities_cfg is None:
        c_cfg, k_cfg, city_cfg = load_configs()
        components_cfg = components_cfg or c_cfg
        couplings_cfg = couplings_cfg or k_cfg
        cities_cfg = cities_cfg or city_cfg
    cfg = override_tau(components_cfg, tau_vector) if tau_vector is not None else components_cfg

    cities = list(cities_cfg["cities"])
    printer_city_map = build_printer_city_map(cities)

    pid = int(printer_id)
    rng = np.random.default_rng(pid)
    monthly_jobs = float(rng.uniform(8.0, 15.0))
    alpha_values = rng.uniform(0.7, 1.3, size=len(COMPONENT_IDS))
    alphas = dict(zip(COMPONENT_IDS, alpha_values, strict=True))

    return PrinterStepper(
        printer_id=pid,
        city_profile=printer_city_map[pid],
        components_cfg=cfg,
        couplings_cfg=couplings_cfg,
        rng=rng,
        monthly_jobs=monthly_jobs,
        alphas=alphas,
    )


def rollout_with_agent(
    printer_id: int,
    *,
    dates: list[date] | None = None,
    agent_fn,
    components_cfg: Mapping[str, Any] | None = None,
    couplings_cfg: Mapping[str, Any] | None = None,
    cities_cfg: Mapping[str, Any] | None = None,
    tau_vector: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Drive a single printer through its full horizon with a per-day agent.

    ``agent_fn(row_state) -> Mapping[str, bool]`` is called *before* each step
    using the previous tick's row dict (or ``None`` on the first tick), and
    must return the per-component preventive-maintenance decision for the
    upcoming day.

    Useful for batch evaluation of a learned per-tick policy outside the
    gymnasium env — e.g. test-set scoring without going through SB3's
    ``predict`` API.
    """
    if dates is None:
        dates = default_dates()
    stepper = make_printer_stepper(
        printer_id,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
        tau_vector=tau_vector,
    )
    rows: list[dict] = []
    last_row: dict | None = None
    for current_date in dates:
        action = agent_fn(last_row)
        row = stepper.step(current_date, agent_action=action)
        rows.append(row)
        last_row = row
    return pd.DataFrame.from_records(rows)
