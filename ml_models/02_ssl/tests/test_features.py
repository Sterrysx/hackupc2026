"""Unit tests for feature engineering used by the Transformer encoder."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from ml_models.lib.data import DEFAULT_FLEET_PATH
from ml_models.lib.features import (
    CALENDAR_COLS,
    COUNTER_COLS,
    add_calendar_features,
    base_feature_columns,
    build_feature_matrix,
    transform_counters,
)


def _tiny_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-01", "2020-04-01", "2020-07-01", "2020-10-01"]),
            "ambient_temp_c": [22.0, 24.0, 28.0, 25.0],
            "humidity_pct": [50.0, 55.0, 45.0, 60.0],
            "daily_print_hours": [4.0, 0.5, 6.0, 3.0],
            "cumulative_print_hours": [4.0, 4.5, 10.5, 13.5],
            "dust_concentration": [50.0, 60.0, 55.0, 70.0],
            "Q_demand": [1.0, 1.1, 1.2, 1.0],
            "N_f": [0, 100, 1000, 10000],
            "N_c": [0, 10, 100, 1000],
            "N_TC": [0, 1, 2, 3],
            "N_on": [0, 1, 1, 2],
            **{f"H_C{i}": [1.0, 0.95, 0.9, 0.85] for i in range(1, 7)},
            **{f"tau_C{i}": [0.0, 24.0, 48.0, 72.0] for i in range(1, 7)},
            **{f"L_C{i}": [0.0, 24.0, 48.0, 72.0] for i in range(1, 7)},
            **{f"hours_since_C{i}_failure": [0.0, 4.0, 8.0, 12.0] for i in range(1, 7)},
            **{f"lambda_C{i}": [1e-3, 1.1e-3, 1.2e-3, 1.3e-3] for i in range(1, 7)},
        }
    )


def test_add_calendar_features_appends_expected_columns() -> None:
    df = add_calendar_features(_tiny_frame())
    for column in CALENDAR_COLS:
        assert column in df.columns
    assert df["sin_doy"].between(-1.0, 1.0).all()
    assert df["cos_doy"].between(-1.0, 1.0).all()


def test_transform_counters_is_log1p_monotonic() -> None:
    transformed = transform_counters(_tiny_frame())
    for column in COUNTER_COLS:
        original = _tiny_frame()[column].to_numpy()
        expected = np.log1p(original.astype(np.float64)).astype(np.float32)
        np.testing.assert_allclose(transformed[column].to_numpy(), expected)


def test_build_feature_matrix_returns_full_column_list() -> None:
    df, columns = build_feature_matrix(_tiny_frame())
    assert columns == base_feature_columns()
    for column in columns:
        assert column in df.columns
    assert len(df) == 4


def test_project_root_resolves_independently_of_cwd(tmp_path, monkeypatch) -> None:
    """Regression for the `Path('ml_models/...')` doubling bug.

    Previously notebook cells used relative paths that resolved against
    Jupyter's cwd. After the fix everything uses ``ml_models.PROJECT_ROOT``
    derived from ``__file__``, which must be cwd-invariant.
    """
    from ml_models import PROJECT_ROOT
    from ml_models.lib.data import DEFAULT_FLEET_PATH as canonical

    monkeypatch.chdir(tmp_path)
    # PROJECT_ROOT is computed from the package's __file__, so it should not
    # care about the new cwd.
    assert (PROJECT_ROOT / "pyproject.toml").exists(), (
        "PROJECT_ROOT must point at the repo root regardless of cwd"
    )
    expected_models_dir = PROJECT_ROOT / "ml_models" / "02_ssl" / "models"
    # PROJECT_ROOT / 'ml_models/02_ssl/models' must NOT be
    # PROJECT_ROOT / 'ml_models/02_ssl/ml_models/02_ssl/models'
    assert "ml_models/02_ssl/ml_models" not in expected_models_dir.as_posix()
    # The DEFAULT_FLEET_PATH constant should point at the canonical location.
    assert canonical.as_posix().endswith("data/fleet_baseline.parquet")


def test_stratified_printer_split_balances_climates() -> None:
    """Each split should contain at least one printer from every climate zone."""
    from ml_models.lib.data import stratified_printer_split
    from sdg.generate import build_printer_city_map, load_configs
    from sdg.schema import CLIMATE_CATEGORIES

    splits = stratified_printer_split(seed=0)
    assert sum(len(v) for v in splits.values()) == 100
    _, _, cities_cfg = load_configs()
    printer_city_map = build_printer_city_map(list(cities_cfg["cities"]))
    for split_name, ids in splits.items():
        zones = {printer_city_map[pid]["climate_zone"] for pid in ids}
        missing = set(CLIMATE_CATEGORIES) - zones
        assert not missing, f"{split_name} missing climate zones: {missing}"


def test_features_align_with_real_parquet_schema_when_available() -> None:
    if not DEFAULT_FLEET_PATH.exists():
        pytest.skip("fleet_baseline.parquet not generated yet")
    schema = pq.read_schema(DEFAULT_FLEET_PATH)
    needed = {
        "date",
        "ambient_temp_c",
        "humidity_pct",
        "daily_print_hours",
        "cumulative_print_hours",
        "dust_concentration",
        "Q_demand",
        *COUNTER_COLS,
        *(f"hours_since_C{i}_failure" for i in range(1, 7)),
    }
    schema_names = set(schema.names)
    missing = needed - schema_names
    assert not missing, f"feature dependencies missing in fleet schema: {missing}"
