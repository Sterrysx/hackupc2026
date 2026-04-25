# Stage Results Comparison

This directory compares the three maintenance-policy stages:

- Stage 01: Optuna baseline over one constant tau vector.
- Stage 02: SSL/RUL surrogate search over one constant tau vector.
- Stage 03: RL policies, with the per-tick PPO+SPR ensemble used as the main Stage 03 result.

Run from the repo root:

```bash
uv run jupyter nbconvert --to notebook --execute --inplace ml_models/04_models/results/compare_01_02_03.ipynb
```

Outputs:

- `REPORT.md` - narrative comparison with tables and interpretation.
- `stage_kpis.csv` - normalized Stage 01/02/03 KPI table.
- `tau_comparison.csv` - fixed/per-printer tau comparison.
- `stage03_auxiliary_kpis.csv` - earlier Stage 03 per-printer tau KPI for context.
- `stage03_per_tick_printer_summary.csv` - per-printer rows for the per-tick ensemble.
- `figures/` - deterministic PNG charts.
