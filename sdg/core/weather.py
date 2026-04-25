from __future__ import annotations

import math
from datetime import date as Date
from functools import lru_cache
from pathlib import Path

import yaml


@lru_cache(maxsize=None)
def get_drivers(city: str, date: Date) -> dict[str, float]:
    """Return deterministic indoor workshop weather for one city and day."""
    profile = _city_profiles()[city]
    day_of_year = date.timetuple().tm_yday
    phase = 2.0 * math.pi * (day_of_year - 15) / 365.25

    temp = float(profile["T_mean_annual"]) + float(profile["T_amplitude"]) * math.cos(phase)
    humidity = float(profile["H_mean_annual"]) + float(profile["H_amplitude"]) * math.sin(
        phase + math.pi / 4.0
    )
    return {
        "ambient_temp_c": float(min(30.0, max(20.0, temp))),
        "humidity_pct": float(min(70.0, max(30.0, humidity))),
    }


@lru_cache(maxsize=1)
def _city_profiles() -> dict[str, dict]:
    config_path = Path(__file__).resolve().parents[1] / "config" / "cities.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return {entry["name"]: entry for entry in data["cities"]}
