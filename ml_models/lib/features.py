"""Feature engineering for the Transformer time-series input."""
from __future__ import annotations

import numpy as np
import pandas as pd

from sdg.schema import COMPONENT_IDS

WEATHER_COLS = ["ambient_temp_c", "humidity_pct"]
WORKLOAD_COLS = ["daily_print_hours", "cumulative_print_hours", "dust_concentration", "Q_demand"]
COUNTER_COLS = ["N_f", "N_c", "N_TC", "N_on"]
HEALTH_COLS = [f"H_{component_id}" for component_id in COMPONENT_IDS]
TAU_COLS = [f"tau_{component_id}" for component_id in COMPONENT_IDS]
LIFE_COLS = [f"L_{component_id}" for component_id in COMPONENT_IDS]
HOURS_SINCE_FAILURE_COLS = [f"hours_since_{component_id}_failure" for component_id in COMPONENT_IDS]
LAMBDA_COLS = [f"lambda_{component_id}" for component_id in COMPONENT_IDS]
CALENDAR_COLS = ["sin_doy", "cos_doy", "sin_month", "cos_month"]


def base_feature_columns() -> list[str]:
    return (
        WEATHER_COLS
        + WORKLOAD_COLS
        + COUNTER_COLS
        + HEALTH_COLS
        + TAU_COLS
        + LIFE_COLS
        + HOURS_SINCE_FAILURE_COLS
        + LAMBDA_COLS
        + CALENDAR_COLS
    )


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Append sin/cos day-of-year and month features."""
    if "date" not in df.columns:
        raise KeyError("expected a 'date' column")
    out = df.copy()
    dates = pd.to_datetime(out["date"])
    doy = dates.dt.dayofyear.to_numpy(dtype=np.float32)
    month = dates.dt.month.to_numpy(dtype=np.float32)
    out["sin_doy"] = np.sin(2.0 * np.pi * doy / 365.25).astype(np.float32)
    out["cos_doy"] = np.cos(2.0 * np.pi * doy / 365.25).astype(np.float32)
    out["sin_month"] = np.sin(2.0 * np.pi * month / 12.0).astype(np.float32)
    out["cos_month"] = np.cos(2.0 * np.pi * month / 12.0).astype(np.float32)
    return out


def transform_counters(df: pd.DataFrame) -> pd.DataFrame:
    """Apply log1p to large cumulative counters so they stay numerically tame."""
    out = df.copy()
    for column in COUNTER_COLS:
        out[column] = np.log1p(out[column].astype(np.float64)).astype(np.float32)
    return out


def build_feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Return a DataFrame with engineered features and the column ordering."""
    enriched = add_calendar_features(df)
    enriched = transform_counters(enriched)
    columns = base_feature_columns()
    missing = [column for column in columns if column not in enriched.columns]
    if missing:
        raise KeyError(f"missing required feature columns: {missing}")
    return enriched, columns
