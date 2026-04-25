"""Unit tests for the cost / availability scoring helpers."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from ml_models.lib.objective import (
    compute_availability,
    compute_costs,
    scalar_objective,
)
from sdg.generate import load_configs
from sdg.schema import COMPONENT_IDS


def _empty_events_df(n_printers: int = 1, n_days: int = 365) -> pd.DataFrame:
    rows = []
    for printer_id in range(n_printers):
        for day in range(n_days):
            row = {"printer_id": printer_id, "day": day}
            for component_id in COMPONENT_IDS:
                row[f"maint_{component_id}"] = False
                row[f"failure_{component_id}"] = False
            rows.append(row)
    return pd.DataFrame(rows)


def test_zero_events_yields_zero_cost_and_full_availability() -> None:
    components_cfg, _, _ = load_configs()
    df = _empty_events_df()
    costs = compute_costs(df, components_cfg)
    assert costs["annual_cost"] == pytest.approx(0.0)
    assert costs["preventive_cost"] == pytest.approx(0.0)
    assert costs["corrective_cost"] == pytest.approx(0.0)
    assert compute_availability(df, components_cfg) == pytest.approx(1.0)


def test_single_preventive_event_uses_components_yaml_cost() -> None:
    components_cfg, _, _ = load_configs()
    df = _empty_events_df()
    df.loc[df["day"] == 100, "maint_C1"] = True

    costs = compute_costs(df, components_cfg)
    spec = components_cfg["components"]["C1"]
    expected_yearly = float(spec["cost_preventive_eur"]) / costs["horizon_years"]
    assert costs["preventive_cost"] == pytest.approx(expected_yearly)
    assert costs["corrective_cost"] == pytest.approx(0.0)
    assert costs["n_preventive_per_component"]["C1"] == 1


def test_single_corrective_event_charges_corrective_cost_and_downtime() -> None:
    components_cfg, _, _ = load_configs()
    df = _empty_events_df()
    df.loc[df["day"] == 50, "failure_C3"] = True

    costs = compute_costs(df, components_cfg)
    spec = components_cfg["components"]["C3"]
    expected_yearly = float(spec["cost_corrective_eur"]) / costs["horizon_years"]
    assert costs["corrective_cost"] == pytest.approx(expected_yearly)

    availability = compute_availability(df, components_cfg)
    n_days = costs["horizon_days"]
    expected_availability = (n_days * 24 - float(spec["downtime_corrective_h"])) / (n_days * 24)
    assert availability == pytest.approx(expected_availability)


def test_scalar_objective_penalises_only_when_below_threshold() -> None:
    components_cfg, _, _ = load_configs()
    df = _empty_events_df(n_printers=1, n_days=10)

    no_penalty = scalar_objective(df, components_cfg, availability_threshold=0.95)
    assert no_penalty["deficit"] == pytest.approx(0.0)
    assert no_penalty["value"] == pytest.approx(no_penalty["annual_cost"])

    df.loc[df["day"] == 0, "failure_C2"] = True
    spec = components_cfg["components"]["C2"]
    n_days = 10
    forced_availability = (n_days * 24 - float(spec["downtime_corrective_h"])) / (n_days * 24)
    assert forced_availability < 0.95

    penalised = scalar_objective(
        df, components_cfg, availability_threshold=0.95, lambda_pen=1_000_000.0
    )
    assert penalised["availability"] == pytest.approx(forced_availability)
    assert penalised["deficit"] > 0.0
    assert penalised["value"] > penalised["annual_cost"]


def test_per_printer_normalisation_is_independent_of_fleet_size() -> None:
    components_cfg, _, _ = load_configs()
    one = _empty_events_df(n_printers=1, n_days=730)
    one.loc[(one["day"] == 100), "maint_C1"] = True

    many = pd.concat(
        [
            _empty_events_df(n_printers=1, n_days=730).assign(printer_id=p)
            for p in range(5)
        ],
        ignore_index=True,
    )
    for printer_id in range(5):
        many.loc[(many["printer_id"] == printer_id) & (many["day"] == 100), "maint_C1"] = True

    one_costs = compute_costs(one, components_cfg)
    many_costs = compute_costs(many, components_cfg)
    assert math.isclose(one_costs["annual_cost"], many_costs["annual_cost"], rel_tol=1e-9)
