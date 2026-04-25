# Stage 01/02/03 Results Comparison

This report compares the three maintenance-policy stages using the generated artifacts under `ml_models/`.

Main Stage 03 result: the per-tick PPO+SPR ensemble from `ml_models/03_rl+ssl/results/per_tick/`. The earlier Stage 03 per-printer tau policy is retained below as auxiliary context because it is useful diagnostically but is weaker than the per-tick policy.

## Headline

- Best overall row by penalized objective: **Stage 03 - per-tick PPO+SPR ensemble**.
- Stage 03 per-tick reduces annual cost by **62.04%** versus Stage 01.
- Stage 03 per-tick improves availability by **70.17%** versus Stage 01.
- None of the stages reach the 95% availability constraint yet, so every final objective still includes a deficit penalty.

## Normalized KPI Table

| stage                                | policy        | annual_cost   | availability | deficit | penalized_value | cost_reduction_vs_01 | value_reduction_vs_01 |
| ------------------------------------ | ------------- | ------------- | ------------ | ------- | --------------- | -------------------- | --------------------- |
| Stage 01 - Optuna constant tau       | constant τ    | EUR 3,620,778 | 5.76%        | 89.24%  | 9.924B          | 0.00%                | 0.00%                 |
| Stage 02 - SSL/RUL surrogate tau     | constant τ    | EUR 4,044,317 | 0.00%        | 95.00%  | 10.500B         | -11.70%              | -5.81%                |
| Stage 03 - per-tick PPO+SPR ensemble | per-printer τ | EUR 1,374,527 | 75.94%       | 19.06%  | 2.906B          | 62.04%               | 70.71%                |

## Maintenance Interval Comparison

Stage 01 and Stage 02 output one constant tau vector. The auxiliary Stage 03 per-printer tau policy outputs one tau vector per test printer; this table shows its mean/min/max by component. The main Stage 03 per-tick policy is event/action based, so it is not directly represented by a fixed tau vector.

| component | stage_01_tau_h | stage_02_tau_h | stage_03_per_printer_tau_mean_h | stage_03_per_printer_tau_min_h | stage_03_per_printer_tau_max_h |
| --------- | -------------- | -------------- | ------------------------------- | ------------------------------ | ------------------------------ |
| C1        | 926.8          | 2.1            | 99.9                            | 99.6                           | 100.2                          |
| C2        | 13,947.1       | 30.1           | 500.0                           | 500.0                          | 500.0                          |
| C3        | 441.8          | 19.2           | 192.1                           | 189.4                          | 195.6                          |
| C4        | 1,900.5        | 83.0           | 100.0                           | 100.0                          | 100.0                          |
| C5        | 2,792.8        | 23.5           | 760.3                           | 758.5                          | 762.2                          |
| C6        | 13,468.5       | 775.7          | 1,000.0                         | 1,000.0                        | 1,000.0                        |

## Stage 02 RUL Head Metrics

Mean held-out RUL error by variant:

| variant           | mae_mean_days | rmse_mean_days |
| ----------------- | ------------- | -------------- |
| scratch_all       | 3.19          | 3.76           |
| pretrained_all    | 4.49          | 5.06           |
| pretrained_frozen | 23.88         | 28.02          |

## Stage 03 Auxiliary Context

Earlier Stage 03 per-printer tau comparison from `ml_models/03_rl+ssl/results/kpi_comparison.csv`:

| stage    | policy_class  | fleet_annual_cost | fleet_availability | fleet_deficit | fleet_value |
| -------- | ------------- | ----------------- | ------------------ | ------------- | ----------- |
| stage_01 | constant τ    | EUR 3,620,778     | 5.76%              | 89.24%        | 9.924B      |
| stage_02 | constant τ    | EUR 4,044,317     | 0.00%              | 95.00%        | 10.500B     |
| stage_03 | per-printer τ | EUR 3,644,173     | 5.08%              | 89.92%        | 9.992B      |

Per-tick PPO+SPR ensemble summary from `per_tick_summary.yaml`:

| metric | value |
| --- | --- |
| fleet annual cost | EUR 1,374,527 |
| fleet availability | 75.94% |
| fleet deficit | 19.06% |
| ensemble size | 3 |
| total timesteps per seed | 20000 |

Per-printer spread for the Stage 03 per-tick ensemble:

| metric            | value         |
| ----------------- | ------------- |
| annual_cost_min   | EUR 1,301,797 |
| annual_cost_mean  | EUR 1,374,527 |
| annual_cost_max   | EUR 1,449,027 |
| availability_min  | 74.17%        |
| availability_mean | 75.94%        |
| availability_max  | 77.60%        |

## Figures

![cost_availability_by_stage](figures/cost_availability_by_stage.png)

![penalized_value_by_stage](figures/penalized_value_by_stage.png)

![tau_comparison](figures/tau_comparison.png)

![stage03_per_printer_cost_availability](figures/stage03_per_printer_cost_availability.png)

## Interpretation

Stage 02 improves cost relative to Stage 01 but leaves availability at zero in the test KPI table. Its RUL model still matters because it produces the trained encoder and RUL head used downstream, but the constant-tau surrogate winner does not satisfy the operational constraint.

The earlier Stage 03 per-printer tau policy barely improves the constant-tau policies. The per-tick PPO+SPR ensemble is materially better: it lowers annual cost and raises availability to about 44%. It is still infeasible against the 95% availability requirement, which means the next useful work is not presentation polish; it is reward/action design and simulator-policy alignment.

High-leverage next steps:

1. Increase Stage 03 training budget and evaluate more seeds.
2. Revisit the reward: availability deficit should dominate earlier, not only after annual cost has already improved.
3. Let the per-tick policy maintain C2/C4/C5/C6 more intelligently; the current ensemble fires daily preventive maintenance for C1/C3 in the per-printer event table.
4. Clear GPU/RAM contention before training. The last run had an unrelated `llama-server` occupying about 20GB on GPU 1 and the system was already using swap.

## Reproduce

```bash
uv run jupyter nbconvert --to notebook --execute --inplace ml_models/04/results/compare_01_02_03.ipynb
```
