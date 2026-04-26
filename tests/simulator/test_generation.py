"""End-to-end tests for backend.simulator.generate.main().

Uses the real Open-Meteo-derived weather parquet
(``data/train/weather_real.parquet``) and a 15-day window so the test
generates only ~1500 rows and runs in seconds.

Skips automatically when the weather parquet isn't available — the SDG
isn't part of CI's required preconditions.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from backend.simulator.generate import (
    CITY_PRINTER_COUNTS,
    EXPECTED_PRINTERS,
    main,
)
from backend.simulator.labels import compute_rul_columns
from backend.simulator.schema import COMPONENT_IDS, FINAL_SCHEMA


_WEATHER_PARQUET = Path("data") / "train" / "weather_real.parquet"
_TEST_START = "2016-01-01"
_TEST_END = "2016-01-15"  # 15-day window — keeps the test fast.
_TEST_DAYS = 15
_TEST_ROWS = EXPECTED_PRINTERS * _TEST_DAYS


pytestmark = pytest.mark.skipif(
    not _WEATHER_PARQUET.exists(),
    reason=f"{_WEATHER_PARQUET} not found — sdg generation tests need the real weather parquet.",
)


@pytest.fixture(scope="module")
def generated_paths(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Run the generator twice with the same seed → two parquets to diff."""
    output_dir = tmp_path_factory.mktemp("sdg")
    first = output_dir / "fleet_a.parquet"
    second = output_dir / "fleet_b.parquet"
    main(first, _TEST_START, _TEST_END, _WEATHER_PARQUET)
    main(second, _TEST_START, _TEST_END, _WEATHER_PARQUET)
    return first, second


@pytest.fixture(scope="module")
def generated_path(generated_paths: tuple[Path, Path]) -> Path:
    return generated_paths[0]


def test_generation_is_byte_deterministic(generated_paths: tuple[Path, Path]) -> None:
    first, second = generated_paths
    assert first.read_bytes() == second.read_bytes()


def test_schema_matches_frozen_schema(generated_path: Path) -> None:
    schema = pq.read_schema(generated_path)
    assert schema.equals(FINAL_SCHEMA, check_metadata=False)
    for field in schema:
        expected_nullable = field.name.startswith("rul_") or field.name == "rul_system"
        assert field.nullable is expected_nullable

    df = pd.read_parquet(
        generated_path,
        columns=[*[f"rul_{component_id}" for component_id in COMPONENT_IDS], "rul_system"],
    )
    assert all(str(dtype) == "Int32" for dtype in df.dtypes)


def test_calendar_shape_for_short_window(generated_path: Path) -> None:
    metadata = pq.read_metadata(generated_path)
    assert metadata.num_rows == _TEST_ROWS

    df = pd.read_parquet(generated_path, columns=["printer_id", "day", "date"])
    assert df.groupby("printer_id", observed=True).size().eq(_TEST_DAYS).all()
    assert df.groupby("printer_id", observed=True)["day"].min().eq(0).all()
    assert df.groupby("printer_id", observed=True)["day"].max().eq(_TEST_DAYS - 1).all()


def test_city_printer_allocation_is_100_printers(generated_path: Path) -> None:
    df = pd.read_parquet(generated_path, columns=["printer_id", "city"])
    per_city = (
        df.drop_duplicates(["printer_id", "city"])
        .groupby("city", observed=True)["printer_id"]
        .nunique()
        .sort_index()
        .tolist()
    )

    # CITY_PRINTER_COUNTS lists per-city counts in cities.yaml order; the
    # parquet groups alphabetically. The two are equal in size and sum.
    assert sum(per_city) == EXPECTED_PRINTERS == 100
    assert sorted(per_city) == sorted(CITY_PRINTER_COUNTS)


def test_climate_ingestion_uses_real_weather_lookup(generated_path: Path) -> None:
    """Generated rows must match the real-weather parquet lookup byte-for-byte."""
    from datetime import date as Date

    fleet_df = pd.read_parquet(
        generated_path,
        columns=["printer_id", "city", "date", "ambient_temp_c", "humidity_pct"],
    )
    weather_df = pd.read_parquet(_WEATHER_PARQUET)

    # Fleet parquet stores ``date`` as Python ``date`` objects (dtype=object);
    # weather parquet stores ``date`` as datetime64. Normalize both to ``date``.
    fleet_dates = fleet_df["date"].apply(
        lambda d: d if isinstance(d, Date) else d.date()
    )
    weather_dates = weather_df["date"].dt.date

    target_date = Date(2016, 1, 10)
    fleet_row = fleet_df[(fleet_df["printer_id"] == 0) & (fleet_dates == target_date)].iloc[0]
    fleet_city = str(fleet_row["city"])
    weather_row = weather_df[(weather_df["city"] == fleet_city) & (weather_dates == target_date)].iloc[0]

    # The simulator clamps T_fab/H_fab into the workshop comfort band
    # ([20, 30] / [30, 70]); the weather parquet stores the raw fab values.
    expected_t = float(min(30.0, max(20.0, float(weather_row["T_fab"]))))
    expected_h = float(min(70.0, max(30.0, float(weather_row["H_fab"]))))
    assert fleet_row["ambient_temp_c"] == pytest.approx(expected_t, abs=1e-6)
    assert fleet_row["humidity_pct"] == pytest.approx(expected_h, abs=1e-6)


def test_compute_rul_columns_anchors_on_failure_events() -> None:
    df = pd.DataFrame(
        {
            "printer_id": [0, 0, 0, 0],
            "day": [0, 1, 2, 3],
            **{f"failure_{component_id}": [False, False, False, False] for component_id in COMPONENT_IDS},
        }
    )
    df["failure_C1"] = [False, False, True, False]

    labeled = compute_rul_columns(df)

    assert labeled["rul_C1"].tolist()[:3] == [2, 1, 0]
    assert pd.isna(labeled.loc[3, "rul_C1"])
    assert labeled["rul_system"].tolist()[:3] == [2, 1, 0]
    assert pd.isna(labeled.loc[3, "rul_system"])
