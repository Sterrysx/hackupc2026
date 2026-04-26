"""Plotting helpers shared across stages."""
from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from backend.simulator.schema import COMPONENT_IDS


def plot_health_curves(df: pd.DataFrame, printer_id: int, *, ax=None):
    """Plot H_C1..H_C6 vs day for a single printer."""
    rows = df.loc[df["printer_id"] == printer_id].sort_values("day")
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 4))
    for component_id in COMPONENT_IDS:
        ax.plot(rows["day"], rows[f"H_{component_id}"], label=component_id, linewidth=1.0)
    ax.set_xlabel("day")
    ax.set_ylabel("Health Index")
    ax.set_title(f"Printer {printer_id}")
    ax.set_ylim(-0.05, 1.05)
    ax.legend(ncol=3, fontsize=8)
    return ax


def plot_event_counts(df: pd.DataFrame, *, ax=None):
    """Bar chart of preventive vs corrective events per component."""
    if ax is None:
        _, ax = plt.subplots(figsize=(8, 4))
    rows = []
    for component_id in COMPONENT_IDS:
        rows.append(
            {
                "component": component_id,
                "preventive": int(df[f"maint_{component_id}"].sum()),
                "corrective": int(df[f"failure_{component_id}"].sum()),
            }
        )
    summary = pd.DataFrame(rows).set_index("component")
    summary.plot(kind="bar", ax=ax, color=["#4c72b0", "#c44e52"])
    ax.set_ylabel("# events")
    return ax


def plot_pareto_cost_availability(study_df: pd.DataFrame, *, ax=None, threshold: float = 0.95):
    """Scatter trial annual_cost vs availability with the constraint line."""
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(study_df["availability"], study_df["annual_cost"], alpha=0.6)
    ax.axvline(threshold, color="red", linestyle="--", label=f"≥{int(threshold*100)}% target")
    ax.set_xlabel("availability")
    ax.set_ylabel("annual cost (€/printer/yr)")
    ax.legend()
    return ax
