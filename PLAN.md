# PLAN - Synthetic Data Generator (Act 1)

Scope: only Act 1, the offline synthetic data generator. Acts 2 (SSL/RUL)
and 3 (RL) are out of scope and consume only the Parquet file produced here.

## Context

The Act 1 deliverable is a deterministic, schema-stable training dataset for a
Digital Twin pipeline for the HP Metal Jet S100. The simulator lives under
`sdg/` and is independent from downstream ML/RL code.

Non-negotiables:

1. Same code, configs, and printer ids must produce byte-identical Parquet.
2. The simulator does not import ML/RL code. Downstream stages read Parquet.

## Dataset Shape

- Date range: 2015-01-01 through 2024-12-31, daily, keeping leap days.
- Days per printer: 3,653.
- Cities: 15 European cities, 5 climate zones, 3 cities each.
- Printers: 100 total, ids 0..99.
- City allocation: 10 cities with 7 printers each, 5 cities with 6 printers each.
- Rows: 100 * 3,653 = 365,300.
- `day` is `(date - 2015-01-01).days`, per printer, spanning 0..3652.

## Output

The generated file is `data/fleet_baseline.parquet`. It contains one row per
`(printer_id, day)` with frozen column names and Arrow types:

- Identity: `printer_id`, `city`, `climate_zone`, `date`, `day`
- Drivers: `ambient_temp_c`, `humidity_pct`
- Endogenous drivers: `dust_concentration`, `Q_demand`
- Workload: `jobs_today`
- Component state: `H_C1..H_C6`, `status_C1..status_C6`,
  `tau_C1..tau_C6`, `L_C1..L_C6`
- Counters: `N_f`, `N_c`, `N_TC`, `N_on`
- Rates and events: `lambda_C1..lambda_C6`, `maint_C1..maint_C6`,
  `failure_C1..failure_C6`
- Labels: nullable `rul_C1..rul_C6`, nullable `rul_system`

`N_iv` is not stored because `N_iv == N_c` and is recomputed at lambda time.

## Implementation Modules

- `sdg/config/components.yaml`: process constants, component costs, lifetimes,
  maintenance intervals, lambda bases, and degradation variables.
- `sdg/config/couplings.yaml`: source-to-target coupling matrix and caps.
- `sdg/config/cities.yaml`: 15 deterministic indoor climate profiles.
- `sdg/core/weather.py`: deterministic sinusoidal daily temperature/humidity.
- `sdg/core/component.py`: component state and maintenance transitions.
- `sdg/core/degradation.py`: lambda and cross-factor calculations.
- `sdg/core/simulator.py`: canonical daily tick order for one printer.
- `sdg/generate.py`: streamed end-to-end Parquet generation.
- `sdg/labels.py`: post-generation RUL label augmentation.

## Canonical Daily Tick

1. Read weather drivers for city/date.
2. Draw daily jobs from Poisson(monthly_jobs / 30).
3. Update cumulative machine counters.
4. Compute endogenous `c_p = c_p0 * (2 - H_C1)` and `Q = Q0 * (2 - H_C6)`
   from pre-degradation health.
5. Build the resolved driver namespace.
6. Compute all cross factors from a consistent pre-degradation snapshot.
7. Compute and log raw per-hour lambdas, then apply daily degradation capped at
   `1.2` health units per day.
8. Apply preventive maintenance, then corrective maintenance.
9. Apply the thermal safety guard for C5/C6.
10. Advance `tau` and `L` by 24 hours.
11. Emit post-state row and event booleans.

## Validation

Required validation coverage:

1. Neutral nominal lambda behavior.
2. Coupling orientation.
3. Thermal pair cap.
4. Same-day preventive-before-corrective ordering.
5. Deterministic generation into two paths.
6. Frozen schema.
7. Calendar row count, day span, and leap days.
8. Weather ingestion equality.

## Deliberately Out Of Scope

- SQLite historian.
- SSL/RUL model training.
- RL policy optimization.
- Optimizer and Monte Carlo wrappers.
