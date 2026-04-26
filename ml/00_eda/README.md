# Fleet Baseline EDA

This directory contains a reproducible exploratory data analysis for the SDG
fleet dataset at `data/train/fleet_baseline.parquet`.

## Run

From the repo root:

```bash
uv run jupyter nbconvert --to notebook --execute --inplace ml/00_eda/eda_fleet_baseline.ipynb
```

The notebook writes:

- `ml/00_eda/REPORT.md`
- deterministic PNG plots under `ml/00_eda/figures/`

To analyze another compatible SDG parquet output:

Edit the configuration cell at the top of `eda_fleet_baseline.ipynb`.

To regenerate only the Markdown report without touching plots:

Set `SKIP_PLOTS = True` in the configuration cell.

## Scope

The report covers:

- dataset shape, date range, printer coverage, city coverage, and climate coverage
- SDG column groups for weather, demand, health, status, tau, L, lambda, events, and RUL labels
- city and climate distributions
- weather and demand summaries by climate zone
- component health and status distributions for `C1`-`C6`
- maintenance and failure event counts
- component and system RUL label coverage
- sanity checks for row uniqueness, daily grid completeness, static city mapping, health bounds, event booleans, and RUL consistency

The notebook uses only dependencies already present in the project environment:
`pandas`, `pyarrow`, `numpy`, and `matplotlib`.
