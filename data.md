# `data/` — Train vs FutureSD Split

This document describes the planned reorganization of the SDG output into **two datasets** instead of one. It is a planning doc — the implementation steps land in a separate PR.

## Motivation

Today the SDG writes a single parquet at `data/fleet_baseline.parquet` covering 2015-01-01 → 2024-12-31 (3 653 days × 100 printers). Both ML training and the live React dashboard read from that one file. That conflates two different uses:

1. **ML training** — needs deterministic, fully-observed history. The labels (RUL, failure events) must reflect what actually happened in that window. The 2015–2024 span is a strong fit because it uses real city climate profiles ("real temperatures" in the sense that `cities.yaml` is calibrated to multi-year averages from Open-Meteo).
2. **Operator dashboard** — should show *current and future* state. A demo dated 2017 looks fake; a demo dated 2030 with rolling forecasts feels like a real digital twin. The dashboard should never display "2015" as the present moment.

The fix: produce two parquets with the same component physics, the same simulator, the same printer fleet — just different time windows and a different weather source for the future window where we have no observations.

## The two datasets

```
data/
├── train/
│   └── fleet_baseline.parquet     # 2015-01-01 → 2024-12-31  (10y, ~3653 days)
└── futureSD/
    └── fleet_baseline.parquet     # 2025-01-01 → 2034-12-31  (10y, ~3653 days)
```

| Dataset | Date range | Weather source | Consumers |
|---|---|---|---|
| `train` | 2015-01-01 → 2024-12-31 | Deterministic city-cosine (`sdg/core/weather.py:get_drivers`) — calibrated from real climatology in `cities.yaml` | Stage 00 EDA, Stage 01 Optuna baseline, Stage 02 SSL pretrain + RUL head, Stage 03 PPO RL, Stage 04 results |
| `futureSD` | 2025-01-01 → 2034-12-31 | Cosine baseline **+ stochastic perturbation** seeded for byte-determinism | FastAPI `/twin/*` endpoints, React dashboard, Ai_Agent grounded retrieval |

The 100-printer fleet, the 6 components, the 15 cities, the alpha sampling, the daily_print_hours sampling, and every degradation rule are **identical** between the two datasets. The only differences are:

- the date range (`START_DATE`, `END_DATE`, `EXPECTED_DAYS`),
- the weather function used to populate `ambient_temp_c` / `humidity_pct` per day, and
- the per-printer RNG namespace (so `train` and `futureSD` are not byte-identical).

A printer's "history" is therefore split: rows for 2015–2024 live in `train`, rows for 2025–2034 live in `futureSD`. Together they form a continuous 20-year story for each printer; separately each parquet stands on its own.

## Weather: real for the past, synthesized for the future

### Train period (2015–2024) — already "real enough"

`sdg/core/weather.py:get_drivers(city, date)` is a deterministic seasonal cosine:

```python
T(d) = T_mean_annual + T_amplitude * cos(2π·(doy-15)/365.25)        # clipped to [20, 30] °C
H(d) = H_mean_annual + H_amplitude * sin(2π·(doy-15)/365.25 + π/4)   # clipped to [30, 70] %
```

The `T_mean_annual` and `T_amplitude` per city in `sdg/config/cities.yaml` are tuned against real multi-year averages from Open-Meteo. So while no specific date in 2015–2024 carries a recorded weather observation, the *climatology* is real. We treat this as the "real temperatures" baseline for the train set.

> **Optional follow-up (out of scope for the first cut):** swap the cosine for a lookup against `data/weather_data.parquet`, which already contains daily T/H/P from Open-Meteo (2020+ for most cities). This would make 2020–2024 truly observation-driven and leave 2015–2019 on the cosine. Doing so requires extending `get_drivers` with a parquet-backed fast path and is a bigger change.

### FutureSD period (2025–2034) — synthesized "with respect to the first set"

Because 2025-onward weather has not happened, we generate it from the same city profiles **plus** stochastic perturbations whose statistics are derived from (or designed to be plausibly close to) the historical period.

Recommended generator:

```python
def get_future_drivers(city: str, date: Date, rng: np.random.Generator) -> dict[str, float]:
    base = get_drivers(city, date)                                        # cosine baseline
    T = base["ambient_temp_c"] + rng.normal(0.0, sigma_T_per_city[city])
    H = base["humidity_pct"]   + rng.normal(0.0, sigma_H_per_city[city])
    # Optional climate-warming drift (e.g. +0.03 °C/year over the future window):
    years_into_future = (date.year - 2025) + date.timetuple().tm_yday / 365.25
    T += 0.03 * years_into_future
    return {
        "ambient_temp_c": float(np.clip(T, 18.0, 32.0)),
        "humidity_pct":   float(np.clip(H, 25.0, 75.0)),
    }
```

- `sigma_T_per_city`, `sigma_H_per_city` — daily noise std per city. Defaults can match the city's `T_amplitude` × ~0.3 (so noise is ~30 % of the seasonal swing — physically reasonable for daily weather), or be derived empirically from `weather_data.parquet` residuals if we choose to refine.
- `rng` — passed in from a per-printer-per-day seed unique to the `futureSD` namespace, e.g. `np.random.default_rng((printer_id << 16) | day_index)` plus a constant offset like `0xF000_0000` so it never collides with the `train` printer rngs.
- The optional warming drift gives the futureSD dataset a slow trend the model can in principle pick up; set it to `0.0` to disable.

This satisfies the user's "fake it (something wrt the first set)" requirement: the perturbations are anchored on the same city climatology that drives the train period, so the futureSD weather looks like a noisy continuation of the same climate, not a different planet.

### Atmospheric pressure

The simulator does not currently read `P_ext` from `get_drivers` (the live driver namespace in `sdg/core/simulator.py:_build_driver_namespace` only exposes `T`, `H`, plus process constants). Pressure is in `data/weather_data.parquet` but not in the live degradation path. So for the SDG output **no pressure column is added** in either dataset — the user's mention of pressure is preserved for a future iteration that wires it into the driver namespace.

If pressure ever becomes a driver, the same recipe applies: cosine baseline + Gaussian noise, with noise stats derived from the historical parquet.

## Code touchpoints

| File | Today | Change |
|---|---|---|
| `sdg/generate.py:17` | `DEFAULT_OUTPUT_PATH = Path("data/fleet_baseline.parquet")` | Become a function that takes a `dataset: Literal["train", "futureSD"]` arg. Two output paths: `data/train/fleet_baseline.parquet`, `data/futureSD/fleet_baseline.parquet`. |
| `sdg/generate.py:18-22` | hard-coded `START_DATE`, `END_DATE`, `EXPECTED_DAYS` | Pulled from a per-dataset config: `train` = 2015-01-01 → 2024-12-31; `futureSD` = 2025-01-01 → 2034-12-31. |
| `sdg/generate.py:42-58` | one writer | Looped over both datasets, or a CLI flag `--dataset`. Recommended: `python -m sdg.generate --dataset train` and `--dataset futureSD`. |
| `sdg/core/weather.py` | `get_drivers(city, date)` only | Add `get_future_drivers(city, date, rng)` and a thin dispatcher `get_drivers_for_dataset(dataset, city, date, rng)`. |
| `sdg/core/simulator.py:246` | `weather_drivers = get_drivers(...)` | Threads `dataset` through `_simulate_one_day` so the right weather function fires. The Component / degradation code is untouched. |
| `sdg/config/cities.yaml` | climatology only | Add `sigma_T_daily`, `sigma_H_daily` per city for the futureSD noise model. Default ~30 % of `T_amplitude`. |
| `sdg/schema.py` | one schema | Schema is shared — both parquets use the same `FINAL_SCHEMA`. No schema change. |
| `Ai_Agent/twin_data.py:24` | `DEFAULT_PARQUET_PATH = "data/fleet_baseline.parquet"` | `DEFAULT_PARQUET_PATH = "data/futureSD/fleet_baseline.parquet"` — frontend now sees the future. |
| `app.py:353` | comment | Update doc-comment to reflect the futureSD source. |
| `ml_models/lib/data.py:13` | `DEFAULT_FLEET_PATH = .../"fleet_baseline.parquet"` | `DEFAULT_FLEET_PATH = .../"train"/"fleet_baseline.parquet"` — ML training stays on the historical set. |
| `ml_models/02_ssl/tests/test_features.py:88` | `endswith("data/fleet_baseline.parquet")` | Update the path assertion. |
| `ml_models/03_rl+ssl/tests/test_per_tick_env.py:22` | `Path("data/fleet_baseline.parquet")` | Same. |
| `sdg/tests/test_generation.py` | regenerates one parquet via `main(tmp_path)` | Parameterise over `["train", "futureSD"]` so both byte-deterministic. |
| `scripts/diagnose_lifespans.py` | reads `cities.yaml` and `components.yaml` | No change — script works against config, not parquet. |
| `Makefile` and `train.sh` | `python -m sdg.generate` | Two invocations: `python -m sdg.generate --dataset train`, then `--dataset futureSD`. |

## RUL labels in each dataset

- `train` parquet keeps the existing `add_rul_labels` pass (`sdg/labels.py`). Labels are looked up forward inside the train window — so failures near 2024-12-31 produce nullable RUL for the right-censored tail. ML training already handles this.
- `futureSD` parquet also gets RUL labels via the same routine. Useful for offline what-if evaluation. The frontend ignores them — it never reads `rul_*` from this parquet.

## Frontend wiring

The frontend does not load any parquet directly; it calls FastAPI. The single source of truth is `Ai_Agent/twin_data.py:DEFAULT_PARQUET_PATH`. Pointing that at `data/futureSD/fleet_baseline.parquet` is the entire change for the dashboard. Endpoint paths (`/twin/snapshot`, `/twin/timeline`, `/twin/printers`, `/twin/cities`, `/agent/*`, `/ws/notifications`) all stay the same.

The "current day" cursor in the dashboard's `LifetimeTelemetryTile` and `Twin` store currently maps tick → date by adding to `2015-01-01`. With the futureSD source the start date becomes `2025-01-01`. Touchpoints:

- `frontend/src/lib/twinApi.ts` — `SIM_DAY_COUNT`, `TICKS_PER_DAY`, `tickToDay`. The day-count stays 3 653 (same window length).
- `frontend/src/components/analytics/LifetimeTelemetryTile.tsx:38` — `SIM_START_DATE_UTC = Date.UTC(2025, 0, 1)` instead of `2015, 0, 1`. The "year ribbon" loop also moves to 2025 → 2035 (instead of 2015 → 2030).
- `frontend/src/store/twin.ts` — any reset-to-day-0 logic stays correct, since "day 0" of the displayed parquet is now 2025-01-01 by construction.

## ML pipeline impact

Stages 00 → 04 train on the **train** dataset only. Concretely:

- `ml_models/lib/data.py:DEFAULT_FLEET_PATH` → `data/train/fleet_baseline.parquet`
- `train.sh` runs each notebook end-to-end against the train parquet. No change needed inside notebooks beyond their already-using `DEFAULT_FLEET_PATH`.
- The trained encoder + RUL head + PPO policy are then published as artifacts under `ml_models/02_ssl/models/` and `ml_models/03_rl+ssl/models/`. The Ai_Agent's `forecast.py` loads them and applies them to the **futureSD** parquet at request time. This is the same dispatch path as today — only the source parquet changes.

There is **no train/test/val split refactor**. `ml_models/lib/data.py:TRAIN_PRINTERS / VAL_PRINTERS / TEST_PRINTERS` (printer 0..69 / 70..84 / 85..99) keeps applying *within* the train dataset. The futureSD set is held entirely separate; it is not used for hyperparameter search or model selection.

## Migration plan (phased)

1. **Phase A — Config + paths.** Make `START_DATE`, `END_DATE`, output path, and weather function configurable per-dataset. Keep behavior identical to today when `--dataset train`. Land tests for the train path.
2. **Phase B — Future weather.** Add `get_future_drivers` + `sigma_T_daily`/`sigma_H_daily` in `cities.yaml`. Add `--dataset futureSD` to `sdg.generate` and a corresponding test fixture (small printer count, full deterministic byte-equality).
3. **Phase C — Generate both.** `make data` (or equivalent) runs both `python -m sdg.generate --dataset train` and `--dataset futureSD`. Commit both parquets (~50 MB each — keep under the 100 MB GitHub soft limit; if they grow larger, gate behind Git LFS).
4. **Phase D — Repoint readers.** Switch `Ai_Agent/twin_data.py` to futureSD; switch `ml_models/lib/data.py` to train. Update the front-end start-date constant. Run the full test suite — expect green.
5. **Phase E — Notebook reruns.** `./train.sh 0..4` rebuilds Stages 00–04 against the train parquet only. Stage-02 retrain refreshes the encoder/head; the dashboard's analytic-fallback exit hatch (`Ai_Agent/forecast.py:active_path`) kicks back over to `"ssl"` automatically.
6. **Phase F — Drop the legacy single parquet.** Delete `data/fleet_baseline.parquet` (the path-without-prefix) once everything has moved. Add a one-line migration note to the project root README so a fresh clone knows where to look.

## Open questions

- **Climate-warming drift slope.** The recommended generator includes an optional `+0.03 °C/year` drift across the futureSD window. Set to zero for "stationary climate" or higher for an alarmist scenario. Default proposed: `0.03`. Easy to tune in `cities.yaml` or as a global SDG config.
- **City-specific noise std vs single global value.** Defaulting to per-city ~30 % × `T_amplitude` is simple and physically reasonable. If we instead fit residuals from `weather_data.parquet`, we get a more realistic spread but introduce a coupling to that parquet's coverage gaps. Recommend the simple per-city default first, fit-from-data as a follow-up.
- **Whether to include atmospheric pressure as a fourth driver.** Today it isn't a degradation driver. Adding it requires extending `_build_driver_namespace`, choosing exponents per component, and a config-validation pass. Out of scope for this split; revisit if a concrete component physics rationale appears.
- **Determinism vs cross-printer correlation.** With per-printer-per-day rngs, two printers in the same city on the same future day will sample independent weather noise — i.e. their indoor T/H drift apart even though they share a climate. Real fleets *should* see correlated weather. If we want city-correlated noise we draw weather noise per (city, day) once and reuse across that city's printers. Recommend: city-level seeding for futureSD weather (one rng per city per day, shared across all printers in that city). This keeps determinism and reproduces fleet-coherent weather.
