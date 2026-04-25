# Fleet Baseline EDA

Input: `data/fleet_baseline.parquet`.

This report profiles the deterministic SDG fleet baseline: one daily row per printer, city, and component state. The SDG generator seeds each printer by `printer_id`, assigns printers to 15 configured European cities, simulates weather and demand, evolves six component health channels `C1`-`C6`, emits maintenance and failure booleans, then derives RUL labels from future failure events.

A null RUL value means the row is right-censored for that label: no later failure for that component was observed inside the 2015-01-01 to 2024-12-31 dataset horizon.

## Dataset Shape

| metric               | value                       |
| -------------------- | --------------------------- |
| data_file            | data/fleet_baseline.parquet |
| file_size_mb         | 27.97                       |
| parquet_rows         | 365,300                     |
| parquet_columns      | 63                          |
| parquet_row_groups   | 1                           |
| dataframe_shape      | 365,300 x 63                |
| memory_mb_loaded     | 74.21                       |
| date_start           | 2015-01-01                  |
| date_end             | 2024-12-31                  |
| calendar_days        | 3,653                       |
| printers             | 100                         |
| cities               | 15                          |
| climate_zones        | 5                           |
| rows_per_printer_min | 3,653                       |
| rows_per_printer_max | 3,653                       |
| components           | C1, C2, C3, C4, C5, C6      |

## Column Groups

| group                 | columns                                                                |
| --------------------- | ---------------------------------------------------------------------- |
| identity              | printer_id, city, climate_zone                                         |
| calendar              | date, day                                                              |
| weather_and_load      | ambient_temp_c, humidity_pct, dust_concentration, Q_demand, jobs_today |
| health                | H_C1, H_C2, H_C3, H_C4, H_C5, H_C6                                     |
| status                | status_C1, status_C2, status_C3, status_C4, status_C5, status_C6       |
| maintenance_clock     | tau_C1, tau_C2, tau_C3, tau_C4, tau_C5, tau_C6                         |
| age_since_replacement | L_C1, L_C2, L_C3, L_C4, L_C5, L_C6                                     |
| counters              | N_f, N_c, N_TC, N_on                                                   |
| hazard_rate           | lambda_C1, lambda_C2, lambda_C3, lambda_C4, lambda_C5, lambda_C6       |
| maintenance_events    | maint_C1, maint_C2, maint_C3, maint_C4, maint_C5, maint_C6             |
| failure_events        | failure_C1, failure_C2, failure_C3, failure_C4, failure_C5, failure_C6 |
| rul_labels            | rul_C1, rul_C2, rul_C3, rul_C4, rul_C5, rul_C6, rul_system             |

## City and Climate Coverage

| city      | climate_zone  | printers | rows   | row_share_pct |
| --------- | ------------- | -------- | ------ | ------------- |
| Helsinki  | nordic        | 7        | 25,571 | 7.00%         |
| Stockholm | nordic        | 7        | 25,571 | 7.00%         |
| Oslo      | nordic        | 7        | 25,571 | 7.00%         |
| Warsaw    | continental   | 7        | 25,571 | 7.00%         |
| Prague    | continental   | 7        | 25,571 | 7.00%         |
| Vienna    | continental   | 7        | 25,571 | 7.00%         |
| London    | oceanic       | 7        | 25,571 | 7.00%         |
| Amsterdam | oceanic       | 7        | 25,571 | 7.00%         |
| Paris     | oceanic       | 7        | 25,571 | 7.00%         |
| Barcelona | mediterranean | 7        | 25,571 | 7.00%         |
| Madrid    | mediterranean | 6        | 21,918 | 6.00%         |
| Rome      | mediterranean | 6        | 21,918 | 6.00%         |
| Budapest  | eastern       | 6        | 21,918 | 6.00%         |
| Bucharest | eastern       | 6        | 21,918 | 6.00%         |
| Athens    | eastern       | 6        | 21,918 | 6.00%         |

| climate_zone  | cities | printers | rows   | row_share_pct |
| ------------- | ------ | -------- | ------ | ------------- |
| nordic        | 3      | 21       | 76,713 | 21.00%        |
| continental   | 3      | 21       | 76,713 | 21.00%        |
| oceanic       | 3      | 21       | 76,713 | 21.00%        |
| mediterranean | 3      | 19       | 69,407 | 19.00%        |
| eastern       | 3      | 18       | 65,754 | 18.00%        |

## Weather and Demand by Climate

| climate_zone  | ambient_temp_c_mean | ambient_temp_c_p05 | ambient_temp_c_p95 | humidity_pct_mean | dust_concentration_mean | q_demand_mean | jobs_today_mean |
| ------------- | ------------------- | ------------------ | ------------------ | ----------------- | ----------------------- | ------------- | --------------- |
| nordic        | 22.57               | 20.16              | 24.88              | 54.00             | 54.20                   | 1.054         | 0.400           |
| continental   | 24.00               | 21.13              | 26.80              | 47.33             | 55.96                   | 1.045         | 0.379           |
| oceanic       | 23.43               | 21.45              | 25.76              | 54.67             | 54.35                   | 1.053         | 0.397           |
| mediterranean | 25.10               | 22.01              | 28.28              | 45.79             | 56.12                   | 1.045         | 0.405           |
| eastern       | 24.93               | 21.50              | 28.28              | 45.00             | 55.64                   | 1.043         | 0.401           |

## Component Status Distribution

Statuses are written after the simulator applies preventive and corrective actions for the day. Because corrective failure handling resets the component before the row is emitted, `status_FAILED` can be zero even when `failure_*` event booleans are true.

| component | OK     | WARNING | CRITICAL | FAILED |
| --------- | ------ | ------- | -------- | ------ |
| C1        | 84.06% | 7.25%   | 8.69%    | 0.00%  |
| C2        | 46.54% | 29.12%  | 24.35%   | 0.00%  |
| C3        | 57.25% | 20.08%  | 22.66%   | 0.00%  |
| C4        | 50.44% | 23.44%  | 26.11%   | 0.00%  |
| C5        | 74.08% | 19.65%  | 6.27%    | 0.00%  |
| C6        | 99.57% | 0.43%   | 0.00%    | 0.00%  |

## Component Health

| component | min    | p01    | p05    | median | mean   | p95    | max    |
| --------- | ------ | ------ | ------ | ------ | ------ | ------ | ------ |
| C1        | 0.1000 | 0.1325 | 0.2742 | 1.0000 | 0.8955 | 1.0000 | 1.0000 |
| C2        | 0.1000 | 0.1140 | 0.1676 | 0.6687 | 0.6296 | 0.9841 | 1.0000 |
| C3        | 0.1000 | 0.1156 | 0.1747 | 0.8458 | 0.7203 | 1.0000 | 1.0000 |
| C4        | 0.1000 | 0.1147 | 0.1664 | 0.7067 | 0.6753 | 1.0000 | 1.0000 |
| C5        | 0.1000 | 0.1725 | 0.3592 | 0.8635 | 0.7962 | 0.9964 | 1.0000 |
| C6        | 0.5720 | 0.7378 | 0.8235 | 0.9758 | 0.9518 | 0.9996 | 1.0000 |

## Tau, L, and Lambda

`tau_*` is the component maintenance clock in hours, `L_*` is age since replacement in hours, and `lambda_*` is the simulated hazard rate per hour.

| component | tau_median_h | tau_max_h | L_median_h | L_max_h | lambda_median_per_h | lambda_p95_per_h | lambda_max_per_h |
| --------- | ------------ | --------- | ---------- | ------- | ------------------- | ---------------- | ---------------- |
| C1        | 24.0         | 600.0     | 24.0       | 864.0   | 5.405e-02           | 1.281e-01        | 2.389e-01        |
| C2        | 1008.0       | 4008.0    | 1056.0     | 11808.0 | 4.265e-04           | 8.566e-04        | 2.114e-03        |
| C3        | 48.0         | 168.0     | 48.0       | 3000.0  | 2.541e-02           | 6.286e-02        | 2.503e-01        |
| C4        | 48.0         | 1008.0    | 48.0       | 3984.0  | 1.688e-02           | 4.839e-02        | 9.389e-02        |
| C5        | 1944.0       | 4008.0    | 11256.0    | 47784.0 | 9.827e-05           | 2.566e-04        | 4.406e-04        |
| C6        | 4008.0       | 8016.0    | 43848.0    | 87672.0 | 1.101e-05           | 4.337e-05        | 1.197e-04        |

## Maintenance and Failure Events

The event columns are daily booleans. Counts below are row counts where that same-day event fired.

| component | maintenance_events | failure_events | printers_with_maintenance | printers_with_failure | maintenance_row_pct | failure_row_pct |
| --------- | ------------------ | -------------- | ------------------------- | --------------------- | ------------------- | --------------- |
| C1        | 2                  | 297,379        | 2                         | 100                   | 0.00%               | 81.41%          |
| C2        | 195                | 4,156          | 100                       | 100                   | 0.05%               | 1.14%           |
| C3        | 2,027              | 168,116        | 100                       | 100                   | 0.55%               | 46.02%          |
| C4        | 181                | 136,974        | 100                       | 100                   | 0.05%               | 37.50%          |
| C5        | 1,878              | 326            | 100                       | 100                   | 0.51%               | 0.09%           |
| C6        | 1,000              | 0              | 100                       | 0                     | 0.27%               | 0.00%           |

## RUL Label Availability

| label      | non_null_rows | coverage_pct | zero_rows | censored_rows | min_days | median_days | p95_days | max_days |
| ---------- | ------------- | ------------ | --------- | ------------- | -------- | ----------- | -------- | -------- |
| rul_C1     | 365,300       | 100.00%      | 297,379   | 0             | 0        | 0.0         | 2.0      | 36       |
| rul_C2     | 362,585       | 99.26%       | 4,156     | 2,715         | 0        | 43.0        | 240.0    | 492      |
| rul_C3     | 365,286       | 100.00%      | 168,116   | 14            | 0        | 1.0         | 4.0      | 125      |
| rul_C4     | 365,291       | 100.00%      | 136,974   | 9             | 0        | 1.0         | 13.0     | 166      |
| rul_C5     | 331,335       | 90.70%       | 326       | 33,965        | 0        | 514.0       | 1405.0   | 1,991    |
| rul_C6     | 0             | 0.00%        | 0         | 365,300       |          |             |          |          |
| rul_system | 365,300       | 100.00%      | 310,153   | 0             | 0        | 0.0         | 2.0      | 36       |

## Sanity Checks

| check                                    | status | detail                                                                |
| ---------------------------------------- | ------ | --------------------------------------------------------------------- |
| parquet_metadata_matches_loaded_frame    | PASS   | metadata=365,300x63, loaded=365,300x63                                |
| full_printer_day_grid                    | PASS   | rows=365,300, printers=100, days=3,653, expected=365,300              |
| no_duplicate_printer_dates               | PASS   | duplicate printer/date rows=0                                         |
| each_printer_has_same_day_count          | PASS   | min=3,653, max=3,653, expected=3,653                                  |
| day_column_matches_date_offset           | PASS   | rows where date != first_date + day: 0                                |
| printer_city_and_climate_are_static      | PASS   | printers with changing city or climate=0                              |
| each_city_maps_to_one_climate            | PASS   | cities with multiple climates=0                                       |
| health_values_in_unit_interval           | PASS   | global health min=0.100001, max=1.000000                              |
| status_values_are_known_categories       | PASS   | all component status columns are within OK, WARNING, CRITICAL, FAILED |
| event_columns_are_boolean_without_nulls  | PASS   | nulls=0                                                               |
| failure_rows_have_zero_component_rul     | PASS   | component failure rows with nonzero RUL=0                             |
| component_rul_is_nonnegative             | PASS   | negative component RUL rows=0                                         |
| system_rul_is_min_observed_component_rul | PASS   | rows where rul_system disagrees with component minimum=0              |
| schema_contains_expected_final_columns   | PASS   | schema columns=63                                                     |

## Figures

![city_printer_distribution](figures/city_printer_distribution.png)

![climate_row_distribution](figures/climate_row_distribution.png)

![component_status_share](figures/component_status_share.png)

![component_health_summary](figures/component_health_summary.png)

![maintenance_failure_events](figures/maintenance_failure_events.png)

![rul_label_coverage](figures/rul_label_coverage.png)

## Reproduce

```bash
uv run jupyter nbconvert --to notebook --execute --inplace ml_models/00_eda/eda_fleet_baseline.ipynb
```

To point the EDA at another compatible SDG output, edit the notebook configuration cell.
