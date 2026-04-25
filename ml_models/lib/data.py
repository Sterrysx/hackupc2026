"""Parquet loading and printer-level train/val/test splits."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from ml_models import PROJECT_ROOT
from sdg.generate import EXPECTED_PRINTERS

DEFAULT_FLEET_PATH = PROJECT_ROOT / "data" / "fleet_baseline.parquet"
TRAIN_PRINTERS: tuple[int, ...] = tuple(range(0, 70))
VAL_PRINTERS: tuple[int, ...] = tuple(range(70, 85))
TEST_PRINTERS: tuple[int, ...] = tuple(range(85, 100))


def printer_split() -> dict[str, tuple[int, ...]]:
    """Return the canonical printer-id partition shared by all stages."""
    if (
        len(TRAIN_PRINTERS) + len(VAL_PRINTERS) + len(TEST_PRINTERS)
        != EXPECTED_PRINTERS
    ):
        raise AssertionError("printer split must cover all 100 printers")
    if set(TRAIN_PRINTERS) & set(VAL_PRINTERS):
        raise AssertionError("train and val printer sets overlap")
    if set(VAL_PRINTERS) & set(TEST_PRINTERS):
        raise AssertionError("val and test printer sets overlap")
    return {
        "train": TRAIN_PRINTERS,
        "val": VAL_PRINTERS,
        "test": TEST_PRINTERS,
    }


def load_fleet(path: str | Path = DEFAULT_FLEET_PATH) -> pd.DataFrame:
    """Read the deterministic fleet parquet produced by sdg.generate."""
    df = pd.read_parquet(path)
    if df.empty:
        raise ValueError(f"empty fleet parquet at {path}")
    return df


def filter_printers(df: pd.DataFrame, printer_ids: Iterable[int]) -> pd.DataFrame:
    """Return rows whose printer_id is in the requested set."""
    ids = {int(pid) for pid in printer_ids}
    return df.loc[df["printer_id"].isin(ids)].reset_index(drop=True)


def to_panel_tensor(
    df: pd.DataFrame,
    feature_cols: list[str],
    *,
    group_col: str = "printer_id",
    time_col: str = "day",
) -> tuple[np.ndarray, list[int]]:
    """Stack a long DataFrame into a (N_groups, T, F) numpy array."""
    sorted_df = df.sort_values([group_col, time_col]).reset_index(drop=True)
    groups = sorted_df[group_col].unique().tolist()
    panels: list[np.ndarray] = []
    for group_id in groups:
        chunk = sorted_df.loc[
            sorted_df[group_col] == group_id, feature_cols
        ].to_numpy(dtype=np.float32)
        panels.append(chunk)
    lengths = {p.shape[0] for p in panels}
    if len(lengths) != 1:
        raise ValueError(f"groups have inconsistent lengths: {lengths}")
    return np.stack(panels, axis=0), groups
