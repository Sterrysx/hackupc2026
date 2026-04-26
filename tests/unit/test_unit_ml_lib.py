"""Unit tests for ``ml_models.lib`` — covers data/features/splits/objective."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.lib import data, features, objective, splits
from backend.simulator.schema import COMPONENT_IDS


# ---------------------------------------------------------- data.printer_split


def test_printer_split_keys_and_total_size():
    split = data.printer_split()
    assert set(split.keys()) == {"train", "val", "test"}
    assert len(split["train"]) == 70
    assert len(split["val"]) == 15
    assert len(split["test"]) == 15
    # Together they cover all 100 printers.
    union = set(split["train"]) | set(split["val"]) | set(split["test"])
    assert union == set(range(100))


def test_printer_split_has_no_overlap():
    split = data.printer_split()
    assert not (set(split["train"]) & set(split["val"]))
    assert not (set(split["val"]) & set(split["test"]))
    assert not (set(split["train"]) & set(split["test"]))


# --------------------------------------------------------- data.filter_printers


def test_filter_printers_returns_only_requested_ids():
    df = pd.DataFrame({
        "printer_id": [0, 0, 1, 2, 3, 4],
        "value": [10, 11, 20, 30, 40, 50],
    })
    sub = data.filter_printers(df, [0, 2])
    assert set(sub["printer_id"].unique()) == {0, 2}
    assert len(sub) == 3  # two rows for printer 0, one for printer 2


def test_filter_printers_returns_empty_when_no_match():
    df = pd.DataFrame({"printer_id": [0, 1, 2], "value": [1, 2, 3]})
    sub = data.filter_printers(df, [99])
    assert sub.empty


# --------------------------------------------------------- data.to_panel_tensor


def test_to_panel_tensor_builds_three_dim_tensor():
    """N_groups, T, F shape from a long-form DataFrame."""
    rows = []
    for printer_id in (0, 1, 2):
        for day in range(5):
            rows.append({
                "printer_id": printer_id,
                "day": day,
                "f1": float(printer_id + day),
                "f2": float(printer_id - day),
            })
    df = pd.DataFrame(rows)
    tensor, groups = data.to_panel_tensor(df, ["f1", "f2"])
    assert tensor.shape == (3, 5, 2)
    assert groups == [0, 1, 2]


def test_to_panel_tensor_raises_when_lengths_inconsistent():
    rows = [
        {"printer_id": 0, "day": 0, "f1": 1.0},
        {"printer_id": 0, "day": 1, "f1": 2.0},
        {"printer_id": 1, "day": 0, "f1": 3.0},  # printer 1 has 1 day, printer 0 has 2.
    ]
    df = pd.DataFrame(rows)
    with pytest.raises(ValueError, match="inconsistent"):
        data.to_panel_tensor(df, ["f1"])


# ----------------------------------------------- features.add_calendar_features


def test_add_calendar_features_adds_four_calendar_columns():
    df = pd.DataFrame({"date": pd.to_datetime(["2026-01-01", "2026-07-01"])})
    out = features.add_calendar_features(df)
    for col in ("sin_doy", "cos_doy", "sin_month", "cos_month"):
        assert col in out.columns
        assert pd.api.types.is_float_dtype(out[col])


def test_add_calendar_features_raises_without_date_column():
    df = pd.DataFrame({"day": [0, 1, 2]})
    with pytest.raises(KeyError, match="date"):
        features.add_calendar_features(df)


def test_transform_counters_applies_log1p_to_counter_columns():
    df = pd.DataFrame({
        "N_f": [0, 9, 99], "N_c": [0, 1, 2], "N_TC": [0, 0, 0], "N_on": [0, 1, 1],
    })
    out = features.transform_counters(df)
    assert out["N_f"].iloc[0] == pytest.approx(0.0)
    assert out["N_f"].iloc[1] == pytest.approx(np.log1p(9), rel=1e-5)
    assert out["N_f"].iloc[2] == pytest.approx(np.log1p(99), rel=1e-5)


# ----------------------------------------------- features.build_feature_matrix


def _build_full_feature_df() -> pd.DataFrame:
    """A 1-row DataFrame containing every column build_feature_matrix needs."""
    row = {
        "date": pd.Timestamp("2026-04-25"),
        "ambient_temp_c": 22.0, "humidity_pct": 50.0,
        "daily_print_hours": 4.0, "cumulative_print_hours": 100.0,
        "dust_concentration": 50.0, "Q_demand": 1.0,
        "N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0,
    }
    for cid in COMPONENT_IDS:
        row[f"H_{cid}"] = 1.0
        row[f"tau_{cid}"] = 0.0
        row[f"L_{cid}"] = 0.0
        row[f"hours_since_{cid}_failure"] = 0.0
        row[f"lambda_{cid}"] = 0.001
    return pd.DataFrame([row])


def test_build_feature_matrix_returns_df_and_canonical_column_list():
    df = _build_full_feature_df()
    enriched, cols = features.build_feature_matrix(df)
    assert cols == features.base_feature_columns()
    # Calendar features must have been appended.
    assert "sin_doy" in enriched.columns
    assert "cos_month" in enriched.columns


def test_build_feature_matrix_raises_when_a_required_column_is_missing():
    df = _build_full_feature_df().drop(columns=["H_C1"])
    with pytest.raises(KeyError):
        features.build_feature_matrix(df)


def test_base_feature_columns_returns_expected_count():
    """Floor at 37 (historic width) + every C1..C6 health column present."""
    cols = features.base_feature_columns()
    assert len(cols) >= 37
    for cid in COMPONENT_IDS:
        assert f"H_{cid}" in cols


# --------------------------------------------- splits.expanding_window_folds


def test_expanding_window_folds_produces_n_folds_with_growing_train():
    folds = splits.expanding_window_folds(
        n_days=2400, n_folds=4, min_train_days=1800, val_days=400,
    )
    assert len(folds) == 4
    assert folds[0][0] == range(0, 1800)
    assert folds[0][1] == range(1800, 2200)


def test_expanding_window_folds_train_grows_monotonically():
    folds = splits.expanding_window_folds(
        n_days=2400, n_folds=4, min_train_days=1800, val_days=400,
    )
    train_ends = [f[0].stop for f in folds]
    assert train_ends == sorted(train_ends)


def test_expanding_window_folds_raises_when_n_days_too_small():
    with pytest.raises(ValueError, match="too small"):
        splits.expanding_window_folds(
            n_days=100, n_folds=4, min_train_days=1800, val_days=400,
        )


def test_expanding_window_folds_rejects_zero_folds():
    with pytest.raises(ValueError, match="n_folds"):
        splits.expanding_window_folds(
            n_days=3000, n_folds=0, min_train_days=1800, val_days=400,
        )


# ------------------------------------------- objective.compute_costs / availability


def _components_cfg() -> dict:
    """Minimal cfg with the four cost/downtime fields per component."""
    default = {
        "cost_preventive_eur": 100.0, "cost_corrective_eur": 1000.0,
        "downtime_preventive_d": 0.1, "downtime_corrective_d": 1.0,
    }
    return {"components": {cid: dict(default) for cid in COMPONENT_IDS}}


def _events_df(maint_events=None, failure_events=None, n_days: int = 365) -> pd.DataFrame:
    """Build a synthetic events DataFrame with maint_Ci + failure_Ci columns."""
    maint_events = maint_events or {}
    failure_events = failure_events or {}
    rows = []
    for day in range(n_days):
        row = {"printer_id": 0, "day": day}
        for cid in COMPONENT_IDS:
            row[f"maint_{cid}"] = (day in maint_events.get(cid, []))
            row[f"failure_{cid}"] = (day in failure_events.get(cid, []))
        rows.append(row)
    return pd.DataFrame(rows)


def test_compute_costs_returns_expected_keys():
    out = objective.compute_costs(_events_df(n_days=365), _components_cfg())
    expected = {
        "annual_cost", "preventive_cost", "corrective_cost",
        "n_preventive_per_component", "n_corrective_per_component",
        "horizon_days", "horizon_years", "n_printers",
    }
    assert expected <= set(out.keys())


def test_compute_costs_sum_equals_annual_cost():
    df = _events_df(maint_events={"C1": [10, 20]}, failure_events={"C3": [50]})
    out = objective.compute_costs(df, _components_cfg())
    assert out["preventive_cost"] + out["corrective_cost"] == pytest.approx(
        out["annual_cost"]
    )


def test_compute_availability_returns_one_when_no_events():
    assert objective.compute_availability(_events_df(), _components_cfg()) == 1.0


def test_compute_availability_clamps_to_zero_under_full_downtime():
    """365 corrective failures on C1 at 1.0d downtime = 365d down on a
    fleet of 1 printer over 365 days -> availability = 0.0."""
    df = _events_df(failure_events={"C1": list(range(365))}, n_days=365)
    assert objective.compute_availability(df, _components_cfg()) == 0.0


def test_scalar_objective_returns_annual_cost_when_feasible():
    df = _events_df(maint_events={"C1": [10]})
    result = objective.scalar_objective(df, _components_cfg(), availability_threshold=0.5)
    assert result["deficit"] == 0.0
    assert result["value"] == result["annual_cost"]
    assert result["value"] < objective.INFEASIBLE_FLOOR


def test_scalar_objective_pushes_above_floor_when_infeasible():
    """High availability_threshold renders the trial infeasible — value
    must climb above INFEASIBLE_FLOOR."""
    df = _events_df(failure_events={"C1": list(range(100))})
    result = objective.scalar_objective(df, _components_cfg(), availability_threshold=0.99)
    assert result["deficit"] > 0.0
    assert result["value"] >= objective.INFEASIBLE_FLOOR
