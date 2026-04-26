"""Open-Meteo Historical Weather API client with on-disk JSON cache."""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

OPEN_METEO_URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = "temperature_2m_mean,relative_humidity_2m_mean,surface_pressure_mean"


def fetch_city(
    city_key: str,
    lat: float,
    lon: float,
    start: str,
    end: str,
    cache_dir: Path,
) -> dict:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"openmeteo_{city_key}.json"

    if cache_path.exists():
        with cache_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": start,
        "end_date": end,
        "daily": DAILY_VARS,
        "timezone": "auto",
    }

    last_exc: Exception | None = None
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            print(f"    GET {OPEN_METEO_URL}  [{city_key}, attempt {attempt + 1}]", flush=True)
            r = requests.get(OPEN_METEO_URL, params=params, timeout=60)
            if r.status_code == 429:
                wait_s = 30 * (attempt + 1)
                print(f"    429 rate-limited, sleeping {wait_s}s", flush=True)
                time.sleep(wait_s)
                continue
            r.raise_for_status()
            payload = r.json()
            break
        except (requests.RequestException, ValueError) as e:
            last_exc = e
            if attempt < max_attempts - 1:
                time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(
            f"Failed to fetch {city_key} after {max_attempts} attempts: {last_exc}"
        ) from last_exc

    with cache_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f)

    return payload


def download_all(
    cities_config: dict,
    start: str,
    end: str,
    cache_dir: Path,
    inter_request_delay_s: float = 1.0,
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    cache_dir = Path(cache_dir)
    for city_key, params in cities_config.items():
        cached = (cache_dir / f"openmeteo_{city_key}.json").exists()
        print(f"  [{city_key}] {params['display_name']}{' (cached)' if cached else ''}", flush=True)
        out[city_key] = fetch_city(
            city_key=city_key,
            lat=params["latitude"],
            lon=params["longitude"],
            start=start,
            end=end,
            cache_dir=cache_dir,
        )
        if not cached and inter_request_delay_s > 0:
            time.sleep(inter_request_delay_s)
    return out
