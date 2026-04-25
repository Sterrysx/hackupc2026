# Stage 03 — RL on top of the SSL encoder

PPO over a per-printer τ policy, conditioned on the **frozen Stage 02
PatchTST encoder**. Strictly extends Stage 02's policy class: a constant
policy that ignores the observation recovers Stage 02's fleet-wide τ, so
the worst case for Stage 03 is a tie. The best case adapts τ to local
climate / load and reduces fleet annual cost while keeping availability ≥ 95 %.

## Why this beats SSL alone

Stages 01 (Optuna) and 02 (SSL surrogate) both ship **one fleet-wide τ**
applied to every printer regardless of city, climate or load. Two
mechanisms give Stage 03 strictly more headroom:

1. **Per-printer τ.** The PPO policy sees the SSL embedding of the printer's
   first-year telemetry plus city one-hot + climate stats, and emits a
   τ tuned to *that* printer.
2. **Real-simulator reward.** Stage 02 picks τ by scoring it with a
   surrogate (RUL head + analytical event-rate model). Stage 03 trains
   directly against `lib.objective.scalar_objective` — no surrogate bias.

## Architecture

```
features[printer_id, :360 days]   ← lib.features.build_feature_matrix
        │
        │  per-channel scaler   (02_ssl/models/feature_scaler.npz)
        │  PatchTST encoder, frozen   (02_ssl/models/ssl_encoder.pt)
        ▼
z ∈ ℝ^{d_model}                              # 256-d Stage 02 default
        ⊕ city_one_hot ∈ {0,1}^15
        ⊕ climate_summary ∈ ℝ^4              # mean/std temp & humidity
        ▼
obs ∈ ℝ^{d_model + 19}                       # 275-d w/ default d_model
        │  PPO MlpPolicy (Tanh, 2×128)
        ▼
action ∈ [-1, 1]^6 → log-uniform → τ ∈ ℝ^6   (per-component bounds match Stages 01/02)
        │  lib.env_runner.run_with_tau (full 10-yr horizon at eval)
        ▼
reward (training) = -(annual_cost / 1e6 + 100 · max(0, 0.95 - availability))
reward (eval)     = lib.objective.scalar_objective(...)["value"]   (Stage 01/02 contract)
```

## Layout

```
03_rl+ssl/
├── 00_setup_and_sanity.ipynb   build env, run 100 random τ, plot reward histogram
├── 01_train_ppo.ipynb          warm-start from Stage 02 τ + train PPO + log curves
├── 02_eval_test.ipynb          held-out test eval, re-score Stages 01 & 02 alongside
├── 03_compare.ipynb            bar / scatter / per-printer τ heatmap + cost delta
├── tests/
│   └── test_gym_env.py         action↔τ math, env shapes, determinism
├── models/                     ppo_policy_best.zip, ppo_policy_final.zip
├── results/                    per_printer_tau_test*.csv, kpi_comparison.csv,
│                               training_curves.{json,png}, plots
└── README.md
```

The actual Python library lives at `ml_models/lib/rl/` (importable as
`ml_models.lib.rl`) — the stage folder name has a `+` so it can't itself be
a Python package.

## Reusable building blocks

| File | Used for |
|---|---|
| `ml_models/lib/rl/encoder_loader.py` | Frozen PatchTST encoder + scaler |
| `ml_models/lib/rl/gym_env.py` | `MaintenanceBanditEnv` (one-shot bandit) |
| `ml_models/lib/rl/policy.py` | Warm-start helper, `MlpPolicy` defaults |
| `ml_models/lib/rl/ppo_trainer.py` | `train_ppo`, validation callback |
| `ml_models/lib/rl/eval.py` | Test-set evaluation matching Stage 01/02 contract |
| `ml_models/lib/env_runner.run_with_tau` | Forward simulation per printer |
| `ml_models/lib/objective.scalar_objective` | Reward source / fleet KPI |

## Run order

1. Make sure Stages 01 and 02 are done (their YAMLs live under
   `01_baseline/results/best_tau.yaml` and
   `02_ssl/results/best_tau_surrogate.yaml`). Stage 03 will warm-start
   from the Stage 02 τ if found, and the test eval re-runs both
   stages on the held-out printers.
2. `00_setup_and_sanity.ipynb` — wire check (random-τ reward histogram).
3. `01_train_ppo.ipynb` — train PPO, save `models/ppo_policy_best.zip`.
4. `02_eval_test.ipynb` — score on test printers, build
   `kpi_comparison.csv` and `per_printer_tau_test.csv`.
5. `03_compare.ipynb` — visualise + headline metrics for the report.

## Tests

```bash
uv run pytest ml_models/03_rl+ssl/tests/ -v
```

The suite covers:
- `action_to_tau` ↔ `tau_to_action` round-trip and bound mapping.
- Env action / observation shapes.
- Step contract (reward sign, info dict keys).
- Determinism (same seed + same τ → same reward).

Tests are designed to pass on a fresh checkout — they fall back to a
randomly-initialised encoder when Stage 02 artefacts aren't present.

## Done criteria for the report

- [ ] `kpi_comparison.csv`: `stage_03.fleet_value < stage_02.fleet_value` on test printers.
- [ ] `stage_03.fleet_availability ≥ 0.95`.
- [ ] `per_printer_tau_heatmap.png` shows actual τ variation across printers — otherwise the policy collapsed and Stage 03 reduces to Stage 02.
- [ ] `training_curves.png` shows monotonic val-value improvement.

## Notes on hyperparameters

The defaults in `01_train_ppo.ipynb` are tuned for a few-hours hackathon
budget on CPU:

- `total_timesteps = 2_000` (≈ 30 PPO updates with `n_steps=64`)
- `TRAIN_DATES = first 730 days` (2-yr training horizon, full 10-yr at val/test)
- `TRAIN_PRINTER_SUBSET = 30/70 train printers`
- Warm-start from Stage 02 τ when available

Bigger budget ideas if a GPU is available:
- Full 10-yr training horizon → longer per-step but truer reward.
- All 70 train printers + `total_timesteps = 20_000`.
- `RecurrentPPO` from `sb3-contrib` for a stretch per-tick policy that
  decides each day whether to maintain — strictly more expressive, but
  needs the SDG simulator to expose a step-by-step interface, which is
  out of scope for this stage.
