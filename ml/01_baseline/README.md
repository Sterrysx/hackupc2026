# Stage 01 — Baseline (no ML)

Bayesian optimisation directly over the 6-dim maintenance-interval vector
$\tau = (\tau_{C1},\dots,\tau_{C6})$, using the SDG simulator inside the
optimiser's inner loop.

## Files

- `search.ipynb` — the full Optuna search: stratified-printer trials,
  full-fleet re-evaluation of the top-K candidates, and persistence of the
  winner to `results/best_tau.yaml`.
- `results/study.db` — SQLite storage of the Optuna study (resumable).
- `results/best_tau.yaml` — winning τ + KPIs (created at the end of the notebook).
- `tests/test_objective.py` — unit tests for `lib/objective.py`.

## Method (in 5 bullets)

1. Search space: `lib.env_runner.TAU_RANGES` (log-uniform priors anchored on
   `ai-context/digital_twin_hp_metal_jet_s100_spec.md` §6).
2. Trial subset: one printer per city (15 printers) for the full 10-year
   window — keeps trials affordable, captures climate diversity.
3. Sampler: TPE with seed 42; pruner: median (warm-up 5 trials).
4. Top-K candidates re-evaluated on all 100 printers for an unbiased ranking.
5. Objective: `lib.objective.scalar_objective` =
   per-printer annual cost + 1e6 × max(0, 0.95 − availability).

## Headline KPIs to record

- Best annual cost (€/printer/year).
- Best availability (must be ≥ 95% to satisfy the constraint).
- Wall-clock for the full study.
- Number of trials before the best-so-far curve flattens.

These are the numbers Stage 02 must beat or match faster.
