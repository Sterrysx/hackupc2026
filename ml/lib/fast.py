"""Run-time knobs for the ML training pipeline.

Two env vars drive everything in ``ml/`` notebooks:

* ``FAST_MODE=1`` — switch every notebook to a minutes-scale smoke profile.
  This is useful for hackathon iteration and end-to-end artifact generation.
  Quality drops because we use fewer schedules, folds, trials, printers,
  dates, PPO updates, and seeds. Default: off (production-quality values).

* ``TRAIN_PARALLEL=N`` — number of parallel workers used by Optuna and by
  the per-printer simulator loops in Stage 01, 02-00, and 02-03. ``0`` or
  unset means "auto" → ``os.cpu_count() // 2`` (leaves headroom for the
  Jupyter kernel itself + IO). Single-digit explicit values override.

Importing this module is cheap and side-effect-free; it just reads env vars.
Notebooks should ``from ml.lib.fast import FAST_MODE, PARALLEL, ...``
and use the named constants in place of literal hyperparameter values.
"""

from __future__ import annotations

import os

import torch


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


FAST_MODE: bool = _env_flag("FAST_MODE")

# Parallel workers for CPU-bound simulator/Optuna loops. 0 → half of CPU count
# (capped at 12 to dodge SQLite contention with Optuna's RDB storage).
_requested_parallel = _env_int("TRAIN_PARALLEL", 0)
if _requested_parallel > 0:
    PARALLEL: int = _requested_parallel
else:
    PARALLEL = max(1, min(12, (os.cpu_count() or 2) // 2))


# ---- Stage-specific hyperparameter knobs --------------------------------- #

# Stage 01 — Optuna baseline τ search (sdg/core/simulator.py inside trial).
# 200 trials gives a strong TPE result; 60 still covers the space well thanks
# to the median pruner on warm-up steps.
N_OPTUNA_TRIALS: int = 40 if FAST_MODE else 200

# Stage 02-00 — number of LHS-sampled tau schedules in the SSL pretrain corpus.
# Fast mode writes to data/policy_runs_fast so smoke artifacts cannot poison
# the full data/policy_runs cache.
N_LHS_SCHEDULES: int = 4 if FAST_MODE else 60
POLICY_RUN_PRINTER_LIMIT: int | None = 12 if FAST_MODE else None

# Stage 02-01 — PatchTST self-supervised pretraining.
PRETRAIN_EPOCHS: int = 2 if FAST_MODE else 20

# Stage 02-02 — supervised RUL fine-tuning. Per-fold epoch count.
FINETUNE_EPOCHS: int = 1 if FAST_MODE else 3
FINETUNE_BATCH_SIZE: int = 256 if FAST_MODE else 128
FINETUNE_FOLDS: int = 1 if FAST_MODE else 4
FINETUNE_VARIANTS: tuple[str, ...] = ("ssl_frozen",) if FAST_MODE else ("ssl_frozen", "scratch")

# Stage 02-03 — Optuna over the simulator-backed surrogate.
SURROGATE_OPTUNA_TRIALS: int = 48 if FAST_MODE else 500
SURROGATE_TOP_K: int = 2 if FAST_MODE else 5
SURROGATE_DAYS: int | None = 730 if FAST_MODE else None
SURROGATE_TEST_PRINTER_LIMIT: int | None = 5 if FAST_MODE else None

# Stage 03-00 — sanity rollouts (random τ on a small printer subset).
SANITY_TRIALS: int = 5 if FAST_MODE else 100
SANITY_PRINTER_LIMIT: int = 2 if FAST_MODE else 5
SANITY_DAYS: int | None = 730 if FAST_MODE else None

# Stage 03-01 — bandit PPO.
BANDIT_PPO_TIMESTEPS: int = 192 if FAST_MODE else 2_000
BANDIT_TRAIN_DAYS: int = 365 if FAST_MODE else 730
BANDIT_VAL_DAYS: int | None = 730 if FAST_MODE else None
BANDIT_TEST_DAYS: int | None = 730 if FAST_MODE else None
BANDIT_TRAIN_PRINTER_LIMIT: int = 8 if FAST_MODE else 30
BANDIT_VAL_PRINTER_LIMIT: int | None = 3 if FAST_MODE else None
BANDIT_TEST_PRINTER_LIMIT: int | None = 5 if FAST_MODE else None
BANDIT_PPO_EPOCHS: int = 2 if FAST_MODE else 8
BANDIT_NET_ARCH: tuple[int, ...] = (64,) if FAST_MODE else (128, 128)

# Stage 03-04 — per-tick recurrent PPO (the runtime tentpole).
PERTICK_TIMESTEPS: int = 360 if FAST_MODE else 20_000
PERTICK_SEEDS: tuple[int, ...] = (0,) if FAST_MODE else (0, 1, 2)
PERTICK_TRAIN_DAYS: int = 365 if FAST_MODE else 730
PERTICK_VAL_DAYS: int = 365 if FAST_MODE else 1460
PERTICK_TEST_DAYS: int | None = 730 if FAST_MODE else None
PERTICK_TRAIN_PRINTER_LIMIT: int = 6 if FAST_MODE else 20
PERTICK_VAL_PRINTER_LIMIT: int = 2 if FAST_MODE else 5
PERTICK_TEST_PRINTER_LIMIT: int | None = 5 if FAST_MODE else None
PERTICK_N_STEPS: int = 90 if FAST_MODE else 180
PERTICK_BATCH_SIZE: int = 30 if FAST_MODE else 60
PERTICK_PPO_EPOCHS: int = 2 if FAST_MODE else 6
PERTICK_FEATURES_DIM: int = 32 if FAST_MODE else 64
PERTICK_HIDDEN_DIMS: tuple[int, ...] = (64,) if FAST_MODE else (128, 128)
PERTICK_BOOTSTRAP_RESAMPLES: int = 1000 if FAST_MODE else 10_000


# ---- Hardware preference -------------------------------------------------- #

def torch_device() -> "torch.device":
    """Always-prefer-GPU helper used by every notebook that touches torch.

    Notebooks already do ``torch.device('cuda' if torch.cuda.is_available()
    else 'cpu')``; this just centralizes that decision and prints a one-line
    summary so you can see in the output which device the run actually used.
    """
    if torch.cuda.is_available():
        n = torch.cuda.device_count()
        names = ", ".join(torch.cuda.get_device_name(i) for i in range(n))
        print(f"[fast] using CUDA · {n} GPU(s): {names}")
        return torch.device("cuda")
    print("[fast] using CPU (no CUDA)")
    return torch.device("cpu")


def banner() -> None:
    """One-shot, idempotent banner to print at the top of any notebook so the
    user can see in the executed output exactly what config was used."""
    mode = "FAST" if FAST_MODE else "FULL"
    print(
        f"[fast] mode={mode} · parallel={PARALLEL} · "
        f"trials={N_OPTUNA_TRIALS}/{SURROGATE_OPTUNA_TRIALS} · "
        f"K={N_LHS_SCHEDULES} · "
        f"epochs={PRETRAIN_EPOCHS}/{FINETUNE_EPOCHS} · folds={FINETUNE_FOLDS} · "
        f"ppo_ts={BANDIT_PPO_TIMESTEPS}/{PERTICK_TIMESTEPS} · "
        f"seeds={PERTICK_SEEDS}"
    )
