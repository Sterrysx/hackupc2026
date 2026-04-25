from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import yaml

from sdg.core.degradation import validate_components_config
from sdg.core.simulator import run_printer
from sdg.core.weather import clear_real_lookup, init_real_lookup
from sdg.labels import add_rul_labels
from sdg.schema import CITY_CATEGORIES, CLIMATE_CATEGORIES, COMPONENT_IDS, FINAL_SCHEMA, RAW_SCHEMA
from sdg.schema import table_from_rows
from sdg.weather.real_weather import build_and_save as build_weather, load_lookup

TRAIN_DIR = Path("data/train")
DEFAULT_OUTPUT_PATH = Path("data/fleet_baseline.parquet")

REAL_START = "2016-01-01"
REAL_END = "2025-12-31"
PROJ_START = "2026-01-01"
PROJ_END = "2035-12-31"

CITY_PRINTER_COUNTS: tuple[int, ...] = (10, 10, 10, 10, 10, 10, 10, 10, 10, 10)
EXPECTED_PRINTERS = sum(CITY_PRINTER_COUNTS)


def main(
    output_path: str | Path,
    start_date: str,
    end_date: str,
    weather_parquet: Path,
) -> None:
    """Generate one fleet Parquet file for the given date range using the supplied weather."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    components_cfg, couplings_cfg, cities_cfg = load_configs()
    validate_components_config(components_cfg)
    cities = _validate_cities(cities_cfg)

    dates = list(pd.date_range(start_date, end_date, freq="D").date)
    expected_days = len(dates)
    expected_rows = EXPECTED_PRINTERS * expected_days

    lookup = load_lookup(weather_parquet)
    init_real_lookup(lookup)

    printer_city_map = build_printer_city_map(cities)

    writer: pq.ParquetWriter | None = None
    row_count = 0
    try:
        writer = pq.ParquetWriter(output, RAW_SCHEMA, compression="snappy", version="2.6")
        for printer_id in range(EXPECTED_PRINTERS):
            rng = np.random.default_rng(printer_id)
            city_profile = printer_city_map[printer_id]
            monthly_jobs = float(rng.uniform(8.0, 15.0))
            alphas = {
                cid: float(
                    np.clip(
                        rng.normal(
                            1.0,
                            float(components_cfg["components"][cid].get("alpha_sigma", 0.10)),
                        ),
                        0.5,
                        2.0,
                    )
                )
                for cid in COMPONENT_IDS
            }
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
        clear_real_lookup()

    if row_count != expected_rows:
        raise AssertionError(f"expected {expected_rows} rows, got {row_count}")

    add_rul_labels(output)
    metadata = pq.read_metadata(output)
    if metadata.num_rows != expected_rows:
        raise AssertionError(f"expected {expected_rows} rows after labeling, got {metadata.num_rows}")
    schema = pq.read_schema(output)
    if not schema.equals(FINAL_SCHEMA, check_metadata=False):
        raise AssertionError("final Parquet schema does not match FINAL_SCHEMA")

    size_mb = output.stat().st_size / 1_048_576
    print(f"  {output}  ({size_mb:.1f} MB, {row_count} rows)")


def generate_all() -> None:
    """Build weather parquets then generate both fleet datasets."""
    TRAIN_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Step 1: build weather parquets ===")
    build_weather(TRAIN_DIR)

    real_wp = TRAIN_DIR / "weather_real.parquet"
    proj_wp = TRAIN_DIR / "weather_projected.parquet"

    print("\n=== Step 2: fleet 2016-2025 (real weather) ===")
    out_real = TRAIN_DIR / "fleet_2016_2025.parquet"
    main(out_real, REAL_START, REAL_END, real_wp)

    print("\n=== Step 3: fleet 2026-2035 (projected weather) ===")
    out_proj = TRAIN_DIR / "fleet_2026_2035.parquet"
    main(out_proj, PROJ_START, PROJ_END, proj_wp)

    # Keep fleet_baseline.parquet pointing at the real 2016-2025 dataset for API compatibility
    import shutil
    shutil.copy2(out_real, DEFAULT_OUTPUT_PATH)
    print(f"\nCopied {out_real.name} → {DEFAULT_OUTPUT_PATH}")


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
    if len(cities) != len(CITY_PRINTER_COUNTS):
        raise ValueError(f"expected {len(CITY_PRINTER_COUNTS)} cities, got {len(cities)}")
    names = [city["name"] for city in cities]
    zones = [city["climate_zone"] for city in cities]
    if tuple(names) != CITY_CATEGORIES:
        raise ValueError("cities.yaml order must match CITY_CATEGORIES")
    if not set(zones).issubset(set(CLIMATE_CATEGORIES)):
        raise ValueError("cities.yaml contains an unknown climate zone")
    return cities


def build_printer_city_map(cities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(cities) != len(CITY_PRINTER_COUNTS):
        raise ValueError("city count does not match CITY_PRINTER_COUNTS")
    printer_city_map: list[dict[str, Any]] = []
    for city, printer_count in zip(cities, CITY_PRINTER_COUNTS, strict=True):
        printer_city_map.extend([city] * printer_count)
    if len(printer_city_map) != EXPECTED_PRINTERS:
        raise AssertionError(f"expected {EXPECTED_PRINTERS} printers, got {len(printer_city_map)}")
    return printer_city_map


if __name__ == "__main__":
    generate_all()
