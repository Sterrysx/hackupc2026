"""Unit tests for the cost / availability scoring helpers."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from ml.lib.objective import (
    INFEASIBLE_FLOOR,
    compute_availability,
    compute_costs,
    scalar_objective,
)
from backend.simulator.generate import load_configs
from backend.simulator.schema import COMPONENT_IDS


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
    expected_availability = (n_days - float(spec["downtime_corrective_d"])) / n_days
    assert availability == pytest.approx(expected_availability)


def test_scalar_objective_returns_cost_when_feasible() -> None:
    components_cfg, _, _ = load_configs()
    df = _empty_events_df(n_printers=1, n_days=10)

    score = scalar_objective(df, components_cfg, availability_threshold=0.95)
    assert score["deficit"] == pytest.approx(0.0)
    assert score["value"] == pytest.approx(score["annual_cost"])
    assert score["value"] < INFEASIBLE_FLOOR


def test_scalar_objective_jumps_above_floor_when_infeasible() -> None:
    components_cfg, _, _ = load_configs()
    df = _empty_events_df(n_printers=1, n_days=10)
    df.loc[df["day"] == 0, "failure_C2"] = True

    spec = components_cfg["components"]["C2"]
    n_days = 10
    forced_availability = (n_days - float(spec["downtime_corrective_d"])) / n_days
    assert forced_availability < 0.95

    penalised = scalar_objective(df, components_cfg, availability_threshold=0.95)
    assert penalised["availability"] == pytest.approx(forced_availability)
    assert penalised["deficit"] > 0.0
    assert penalised["value"] >= INFEASIBLE_FLOOR
    assert penalised["value"] > penalised["annual_cost"]


def test_availability_is_clamped_to_zero_when_downtime_exceeds_horizon() -> None:
    components_cfg, _, _ = load_configs()
    # Force every day to be a corrective on every component over 1 printer × 10 days.
    df = _empty_events_df(n_printers=1, n_days=10)
    for component_id in COMPONENT_IDS:
        df[f"failure_{component_id}"] = True

    availability = compute_availability(df, components_cfg)
    assert availability == pytest.approx(0.0)
    assert 0.0 <= availability <= 1.0


def test_infeasible_trial_value_dominates_any_feasible_value() -> None:
    components_cfg, _, _ = load_configs()
    feasible = _empty_events_df(n_printers=1, n_days=365)
    feasible.loc[feasible["day"] == 100, "failure_C3"] = True  # high cost, but tiny downtime

    infeasible = _empty_events_df(n_printers=1, n_days=10)
    infeasible.loc[infeasible["day"] == 0, "failure_C2"] = True  # cheap but huge availability hit

    feasible_score = scalar_objective(feasible, components_cfg)
    infeasible_score = scalar_objective(infeasible, components_cfg)

    assert feasible_score["availability"] >= 0.95
    assert infeasible_score["availability"] < 0.95
    assert feasible_score["value"] < infeasible_score["value"]
    assert infeasible_score["value"] >= INFEASIBLE_FLOOR


def test_run_with_tau_returns_dataframe_with_required_event_columns() -> None:
    """Smoke test that the no-Arrow-roundtrip return path keeps cost columns intact."""
    from datetime import date, timedelta

    from ml.lib.env_runner import run_with_tau

    components_cfg, couplings_cfg, cities_cfg = load_configs()
    short_dates = [date(2015, 1, 1) + timedelta(days=d) for d in range(20)]
    tau = {component_id: float(components_cfg["components"][component_id]["tau_nom_d"])
           for component_id in COMPONENT_IDS}
    df = run_with_tau(
        tau, printer_ids=[0], dates=short_dates,
        components_cfg=components_cfg, couplings_cfg=couplings_cfg, cities_cfg=cities_cfg,
    )
    assert isinstance(df, pd.DataFrame)
    assert {"printer_id", "day"}.issubset(df.columns)
    for component_id in COMPONENT_IDS:
        assert f"maint_{component_id}" in df.columns
        assert f"failure_{component_id}" in df.columns


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
