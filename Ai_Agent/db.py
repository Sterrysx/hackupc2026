import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "historian.db"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS telemetry (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    run_id       TEXT    NOT NULL,
    component    TEXT    NOT NULL,
    health_index REAL    NOT NULL,
    status       TEXT    NOT NULL,
    temperature  REAL    NOT NULL,
    pressure     REAL    NOT NULL,
    fan_speed    REAL    NOT NULL,
    metrics      TEXT    NOT NULL
)
"""

_SEED_ROWS = [
    ("2026-04-25T14:00:00", "R1", "recoater_blade",  0.85, "FUNCTIONAL", 45.2,  1.01, 2800, json.dumps({"thickness_mm": 2.1,  "wear_rate": 0.002})),
    ("2026-04-25T14:05:02", "R1", "nozzle_plate",    0.32, "CRITICAL",   312.8, 1.45, 1200, json.dumps({"clog_percentage": 68.5, "droplet_volume_pl": 3.2})),
    ("2026-04-25T14:05:02", "R1", "heating_element", 0.55, "DEGRADED",   298.0, 1.02, 2400, json.dumps({"resistance_ohm": 15.8, "power_draw_w": 1450})),
    ("2026-04-25T14:10:00", "R1", "nozzle_plate",    0.18, "CRITICAL",   328.4, 1.61,  950, json.dumps({"clog_percentage": 82.1, "droplet_volume_pl": 1.9})),
    ("2026-04-25T16:00:00", "R2", "recoater_blade",  0.72, "FUNCTIONAL", 47.5,  1.00, 2750, json.dumps({"thickness_mm": 2.0,  "wear_rate": 0.003})),
    ("2026-04-25T16:45:00", "R2", "nozzle_plate",    0.05, "FAILED",     380.0, 2.10,  400, json.dumps({"clog_percentage": 95.0, "droplet_volume_pl": 0.8})),
    ("2026-04-25T16:45:00", "R2", "heating_element", 0.21, "CRITICAL",   356.2, 1.85, 1100, json.dumps({"resistance_ohm": 22.4, "power_draw_w": 1820})),
]

_INSERT_SQL = """
INSERT INTO telemetry
    (timestamp, run_id, component, health_index, status, temperature, pressure, fan_speed, metrics)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(CREATE_TABLE_SQL)
        if conn.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0] == 0:
            conn.executemany(_INSERT_SQL, _SEED_ROWS)
