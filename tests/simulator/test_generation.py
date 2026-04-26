from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from backend.simulator.core.weather import get_drivers
from backend.simulator.generate import CITY_PRINTER_COUNTS, EXPECTED_DAYS, EXPECTED_ROWS, main
from backend.simulator.labels import compute_rul_columns
from backend.simulator.schema import COMPONENT_IDS, FINAL_SCHEMA


@pytest.fixture(scope="session")
def generated_paths(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    output_dir = tmp_path_factory.mktemp("sdg")
    first = output_dir / "fleet_a.parquet"
    second = output_dir / "fleet_b.parquet"
    main(first)
    main(second)
    return first, second


@pytest.fixture(scope="session")
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


def test_calendar_shape_and_leap_days(generated_path: Path) -> None:
    metadata = pq.read_metadata(generated_path)
    assert metadata.num_rows == EXPECTED_ROWS

    df = pd.read_parquet(generated_path, columns=["printer_id", "day", "date"])
    assert df.groupby("printer_id", observed=True).size().eq(EXPECTED_DAYS).all()
    assert df.groupby("printer_id", observed=True)["day"].min().eq(0).all()
    assert df.groupby("printer_id", observed=True)["day"].max().eq(EXPECTED_DAYS - 1).all()

    dates = set(pd.to_datetime(df["date"]).dt.date)
    assert date(2016, 2, 29) in dates
    assert date(2020, 2, 29) in dates
    assert date(2024, 2, 29) in dates


def test_city_printer_allocation_is_100_printers(generated_path: Path) -> None:
    df = pd.read_parquet(generated_path, columns=["printer_id", "city"])
    per_city = (
        df.drop_duplicates(["printer_id", "city"])
        .groupby("city", observed=True)["printer_id"]
        .nunique()
        .tolist()
    )

    assert per_city == list(CITY_PRINTER_COUNTS)
    assert sum(per_city) == 100


def test_climate_ingestion_matches_weather_function(generated_path: Path) -> None:
    target_date = date(2020, 2, 29)
    df = pd.read_parquet(
        generated_path,
        columns=["printer_id", "date", "ambient_temp_c", "humidity_pct"],
    )
    dates = pd.to_datetime(df["date"]).dt.date
    row = df[(df["printer_id"] == 0) & (dates == target_date)].iloc[0]
    expected = get_drivers("Helsinki", target_date)

    assert row["ambient_temp_c"] == pytest.approx(expected["ambient_temp_c"], abs=1e-6)
    assert row["humidity_pct"] == pytest.approx(expected["humidity_pct"], abs=1e-6)


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
