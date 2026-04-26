"""Clean business-cost demo for Stage 01/02/03.

This runner uses explicit train/val/test printer splits and does not tune on
test. It is intended for fast, defensible hackathon evidence:

    Stage 01: naive lifetime-only fixed maintenance interval.
    Stage 02: best fleet-wide constant interval selected on validation.
    Stage 03: best condition-aware per-tick policy selected on validation.

The business metric is annual maintenance cost plus an explicit downtime-loss
assumption. All outputs state that assumption so the result is reproducible.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
import yaml
from scipy.stats import qmc

from ml import PROJECT_ROOT
from ml.lib.data import TEST_PRINTERS, TRAIN_PRINTERS, VAL_PRINTERS
from ml.lib.env_runner import default_dates, rollout_with_agent, run_with_tau
from ml.lib.objective import DAYS_PER_YEAR, compute_business_cost, scalar_objective
from backend.simulator.generate import load_configs
from backend.simulator.schema import COMPONENT_IDS


OUT_DIR = PROJECT_ROOT / "ml/04_models/results/business_demo"
FIG_DIR = OUT_DIR / "figures"


@dataclass(frozen=True)
class Split:
    name: str
    train: tuple[int, ...]
    val: tuple[int, ...]
    test: tuple[int, ...]


@dataclass(frozen=True)
class BusinessScore:
    label: str
    policy_class: str
    maintenance_cost: float
    availability: float
    business_cost: float
    downtime_loss: float
    downtime_days_per_year: float
    details: dict[str, Any]


def split_for_profile(profile: str) -> Split:
    if profile == "fast20":
        # IDs 80–99: sits inside the final100 test slice so the fast iteration
        # is a genuine subset of the test printers and shares no overlap with
        # the final100 training set (0–69).
        return Split(
            name="fast20",
            train=tuple(range(80, 94)),
            val=tuple(range(94, 97)),
            test=tuple(range(97, 100)),
        )
    if profile == "final100":
        return Split(
            name="final100",
            train=TRAIN_PRINTERS,
            val=VAL_PRINTERS,
            test=TEST_PRINTERS,
        )
    raise ValueError(f"unknown profile: {profile}")


def business_from_score(
    label: str,
    policy_class: str,
    score: Mapping[str, Any],
    *,
    downtime_loss_eur_per_day: float,
    details: dict[str, Any] | None = None,
) -> BusinessScore:
    bc = compute_business_cost(score, downtime_loss_eur_per_day)
    return BusinessScore(
        label=label,
        policy_class=policy_class,
        maintenance_cost=bc["maintenance_cost"],
        availability=bc["availability"],
        business_cost=bc["business_cost"],
        downtime_loss=bc["downtime_loss"],
        downtime_days_per_year=bc["downtime_days_per_year"],
        details=details or {},
    )


def money_m(value: float) -> str:
    thousands = int(float(value) // 1_000)
    return f"{thousands // 1_000}'{thousands % 1_000:03d} M EUR"


def money_auto(value: float) -> str:
    if abs(float(value)) < 1_000_000:
        return f"{float(value) / 1_000:.0f}k EUR"
    return money_m(value)


def _score_tau(
    label: str,
    tau: Mapping[str, float],
    *,
    printer_ids: list[int],
    dates,
    components_cfg,
    couplings_cfg,
    cities_cfg,
    downtime_loss_eur_per_day: float,
) -> BusinessScore:
    events = run_with_tau(
        tau,
        printer_ids=printer_ids,
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
    )
    score = scalar_objective(events, components_cfg)
    return business_from_score(
        label,
        "constant schedule",
        score,
        downtime_loss_eur_per_day=downtime_loss_eur_per_day,
        details={f"tau_d_{c}": float(tau[c]) for c in COMPONENT_IDS},
    )


def _score_threshold_policy(
    label: str,
    thresholds: Mapping[str, float],
    *,
    printer_ids: list[int],
    dates,
    components_cfg,
    couplings_cfg,
    cities_cfg,
    downtime_loss_eur_per_day: float,
) -> BusinessScore:
    frames: list[pd.DataFrame] = []

    def agent(row):
        if row is None:
            return {c: False for c in COMPONENT_IDS}
        return {c: float(row[f"H_{c}"]) <= float(thresholds[c]) for c in COMPONENT_IDS}

    for printer_id in printer_ids:
        frames.append(
            rollout_with_agent(
                int(printer_id),
                dates=dates,
                agent_fn=agent,
                components_cfg=components_cfg,
                couplings_cfg=couplings_cfg,
                cities_cfg=cities_cfg,
            )
        )
    score = scalar_objective(pd.concat(frames, ignore_index=True), components_cfg)
    return business_from_score(
        label,
        "condition-aware per-tick policy",
        score,
        downtime_loss_eur_per_day=downtime_loss_eur_per_day,
        details={f"H_threshold_{c}": float(thresholds[c]) for c in COMPONENT_IDS},
    )


def _constant_candidates(n_lhs: int, components_cfg) -> list[tuple[str, dict[str, float]]]:
    components = components_cfg["components"]
    lifetime = {c: float(components[c]["L_nom_d"]) for c in COMPONENT_IDS}
    nominal = {c: float(components[c]["tau_nom_d"]) for c in COMPONENT_IDS}
    # naive_lifetime_only is NOT included here: it is the explicit Stage 01
    # baseline evaluated separately in main() and never competes for Stage 02
    # selection, so it cannot accidentally "win" and collapse Stage 02 = Stage 01.
    candidates: list[tuple[str, dict[str, float]]] = [
        ("manufacturer_nominal_interval", nominal),
        ("run_to_failure", {c: 1e12 for c in COMPONENT_IDS}),
    ]
    # Anchor grid: covers the short-to-mid range explicitly so the LHS is not
    # the only way to find good short intervals.
    for multiplier in (0.10, 0.20, 0.33, 0.50, 0.75, 1.0, 1.5):
        candidates.append((f"lifetime_x_{multiplier:g}", {c: lifetime[c] * multiplier for c in COMPONENT_IDS}))

    # LHS range: 5%–150% of L_nom.  The old 4× upper bound filled the sample
    # with near-run-to-failure intervals; 1.5× keeps the search in the regime
    # where preventive maintenance has a chance to beat corrective alone.
    ranges = {
        c: (max(3.0, lifetime[c] * 0.05), max(lifetime[c] * 1.5, 14.0))
        for c in COMPONENT_IDS
    }
    sampler = qmc.LatinHypercube(d=len(COMPONENT_IDS), seed=45021)
    rows = sampler.random(int(n_lhs))
    for i, row in enumerate(rows):
        tau = {}
        for j, c in enumerate(COMPONENT_IDS):
            low, high = ranges[c]
            tau[c] = float(np.exp(np.log(low) + row[j] * (np.log(high) - np.log(low))))
        candidates.append((f"lhs_constant_{i:04d}", tau))
    return candidates


def _threshold_candidates(n_lhs: int = 96) -> list[tuple[str, dict[str, float]]]:
    candidates: list[tuple[str, dict[str, float]]] = []
    # Uniform shared-threshold sweep — covers the full [0.30, 0.85] range at
    # step 0.05 so common operating points are always in the candidate set.
    for threshold in np.arange(0.30, 0.90, 0.05):
        candidates.append(
            (f"health_le_{threshold:.2f}", {c: float(threshold) for c in COMPONENT_IDS})
        )
    # Per-component LHS — every component gets an independent threshold so the
    # search is not limited to diagonal slices of the 6-d space.
    sampler = qmc.LatinHypercube(d=len(COMPONENT_IDS), seed=58301)
    lo, hi = 0.30, 0.85
    rows = sampler.random(int(n_lhs))
    for i, row in enumerate(rows):
        th = {c: float(lo + row[j] * (hi - lo)) for j, c in enumerate(COMPONENT_IDS)}
        candidates.append((f"lhs_threshold_{i:04d}", th))
    return candidates


def _train_business_ppo(
    split: "Split",
    *,
    dates,
    components_cfg,
    couplings_cfg,
    cities_cfg,
    downtime_loss_eur_per_day: float,
    ppo_timesteps: int,
    ppo_seeds: int,
    out_dir: Path,
) -> "Any":
    """Train per-tick PPO with the business-cost reward on split.train/val.

    Returns the loaded best-seed PPO model.  If ``out_dir`` already contains
    a ``multi_seed_summary.json`` the training step is skipped so re-runs are
    fast.
    """
    from stable_baselines3 import PPO as _PPO

    from ml.lib.rl.per_tick_env import MaintenancePerTickEnv
    from ml.lib.rl.recurrent_trainer import PerTickPPOConfig, train_multi_seed

    summary_path = out_dir / "multi_seed_summary.json"
    if not summary_path.exists():
        import json as _json

        # n_steps=512 gives ~1000 PPO updates at 500k steps.
        # Old cap of 2048 gave only 73 updates at 150k — too few for convergence.
        n_steps = min(512, max(64, (ppo_timesteps // 200) & ~63))

        def make_train_env():
            return MaintenancePerTickEnv(
                list(split.train),
                components_cfg=components_cfg,
                couplings_cfg=couplings_cfg,
                cities_cfg=cities_cfg,
                dates=dates,
                downtime_loss_eur_per_day=float(downtime_loss_eur_per_day),
                downtime_lambda=0.0,
                cost_scale=1e5,
            )

        def make_val_env():
            return MaintenancePerTickEnv(
                list(split.val),
                components_cfg=components_cfg,
                couplings_cfg=couplings_cfg,
                cities_cfg=cities_cfg,
                dates=dates,
                downtime_loss_eur_per_day=float(downtime_loss_eur_per_day),
                downtime_lambda=0.0,
                cost_scale=1e5,
            )

        config = PerTickPPOConfig(
            total_timesteps=ppo_timesteps,
            n_steps=n_steps,
            batch_size=256,
            n_epochs=10,
            features_dim=64,
            val_eval_every=max(1000, ppo_timesteps // 20),
        )
        print(
            f"[ppo] training {ppo_seeds} seeds × {ppo_timesteps:,} timesteps "
            f"(n_steps={n_steps})",
            flush=True,
        )
        train_multi_seed(
            make_train_env,
            make_val_env,
            config,
            seeds=list(range(ppo_seeds)),
            save_dir=out_dir,
        )

    import json as _json

    with summary_path.open(encoding="utf-8") as fh:
        summary = _json.load(fh)
    best_seed = min(summary, key=lambda k: float(summary[k]["best_val_value"]))
    best_path = out_dir / f"seed_{best_seed}" / "ppo_per_tick_best.zip"
    print(f"[ppo] loading best seed={best_seed} from {best_path}", flush=True)
    return _PPO.load(str(best_path))


def _score_ppo_policy(
    label: str,
    model: "Any",
    *,
    printer_ids: list[int],
    dates,
    components_cfg,
    couplings_cfg,
    cities_cfg,
    downtime_loss_eur_per_day: float,
) -> BusinessScore:
    """Roll out a trained PPO over printer_ids; return a BusinessScore."""
    from ml.lib.rl.per_tick_env import MaintenancePerTickEnv
    from ml.lib.rl.recurrent_trainer import evaluate_per_tick_policy

    env = MaintenancePerTickEnv(
        list(printer_ids),
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
        dates=dates,
        downtime_loss_eur_per_day=float(downtime_loss_eur_per_day),
        downtime_lambda=0.0,
        cost_scale=1e5,
    )
    kpis = evaluate_per_tick_policy(model, env, deterministic=True)
    score = {
        "annual_cost": kpis["annual_cost"],
        "availability": kpis["availability"],
    }
    return business_from_score(
        label,
        "per-tick PPO (business-cost reward)",
        score,
        downtime_loss_eur_per_day=float(downtime_loss_eur_per_day),
    )


def _select_best(
    labels_and_scorers: list[tuple[str, Callable[[list[int]], BusinessScore]]],
    *,
    val_printers: list[int],
) -> tuple[BusinessScore, list[BusinessScore]]:
    scores: list[BusinessScore] = []
    for i, (_label, scorer) in enumerate(labels_and_scorers, start=1):
        if i == 1 or i % 50 == 0 or i == len(labels_and_scorers):
            print(f"[select] scoring {i}/{len(labels_and_scorers)}", flush=True)
        scores.append(scorer(val_printers))
    scores.sort(key=lambda s: s.business_cost)
    return scores[0], scores


def _score_rows(scores: list[BusinessScore], *, split: Split, horizon_days: int) -> pd.DataFrame:
    rows = []
    baseline = scores[0].business_cost
    for idx, score in enumerate(scores, start=1):
        rows.append(
            {
                "stage": f"stage_{idx:02d}",
                "label": score.label,
                "policy_class": score.policy_class,
                "business_cost": score.business_cost,
                "maintenance_cost": score.maintenance_cost,
                "downtime_loss": score.downtime_loss,
                "downtime_days_per_year": score.downtime_days_per_year,
                "availability": score.availability,
                "business_cost_reduction_vs_stage01_pct": (
                    (baseline - score.business_cost) / baseline * 100.0
                ),
                "split_profile": split.name,
                "n_train_printers": len(split.train),
                "n_val_printers": len(split.val),
                "n_test_printers": len(split.test),
                "horizon_days": horizon_days,
            }
        )
    return pd.DataFrame(rows)


def _write_figures(kpis: pd.DataFrame) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    colors = ["#6b7280", "#2563eb", "#059669"]

    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    values = kpis["business_cost"].astype(float) / 1_000_000.0
    bars = ax.bar(kpis["stage"], values, color=colors[: len(kpis)], width=0.62)
    ax.set_title("Business Cost by Stage")
    ax.set_ylabel("Business cost (M EUR / printer-year)")
    ax.margins(y=0.15)
    for bar, raw in zip(bars, kpis["business_cost"], strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            money_m(float(raw)),
            ha="center",
            va="bottom",
            fontsize=9,
        )
    fig.tight_layout()
    fig.savefig(FIG_DIR / "business_cost_by_stage.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    x = np.arange(len(kpis))
    width = 0.36
    ax.bar(x - width / 2, kpis["maintenance_cost"] / 1_000_000.0, width, label="maintenance", color="#2563eb")
    ax.bar(x + width / 2, kpis["downtime_loss"] / 1_000_000.0, width, label="downtime loss", color="#dc2626")
    ax.set_xticks(x, kpis["stage"])
    ax.set_ylabel("Cost component (M EUR / printer-year)")
    ax.set_title("Business Cost Components")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "business_cost_components.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.8, 5.0))
    ax.bar(kpis["stage"], kpis["availability"] * 100.0, color=colors[: len(kpis)], width=0.62)
    ax.set_ylabel("Availability (%)")
    ax.set_title("Availability by Stage")
    for i, value in enumerate(kpis["availability"]):
        ax.text(i, value * 100.0, f"{value * 100.0:.1f}%", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "availability_by_stage.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def _write_report(
    *,
    kpis: pd.DataFrame,
    split: Split,
    downtime_loss_eur_per_day: float,
    elapsed_seconds: float,
    stage2_val: BusinessScore,
    stage3_val: BusinessScore,
) -> None:
    display = kpis[
        [
            "stage",
            "label",
            "business_cost",
            "maintenance_cost",
            "downtime_loss",
            "availability",
            "business_cost_reduction_vs_stage01_pct",
        ]
    ].copy()
    display["business_cost"] = display["business_cost"].map(money_m)
    display["maintenance_cost"] = display["maintenance_cost"].map(money_m)
    display["downtime_loss"] = display["downtime_loss"].map(money_m)
    display["availability"] = display["availability"].map(lambda v: f"{float(v) * 100.0:.2f}%")
    display["business_cost_reduction_vs_stage01_pct"] = display[
        "business_cost_reduction_vs_stage01_pct"
    ].map(lambda v: f"{float(v):.2f}%")

    def md_table(df: pd.DataFrame) -> str:
        headers = list(df.columns)
        rows = [[str(v) for v in row] for row in df.itertuples(index=False, name=None)]
        widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]
        out = [
            "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
            "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
        ]
        for row in rows:
            out.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |")
        return "\n".join(out)

    report = f"""# Business-Cost Demo

Metric: annual maintenance cost plus downtime business loss. Lower is better.

**Stage 01 – naive lifetime-only baseline**: every preventive action fires at
`L_nom_d` for that component; no condition data is used. This is a deliberately
weak baseline. The gap to Stages 02/03 is the value of the data and policy work.

Downtime loss assumption: **{money_auto(downtime_loss_eur_per_day)} per printer-day down**.
This figure is fixed before any experiment and never tuned on test results.

Split profile `{split.name}`:

- train printers: {list(split.train)}
- validation printers: {list(split.val)}
- test printers: {list(split.test)}

The Stage 02 and Stage 03 policy choices were selected on validation and then
evaluated once on test. Test is not used for selection.

Runtime: {elapsed_seconds:.1f} seconds.

| selected on validation | validation business cost |
| --- | ---: |
| Stage 02: {stage2_val.label} | {money_m(stage2_val.business_cost)} |
| Stage 03: {stage3_val.label} | {money_m(stage3_val.business_cost)} |

## Test Results

{md_table(display)}

## Figures

![business_cost_by_stage](figures/business_cost_by_stage.png)

![business_cost_components](figures/business_cost_components.png)

![availability_by_stage](figures/availability_by_stage.png)
"""
    (OUT_DIR / "REPORT.md").write_text(report, encoding="utf-8")
    print(report, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("fast20", "final100"), default="final100")
    parser.add_argument("--days", type=int, default=1460)
    parser.add_argument("--stage2-trials", type=int, default=384)
    parser.add_argument("--downtime-loss-eur-per-day", type=float, default=30_000.0)
    parser.add_argument("--ppo-timesteps", type=int, default=500_000,
                        help="PPO total_timesteps per seed (500k fast, 1M+ final)")
    parser.add_argument("--ppo-seeds", type=int, default=3,
                        help="number of PPO seeds to train; best val seed is kept")
    parser.add_argument("--skip-ppo", action="store_true",
                        help="skip PPO training/scoring (threshold-only Stage 3)")
    args = parser.parse_args()
    started = time.perf_counter()

    split = split_for_profile(args.profile)
    components_cfg, couplings_cfg, cities_cfg = load_configs()
    dates = default_dates()[: int(args.days)]

    print(
        f"business-demo profile={split.name} train={len(split.train)} "
        f"val={len(split.val)} test={len(split.test)} days={len(dates)} "
        f"downtime_loss={args.downtime_loss_eur_per_day:g}",
        flush=True,
    )

    lifetime_tau = {
        c: float(components_cfg["components"][c]["L_nom_d"])
        for c in COMPONENT_IDS
    }
    stage1_test = _score_tau(
        "naive_lifetime_only",
        lifetime_tau,
        printer_ids=list(split.test),
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
        downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
    )

    stage2_scorers = []
    for label, tau in _constant_candidates(int(args.stage2_trials), components_cfg):
        stage2_scorers.append(
            (
                label,
                lambda printers, label=label, tau=tau: _score_tau(
                    label,
                    tau,
                    printer_ids=printers,
                    dates=dates,
                    components_cfg=components_cfg,
                    couplings_cfg=couplings_cfg,
                    cities_cfg=cities_cfg,
                    downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
                ),
            )
        )
    print("[stage02] selecting constant schedule on validation", flush=True)
    stage2_val, stage2_val_scores = _select_best(stage2_scorers, val_printers=list(split.val))
    stage2_tau = {c: float(stage2_val.details[f"tau_d_{c}"]) for c in COMPONENT_IDS}
    stage2_test = _score_tau(
        stage2_val.label,
        stage2_tau,
        printer_ids=list(split.test),
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
        downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
    )

    stage3_scorers = []
    for label, thresholds in _threshold_candidates():
        stage3_scorers.append(
            (
                label,
                lambda printers, label=label, thresholds=thresholds: _score_threshold_policy(
                    label,
                    thresholds,
                    printer_ids=printers,
                    dates=dates,
                    components_cfg=components_cfg,
                    couplings_cfg=couplings_cfg,
                    cities_cfg=cities_cfg,
                    downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
                ),
            )
        )
    print("[stage03] selecting condition-aware threshold policy on validation", flush=True)
    threshold_val, stage3_val_scores = _select_best(stage3_scorers, val_printers=list(split.val))
    threshold_thresholds = {c: float(threshold_val.details[f"H_threshold_{c}"]) for c in COMPONENT_IDS}
    threshold_test = _score_threshold_policy(
        threshold_val.label,
        threshold_thresholds,
        printer_ids=list(split.test),
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
        downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
    )

    # --- Stage 03b: per-tick PPO trained with business-cost reward ---
    ppo_dir = PROJECT_ROOT / "ml/03_rl/results/per_tick/business"
    if not args.skip_ppo:
        print("[stage03] training per-tick PPO with business-cost reward", flush=True)
        ppo_model = _train_business_ppo(
            split,
            dates=dates,
            components_cfg=components_cfg,
            couplings_cfg=couplings_cfg,
            cities_cfg=cities_cfg,
            downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
            ppo_timesteps=int(args.ppo_timesteps),
            ppo_seeds=int(args.ppo_seeds),
            out_dir=ppo_dir,
        )
        ppo_val = _score_ppo_policy(
            "ppo_business_cost_reward",
            ppo_model,
            printer_ids=list(split.val),
            dates=dates,
            components_cfg=components_cfg,
            couplings_cfg=couplings_cfg,
            cities_cfg=cities_cfg,
            downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
        )
        # Select Stage 3 winner on validation (lower business cost = better).
        if ppo_val.business_cost < threshold_val.business_cost:
            print(
                f"[stage03] PPO wins on val "
                f"({ppo_val.business_cost:.0f} < {threshold_val.business_cost:.0f})",
                flush=True,
            )
            stage3_val = ppo_val
            stage3_test = _score_ppo_policy(
                "ppo_business_cost_reward",
                ppo_model,
                printer_ids=list(split.test),
                dates=dates,
                components_cfg=components_cfg,
                couplings_cfg=couplings_cfg,
                cities_cfg=cities_cfg,
                downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
            )
        else:
            print(
                f"[stage03] threshold policy wins on val "
                f"({threshold_val.business_cost:.0f} < {ppo_val.business_cost:.0f})",
                flush=True,
            )
            stage3_val = threshold_val
            stage3_test = threshold_test
        # Append PPO to the val leaderboard for honesty.
        stage3_val_scores.append(ppo_val)
    else:
        stage3_val = threshold_val
        stage3_test = threshold_test

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    kpis = _score_rows([stage1_test, stage2_test, stage3_test], split=split, horizon_days=len(dates))
    kpis.to_csv(OUT_DIR / "stage_kpis.csv", index=False)
    pd.DataFrame([s.__dict__ | s.details for s in stage2_val_scores]).to_csv(
        OUT_DIR / "stage02_val_leaderboard.csv", index=False
    )
    pd.DataFrame([s.__dict__ | s.details for s in stage3_val_scores]).to_csv(
        OUT_DIR / "stage03_val_leaderboard.csv", index=False
    )
    payload = {
        "profile": split.name,
        "train_printers": list(split.train),
        "val_printers": list(split.val),
        "test_printers": list(split.test),
        "horizon_days": len(dates),
        "downtime_loss_eur_per_day": float(args.downtime_loss_eur_per_day),
        "stage01_tau_lifetime_d": lifetime_tau,
        "stage02_selected_tau_d": stage2_tau,
        "stage03_winner_label": stage3_val.label,
        "stage03_winner_policy_class": stage3_val.policy_class,
        "stage03_threshold_thresholds": threshold_thresholds,
        "ppo_artifacts_dir": str(ppo_dir) if not args.skip_ppo else None,
    }
    (OUT_DIR / "policies.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    _write_figures(kpis)
    _write_report(
        kpis=kpis,
        split=split,
        downtime_loss_eur_per_day=float(args.downtime_loss_eur_per_day),
        elapsed_seconds=time.perf_counter() - started,
        stage2_val=stage2_val,
        stage3_val=stage3_val,
    )
    print(f"Wrote {OUT_DIR}", flush=True)


if __name__ == "__main__":
    main()
