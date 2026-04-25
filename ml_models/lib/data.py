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


def stratified_printer_split(
    seed: int = 0,
    train_frac: float = 0.70,
    val_frac: float = 0.15,
) -> dict[str, tuple[int, ...]]:
    """Climate-stratified printer split (opt-in alternative to ``printer_split``).

    The default ``printer_split`` partitions printers by ID range, which on the
    current ``CITY_PRINTER_COUNTS`` layout is climate-imbalanced — train sees
    only nordic / continental / oceanic / mediterranean (Barcelona only), while
    test gets all-eastern. That breaks SSL generalisation on test.

    This helper distributes printers from each climate zone proportionally
    across train / val / test, so every split sees every climate. Returns the
    same shape as :func:`printer_split` and is a drop-in replacement once a
    fresh SSL encoder is trained against it.

    Note: the existing trained SSL encoder under
    ``ml_models/02_ssl/models/ssl_encoder.pt`` was fitted on the legacy
    ``printer_split``. Calling this helper changes which printers feed
    SSL pretraining, so retraining is required before the surrogate /
    Stage 03 evals are valid.
    """
    from sdg.generate import build_printer_city_map, load_configs

    _, _, cities_cfg = load_configs()
    printer_city_map = build_printer_city_map(list(cities_cfg["cities"]))
    by_zone: dict[str, list[int]] = {}
    for printer_id, profile in enumerate(printer_city_map):
        by_zone.setdefault(profile["climate_zone"], []).append(printer_id)

    rng = np.random.default_rng(seed)
    train: list[int] = []
    val: list[int] = []
    test: list[int] = []
    for zone, ids in sorted(by_zone.items()):
        ids = list(ids)
        rng.shuffle(ids)
        n = len(ids)
        n_train = int(round(n * train_frac))
        n_val = int(round(n * val_frac))
        # remainder goes to test
        train.extend(ids[:n_train])
        val.extend(ids[n_train : n_train + n_val])
        test.extend(ids[n_train + n_val :])
    if len(train) + len(val) + len(test) != EXPECTED_PRINTERS:
        raise AssertionError("stratified split must cover all 100 printers")
    return {
        "train": tuple(sorted(train)),
        "val": tuple(sorted(val)),
        "test": tuple(sorted(test)),
    }


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
