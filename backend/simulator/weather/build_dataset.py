"""CLI orchestrator: download Open-Meteo data + transform -> data/weather_data.parquet.

Usage:
    uv run python -m sdg.weather.build_dataset
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from .download import download_all
from .transform import build_city_frame

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = ROOT / "backend" / "simulator" / "config" / "cities_climate.yaml"
RAW_DIR = ROOT / "data" / "raw"
OUT_PATH = ROOT / "data" / "weather_data.parquet"

SOURCE_START = "2016-01-01"
SOURCE_END = "2025-12-31"
SHIFT_YEARS = 4               # source 2016-2025  ->  target 2020-2029
TARGET_DAYS_PER_CITY = 3653   # 10 years incl. 3 leap years (2020, 2024, 2028)
TARGET_MIN = pd.Timestamp("2020-01-01")
TARGET_MAX = pd.Timestamp("2029-12-31")


def load_config(path: Path) -> tuple[dict, dict]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["defaults"], data["cities"]


def validate_frame(df: pd.DataFrame) -> None:
    counts = df.groupby("city", observed=True).size()
    if not (counts == TARGET_DAYS_PER_CITY).all():
        raise ValueError(
            f"Expected {TARGET_DAYS_PER_CITY} rows per city, got:\n{counts}"
        )

    num_cols = ["T_ext", "H_ext", "P_ext", "T_fab", "H_fab", "P_fab"]
    nans = df[num_cols].isna().sum()
    if nans.any():
        raise ValueError(f"Unexpected NaN values:\n{nans}")

    if not df["T_fab"].between(18.0, 30.0).all():
        raise ValueError("T_fab outside clip bounds [18, 30]")
    if not df["H_fab"].between(30.0, 70.0).all():
        raise ValueError("H_fab outside clip bounds [30, 70]")

    if df["date"].min() != TARGET_MIN or df["date"].max() != TARGET_MAX:
        raise ValueError(
            f"Date coverage mismatch: got [{df['date'].min()}, {df['date'].max()}], "
            f"expected [{TARGET_MIN.date()}, {TARGET_MAX.date()}]"
        )


def main() -> None:
    print(f"Loading config from {CONFIG_PATH.relative_to(ROOT)}")
    defaults, cities_config = load_config(CONFIG_PATH)
    print(f"  -> {len(cities_config)} cities")

    print(f"\nDownloading Open-Meteo data [{SOURCE_START} -> {SOURCE_END}]")
    print(f"  cache dir: {RAW_DIR.relative_to(ROOT)}")
    raw_payloads = download_all(cities_config, SOURCE_START, SOURCE_END, RAW_DIR)

    print(f"\nApplying transfer functions (relabel +{SHIFT_YEARS} years)")
    frames = []
    for city_key, raw in raw_payloads.items():
        params = cities_config[city_key]
        df = build_city_frame(
            city_key=city_key,
            raw=raw,
            alpha_T=params["alpha_T"],
            alpha_H=params["alpha_H"],
            defaults=defaults,
            shift_years=SHIFT_YEARS,
        )
        frames.append(df)
        print(
            f"  [{city_key:<13}] rows={len(df)}  "
            f"T_fab_mean={df['T_fab'].mean():.2f}  "
            f"H_fab_mean={df['H_fab'].mean():.2f}  "
            f"P_fab_mean={df['P_fab'].mean():.1f}"
        )

    full = pd.concat(frames, ignore_index=True)
    full["city"] = full["city"].astype("category")
    print(f"\nConcatenated frame: shape={full.shape}")

    print("Validating...")
    validate_frame(full)
    print("  OK")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    full.to_parquet(OUT_PATH, compression="snappy", index=False)
    size_kb = OUT_PATH.stat().st_size / 1024
    print(
        f"\nWrote {OUT_PATH.relative_to(ROOT)}  "
        f"({size_kb:.1f} KB, {len(full)} rows)"
    )


if __name__ == "__main__":
    main()
