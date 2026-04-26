"""Read-only accessor for the forward-projected prediction parquet
(``data/prediction/fleet_2026_2035.parquet``).

The validation parquet is a 10-year forward simulation of the operator-facing
fleet (10 cities, 100 printers, 2026-01-01 .. 2035-12-31, ~365 200 rows). It
shares the same 70-column schema as ``fleet_baseline.parquet`` plus the
pre-computed ``rul_C{i}`` / ``rul_system`` labels — i.e. the model's
predicted remaining-useful-life **per day** for every component.

This module is the analytics-side counterpart of ``twin_data``: same shape
helpers (timeline, ``hours_since_failure`` etc.), different parquet, and
cities are kept in their native operator-facing names (``singapore``,
``dubai``, ``mumbai``…) so no Europe-remap layer is needed.

The frontend uses this endpoint exclusively for the **predictive trajectory**
analytics tile, where the full 10-year curve is sampled once per
(city, printer) and the cursor advances with the playback tick. Live mode
freezes the cursor at the current day; play mode walks it forward.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Iterable

import pandas as pd

from backend.simulator.schema import COMPONENT_IDS

DEFAULT_VALIDATION_PARQUET_PATH = os.path.join(
    "data", "prediction", "fleet_2026_2035.parquet"
)


def _resolve_path(path: str | None) -> str:
    if path is not None:
        return path
    env = os.environ.get("VALIDATION_PARQUET_PATH")
    return env if env else DEFAULT_VALIDATION_PARQUET_PATH


@lru_cache(maxsize=2)
def _load_parquet(path: str) -> pd.DataFrame:
    df = pd.read_parquet(path)
    # Same Categorical-stripping pass as `twin_data._load_parquet` so string
    # comparisons against `city` / `status_*` work without coerce surprises.
    if hasattr(df["city"], "cat"):
        df["city"] = df["city"].astype(str)
    if "climate_zone" in df.columns and hasattr(df["climate_zone"], "cat"):
        df["climate_zone"] = df["climate_zone"].astype(str)
    for cid in COMPONENT_IDS:
        col = f"status_{cid}"
        if col in df.columns and hasattr(df[col], "cat"):
            df[col] = df[col].astype(str)
    return df


def get_dataset(path: str | None = None) -> pd.DataFrame:
    return _load_parquet(_resolve_path(path))


def reset_cache() -> None:
    _load_parquet.cache_clear()


# ----------------------------------------------------------------- accessors


def list_cities(path: str | None = None) -> list[str]:
    df = get_dataset(path)
    return sorted(df["city"].unique().tolist())


def list_printers(city: str, path: str | None = None) -> list[int]:
    df = get_dataset(path)
    matches = df.loc[df["city"] == city, "printer_id"]
    if matches.empty:
        raise KeyError(f"unknown city: {city!r}")
    return sorted(int(p) for p in matches.unique())


def day_range(path: str | None = None) -> tuple[int, int]:
    df = get_dataset(path)
    return int(df["day"].min()), int(df["day"].max())


# ------------------------------------------------------------------ timeline


# Mirror `twin_data._TIMELINE_ALLOWED_COLUMNS` plus the validation-only
# `rul_C{i}` / `rul_system` labels.
_BASE_COLUMNS: list[str] = (
    ["day", "date", "ambient_temp_c", "humidity_pct",
     "dust_concentration", "Q_demand",
     "daily_print_hours", "cumulative_print_hours",
     "N_f", "N_c", "N_TC", "N_on"]
    + [f"H_{c}"                     for c in COMPONENT_IDS]
    + [f"status_{c}"                for c in COMPONENT_IDS]
    + [f"tau_{c}"                   for c in COMPONENT_IDS]
    + [f"L_{c}"                     for c in COMPONENT_IDS]
    + [f"lambda_{c}"                for c in COMPONENT_IDS]
    + [f"maint_{c}"                 for c in COMPONENT_IDS]
    + [f"failure_{c}"               for c in COMPONENT_IDS]
    + [f"rul_{c}"                   for c in COMPONENT_IDS]
    + ["rul_system"]
)
_TIMELINE_ALLOWED_COLUMNS: frozenset[str] = frozenset(_BASE_COLUMNS)


def get_timeline(
    city: str,
    printer_id: int,
    fields: Iterable[str],
    *,
    day_from: int | None = None,
    day_to: int | None = None,
    path: str | None = None,
) -> dict[str, list]:
    """Return per-field arrays for a printer's predicted timeline.

    Same contract as ``twin_data.get_timeline`` but draws from the validation
    parquet. Always includes ``"day"``. Validates field names against the
    allow list — unknown columns raise ``KeyError`` (HTTP 404 from FastAPI).
    """
    requested = list(fields)
    bad = [f for f in requested if f not in _TIMELINE_ALLOWED_COLUMNS]
    if bad:
        raise KeyError(f"unknown prediction-timeline fields: {bad}")

    df = get_dataset(path)
    mask = (df["city"] == city) & (df["printer_id"] == int(printer_id))
    if day_from is not None:
        mask &= df["day"] >= int(day_from)
    if day_to is not None:
        mask &= df["day"] <= int(day_to)
    sub = df.loc[mask].sort_values("day")
    if sub.empty:
        raise KeyError(
            f"no validation rows for city={city!r} printer_id={printer_id}"
        )

    out: dict[str, list] = {"day": sub["day"].astype(int).tolist()}
    for col in requested:
        if col == "day":
            continue
        if col == "date":
            out["date"] = [
                (d.isoformat() if hasattr(d, "isoformat") else str(d))
                for d in sub["date"]
            ]
            continue
        series = sub[col]
        if series.dtype == bool:
            out[col] = series.astype(bool).tolist()
        elif "int" in str(series.dtype).lower():
            # rul_C{i} columns are nullable Int32 — cast None-safe.
            out[col] = [None if pd.isna(v) else int(v) for v in series.tolist()]
        elif "float" in str(series.dtype).lower():
            out[col] = series.astype(float).tolist()
        else:
            out[col] = series.astype(str).tolist()
    return out
