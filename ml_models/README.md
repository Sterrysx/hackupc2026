# `ml_models/` — maintenance-policy modelling ladder

This directory implements a progressive ladder of approaches to the optimisation
problem stated in [`CONTEXT.md`](../CONTEXT.md) §10:

```
minimize  E[per-printer annual cost]   (preventive + corrective €/yr)
subject to  availability >= 95%
action     τ = (τ_C1, τ_C2, τ_C3, τ_C4, τ_C5, τ_C6)   maintenance intervals (h)
```

| Stage | Method | Status |
|-------|--------|--------|
| `00_eda/` | Exploratory data analysis over the SDG fleet baseline | ✅ implemented |
| `01_baseline/` | No ML — Optuna over τ calling the SDG simulator directly | ✅ implemented |
| `02_ssl/` | PatchTST self-supervised pretrain → frozen-encoder RUL head → surrogate-driven τ search | ✅ implemented |
| `03_rl+ssl/` | PPO + frozen Stage 02 encoder → per-printer/per-tick policies | ✅ implemented |
| `04_models/results/` | Final comparison report across Stages 01/02/03 | ✅ implemented |

## Data splits (printer-level)

Defined once in `lib/data.py` so every stage uses the same partition:

| Split | Printer ids | Count | Used for |
|-------|-------------|-------|----------|
| Train | 0..69 | 70 | SSL pretraining + supervised fine-tuning training set |
| Val | 70..84 | 15 | Sliding-cumulative time-series CV (HP selection, early stopping) |
| Test | 85..99 | 15 | Final unseen evaluation (Stage 02 reports here) |

The validation folds inside printers 70..84 use an expanding-window CV
(`lib/splits.expanding_window_folds`) to mirror real deployment, where
the model only ever sees past data.

## How to run

Always execute via `uv run` so the project's pinned environment is used:

```bash
# core deps + ML deps
uv sync

# Run everything end-to-end: 00, 01, 02, 03, then 04
./train.sh

# Stage 00 EDA
uv run jupyter lab ml_models/00_eda/eda_fleet_baseline.ipynb

# Stage 01 baseline (pure simulator + Optuna; CPU-only is fine)
uv run jupyter lab ml_models/01_baseline/search.ipynb

# Stage 02 SSL (CUDA recommended — uses HuggingFace PatchTST)
uv run jupyter lab ml_models/02_ssl/00_generate_policy_runs.ipynb
uv run jupyter lab ml_models/02_ssl/01_pretrain.ipynb
uv run jupyter lab ml_models/02_ssl/02_finetune_rul.ipynb
uv run jupyter lab ml_models/02_ssl/03_surrogate_search.ipynb

# Stage 03 RL+SSL (uses Stage 02 encoder; CPU is fine, GPU helps PPO updates)
uv run jupyter lab ml_models/03_rl+ssl/00_setup_and_sanity.ipynb
uv run jupyter lab ml_models/03_rl+ssl/01_train_ppo.ipynb
uv run jupyter lab ml_models/03_rl+ssl/02_eval_test.ipynb
uv run jupyter lab ml_models/03_rl+ssl/03_compare.ipynb
uv run jupyter lab ml_models/03_rl+ssl/04_per_tick_recurrent_ppo.ipynb

# Stage 04 results comparison
uv run jupyter lab ml_models/04_models/results/compare_01_02_03.ipynb

# Tests (lib code only; notebooks are not exercised in CI)
uv run pytest sdg/tests ml_models/01_baseline/tests ml_models/02_ssl/tests ml_models/03_rl+ssl/tests
```

## GPU configuration (2× RTX 3090)

The SSL notebooks default to `torch.device('cuda' if available else 'cpu')` and
opportunistically wrap the model in `nn.DataParallel` if more than one GPU is
visible. For larger sweeps, prefer DDP via `accelerate launch` from the CLI
(see HuggingFace `accelerate` docs); the notebook code is DDP-compatible.

**Windows note:** `uv add torch` pulls a CPU wheel by default on Windows
(verified here: this repo currently has `torch==2.11.0+cpu`). The Stage 02
notebooks will still run, but training will be ~50× slower. To pick up the
3090s, install the CUDA wheel explicitly:

```bash
# inside the project's .venv (uv run gives you the right interpreter)
uv pip install --upgrade --index https://download.pytorch.org/whl/cu124 torch
```

After the upgrade, verify with:

```bash
uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"
# expected: True 2
```

## What `lib/` provides

Single source of truth for cross-stage utilities (no Python module names with
digits or `+`, so all imports are clean):

- `lib/data.py` — parquet loading + canonical printer split.
- `lib/splits.py` — expanding-window time-series CV folds.
- `lib/objective.py` — cost / availability / scalar objective from event booleans.
- `lib/env_runner.py` — runs `sdg.simulator.run_printer` with a custom τ vector
  (deterministic per printer; reuses the existing `np.random.default_rng(printer_id)`).
- `lib/features.py` — feature engineering (calendar sin/cos, log1p counters,
  health/τ/L/lambda channels) used by the Transformer.
- `lib/plotting.py` — shared matplotlib helpers.
- `lib/rl/` — Stage 03 RL building blocks (frozen-encoder loader,
  `MaintenanceBanditEnv`, PPO trainer, eval helpers). Lives here rather than
  inside `03_rl+ssl/` because the stage folder name has `+` and can't be a
  Python package.

## Numbering note on `03_rl+ssl/`

The literal `+` in `03_rl+ssl/` means that folder is **not** a Python package
(it can't be one — `+` is invalid in module names). All importable code lives
in `ml_models/lib/`; the numbered folders only host scripts, notebooks, and
artefacts. Notebooks import via `from ml_models.lib.* import …`, which is
unaffected by sibling folder names.
