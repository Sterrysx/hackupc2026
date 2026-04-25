# Fleet Baseline EDA

Input: `data/fleet_baseline.parquet`.

This report profiles the deterministic SDG fleet baseline: one daily row per printer, city, and component state. The SDG generator seeds each printer by `printer_id`, assigns printers to 15 configured European cities, simulates weather and demand, evolves six component health channels `C1`-`C6`, emits maintenance and failure booleans, then derives RUL labels from future failure events.

A null RUL value means the row is right-censored for that label: no later failure for that component was observed inside the 2015-01-01 to 2024-12-31 dataset horizon.

## Dataset Shape

| metric               | value                       |
| -------------------- | --------------------------- |
| data_file            | data/fleet_baseline.parquet |
| file_size_mb         | 46.87                       |
| parquet_rows         | 365,300                     |
| parquet_columns      | 70                          |
| parquet_row_groups   | 1                           |
| dataframe_shape      | 365,300 x 70                |
| memory_mb_loaded     | 84.66                       |
| date_start           | 2016-01-01                  |
| date_end             | 2025-12-31                  |
| calendar_days        | 3,653                       |
| printers             | 100                         |
| cities               | 10                          |
| climate_zones        | 8                           |
| rows_per_printer_min | 3,653                       |
| rows_per_printer_max | 3,653                       |
| components           | C1, C2, C3, C4, C5, C6      |

## Column Groups

| group                 | columns                                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------------------- |
| identity              | printer_id, city, climate_zone                                                                        |
| calendar              | date, day                                                                                             |
| weather_and_load      | ambient_temp_c, humidity_pct, dust_concentration, Q_demand, daily_print_hours, cumulative_print_hours |
| health                | H_C1, H_C2, H_C3, H_C4, H_C5, H_C6                                                                    |
| status                | status_C1, status_C2, status_C3, status_C4, status_C5, status_C6                                      |
| maintenance_clock     | tau_C1, tau_C2, tau_C3, tau_C4, tau_C5, tau_C6                                                        |
| age_since_replacement | L_C1, L_C2, L_C3, L_C4, L_C5, L_C6                                                                    |
| counters              | N_f, N_c, N_TC, N_on                                                                                  |
| hazard_rate           | lambda_C1, lambda_C2, lambda_C3, lambda_C4, lambda_C5, lambda_C6                                      |
| maintenance_events    | maint_C1, maint_C2, maint_C3, maint_C4, maint_C5, maint_C6                                            |
| failure_events        | failure_C1, failure_C2, failure_C3, failure_C4, failure_C5, failure_C6                                |
| rul_labels            | rul_C1, rul_C2, rul_C3, rul_C4, rul_C5, rul_C6, rul_system                                            |

## City and Climate Coverage

| city        | climate_zone         | printers | rows   | row_share_pct |
| ----------- | -------------------- | -------- | ------ | ------------- |
| singapore   | tropical             | 10       | 36,530 | 10.00%        |
| dubai       | arid                 | 10       | 36,530 | 10.00%        |
| mumbai      | tropical             | 10       | 36,530 | 10.00%        |
| shanghai    | humid_subtropical    | 10       | 36,530 | 10.00%        |
| barcelona   | mediterranean        | 10       | 36,530 | 10.00%        |
| london      | temperate            | 10       | 36,530 | 10.00%        |
| moscow      | continental          | 10       | 36,530 | 10.00%        |
| chicago     | continental          | 10       | 36,530 | 10.00%        |
| houston     | subtropical          | 10       | 36,530 | 10.00%        |
| mexico_city | highland_subtropical | 10       | 36,530 | 10.00%        |

| climate_zone         | cities | printers | rows   | row_share_pct |
| -------------------- | ------ | -------- | ------ | ------------- |
| tropical             | 2      | 20       | 73,060 | 20.00%        |
| arid                 | 1      | 10       | 36,530 | 10.00%        |
| humid_subtropical    | 1      | 10       | 36,530 | 10.00%        |
| mediterranean        | 1      | 10       | 36,530 | 10.00%        |
| temperate            | 1      | 10       | 36,530 | 10.00%        |
| continental          | 2      | 20       | 73,060 | 20.00%        |
| subtropical          | 1      | 10       | 36,530 | 10.00%        |
| highland_subtropical | 1      | 10       | 36,530 | 10.00%        |

## Weather and Demand by Climate

| climate_zone         | ambient_temp_c_mean | ambient_temp_c_p05 | ambient_temp_c_p95 | humidity_pct_mean | dust_concentration_mean | q_demand_mean | daily_print_hours_mean |
| -------------------- | ------------------- | ------------------ | ------------------ | ----------------- | ----------------------- | ------------- | ---------------------- |
| tropical             | 22.80               | 22.49              | 23.22              | 51.79             | 52.17                   | 1.089         | 4.003                  |
| arid                 | 22.97               | 21.89              | 23.94              | 44.80             | 52.81                   | 1.083         | 4.011                  |
| humid_subtropical    | 21.73               | 20.34              | 22.99              | 49.78             | 52.27                   | 1.086         | 3.977                  |
| mediterranean        | 21.71               | 20.99              | 22.50              | 47.78             | 52.36                   | 1.082         | 3.995                  |
| temperate            | 21.23               | 20.41              | 22.02              | 49.05             | 52.47                   | 1.086         | 4.009                  |
| continental          | 20.84               | 20.00              | 22.57              | 48.81             | 52.39                   | 1.085         | 3.993                  |
| subtropical          | 22.15               | 20.64              | 23.16              | 50.30             | 52.29                   | 1.085         | 4.015                  |
| highland_subtropical | 21.79               | 21.51              | 22.10              | 45.10             | 52.73                   | 1.080         | 4.005                  |

## Component Status Distribution

Statuses are written after the simulator applies preventive and corrective actions for the day. Because corrective failure handling resets the component before the row is emitted, `status_FAILED` can be zero even when `failure_*` event booleans are true.

| component | OK     | WARNING | CRITICAL | FAILED |
| --------- | ------ | ------- | -------- | ------ |
| C1        | 88.96% | 4.66%   | 6.37%    | 0.00%  |
| C2        | 47.16% | 29.49%  | 23.35%   | 0.00%  |
| C3        | 84.92% | 7.20%   | 7.87%    | 0.00%  |
| C4        | 43.71% | 32.70%  | 23.59%   | 0.00%  |
| C5        | 60.32% | 26.07%  | 13.61%   | 0.00%  |
| C6        | 69.31% | 25.75%  | 4.94%    | 0.00%  |

## Component Health

| component | min    | p01    | p05    | median | mean   | p95    | max    |
| --------- | ------ | ------ | ------ | ------ | ------ | ------ | ------ |
| C1        | 0.1000 | 0.1385 | 0.3314 | 1.0000 | 0.9268 | 1.0000 | 1.0000 |
| C2        | 0.1000 | 0.1145 | 0.1709 | 0.6746 | 0.6353 | 0.9854 | 1.0000 |
| C3        | 0.1000 | 0.1361 | 0.2821 | 1.0000 | 0.9013 | 1.0000 | 1.0000 |
| C4        | 0.1000 | 0.1125 | 0.1646 | 0.6328 | 0.6474 | 1.0000 | 1.0000 |
| C5        | 0.1000 | 0.1379 | 0.2495 | 0.7805 | 0.7211 | 0.9938 | 1.0000 |
| C6        | 0.1021 | 0.2939 | 0.4011 | 0.8336 | 0.7814 | 0.9963 | 1.0000 |

## Tau, L, and Lambda

`tau_*` is the component maintenance clock in hours, `L_*` is age since replacement in hours, and `lambda_*` is the simulated hazard rate per hour.

| component | tau_median_h | tau_max_h | L_median_h | L_max_h | lambda_median_per_h | lambda_p95_per_h | lambda_max_per_h |
| --------- | ------------ | --------- | ---------- | ------- | ------------------- | ---------------- | ---------------- |
| C1        | 1.0          | 20.0      | 1.0        | 20.0    | 1.785e+00           | 3.535e+00        | 5.927e+00        |
| C2        | 44.0         | 167.0     | 46.0       | 497.0   | 1.015e-02           | 1.843e-02        | 4.079e-02        |
| C3        | 1.0          | 7.0       | 1.0        | 47.0    | 1.569e+00           | 3.058e+00        | 9.417e+00        |
| C4        | 2.0          | 42.0      | 2.0        | 112.0   | 3.064e-01           | 5.956e-01        | 8.097e-01        |
| C5        | 78.0         | 167.0     | 245.0      | 1300.0  | 3.218e-03           | 7.467e-03        | 1.463e-02        |
| C6        | 153.0        | 334.0     | 520.0      | 2540.0  | 1.522e-03           | 2.997e-03        | 5.401e-03        |

## Maintenance and Failure Events

The event columns are daily booleans. Counts below are row counts where that same-day event fired.

| component | maintenance_events | failure_events | printers_with_maintenance | printers_with_failure | maintenance_row_pct | failure_row_pct |
| --------- | ------------------ | -------------- | ------------------------- | --------------------- | ------------------- | --------------- |
| C1        | 0                  | 318,541        | 0                         | 100                   | 0.00%               | 87.20%          |
| C2        | 206                | 3,947          | 100                       | 100                   | 0.06%               | 1.08%           |
| C3        | 752                | 296,734        | 100                       | 100                   | 0.21%               | 81.23%          |
| C4        | 126                | 104,594        | 100                       | 100                   | 0.03%               | 28.63%          |
| C5        | 1,563              | 714            | 100                       | 100                   | 0.43%               | 0.20%           |
| C6        | 708                | 404            | 100                       | 100                   | 0.19%               | 0.11%           |

## RUL Label Availability

| label      | non_null_rows | coverage_pct | zero_rows | censored_rows | min_days | median_days | p95_days | max_days |
| ---------- | ------------- | ------------ | --------- | ------------- | -------- | ----------- | -------- | -------- |
| rul_C1     | 365,300       | 100.00%      | 318,541   | 0             | 0        | 0.0         | 1.0      | 20       |
| rul_C2     | 362,491       | 99.23%       | 3,947     | 2,809         | 0        | 45.0        | 270.0    | 497      |
| rul_C3     | 365,300       | 100.00%      | 296,734   | 0             | 0        | 0.0         | 2.0      | 47       |
| rul_C4     | 365,244       | 99.98%       | 104,594   | 56            | 0        | 1.0         | 11.0     | 112      |
| rul_C5     | 352,061       | 96.38%       | 714       | 13,239        | 0        | 254.0       | 990.0    | 1,300    |
| rul_C6     | 348,693       | 95.45%       | 404       | 16,607        | 0        | 560.0       | 1977.0   | 2,540    |
| rul_system | 365,300       | 100.00%      | 326,904   | 0             | 0        | 0.0         | 1.0      | 20       |

## Sanity Checks

| check                                    | status | detail                                                                |
| ---------------------------------------- | ------ | --------------------------------------------------------------------- |
| parquet_metadata_matches_loaded_frame    | PASS   | metadata=365,300x70, loaded=365,300x70                                |
| full_printer_day_grid                    | PASS   | rows=365,300, printers=100, days=3,653, expected=365,300              |
| no_duplicate_printer_dates               | PASS   | duplicate printer/date rows=0                                         |
| each_printer_has_same_day_count          | PASS   | min=3,653, max=3,653, expected=3,653                                  |
| day_column_matches_date_offset           | PASS   | rows where date != first_date + day: 0                                |
| printer_city_and_climate_are_static      | PASS   | printers with changing city or climate=0                              |
| each_city_maps_to_one_climate            | PASS   | cities with multiple climates=0                                       |
| health_values_in_unit_interval           | PASS   | global health min=0.100003, max=1.000000                              |
| status_values_are_known_categories       | PASS   | all component status columns are within OK, WARNING, CRITICAL, FAILED |
| event_columns_are_boolean_without_nulls  | PASS   | nulls=0                                                               |
| failure_rows_have_zero_component_rul     | PASS   | component failure rows with nonzero RUL=0                             |
| component_rul_is_nonnegative             | PASS   | negative component RUL rows=0                                         |
| system_rul_is_min_observed_component_rul | PASS   | rows where rul_system disagrees with component minimum=0              |
| schema_contains_expected_final_columns   | PASS   | schema columns=70                                                     |

## Variable Correlations

The heatmap below shows Pearson correlation across the numeric variables in the fleet baseline. `printer_id` is excluded because it is an identifier rather than a signal feature.

## Climate and Load Profile

This heatmap normalizes each metric column independently so the climate zones can be compared on the same color scale.

## Component Dynamics Profile

`tau_*`, `L_*`, and the median hazard rate summarize the component lifecycle state in one compact view.

## Component Risk Profile

Bubble size reflects maintenance volume, while color reflects the median hazard rate on a log scale.


## Mean Time to Error

This chart averages the `hours_since_*_failure` clocks to show how long each component typically runs between errors.


## Figures

![city_printer_distribution](figures/city_printer_distribution.png)

![climate_row_distribution](figures/climate_row_distribution.png)

![component_status_share](figures/component_status_share.png)

![component_health_summary](figures/component_health_summary.png)

![maintenance_failure_events](figures/maintenance_failure_events.png)

![rul_label_coverage](figures/rul_label_coverage.png)

![variable_correlation_heatmap](figures/variable_correlation_heatmap.png)

![climate_profile_heatmap](figures/climate_profile_heatmap.png)

![component_dynamics_heatmap](figures/component_dynamics_heatmap.png)

![component_risk_profile](figures/component_risk_profile.png)

![mean_time_to_error_by_component](figures/mean_time_to_error_by_component.png)

## Reproduce

```bash
uv run jupyter nbconvert --to notebook --execute --inplace ml_models/00_eda/eda_fleet_baseline.ipynb
```

To point the EDA at another compatible SDG output, edit the notebook configuration cell.
