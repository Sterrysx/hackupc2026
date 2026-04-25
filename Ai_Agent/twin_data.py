"""Read-only accessor over the Stage 1 simulator parquet (`data/fleet_baseline.parquet`).

Loads the parquet once on first access, then serves per-city / per-printer /
per-day slices to the FastAPI layer. Output shapes follow the frontend
telemetry contract (`frontend/src/types/telemetry.ts`) so an HTTP response
maps directly onto the React store with no conversion layer.

The parquet is treated as the source of truth for the timeline of
degradation; this module does not run the simulator itself.
"""
from __future__ import annotations

import os
from datetime import date as Date, datetime, time
from functools import lru_cache
from typing import Any, Iterable

import pandas as pd

from Ai_Agent.component_map import COMPONENTS, map_status
from Ai_Agent.derived_metrics import compute_metrics, primary_metric_key
from sdg.schema import COMPONENT_IDS

DEFAULT_PARQUET_PATH = os.path.join("data", "fleet_baseline.parquet")
DEFAULT_FORECAST_HORIZON_MIN = 45


def _resolve_path(path: str | None) -> str:
    if path is not None:
        return path
    env = os.environ.get("FLEET_PARQUET_PATH")
    return env if env else DEFAULT_PARQUET_PATH


@lru_cache(maxsize=4)
def _load_parquet(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    # ``city`` is stored as a pandas Categorical with all 15 cities as
    # categories. `.astype(str)` drops the categorical so downstream
    # comparisons work cleanly with bare Python strings.
    if hasattr(df["city"], "cat"):
        df["city"] = df["city"].astype(str)
    if hasattr(df["climate_zone"], "cat"):
        df["climate_zone"] = df["climate_zone"].astype(str)
    for cid in COMPONENT_IDS:
        col = f"status_{cid}"
        if hasattr(df[col], "cat"):
            df[col] = df[col].astype(str)
    return df


def get_dataset(path: str | None = None) -> pd.DataFrame:
    """Return the cached parquet DataFrame (loads it on first call)."""
    return _load_parquet(_resolve_path(path))


def reset_cache() -> None:
    """Clear the parquet cache. Used by tests with custom fixtures."""
    _load_parquet.cache_clear()


# ------------------------------------------------------------------ accessors


def list_cities(path: str | None = None) -> list[str]:
    df = get_dataset(path)
    return sorted(df["city"].unique().tolist())


def list_printers(city: str, path: str | None = None) -> list[int]:
    """Return printer ids assigned to a city, ascending."""
    df = get_dataset(path)
    matches = df.loc[df["city"] == city, "printer_id"]
    if matches.empty:
        raise KeyError(f"unknown city: {city!r}")
    return sorted(int(p) for p in matches.unique())


def day_range(path: str | None = None) -> tuple[int, int]:
    """Return the (min, max) `day` value present in the dataset."""
    df = get_dataset(path)
    return int(df["day"].min()), int(df["day"].max())


# --------------------------------------------------------- snapshot building


def _row_for(city: str, printer_id: int, day: int, df: pd.DataFrame) -> pd.Series:
    mask = (
        (df["city"] == city)
        & (df["printer_id"] == int(printer_id))
        & (df["day"] == int(day))
    )
    sub = df.loc[mask]
    if sub.empty:
        raise KeyError(
            f"no row for city={city!r} printer_id={printer_id} day={day}"
        )
    if len(sub) > 1:
        raise RuntimeError(
            f"multiple rows for city={city!r} printer_id={printer_id} day={day}"
        )
    return sub.iloc[0]


def _iso_timestamp(d: Date | datetime) -> str:
    if isinstance(d, datetime):
        return d.isoformat()
    return datetime.combine(d, time(12, 0, 0)).isoformat()


def _build_drivers(row: pd.Series) -> dict[str, float]:
    return {
        "ambientTempC": float(row["ambient_temp_c"]),
        "humidityPct": float(row["humidity_pct"]),
        "contaminationPct": float(row["dust_concentration"]),
        "loadPct": float(row["jobs_today"]),
        "maintenanceCoeff": 1.0,
    }


def _build_components(row: pd.Series) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for info in COMPONENTS:
        sid = info.sim_id
        sim_status = str(row[f"status_{sid}"])
        out.append({
            "id": info.frontend_id,
            "label": info.label,
            "subsystem": info.subsystem,
            "healthIndex": float(row[f"H_{sid}"]),
            "status": map_status(sim_status),
            "metrics": compute_metrics(row, sid),
            "primaryMetricKey": primary_metric_key(sid),
        })
    return out


def get_snapshot(
    city: str,
    printer_id: int,
    day: int,
    *,
    path: str | None = None,
    forecast_horizon_min: int = DEFAULT_FORECAST_HORIZON_MIN,
) -> dict[str, Any]:
    """Return a single SystemSnapshot-shaped dict for one (city, printer, day)."""
    df = get_dataset(path)
    row = _row_for(city, printer_id, day, df)
    return {
        "timestamp": _iso_timestamp(row["date"]),
        "tick": int(row["day"]),
        "drivers": _build_drivers(row),
        "components": _build_components(row),
        "forecasts": [],  # populated by the Stage 2 forecast endpoint
        "forecastHorizonMin": int(forecast_horizon_min),
    }


# ---------------------------------------------------------------- timelines


_TIMELINE_ALLOWED_COLUMNS: frozenset[str] = frozenset(
    ["day", "date", "ambient_temp_c", "humidity_pct",
     "dust_concentration", "Q_demand", "jobs_today",
     "N_f", "N_c", "N_TC", "N_on"]
    + [f"H_{c}"      for c in COMPONENT_IDS]
    + [f"status_{c}" for c in COMPONENT_IDS]
    + [f"tau_{c}"    for c in COMPONENT_IDS]
    + [f"L_{c}"      for c in COMPONENT_IDS]
    + [f"lambda_{c}" for c in COMPONENT_IDS]
    + [f"maint_{c}"  for c in COMPONENT_IDS]
    + [f"failure_{c}" for c in COMPONENT_IDS]
)


def get_timeline(
    city: str,
    printer_id: int,
    fields: Iterable[str],
    *,
    day_from: int | None = None,
    day_to: int | None = None,
    path: str | None = None,
) -> dict[str, list]:
    """Return per-field arrays for a printer's timeline.

    Always includes ``"day"`` so callers can align the X-axis. ``fields`` is
    validated against the parquet schema; unknown columns raise ``KeyError``
    rather than silently dropping data.
    """
    requested = list(fields)
    bad = [f for f in requested if f not in _TIMELINE_ALLOWED_COLUMNS]
    if bad:
        raise KeyError(f"unknown timeline fields: {bad}")

    df = get_dataset(path)
    mask = (df["city"] == city) & (df["printer_id"] == int(printer_id))
    if day_from is not None:
        mask &= df["day"] >= int(day_from)
    if day_to is not None:
        mask &= df["day"] <= int(day_to)
    sub = df.loc[mask].sort_values("day")
    if sub.empty:
        raise KeyError(
            f"no timeline rows for city={city!r} printer_id={printer_id}"
        )

    out: dict[str, list] = {"day": sub["day"].astype(int).tolist()}
    for col in requested:
        if col == "day":
            continue
        if col == "date":
            out["date"] = [_iso_timestamp(d).split("T")[0] for d in sub["date"]]
        else:
            series = sub[col]
            if series.dtype == bool:
                out[col] = series.astype(bool).tolist()
            elif "int" in str(series.dtype).lower():
                out[col] = series.astype(int).tolist()
            elif "float" in str(series.dtype).lower():
                out[col] = series.astype(float).tolist()
            else:
                out[col] = series.astype(str).tolist()
    return out
