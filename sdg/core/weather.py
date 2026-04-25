from __future__ import annotations

import math
from datetime import date as Date
from functools import lru_cache
from pathlib import Path

import yaml

# {city_key: {date_iso: (T_fab, H_fab)}} — populated by init_real_lookup()
_REAL_LOOKUP: dict[str, dict[str, tuple[float, float]]] | None = None


def init_real_lookup(lookup: dict[str, dict[str, tuple[float, float]]]) -> None:
    global _REAL_LOOKUP
    _REAL_LOOKUP = lookup
    get_drivers.cache_clear()


def clear_real_lookup() -> None:
    global _REAL_LOOKUP
    _REAL_LOOKUP = None
    get_drivers.cache_clear()


@lru_cache(maxsize=None)
def get_drivers(city: str, date: Date) -> dict[str, float]:
    """Return indoor workshop weather drivers for one city and day.

    Uses real Open-Meteo-derived T_fab/H_fab when a lookup is loaded;
    falls back to the synthetic cosine formula from cities.yaml.
    """
    if _REAL_LOOKUP is not None:
        city_data = _REAL_LOOKUP.get(city)
        if city_data is not None:
            entry = city_data.get(date.isoformat())
            if entry is not None:
                T_fab, H_fab = entry
                return {
                    "ambient_temp_c": float(min(30.0, max(20.0, T_fab))),
                    "humidity_pct": float(min(70.0, max(30.0, H_fab))),
                }

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
