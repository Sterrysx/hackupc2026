"""Run-time knobs for the ML training pipeline.

Two env vars drive everything in ``ml_models/`` notebooks:

* ``FAST_MODE=1`` — switch every notebook to a smaller, faster set of
  hyperparameters. Useful for the first pass on a new machine or a sanity
  check. Quality drops but the full pipeline finishes in a fraction of the
  time. Default: off (production-quality values).

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
N_OPTUNA_TRIALS: int = 60 if FAST_MODE else 200

# Stage 02-00 — number of LHS-sampled τ schedules in the SSL pretrain corpus.
# Each schedule = ~21 MB on disk, 70 printers × 10 yr of rows. K=20 is the
# minimum that gives the encoder a useful τ-conditioned view; K=60 is the
# committed corpus that ships in the repo.
N_LHS_SCHEDULES: int = 20 if FAST_MODE else 60

# Stage 02-01 — PatchTST self-supervised pretraining.
PRETRAIN_EPOCHS: int = 8 if FAST_MODE else 20

# Stage 02-02 — supervised RUL fine-tuning. Per-fold epoch count.
FINETUNE_EPOCHS: int = 2 if FAST_MODE else 3

# Stage 02-03 — Optuna over the smooth surrogate (cheap; trials are <1ms).
SURROGATE_OPTUNA_TRIALS: int = 200 if FAST_MODE else 500

# Stage 03-00 — sanity rollouts (random τ on a small printer subset).
SANITY_TRIALS: int = 30 if FAST_MODE else 100

# Stage 03-01 — bandit PPO.
BANDIT_PPO_TIMESTEPS: int = 1_000 if FAST_MODE else 2_000

# Stage 03-04 — per-tick recurrent PPO (the runtime tentpole).
PERTICK_TIMESTEPS: int = 8_000 if FAST_MODE else 20_000
PERTICK_SEEDS: tuple[int, ...] = (0, 1) if FAST_MODE else (0, 1, 2)


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
        f"epochs={PRETRAIN_EPOCHS}/{FINETUNE_EPOCHS} · "
        f"ppo_ts={BANDIT_PPO_TIMESTEPS}/{PERTICK_TIMESTEPS} · "
        f"seeds={PERTICK_SEEDS}"
    )
