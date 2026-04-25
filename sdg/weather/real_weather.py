"""Build weather parquets from cached Open-Meteo JSON files.

Outputs:
  data/train/weather_real.parquet       2016-2025 fab conditions (T_fab, H_fab, P_fab)
  data/train/weather_projected.parquet  2026-2035 (cycled from real, leap days clamped)
"""
from __future__ import annotations

import json
from datetime import date as Date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from sdg.weather.transform import apply_transfer_functions

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
TRAIN_DIR = ROOT / "data" / "train"
CLIMATE_CFG_PATH = ROOT / "sdg" / "config" / "cities_climate.yaml"


def _load_climate_cfg() -> tuple[dict, dict]:
    with CLIMATE_CFG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["defaults"], data["cities"]


def build_real_weather() -> pd.DataFrame:
    """Read Open-Meteo JSONs and apply transfer functions. Returns 2016-2025 fab conditions."""
    defaults, cities = _load_climate_cfg()
    frames = []

    for city_key, params in cities.items():
        json_path = RAW_DIR / f"openmeteo_{city_key}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"Missing weather cache: {json_path}")

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        daily = raw["daily"]

        dates = daily["time"]
        T_ext = np.asarray(daily["temperature_2m_mean"], dtype=np.float64)
        H_ext = np.asarray(daily["relative_humidity_2m_mean"], dtype=np.float64)
        P_ext = np.asarray(daily["surface_pressure_mean"], dtype=np.float64)

        T_fab, H_fab, P_fab = apply_transfer_functions(
            T_ext, H_ext, P_ext,
            alpha_T=float(params["alpha_T"]),
            alpha_H=float(params["alpha_H"]),
            defaults=defaults,
        )

        frames.append(pd.DataFrame({
            "city": city_key,
            "date": pd.to_datetime(dates),
            "T_fab": T_fab.astype(np.float32),
            "H_fab": H_fab.astype(np.float32),
            "P_fab": P_fab.astype(np.float32),
        }))

    return pd.concat(frames, ignore_index=True)


def _safe_shift_back(d: Date) -> Date:
    """Map a date in 2026-2035 to corresponding 2016-2025 date (handles Feb 29)."""
    try:
        return d.replace(year=d.year - 10)
    except ValueError:
        return d.replace(year=d.year - 10, day=28)


def build_projected_weather(real_df: pd.DataFrame) -> pd.DataFrame:
    """Cycle 2016-2025 real data to cover 2026-2035."""
    real_df = real_df.copy()
    real_df["_date_key"] = pd.to_datetime(real_df["date"]).dt.date
    lookup = real_df.set_index(["city", "_date_key"])[["T_fab", "H_fab", "P_fab"]]

    proj_dates = pd.date_range("2026-01-01", "2035-12-31", freq="D").date
    cities = real_df["city"].unique().tolist()

    frames = []
    for city in cities:
        rows = []
        for d in proj_dates:
            src = _safe_shift_back(d)
            row = lookup.loc[(city, src)]
            rows.append({
                "city": city,
                "date": pd.Timestamp(d),
                "T_fab": float(row["T_fab"]),
                "H_fab": float(row["H_fab"]),
                "P_fab": float(row["P_fab"]),
            })
        frames.append(pd.DataFrame(rows))

    return pd.concat(frames, ignore_index=True)


def _save(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, compression="snappy", index=False)
    abs_path = path.resolve()
    label = abs_path.relative_to(ROOT) if abs_path.is_relative_to(ROOT) else abs_path
    print(f"  saved {label}  ({abs_path.stat().st_size // 1024} KB, {len(df)} rows)")


def build_and_save(train_dir: Path = TRAIN_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("Building real weather (2016-2025)...")
    real_df = build_real_weather()
    _save(real_df, train_dir / "weather_real.parquet")

    print("Building projected weather (2026-2035)...")
    proj_df = build_projected_weather(real_df)
    _save(proj_df, train_dir / "weather_projected.parquet")

    return real_df, proj_df


def load_lookup(parquet_path: Path) -> dict[str, dict[str, tuple[float, float]]]:
    """Load weather parquet into a {city: {date_iso: (T_fab, H_fab)}} dict for fast lookup."""
    df = pd.read_parquet(parquet_path)
    lookup: dict[str, dict[str, tuple[float, float]]] = {}
    for row in df.itertuples(index=False):
        city = str(row.city)
        date_str = str(row.date.date()) if hasattr(row.date, "date") else str(row.date)[:10]
        lookup.setdefault(city, {})[date_str] = (float(row.T_fab), float(row.H_fab))
    return lookup


if __name__ == "__main__":
    build_and_save()
