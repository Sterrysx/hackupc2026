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
from sdg.core.simulator import run_printer
from sdg.generate import (
    END_DATE,
    START_DATE,
    build_printer_city_map,
    load_configs,
)
from sdg.schema import COMPONENT_IDS, table_from_rows


def default_dates() -> list[date]:
    return list(pd.date_range(START_DATE, END_DATE, freq="D").date)


def override_tau(
    components_cfg: Mapping[str, Any],
    tau_vector: Mapping[str, float],
) -> dict[str, Any]:
    """Return a deep copy of components_cfg with tau_nom_h overridden per component."""
    cfg = copy.deepcopy(components_cfg)
    components = cfg["components"]
    for component_id in COMPONENT_IDS:
        if component_id not in tau_vector:
            raise KeyError(f"tau_vector missing component {component_id}")
        components[component_id]["tau_nom_h"] = float(tau_vector[component_id])
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

    table = table_from_rows(rows, include_rul=False)
    return table.to_pandas()
