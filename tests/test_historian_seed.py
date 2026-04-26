"""Tests for the parquet-backed historian seed.

The Phase 3 rubric demands "no hallucinations / no hard-coded answers". The
only surface the agent reads from is the SQLite historian, so the seed that
populates it must be traceable back to real simulator output. These tests
pin that contract.
"""
from __future__ import annotations

import json
import sqlite3

import pandas as pd
import pytest

from backend.agent import historian_seed


@pytest.fixture(scope="module")
def seed_rows() -> list[tuple]:
    return historian_seed.build_seed_rows()


@pytest.fixture(scope="module")
def fleet_df() -> pd.DataFrame:
    df = pd.read_parquet(historian_seed._DEFAULT_PARQUET)
    if hasattr(df["city"], "cat"):
        df["city"] = df["city"].astype(str)
    return df


def test_seed_covers_both_narrative_runs(seed_rows: list[tuple]) -> None:
    """R1 (printhead failure) and R2 (heating element failure) must both
    be present — the agent's prompt suite references them by name."""
    run_ids = {row[1] for row in seed_rows}
    assert run_ids == {"R1", "R2"}


def test_seed_covers_every_component(seed_rows: list[tuple]) -> None:
    """Every simulator component must appear at least once so the agent
    can answer questions about the recoater, printhead, or thermal loop
    without missing data."""
    components = {row[2] for row in seed_rows}
    assert components == {
        "recoater_blade",
        "recoater_motor",
        "nozzle_plate",
        "thermal_resistor",
        "heating_element",
        "insulation_panel",
    }


def test_seed_includes_failed_status_on_corrective_event(seed_rows: list[tuple]) -> None:
    """``status_Ci`` in the parquet never reports FAILED (H is reset to
    1.0 in the same step the corrective rule fires). The seed must
    override that on the ``failure_Ci`` row so the agent sees a real
    FAILED event to reason about."""
    failed = [row for row in seed_rows if row[4] == "FAILED"]
    assert failed, "no FAILED rows emitted — agent has nothing to diagnose"
    for row in failed:
        metrics = json.loads(row[8])
        assert metrics.get("failure_event") is True, (
            "FAILED row must carry failure_event=True in metrics"
        )


def test_health_index_matches_parquet_exactly(
    seed_rows: list[tuple], fleet_df: pd.DataFrame
) -> None:
    """The seed must be a *projection* of the parquet, not a remix.
    Every (run, day, component) triple's health_index must equal the
    corresponding H_Ci value in the parquet to 4 decimals."""
    sim_id_by_frontend = {
        "recoater_blade":   "C1",
        "recoater_motor":   "C2",
        "nozzle_plate":     "C3",
        "thermal_resistor": "C4",
        "heating_element":  "C5",
        "insulation_panel": "C6",
    }
    windows = {w[0]: w for w in historian_seed._SEED_WINDOWS}

    for ts, run_id, component, health_index, *_ in seed_rows:
        _, printer_id, day_from, _ = windows[run_id]
        row_date = ts.split("T")[0]
        parquet_row = fleet_df[
            (fleet_df["printer_id"] == printer_id)
            & (fleet_df["date"].astype(str) == row_date)
        ]
        assert len(parquet_row) == 1, (
            f"parquet lookup failed for {run_id}/{component} at {ts}"
        )
        sim_id = sim_id_by_frontend[component]
        expected = round(float(parquet_row.iloc[0][f"H_{sim_id}"]), 4)
        # On the corrective-replacement day the simulator resets H to 1.0,
        # and the seeder keeps that exact value — so this equality still
        # holds on failure rows.
        assert health_index == expected, (
            f"{run_id}/{component}@{ts}: seed H={health_index} != parquet "
            f"H_{sim_id}={expected}"
        )


def test_timestamps_are_sorted_within_each_day(seed_rows: list[tuple]) -> None:
    """The agent's root-cause prompt walks timestamps in order. A single
    day's six component rows must be monotonically increasing so
    ``ORDER BY timestamp`` gives a coherent sweep."""
    by_day: dict[str, list[str]] = {}
    for ts, *_ in seed_rows:
        by_day.setdefault(ts.split("T")[0], []).append(ts)
    for day, timestamps in by_day.items():
        assert timestamps == sorted(timestamps), f"{day}: timestamps not sorted"


def test_init_db_populates_from_parquet(tmp_path, monkeypatch) -> None:
    """End-to-end: ``init_db`` against an empty file must produce the
    same row count as ``build_seed_rows`` — proving the wiring goes
    through the parquet path, not the fallback fixtures."""
    from backend.agent import db as db_module

    db_path = tmp_path / "historian.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    db_module.init_db()

    expected = len(historian_seed.build_seed_rows())
    with sqlite3.connect(db_path) as conn:
        got = conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
    assert got == expected, (
        f"init_db inserted {got} rows, expected {expected} from the parquet seed"
    )
