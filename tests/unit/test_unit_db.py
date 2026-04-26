"""Unit tests for the SQLite historian wrapper in ``Ai_Agent.db``.

Every test redirects ``DB_PATH`` to a ``tmp_path`` SQLite file via
``monkeypatch`` so the real ``data/historian.db`` is never touched. The
parquet seed loader (``_load_parquet_seed_rows``) is also stubbed to return
``None`` so ``init_db`` falls back to the in-module ``_FALLBACK_SEED_ROWS``
deterministically.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from Ai_Agent import db as db_module


# ----------------------------------------------------------- fixtures


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point ``DB_PATH`` at an empty tmp_path file and force fallback seeds."""
    db_path = tmp_path / "historian.db"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    # Force the fallback seed branch so we don't depend on the real parquet.
    monkeypatch.setattr(db_module, "_load_parquet_seed_rows", lambda: None)
    return db_path


# --------------------------------------------------------- init_db basics


def test_init_db_creates_telemetry_table(isolated_db):
    db_module.init_db()
    with sqlite3.connect(isolated_db) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='telemetry'"
        ).fetchall()
    assert rows == [("telemetry",)]


def test_init_db_is_idempotent(isolated_db):
    """Calling init_db twice must not raise nor duplicate the seed rows."""
    db_module.init_db()
    with sqlite3.connect(isolated_db) as conn:
        first = conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
    db_module.init_db()
    with sqlite3.connect(isolated_db) as conn:
        second = conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
    assert first == second


def test_init_db_inserts_fallback_seed_rows(isolated_db):
    db_module.init_db()
    with sqlite3.connect(isolated_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]
    assert count == len(db_module._FALLBACK_SEED_ROWS)
    assert count == 7  # documented fallback row count


def test_init_db_table_columns_match_create_sql(isolated_db):
    """Schema must match ``CREATE_TABLE_SQL`` — no drift between the
    constant and what's actually applied."""
    db_module.init_db()
    with sqlite3.connect(isolated_db) as conn:
        # `pragma_table_info` is the SQLite-canonical introspection.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(telemetry)").fetchall()]
    expected = [
        "id", "timestamp", "run_id", "component", "health_index",
        "status", "temperature", "pressure", "fan_speed", "metrics",
    ]
    assert cols == expected


# -------------------------------------------------------- get_connection


def test_get_connection_uses_row_factory(isolated_db):
    """Rows returned by ``get_connection`` must be ``sqlite3.Row`` so the
    agent can read columns by name rather than positional index."""
    db_module.init_db()
    conn = db_module.get_connection()
    try:
        assert conn.row_factory is sqlite3.Row
        cursor = conn.execute("SELECT timestamp, run_id FROM telemetry LIMIT 1")
        row = cursor.fetchone()
        # Row must support both index AND keyword access.
        assert row[0] == row["timestamp"]
    finally:
        conn.close()


# -------------------------------------------------------- insert_telemetry


def test_insert_telemetry_returns_autoincrement_id(isolated_db):
    db_module.init_db()
    initial_count = len(db_module._FALLBACK_SEED_ROWS)
    new_id = db_module.insert_telemetry(
        timestamp="2026-04-25T18:00:00",
        run_id="R3",
        component="recoater_blade",
        health_index=0.45,
        status="DEGRADED",
        temperature=44.0,
        pressure=1.01,
        fan_speed=2400.0,
        metrics={"wear_rate": 0.005},
    )
    # IDs are autoincrement -> the new ID must be > initial seed count.
    assert new_id == initial_count + 1


def test_insert_telemetry_persists_metrics_as_json_round_trip(isolated_db):
    db_module.init_db()
    metrics = {"clog_percentage": 88.5, "droplet_volume_pl": 2.0, "nested": [1, 2]}
    new_id = db_module.insert_telemetry(
        timestamp="2026-04-25T18:30:00",
        run_id="R4",
        component="nozzle_plate",
        health_index=0.20,
        status="CRITICAL",
        temperature=320.0,
        pressure=1.5,
        fan_speed=1100.0,
        metrics=metrics,
    )
    with sqlite3.connect(isolated_db) as conn:
        row = conn.execute(
            "SELECT metrics FROM telemetry WHERE id = ?", (new_id,)
        ).fetchone()
    assert json.loads(row[0]) == metrics


def test_insert_telemetry_with_empty_metrics_dict(isolated_db):
    """Empty metrics dict must serialise cleanly (no TypeError on json.dumps)."""
    db_module.init_db()
    new_id = db_module.insert_telemetry(
        timestamp="2026-04-25T19:00:00",
        run_id="R5",
        component="heating_element",
        health_index=0.95,
        status="FUNCTIONAL",
        temperature=300.0,
        pressure=1.0,
        fan_speed=2400.0,
        metrics={},
    )
    with sqlite3.connect(isolated_db) as conn:
        row = conn.execute(
            "SELECT metrics FROM telemetry WHERE id = ?", (new_id,)
        ).fetchone()
    assert json.loads(row[0]) == {}


def test_insert_telemetry_persists_all_scalar_fields(isolated_db):
    """Make sure every column in the INSERT lands in the right place."""
    db_module.init_db()
    new_id = db_module.insert_telemetry(
        timestamp="2026-04-25T20:00:00",
        run_id="R6",
        component="thermal_resistor",
        health_index=0.62,
        status="DEGRADED",
        temperature=275.5,
        pressure=1.13,
        fan_speed=2200.0,
        metrics={"resistance_ohm": 14.0},
    )
    with sqlite3.connect(isolated_db) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM telemetry WHERE id = ?", (new_id,)
        ).fetchone()
    assert row["run_id"] == "R6"
    assert row["component"] == "thermal_resistor"
    assert row["health_index"] == pytest.approx(0.62)
    assert row["status"] == "DEGRADED"
    assert row["temperature"] == pytest.approx(275.5)
    assert row["pressure"] == pytest.approx(1.13)
    assert row["fan_speed"] == pytest.approx(2200.0)
