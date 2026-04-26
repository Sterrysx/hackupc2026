from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml


COMPONENTS = ("C1", "C2", "C3", "C4", "C5", "C6")


def find_repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "ml").exists():
            return candidate
    raise RuntimeError(f"Could not find repository root from {start}")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a YAML mapping")
    return data


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not contain a JSON mapping")
    return data


def pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def money(value: float) -> str:
    thousands = int(float(value) // 1_000)
    return f"{thousands // 1_000}'{thousands % 1_000:03d} M EUR"


def short_float(value: float) -> str:
    if abs(value) >= 1e9:
        return f"{value / 1e9:.3f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.3f}M"
    if abs(value) >= 1e3:
        return f"{value / 1e3:.3f}K"
    return f"{value:.3f}"


def short_money(value: float) -> str:
    return money(value)


def md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    headers = list(df.columns)
    rows = [[str(v) for v in row] for row in df.itertuples(index=False, name=None)]
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows))
        for i in range(len(headers))
    ]
    out = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    for row in rows:
        out.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(out)


def _paths(root: Path, out_dir: Path) -> dict[str, Path]:
    return {
        "stage_01_best": root / "ml/01_baseline/results/best_tau.yaml",
        "stage_02_best": root / "ml/02_ssl/results/best_tau_surrogate.yaml",
        "stage_02_test_metrics": root / "ml/02_ssl/results/test_metrics.json",
        "stage_03_kpi": root / "ml/03_rl/results/kpi_comparison.csv",
        "stage_03_per_tick_kpi": root / "ml/03_rl/results/per_tick/kpi_comparison_with_ci.csv",
        "stage_03_per_tick_summary": root / "ml/03_rl/results/per_tick/per_tick_summary.yaml",
        "stage_03_per_tick_printers": root / "ml/03_rl/results/per_tick/per_printer_test_ensemble.csv",
        "stage_03_tau": root / "ml/03_rl/results/best_tau_per_printer.yaml",
        "cost_demo_kpis": out_dir / "cost_demo/stage_kpis.csv",
        "cost_demo_leaderboard": out_dir / "cost_demo/stage02_leaderboard.csv",
        "cost_demo_per_printer": out_dir / "cost_demo/stage03_per_printer.csv",
        "business_demo_kpis": out_dir / "business_demo/stage_kpis.csv",
    }


def require_inputs(root: Path, out_dir: Path) -> None:
    paths = _paths(root, out_dir)
    required = [
        paths["stage_01_best"],
        paths["stage_02_best"],
        paths["stage_02_test_metrics"],
        paths["stage_03_kpi"],
        paths["stage_03_per_tick_kpi"],
        paths["stage_03_per_tick_summary"],
        paths["stage_03_per_tick_printers"],
        paths["stage_03_tau"],
    ]
    missing = [str(p.relative_to(root)) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing comparison inputs. Run stages 01/02/03 first:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )


def load_cost_demo(root: Path, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None:
    paths = _paths(root, out_dir)
    inputs = [paths["cost_demo_kpis"], paths["cost_demo_leaderboard"], paths["cost_demo_per_printer"]]
    if not all(path.exists() for path in inputs):
        return None
    return (
        pd.read_csv(paths["cost_demo_kpis"]),
        pd.read_csv(paths["cost_demo_leaderboard"]),
        pd.read_csv(paths["cost_demo_per_printer"]),
    )


def load_business_demo(root: Path, out_dir: Path) -> pd.DataFrame | None:
    path = _paths(root, out_dir)["business_demo_kpis"]
    if not path.exists():
        return None
    return pd.read_csv(path)


def build_pipeline_stage_kpis(root: Path, out_dir: Path) -> pd.DataFrame:
    src = pd.read_csv(_paths(root, out_dir)["stage_03_per_tick_kpi"])
    keep = src[src["stage"].isin(["stage_01", "stage_02", "stage_03_per_tick"])].copy()
    labels = {
        "stage_01": "Stage 01 - Optuna constant tau",
        "stage_02": "Stage 02 - SSL/RUL surrogate tau",
        "stage_03_per_tick": "Stage 03 - per-tick PPO+SPR ensemble",
    }
    keep["stage_label"] = keep["stage"].map(labels)
    keep = keep.sort_values("stage").reset_index(drop=True)

    baseline = float(keep.loc[keep["stage"] == "stage_01", "fleet_annual_cost"].iloc[0])
    baseline_value = float(keep.loc[keep["stage"] == "stage_01", "fleet_value"].iloc[0])
    keep["annual_cost_delta_vs_stage01"] = keep["fleet_annual_cost"] - baseline
    keep["annual_cost_reduction_vs_stage01_pct"] = (baseline - keep["fleet_annual_cost"]) / baseline
    keep["value_delta_vs_stage01"] = keep["fleet_value"] - baseline_value
    keep["value_reduction_vs_stage01_pct"] = (baseline_value - keep["fleet_value"]) / baseline_value
    return keep


def build_tau_comparison(root: Path, out_dir: Path) -> pd.DataFrame:
    paths = _paths(root, out_dir)
    s1 = load_yaml(paths["stage_01_best"])["tau_nom_h"]
    s2 = load_yaml(paths["stage_02_best"])["tau_nom_h"]
    s3 = load_yaml(paths["stage_03_tau"])["tau_per_printer"]
    s3_df = pd.DataFrame.from_dict(s3, orient="index").astype(float)

    rows = []
    for component in COMPONENTS:
        rows.append(
            {
                "component": component,
                "stage_01_tau_h": float(s1[component]),
                "stage_02_tau_h": float(s2[component]),
                "stage_03_per_printer_tau_mean_h": float(s3_df[component].mean()),
                "stage_03_per_printer_tau_min_h": float(s3_df[component].min()),
                "stage_03_per_printer_tau_max_h": float(s3_df[component].max()),
            }
        )
    return pd.DataFrame(rows)


def build_auxiliary_stage03(root: Path, out_dir: Path) -> pd.DataFrame:
    return pd.read_csv(_paths(root, out_dir)["stage_03_kpi"])


def build_stage03_per_printer_summary(root: Path, out_dir: Path) -> pd.DataFrame:
    df = pd.read_csv(_paths(root, out_dir)["stage_03_per_tick_printers"])
    cols = [
        "printer_id",
        "annual_cost",
        "availability",
        "deficit",
        "n_preventive",
        "n_corrective",
    ]
    return df[cols].copy()


def write_pipeline_plots(
    *,
    pipeline_kpis: pd.DataFrame,
    tau_df: pd.DataFrame,
    per_printer: pd.DataFrame,
    fig_dir: Path,
) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    labels = ["Stage 01", "Stage 02", "Stage 03"]
    colors = ["#6b7280", "#2563eb", "#059669"]

    fig, ax_cost = plt.subplots(figsize=(10, 5.5))
    x = np.arange(len(pipeline_kpis))
    costs_m = pipeline_kpis["fleet_annual_cost"].to_numpy(dtype=float) / 1e6
    ax_cost.bar(x, costs_m, color=colors, alpha=0.86)
    ax_cost.set_ylabel("Annual cost (EUR M / printer-year)")
    ax_cost.set_xticks(x, labels)
    ax_cost.set_title("Fast pipeline artifact cost and availability")
    ax_avail = ax_cost.twinx()
    ax_avail.plot(x, pipeline_kpis["fleet_availability"], color="#111827", marker="o", linewidth=2.0)
    ax_avail.set_ylim(0, 1)
    ax_avail.set_ylabel("Availability")
    for i, value in enumerate(costs_m):
        ax_cost.text(i, value, f"{value:.2f}M", ha="center", va="bottom", fontsize=9)
    for i, value in enumerate(pipeline_kpis["fleet_availability"]):
        ax_avail.text(i, value + 0.03, pct(float(value)), ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "pipeline_cost_availability_by_stage.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    values_b = pipeline_kpis["fleet_value"].to_numpy(dtype=float) / 1e9
    ax.bar(labels, values_b, color=colors, alpha=0.86)
    ax.set_ylabel("Penalized objective (B)")
    ax.set_title("Fast pipeline penalized objective by stage")
    for i, value in enumerate(values_b):
        ax.text(i, value, f"{value:.2f}B", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(fig_dir / "penalized_value_by_stage.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    idx = np.arange(len(tau_df))
    width = 0.25
    ax.bar(idx - width, tau_df["stage_01_tau_h"], width, label="Stage 01", color=colors[0])
    ax.bar(idx, tau_df["stage_02_tau_h"], width, label="Stage 02", color=colors[1])
    ax.bar(
        idx + width,
        tau_df["stage_03_per_printer_tau_mean_h"],
        width,
        label="Stage 03 per-printer mean",
        color=colors[2],
    )
    ax.set_yscale("log")
    ax.set_xticks(idx, tau_df["component"])
    ax.set_ylabel("tau interval (hours, log scale)")
    ax.set_title("Maintenance interval comparison")
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "tau_comparison.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5.5))
    ax.scatter(
        per_printer["availability"],
        per_printer["annual_cost"] / 1e6,
        s=58,
        color="#059669",
        edgecolor="#064e3b",
        linewidth=0.8,
    )
    for _, row in per_printer.iterrows():
        ax.text(row["availability"] + 0.004, row["annual_cost"] / 1e6, str(int(row["printer_id"])), fontsize=8)
    ax.set_xlabel("Availability")
    ax.set_ylabel("Annual cost (EUR M / printer-year)")
    ax.set_title("Stage 03 per-tick ensemble by test printer")
    fig.tight_layout()
    fig.savefig(fig_dir / "stage03_per_printer_cost_availability.png", dpi=160)
    plt.close(fig)


def write_cost_demo_plots(
    *,
    cost_kpis: pd.DataFrame,
    stage2_leaderboard: pd.DataFrame,
    stage3_per_printer: pd.DataFrame,
    fig_dir: Path,
) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    colors = {
        "stage_01": "#6b7280",
        "stage_02": "#2563eb",
        "stage_03": "#059669",
    }
    stage_colors = [colors.get(stage, "#374151") for stage in cost_kpis["stage"]]

    fig, ax_cost = plt.subplots(figsize=(9.5, 5.2))
    costs_m = cost_kpis["annual_cost"].astype(float) / 1_000_000.0
    bars = ax_cost.bar(cost_kpis["stage"], costs_m, color=stage_colors, width=0.62)
    ax_cost.set_title("Annual Cost by Stage")
    ax_cost.set_ylabel("Annual cost (M EUR / printer-year)")
    ax_cost.ticklabel_format(style="plain", axis="y")
    ax_cost.margins(y=0.15)
    for bar, value in zip(bars, cost_kpis["annual_cost"], strict=True):
        ax_cost.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            short_money(float(value)),
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax_avail = ax_cost.twinx()
    ax_avail.plot(
        cost_kpis["stage"],
        cost_kpis["availability"] * 100.0,
        color="#111827",
        marker="o",
        linewidth=2.0,
    )
    ax_avail.set_ylabel("Availability (%)")
    ax_avail.set_ylim(
        max(0.0, float(cost_kpis["availability"].min() * 100.0) - 2.0),
        min(100.0, float(cost_kpis["availability"].max() * 100.0) + 2.0),
    )
    fig.tight_layout()
    fig.savefig(fig_dir / "cost_availability_by_stage.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    reductions = cost_kpis["annual_cost_reduction_vs_stage01_pct"]
    bars = ax.bar(cost_kpis["stage"], reductions, color=stage_colors, width=0.62)
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
    fig.savefig(fig_dir / "cost_reduction_vs_stage01.png", dpi=160)
    plt.close(fig)

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
    fig.savefig(fig_dir / "stage02_top_candidates.png", dpi=160)
    plt.close(fig)

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
    fig.savefig(fig_dir / "stage03_per_printer_cost.png", dpi=160)
    plt.close(fig)


def _format_cost_demo_table(cost_kpis: pd.DataFrame) -> pd.DataFrame:
    display = cost_kpis[
        [
            "stage",
            "policy_class",
            "annual_cost",
            "availability",
            "annual_cost_reduction_vs_stage01_pct",
        ]
    ].copy()
    display.columns = ["stage", "policy", "annual_cost", "availability", "cost_reduction_vs_01"]
    display["annual_cost"] = display["annual_cost"].map(money)
    display["availability"] = display["availability"].map(pct)
    display["cost_reduction_vs_01"] = display["cost_reduction_vs_01"].map(lambda v: f"{float(v):.2f}%")
    return display


def _format_business_demo_table(business_kpis: pd.DataFrame) -> pd.DataFrame:
    display = business_kpis[
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
    display.columns = [
        "stage",
        "policy",
        "business_cost",
        "maintenance_cost",
        "downtime_loss",
        "availability",
        "reduction_vs_01",
    ]
    display["business_cost"] = display["business_cost"].map(money)
    display["maintenance_cost"] = display["maintenance_cost"].map(money)
    display["downtime_loss"] = display["downtime_loss"].map(money)
    display["availability"] = display["availability"].map(pct)
    display["reduction_vs_01"] = display["reduction_vs_01"].map(lambda v: f"{float(v):.2f}%")
    return display


def _format_pipeline_table(pipeline_kpis: pd.DataFrame) -> pd.DataFrame:
    display = pipeline_kpis[
        [
            "stage_label",
            "policy_class",
            "fleet_annual_cost",
            "fleet_availability",
            "fleet_deficit",
            "fleet_value",
            "annual_cost_reduction_vs_stage01_pct",
            "value_reduction_vs_stage01_pct",
        ]
    ].copy()
    display.columns = [
        "stage",
        "policy",
        "annual_cost",
        "availability",
        "deficit",
        "penalized_value",
        "cost_reduction_vs_01",
        "value_reduction_vs_01",
    ]
    display["annual_cost"] = display["annual_cost"].map(money)
    display["availability"] = display["availability"].map(pct)
    display["deficit"] = display["deficit"].map(pct)
    display["penalized_value"] = display["penalized_value"].map(short_float)
    display["cost_reduction_vs_01"] = display["cost_reduction_vs_01"].map(pct)
    display["value_reduction_vs_01"] = display["value_reduction_vs_01"].map(pct)
    return display


def write_report(
    *,
    root: Path,
    out_dir: Path,
    pipeline_kpis: pd.DataFrame,
    tau_df: pd.DataFrame,
    aux_stage03: pd.DataFrame,
    per_printer: pd.DataFrame,
    business_demo: pd.DataFrame | None,
    cost_demo: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame] | None,
) -> None:
    paths = _paths(root, out_dir)
    s2_metrics = load_json(paths["stage_02_test_metrics"])
    per_tick_summary = load_yaml(paths["stage_03_per_tick_summary"])

    tau_display = tau_df.copy()
    for col in tau_display.columns:
        if col != "component":
            tau_display[col] = tau_display[col].map(lambda v: f"{v:,.1f}")

    aux_display = aux_stage03.copy()
    aux_display["fleet_annual_cost"] = aux_display["fleet_annual_cost"].map(money)
    aux_display["fleet_availability"] = aux_display["fleet_availability"].map(pct)
    aux_display["fleet_deficit"] = aux_display["fleet_deficit"].map(pct)
    aux_display["fleet_value"] = aux_display["fleet_value"].map(short_float)
    aux_display = aux_display[
        ["stage", "policy_class", "fleet_annual_cost", "fleet_availability", "fleet_deficit", "fleet_value"]
    ]

    per_printer_summary = pd.DataFrame(
        [
            {"metric": "annual_cost_min", "value": money(float(per_printer["annual_cost"].min()))},
            {"metric": "annual_cost_mean", "value": money(float(per_printer["annual_cost"].mean()))},
            {"metric": "annual_cost_max", "value": money(float(per_printer["annual_cost"].max()))},
            {"metric": "availability_min", "value": pct(float(per_printer["availability"].min()))},
            {"metric": "availability_mean", "value": pct(float(per_printer["availability"].mean()))},
            {"metric": "availability_max", "value": pct(float(per_printer["availability"].max()))},
        ]
    )

    s2_display = pd.DataFrame(
        [
            {
                "variant": name,
                "mae_mean_days": f"{metrics['mae_mean']:.2f}",
                "rmse_mean_days": f"{metrics['rmse_mean']:.2f}",
            }
            for name, metrics in s2_metrics.items()
        ]
    )

    winner = pipeline_kpis.sort_values(["fleet_value", "fleet_annual_cost"]).iloc[0]
    pipeline_cost_reduction = float(
        pipeline_kpis.loc[
            pipeline_kpis["stage"] == "stage_03_per_tick",
            "annual_cost_reduction_vs_stage01_pct",
        ].iloc[0]
    )
    pipeline_avail_gain = float(
        pipeline_kpis.loc[pipeline_kpis["stage"] == "stage_03_per_tick", "fleet_availability"].iloc[0]
        - pipeline_kpis.loc[pipeline_kpis["stage"] == "stage_01", "fleet_availability"].iloc[0]
    )
    s2_cost_reduction = float(
        pipeline_kpis.loc[pipeline_kpis["stage"] == "stage_02", "annual_cost_reduction_vs_stage01_pct"].iloc[0]
    )
    s2_avail_gain = float(
        pipeline_kpis.loc[pipeline_kpis["stage"] == "stage_02", "fleet_availability"].iloc[0]
        - pipeline_kpis.loc[pipeline_kpis["stage"] == "stage_01", "fleet_availability"].iloc[0]
    )

    pipeline_cost_direction = "reduces" if pipeline_cost_reduction >= 0 else "increases"
    pipeline_avail_direction = "improves" if pipeline_avail_gain >= 0 else "reduces"
    s2_cost_direction = "reduces" if s2_cost_reduction >= 0 else "increases"
    s2_avail_direction = "improves" if s2_avail_gain >= 0 else "reduces"
    per_tick_summary_line = str(per_tick_summary.get("evaluated_on", "test set"))

    cost_section = ""
    cost_headline = "- Cost-only demo artifacts were not found; showing constrained fast-pipeline artifacts only."
    business_section = ""
    business_headline = ""
    if business_demo is not None:
        ordered_business = business_demo.sort_values("business_cost")["stage"].tolist()
        stage3_business_reduction = float(
            business_demo.loc[
                business_demo["stage"] == "stage_03",
                "business_cost_reduction_vs_stage01_pct",
            ].iloc[0]
        )
        business_headline = (
            "- Primary business-cost ordering: "
            f"**{' < '.join(ordered_business)}**. "
            f"Stage 03 reduces business cost by **{stage3_business_reduction:.2f}%** versus Stage 01."
        )
        business_section = f"""
## Business-Cost Result

This is the primary demo metric: annual maintenance cost plus downtime business
loss. Lower is better. The business-demo policy choices are selected on
validation and evaluated once on test.

{md_table(_format_business_demo_table(business_demo))}

### Business-Cost Figures

![business_cost_by_stage](figures/business_cost_by_stage.png)

![business_cost_components](figures/business_cost_components.png)

![availability_by_stage](figures/availability_by_stage.png)
"""
    if cost_demo is not None:
        cost_kpis, _, _ = cost_demo
        ordered = cost_kpis.sort_values("annual_cost")["stage"].tolist()
        proves = ordered == ["stage_03", "stage_02", "stage_01"]
        stage3_reduction = float(
            cost_kpis.loc[
                cost_kpis["stage"] == "stage_03",
                "annual_cost_reduction_vs_stage01_pct",
            ].iloc[0]
        )
        stage2_reduction = float(
            cost_kpis.loc[
                cost_kpis["stage"] == "stage_02",
                "annual_cost_reduction_vs_stage01_pct",
            ].iloc[0]
        )
        cost_headline = (
            "- Primary annual-cost ordering: "
            f"**{' < '.join(ordered)}**. "
            f"Proof target `stage_03 < stage_02 < stage_01`: **{proves}**."
        )
        cost_section = f"""
## Annual-Cost Result

This is the metric to minimize: annual cost per printer-year. Lower is better.
These rows come from `ml/04_models/results/cost_demo/`, a medium run
that is longer than `--fast` but still bounded to minutes.

{md_table(_format_cost_demo_table(cost_kpis))}

- Stage 02 reduces annual cost by **{stage2_reduction:.2f}%** versus Stage 01.
- Stage 03 reduces annual cost by **{stage3_reduction:.2f}%** versus Stage 01.
- Ordering by annual cost: **{' < '.join(ordered)}**.

### Annual-Cost Figures

![cost_availability_by_stage](figures/cost_availability_by_stage.png)

![cost_reduction_vs_stage01](figures/cost_reduction_vs_stage01.png)

![stage02_top_candidates](figures/stage02_top_candidates.png)

![stage03_per_printer_cost](figures/stage03_per_printer_cost.png)
"""

    report = f"""# Stage 01/02/03 Results Comparison

This report compares the three maintenance-policy stages using generated artifacts under `ml/`.

## Headline

{business_headline}
{cost_headline}
- Fast-pipeline context still exists below. Those rows use the constrained `fleet_value` artifact path and fast smoke settings, so they are not the proof for the business-cost demo.

{business_section}

{cost_section}

## Fast Pipeline Artifact Context

Main Stage 03 fast-pipeline row: the per-tick PPO+SPR ensemble from
`ml/03_rl/results/per_tick/`. This context is retained because it
shows what the current notebook pipeline produced, but the annual-cost result
above is the primary answer for the cost-only objective.

- Best row by constrained penalized objective: **{winner['stage_label']}**.
- Stage 03 per-tick {pipeline_cost_direction} annual cost by **{pct(abs(pipeline_cost_reduction))}** versus Stage 01.
- Stage 03 per-tick {pipeline_avail_direction} availability by **{pct(abs(pipeline_avail_gain))}** versus Stage 01.
- None of the fast-pipeline rows reach the 95% availability constraint yet, so every constrained objective still includes a deficit penalty.

### Fast Pipeline KPI Table

{md_table(_format_pipeline_table(pipeline_kpis))}

### Maintenance Interval Comparison

Stage 01 and Stage 02 output one constant tau vector. The auxiliary Stage 03
per-printer tau policy outputs one tau vector per test printer; this table
shows its mean/min/max by component. The main Stage 03 per-tick policy is
event/action based, so it is not directly represented by a fixed tau vector.

{md_table(tau_display)}

### Stage 02 RUL Head Metrics

Mean held-out RUL error by variant:

{md_table(s2_display)}

### Stage 03 Auxiliary Context

Earlier Stage 03 per-printer tau comparison from `ml/03_rl/results/kpi_comparison.csv`:

{md_table(aux_display)}

Per-tick PPO+SPR ensemble summary from `per_tick_summary.yaml`:

| metric | value |
| --- | --- |
| fleet annual cost | {money(float(per_tick_summary['fleet_annual_cost_eur_per_printer_year']))} |
| fleet availability | {pct(float(per_tick_summary['fleet_availability']))} |
| fleet deficit | {pct(float(per_tick_summary['fleet_deficit']))} |
| evaluated on | {per_tick_summary_line} |
| ensemble size | {per_tick_summary['ensemble_size']} |
| total timesteps per seed | {per_tick_summary['config']['total_timesteps_per_seed']} |

Per-printer spread for the Stage 03 per-tick ensemble:

{md_table(per_printer_summary)}

### Fast Pipeline Figures

![pipeline_cost_availability_by_stage](figures/pipeline_cost_availability_by_stage.png)

![penalized_value_by_stage](figures/penalized_value_by_stage.png)

![tau_comparison](figures/tau_comparison.png)

![stage03_per_printer_cost_availability](figures/stage03_per_printer_cost_availability.png)

## Interpretation

The fast-pipeline context reflects the generated artifact profile, including
fast-mode smoke settings when `FAST_MODE=1` was used. Stage 02
{s2_cost_direction} annual cost by **{pct(abs(s2_cost_reduction))}** and
{s2_avail_direction} availability by **{pct(abs(s2_avail_gain))}** versus
Stage 01 on that artifact set. Its RUL model still matters because it produces
the trained encoder and RUL head used downstream, but the fast constant-tau
surrogate winner is not the annual-cost proof.

The per-tick PPO+SPR ensemble {pipeline_cost_direction} annual cost by
**{pct(abs(pipeline_cost_reduction))}** and {pipeline_avail_direction}
availability by **{pct(abs(pipeline_avail_gain))}** versus Stage 01 on this
fast run. It is still infeasible against the 95% availability requirement.

## Reproduce

```bash
./ml/train.sh cost-demo
./ml/train.sh 4
```
"""
    (out_dir / "REPORT.md").write_text(report, encoding="utf-8")


def run_stage4_report(out_dir: Path) -> None:
    root = find_repo_root(out_dir)
    fig_dir = out_dir / "figures"
    require_inputs(root, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    pipeline_kpis = build_pipeline_stage_kpis(root, out_dir)
    tau_df = build_tau_comparison(root, out_dir)
    aux_stage03 = build_auxiliary_stage03(root, out_dir)
    per_printer = build_stage03_per_printer_summary(root, out_dir)
    business_demo = load_business_demo(root, out_dir)
    cost_demo = load_cost_demo(root, out_dir)

    if business_demo is not None:
        business_demo.to_csv(out_dir / "stage_kpis.csv", index=False)
        pipeline_kpis.to_csv(out_dir / "pipeline_stage_kpis.csv", index=False)
        if cost_demo is not None:
            cost_demo[0].to_csv(out_dir / "annual_cost_stage_kpis.csv", index=False)
    elif cost_demo is None:
        pipeline_kpis.to_csv(out_dir / "stage_kpis.csv", index=False)
    else:
        pipeline_kpis.to_csv(out_dir / "pipeline_stage_kpis.csv", index=False)
        cost_demo[0].to_csv(out_dir / "stage_kpis.csv", index=False)
        cost_demo[1].to_csv(out_dir / "stage02_leaderboard.csv", index=False)
        cost_demo[2].to_csv(out_dir / "stage03_per_printer.csv", index=False)

    tau_df.to_csv(out_dir / "tau_comparison.csv", index=False)
    aux_stage03.to_csv(out_dir / "stage03_auxiliary_kpis.csv", index=False)
    per_printer.to_csv(out_dir / "stage03_per_tick_printer_summary.csv", index=False)

    write_pipeline_plots(
        pipeline_kpis=pipeline_kpis,
        tau_df=tau_df,
        per_printer=per_printer,
        fig_dir=fig_dir,
    )
    if cost_demo is not None:
        write_cost_demo_plots(
            cost_kpis=cost_demo[0],
            stage2_leaderboard=cost_demo[1],
            stage3_per_printer=cost_demo[2],
            fig_dir=fig_dir,
        )
    if business_demo is not None:
        business_fig_dir = out_dir / "business_demo/figures"
        for name in (
            "business_cost_by_stage.png",
            "business_cost_components.png",
            "availability_by_stage.png",
        ):
            src = business_fig_dir / name
            if src.exists():
                shutil.copyfile(src, fig_dir / name)

    write_report(
        root=root,
        out_dir=out_dir,
        pipeline_kpis=pipeline_kpis,
        tau_df=tau_df,
        aux_stage03=aux_stage03,
        per_printer=per_printer,
        business_demo=business_demo,
        cost_demo=cost_demo,
    )

    print(f"Wrote {out_dir / 'REPORT.md'}")
    print(f"Wrote {out_dir / 'stage_kpis.csv'}")
    if cost_demo is not None:
        print(f"Wrote {out_dir / 'pipeline_stage_kpis.csv'}")
    print(f"Wrote {out_dir / 'tau_comparison.csv'}")
    print(f"Wrote {fig_dir}")
