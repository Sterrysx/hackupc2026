from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .schema import COMPONENT_IDS, FINAL_SCHEMA, table_from_dataframe


def add_rul_labels(parquet_path: str | Path) -> None:
    """Read, augment with RUL columns, and atomically rewrite the Parquet file."""
    path = Path(parquet_path)
    tmp_path = path.with_name(f"{path.name}.tmp")
    df = pd.read_parquet(path)
    labeled = compute_rul_columns(df)
    table = table_from_dataframe(labeled, include_rul=True)
    if not table.schema.equals(FINAL_SCHEMA, check_metadata=False):
        raise ValueError("generated RUL table does not match FINAL_SCHEMA")
    try:
        pq.write_table(table, tmp_path, compression="snappy", version="2.6")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def compute_rul_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute component and system RUL labels from failure event booleans."""
    labeled = df.copy()
    for component_id in COMPONENT_IDS:
        labeled[f"rul_{component_id}"] = _component_rul(labeled, component_id)

    rul_columns = [f"rul_{component_id}" for component_id in COMPONENT_IDS]
    all_censored = labeled[rul_columns].isna().all(axis=1)
    system_rul = labeled[rul_columns].min(axis=1, skipna=True)
    labeled["rul_system"] = system_rul.mask(all_censored, pd.NA).astype("Int32")
    return labeled


def _component_rul(df: pd.DataFrame, component_id: str) -> pd.Series:
    result = pd.Series(pd.NA, index=df.index, dtype="Int32")
    failure_column = f"failure_{component_id}"

    for _printer_id, group in df.groupby("printer_id", sort=False):
        ordered = group.sort_values("day")
        days = ordered["day"].to_numpy(dtype=np.int32)
        failures = ordered[failure_column].to_numpy(dtype=bool)
        values = np.empty(len(ordered), dtype=np.int32)
        mask = np.ones(len(ordered), dtype=bool)

        last_failure_day: int | None = None
        for pos in range(len(ordered) - 1, -1, -1):
            if failures[pos]:
                values[pos] = 0
                mask[pos] = False
                last_failure_day = int(days[pos])
            elif last_failure_day is not None:
                values[pos] = last_failure_day - int(days[pos])
                mask[pos] = False

        result.loc[ordered.index] = pd.arrays.IntegerArray(values, mask)

    return result.astype("Int32")
