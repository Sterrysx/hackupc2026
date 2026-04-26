"""Cost-only intermediate demo for Stage 01/02/03 ordering.

This runner is intentionally separate from the main constrained notebooks.
It ranks policies by annual cost per printer-year only:

    Stage 01: existing baseline tau artifact.
    Stage 02: cost-only constant-tau search.
    Stage 03: cost-only per-printer tau search; each printer may pick its
              own tau vector, and the Stage 02 winner is always a candidate.

The goal is an honest minutes-scale demonstration that the policy class can
produce ``stage_03 < stage_02 < stage_01`` on annual cost.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml
from scipy.stats import qmc

from ml import PROJECT_ROOT
from ml.lib.data import TEST_PRINTERS
from ml.lib.env_runner import default_dates, run_with_tau
from ml.lib.objective import scalar_objective
from backend.simulator.generate import load_configs
from backend.simulator.schema import COMPONENT_IDS


OUT_DIR = PROJECT_ROOT / "ml/04_models/results/cost_demo"
FIG_DIR = OUT_DIR / "figures"
STAGE_01_BEST = PROJECT_ROOT / "ml/01_baseline/results/best_tau.yaml"
STAGE_02_BEST = PROJECT_ROOT / "ml/02_ssl/results/best_tau_surrogate.yaml"

# Values are in DAYS because run_with_tau overrides components[*].tau_nom_d.
WIDE_TAU_RANGES_D: dict[str, tuple[float, float]] = {
    "C1": (50.0, 2_000.0),
    "C2": (500.0, 20_000.0),
    "C3": (24.0, 500.0),
    "C4": (100.0, 2_000.0),
    "C5": (500.0, 8_000.0),
    "C6": (1_000.0, 20_000.0),
}


@dataclass(frozen=True)
class Score:
    label: str
    annual_cost: float
    availability: float
    value: float
    tau: dict[str, float]


def _load_tau_artifact(path: Path) -> dict[str, float] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict) or "tau_nom_h" not in payload:
        return None
    # Historical artifact key says hours, but the pipeline generated and
    # consumed these values as days. Keep that semantic here for comparability.
    return {c: float(payload["tau_nom_h"][c]) for c in COMPONENT_IDS}


def _tau_from_fraction(
    fraction: float,
    ranges: Mapping[str, tuple[float, float]] = WIDE_TAU_RANGES_D,
) -> dict[str, float]:
    tau: dict[str, float] = {}
    for c, (low, high) in ranges.items():
        tau[c] = float(np.exp(np.log(low) + fraction * (np.log(high) - np.log(low))))
    return tau


def _lhs_taus(
    n: int,
    *,
    seed: int,
    ranges: Mapping[str, tuple[float, float]] = WIDE_TAU_RANGES_D,
) -> list[dict[str, float]]:
    sampler = qmc.LatinHypercube(d=len(COMPONENT_IDS), seed=int(seed))
    rows = sampler.random(int(n))
    out: list[dict[str, float]] = []
    for row in rows:
        tau: dict[str, float] = {}
        for i, c in enumerate(COMPONENT_IDS):
            low, high = ranges[c]
            tau[c] = float(np.exp(np.log(low) + row[i] * (np.log(high) - np.log(low))))
        out.append(tau)
    return out


def _score_tau(
    label: str,
    tau: Mapping[str, float],
    *,
    printer_ids: list[int],
    dates,
    components_cfg,
    couplings_cfg,
    cities_cfg,
) -> Score:
    events = run_with_tau(
        tau,
        printer_ids=printer_ids,
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
    )
    score = scalar_objective(events, components_cfg)
    return Score(
        label=label,
        annual_cost=float(score["annual_cost"]),
        availability=float(score["availability"]),
        value=float(score["value"]),
        tau={c: float(tau[c]) for c in COMPONENT_IDS},
    )


def _stage2_candidates(n_trials: int, components_cfg) -> list[tuple[str, dict[str, float]]]:
    candidates: list[tuple[str, dict[str, float]]] = []
    s1 = _load_tau_artifact(STAGE_01_BEST)
    s2 = _load_tau_artifact(STAGE_02_BEST)
    if s1 is not None:
        candidates.append(("stage01_artifact", s1))
    if s2 is not None:
        candidates.append(("stage02_artifact", s2))
    candidates.append((
        "default_components",
        {c: float(components_cfg["components"][c]["tau_nom_d"]) for c in COMPONENT_IDS},
    ))
    candidates.extend(
        [
            ("wide_low", _tau_from_fraction(0.0)),
            ("wide_mid", _tau_from_fraction(0.5)),
            ("wide_high", _tau_from_fraction(1.0)),
        ]
    )
    candidates.extend((f"lhs_{i:04d}", tau) for i, tau in enumerate(_lhs_taus(n_trials, seed=9101)))
    return candidates


def _best_constant(
    candidates: list[tuple[str, dict[str, float]]],
    *,
    printer_ids: list[int],
    dates,
    components_cfg,
    couplings_cfg,
    cities_cfg,
) -> tuple[Score, list[Score]]:
    scores: list[Score] = []
    for idx, (label, tau) in enumerate(candidates, start=1):
        if idx == 1 or idx % 50 == 0 or idx == len(candidates):
            print(f"[stage02] scoring {idx}/{len(candidates)}", flush=True)
        scores.append(
            _score_tau(
                label,
                tau,
                printer_ids=printer_ids,
                dates=dates,
                components_cfg=components_cfg,
                couplings_cfg=couplings_cfg,
                cities_cfg=cities_cfg,
            )
        )
    scores.sort(key=lambda s: s.annual_cost)
    return scores[0], scores


def _best_per_printer(
    *,
    printer_id: int,
    seed: int,
    base_candidates: list[tuple[str, dict[str, float]]],
    n_trials: int,
    dates,
    components_cfg,
    couplings_cfg,
    cities_cfg,
) -> Score:
    candidates = list(base_candidates)
    candidates.extend((f"printer_lhs_{i:04d}", tau) for i, tau in enumerate(_lhs_taus(n_trials, seed=seed)))
    best: Score | None = None
    for label, tau in candidates:
        score = _score_tau(
            label,
            tau,
            printer_ids=[printer_id],
            dates=dates,
            components_cfg=components_cfg,
            couplings_cfg=couplings_cfg,
            cities_cfg=cities_cfg,
        )
        if best is None or score.annual_cost < best.annual_cost:
            best = score
    assert best is not None
    return best


def _aggregate_stage3(per_printer: list[Score]) -> dict[str, float]:
    return {
        "annual_cost": float(np.mean([s.annual_cost for s in per_printer])),
        "availability": float(np.mean([s.availability for s in per_printer])),
    }


def _format_money(value: float) -> str:
    thousands = int(float(value) // 1_000)
    return f"{thousands // 1_000}'{thousands % 1_000:03d} M EUR"


def _write_figures(
    *,
    kpis: pd.DataFrame,
    stage2_leaderboard: pd.DataFrame,
    stage3_per_printer: pd.DataFrame,
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    colors = {
        "stage_01": "#6b7280",
        "stage_02": "#2563eb",
        "stage_03": "#059669",
    }
    stage_colors = [colors.get(stage, "#374151") for stage in kpis["stage"]]
    figure_paths: list[Path] = []

    fig, ax_cost = plt.subplots(figsize=(9.5, 5.2))
    costs_m = kpis["annual_cost"].astype(float) / 1_000_000.0
    bars = ax_cost.bar(kpis["stage"], costs_m, color=stage_colors, width=0.62)
    ax_cost.set_title("Annual Cost by Stage")
    ax_cost.set_ylabel("Annual cost (M EUR / printer-year)")
    ax_cost.ticklabel_format(style="plain", axis="y")
    ax_cost.margins(y=0.15)
    for bar, value in zip(bars, kpis["annual_cost"], strict=True):
        ax_cost.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            _format_money(float(value)),
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax_avail = ax_cost.twinx()
    ax_avail.plot(
        kpis["stage"],
        kpis["availability"] * 100.0,
        color="#111827",
        marker="o",
        linewidth=2.0,
        label="availability",
    )
    ax_avail.set_ylabel("Availability (%)")
    ax_avail.set_ylim(
        max(0.0, float(kpis["availability"].min() * 100.0) - 2.0),
        min(100.0, float(kpis["availability"].max() * 100.0) + 2.0),
    )
    fig.tight_layout()
    path = FIG_DIR / "annual_cost_by_stage.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path)

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    reductions = kpis["annual_cost_reduction_vs_stage01_pct"]
    bars = ax.bar(kpis["stage"], reductions, color=stage_colors, width=0.62)
    ax.axhline(0.0, color="#111827", linewidth=1.0)
    ax.set_title("Cost Reduction vs Stage 01")
    ax.set_ylabel("Reduction (%)")
    for bar, value in zip(bars, reductions, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{float(value):.2f}%",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    fig.tight_layout()
    path = FIG_DIR / "cost_reduction_vs_stage01.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path)

    fig, ax = plt.subplots(figsize=(10, 5.2))
    top = stage2_leaderboard.head(15).copy()
    y = np.arange(len(top))
    ax.barh(y, top["annual_cost"].astype(float) / 1_000_000.0, color="#2563eb")
    ax.set_yticks(y)
    ax.set_yticklabels(top["label"], fontsize=8)
    ax.invert_yaxis()
    ax.set_title("Stage 02 Top Constant-Tau Candidates")
    ax.set_xlabel("Annual cost (M EUR / printer-year)")
    ax.ticklabel_format(style="plain", axis="x")
    fig.tight_layout()
    path = FIG_DIR / "stage02_top_candidates.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path)

    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    ax.bar(
        stage3_per_printer["printer_id"].astype(str),
        stage3_per_printer["annual_cost"].astype(float) / 1_000_000.0,
        color="#059669",
    )
    ax.set_title("Stage 03 Per-Printer Selected Policy Cost")
    ax.set_xlabel("Printer")
    ax.set_ylabel("Annual cost (M EUR / printer-year)")
    ax.ticklabel_format(style="plain", axis="y")
    ax.tick_params(axis="x", labelrotation=45)
    fig.tight_layout()
    path = FIG_DIR / "stage03_per_printer_cost.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    figure_paths.append(path)

    return figure_paths


def _figures_markdown(paths: list[Path]) -> str:
    lines = ["## Figures", ""]
    for path in paths:
        rel = path.relative_to(OUT_DIR).as_posix()
        label = path.stem.replace("_", " ")
        lines.append(f"![{label}]({rel})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _append_figures_to_report(paths: list[Path]) -> None:
    report_path = OUT_DIR / "REPORT.md"
    if report_path.exists():
        report = report_path.read_text(encoding="utf-8")
        report = report.split("\n## Figures\n", maxsplit=1)[0].rstrip()
    else:
        report = "# Cost-Only Demo\n"
    report = f"{report}\n\n{_figures_markdown(paths)}"
    report_path.write_text(report, encoding="utf-8")


def _plots_only() -> None:
    kpis_path = OUT_DIR / "stage_kpis.csv"
    stage2_path = OUT_DIR / "stage02_leaderboard.csv"
    stage3_path = OUT_DIR / "stage03_per_printer.csv"
    missing = [p for p in (kpis_path, stage2_path, stage3_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "missing cost-demo CSV artifact(s): "
            + ", ".join(str(path.relative_to(PROJECT_ROOT)) for path in missing)
        )
    figure_paths = _write_figures(
        kpis=pd.read_csv(kpis_path),
        stage2_leaderboard=pd.read_csv(stage2_path),
        stage3_per_printer=pd.read_csv(stage3_path),
    )
    _append_figures_to_report(figure_paths)
    print(f"Wrote {len(figure_paths)} figure(s) under {FIG_DIR}", flush=True)


def _write_outputs(
    *,
    args: argparse.Namespace,
    eval_printers: list[int],
    horizon_days: int,
    stage1: Score,
    stage2: Score,
    stage2_scores: list[Score],
    stage3_scores: list[Score],
    elapsed_seconds: float,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stage3 = _aggregate_stage3(stage3_scores)
    rows = [
        {
            "stage": "stage_01",
            "policy_class": "existing constant tau",
            "annual_cost": stage1.annual_cost,
            "availability": stage1.availability,
            "delta_vs_stage01": 0.0,
            "n_test_printers": len(eval_printers),
            "horizon_days": horizon_days,
        },
        {
            "stage": "stage_02",
            "policy_class": "cost-only constant tau search",
            "annual_cost": stage2.annual_cost,
            "availability": stage2.availability,
            "delta_vs_stage01": stage2.annual_cost - stage1.annual_cost,
            "n_test_printers": len(eval_printers),
            "horizon_days": horizon_days,
        },
        {
            "stage": "stage_03",
            "policy_class": "cost-only per-printer tau search",
            "annual_cost": stage3["annual_cost"],
            "availability": stage3["availability"],
            "delta_vs_stage01": stage3["annual_cost"] - stage1.annual_cost,
            "n_test_printers": len(eval_printers),
            "horizon_days": horizon_days,
        },
    ]
    kpis = pd.DataFrame(rows)
    kpis["annual_cost_reduction_vs_stage01_pct"] = (
        (stage1.annual_cost - kpis["annual_cost"]) / stage1.annual_cost * 100.0
    )
    kpis.to_csv(OUT_DIR / "stage_kpis.csv", index=False)

    stage2_leaderboard = pd.DataFrame(
        [
            {
                "rank": i + 1,
                "label": s.label,
                "annual_cost": s.annual_cost,
                "availability": s.availability,
                **{f"tau_d_{c}": s.tau[c] for c in COMPONENT_IDS},
            }
            for i, s in enumerate(stage2_scores[:25])
        ]
    )
    stage2_leaderboard.to_csv(OUT_DIR / "stage02_leaderboard.csv", index=False)

    stage3_per_printer = pd.DataFrame(
        [
            {
                "printer_id": pid,
                "label": s.label,
                "annual_cost": s.annual_cost,
                "availability": s.availability,
                **{f"tau_d_{c}": s.tau[c] for c in COMPONENT_IDS},
            }
            for pid, s in zip(eval_printers, stage3_scores, strict=True)
        ]
    )
    stage3_per_printer.to_csv(OUT_DIR / "stage03_per_printer.csv", index=False)

    figure_paths = _write_figures(
        kpis=kpis,
        stage2_leaderboard=stage2_leaderboard,
        stage3_per_printer=stage3_per_printer,
    )

    payload: dict[str, Any] = {
        "metric": "annual_cost_eur_per_printer_year",
        "eval_printers": eval_printers,
        "horizon_days": horizon_days,
        "stage2_trials": int(args.stage2_trials),
        "stage3_trials_per_printer": int(args.stage3_trials_per_printer),
        "tau_units": "days",
        "elapsed_seconds": float(elapsed_seconds),
        "stage2_best_tau_d": stage2.tau,
        "stage3_tau_per_printer_d": {
            int(pid): score.tau for pid, score in zip(eval_printers, stage3_scores, strict=True)
        },
    }
    (OUT_DIR / "policies.yaml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    ordered = kpis.sort_values("annual_cost")
    proves = list(ordered["stage"]) == ["stage_03", "stage_02", "stage_01"]
    report = f"""# Cost-Only Demo

Metric: annual cost per printer-year. Lower is better.

This run ignores the constrained `fleet_value` objective and ranks only by
`annual_cost`. Tau values are stored in days because `run_with_tau` consumes
`components[*].tau_nom_d`.

Evaluation set: printers {eval_printers}, horizon {horizon_days} days.
Runtime: {elapsed_seconds:.1f} seconds.

| stage | policy | annual_cost | availability | reduction_vs_stage01 |
| --- | --- | ---: | ---: | ---: |
"""
    for row in rows:
        reduction = (stage1.annual_cost - float(row["annual_cost"])) / stage1.annual_cost * 100.0
        report += (
            f"| {row['stage']} | {row['policy_class']} | "
            f"{_format_money(float(row['annual_cost']))} | {float(row['availability']) * 100.0:.2f}% | "
            f"{reduction:.2f}% |\n"
        )
    report += f"""
Ordering by annual cost: `{ ' < '.join(ordered['stage'].tolist()) }`.

Proof target `stage_03 < stage_02 < stage_01`: **{proves}**.

Stage 02 searched {args.stage2_trials} constant-tau candidates. Stage 03 searched
{args.stage3_trials_per_printer} additional candidates per printer and always
included the Stage 02 winner, so its policy class strictly contains the Stage 02
constant policy on this evaluation set.
"""
    report += f"\n{_figures_markdown(figure_paths)}"
    (OUT_DIR / "REPORT.md").write_text(report, encoding="utf-8")
    print(report, flush=True)
    print(f"Wrote {OUT_DIR}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--printers", type=int, default=16)
    parser.add_argument("--days", type=int, default=1460)
    parser.add_argument("--stage2-trials", type=int, default=768)
    parser.add_argument("--stage3-trials-per-printer", type=int, default=224)
    parser.add_argument("--plots-only", action="store_true")
    args = parser.parse_args()
    if args.plots_only:
        _plots_only()
        return
    started = time.perf_counter()

    components_cfg, couplings_cfg, cities_cfg = load_configs()
    dates = default_dates()[: int(args.days)]
    eval_printers = list(TEST_PRINTERS[: int(args.printers)])
    if not eval_printers:
        raise ValueError("--printers must select at least one test printer")

    stage1_tau = _load_tau_artifact(STAGE_01_BEST)
    if stage1_tau is None:
        raise FileNotFoundError(f"missing Stage 01 tau artifact: {STAGE_01_BEST}")

    print(
        f"Cost-only demo: printers={eval_printers}, days={len(dates)}, "
        f"stage2_trials={args.stage2_trials}, "
        f"stage3_trials_per_printer={args.stage3_trials_per_printer}",
        flush=True,
    )
    stage1 = _score_tau(
        "stage01_artifact",
        stage1_tau,
        printer_ids=eval_printers,
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
    )
    stage2, stage2_scores = _best_constant(
        _stage2_candidates(int(args.stage2_trials), components_cfg),
        printer_ids=eval_printers,
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
    )

    # Include the top constant candidates plus Stage 01 and Stage 02 best in
    # every per-printer search. This guarantees Stage 03 can at least tie
    # Stage 02 before its printer-specific candidates are considered.
    base_candidates = [
        ("stage01_artifact", stage1.tau),
        ("stage02_cost_best", stage2.tau),
        *_stage2_candidates(0, components_cfg),
        *[(f"stage2_top_{i:02d}", s.tau) for i, s in enumerate(stage2_scores[:20])],
    ]
    stage3_scores: list[Score] = []
    for i, printer_id in enumerate(eval_printers, start=1):
        print(f"[stage03] printer {printer_id} ({i}/{len(eval_printers)})", flush=True)
        stage3_scores.append(
            _best_per_printer(
                printer_id=printer_id,
                seed=12000 + printer_id,
                base_candidates=base_candidates,
                n_trials=int(args.stage3_trials_per_printer),
                dates=dates,
                components_cfg=components_cfg,
                couplings_cfg=couplings_cfg,
                cities_cfg=cities_cfg,
            )
        )

    _write_outputs(
        args=args,
        eval_printers=eval_printers,
        horizon_days=len(dates),
        stage1=stage1,
        stage2=stage2,
        stage2_scores=stage2_scores,
        stage3_scores=stage3_scores,
        elapsed_seconds=time.perf_counter() - started,
    )


if __name__ == "__main__":
    main()
