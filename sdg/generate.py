from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from sdg.core.degradation import validate_components_config
from sdg.core.simulator import run_printer
from sdg.labels import add_rul_labels
from sdg.schema import CITY_CATEGORIES, CLIMATE_CATEGORIES, COMPONENT_IDS, FINAL_SCHEMA, RAW_SCHEMA
from sdg.schema import table_from_rows

DEFAULT_OUTPUT_PATH = Path("data/fleet_baseline.parquet")
START_DATE = "2015-01-01"
END_DATE = "2024-12-31"
PRINTERS_PER_CITY = 7
EXPECTED_PRINTERS = 105
EXPECTED_DAYS = 3653
EXPECTED_ROWS = EXPECTED_PRINTERS * EXPECTED_DAYS


def main(output_path: str | Path = DEFAULT_OUTPUT_PATH) -> None:
    """Generate the deterministic fleet baseline Parquet file."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    components_cfg, couplings_cfg, cities_cfg = load_configs()
    validate_components_config(components_cfg)
    cities = _validate_cities(cities_cfg)
    dates = list(pd.date_range(START_DATE, END_DATE, freq="D").date)
    if len(dates) != EXPECTED_DAYS:
        raise AssertionError(f"expected {EXPECTED_DAYS} days, got {len(dates)}")

    writer: pq.ParquetWriter | None = None
    row_count = 0
    try:
        writer = pq.ParquetWriter(output, RAW_SCHEMA, compression="snappy", version="2.6")
        for printer_id in range(EXPECTED_PRINTERS):
            rng = np.random.default_rng(printer_id)
            city_profile = cities[printer_id // PRINTERS_PER_CITY]
            monthly_jobs = float(rng.uniform(8.0, 15.0))
            alpha_values = rng.uniform(0.7, 1.3, size=len(COMPONENT_IDS))
            alphas = dict(zip(COMPONENT_IDS, alpha_values, strict=True))
            rows = run_printer(
                printer_id=printer_id,
                city_profile=city_profile,
                dates=dates,
                components_cfg=components_cfg,
                couplings_cfg=couplings_cfg,
                rng=rng,
                monthly_jobs=monthly_jobs,
                alphas=alphas,
            )
            table = table_from_rows(rows, include_rul=False)
            writer.write_table(table)
            row_count += table.num_rows
    finally:
        if writer is not None:
            writer.close()

    if row_count != EXPECTED_ROWS:
        raise AssertionError(f"expected {EXPECTED_ROWS} rows, got {row_count}")

    add_rul_labels(output)
    metadata = pq.read_metadata(output)
    if metadata.num_rows != EXPECTED_ROWS:
        raise AssertionError(f"expected {EXPECTED_ROWS} rows after labeling, got {metadata.num_rows}")
    schema = pq.read_schema(output)
    if not schema.equals(FINAL_SCHEMA, check_metadata=False):
        raise AssertionError("final Parquet schema does not match FINAL_SCHEMA")


def load_configs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config_dir = Path(__file__).resolve().parent / "config"
    return (
        _load_yaml(config_dir / "components.yaml"),
        _load_yaml(config_dir / "couplings.yaml"),
        _load_yaml(config_dir / "cities.yaml"),
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _validate_cities(cities_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    cities = list(cities_cfg["cities"])
    if len(cities) != 15:
        raise ValueError(f"expected 15 cities, got {len(cities)}")
    names = [city["name"] for city in cities]
    zones = [city["climate_zone"] for city in cities]
    if tuple(names) != CITY_CATEGORIES:
        raise ValueError("cities.yaml order must match frozen city categories")
    if not set(zones).issubset(set(CLIMATE_CATEGORIES)):
        raise ValueError("cities.yaml contains an unknown climate zone")
    return cities


if __name__ == "__main__":
    main()
