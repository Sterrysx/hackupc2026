"""Sliding-cumulative (expanding) window time-series CV folds."""
from __future__ import annotations


def expanding_window_folds(
    n_days: int,
    n_folds: int = 4,
    min_train_days: int = 1800,
    val_days: int = 400,
) -> list[tuple[range, range]]:
    """Yield (train_idx, val_idx) day-index ranges for each fold.

    Each fold's train window is [0, train_end), val is [train_end, train_end + val_days).
    train_end advances by `step` between folds so the train window grows.
    """
    if n_days < min_train_days + val_days:
        raise ValueError("n_days too small for the requested fold layout")
    if n_folds < 1:
        raise ValueError("n_folds must be >= 1")

    available = n_days - min_train_days - val_days
    step = available // max(n_folds - 1, 1) if n_folds > 1 else 0

    folds: list[tuple[range, range]] = []
    for i in range(n_folds):
        train_end = min_train_days + i * step
        val_end = train_end + val_days
        if val_end > n_days:
            break
        folds.append((range(0, train_end), range(train_end, val_end)))
    return folds
