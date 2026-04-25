import json
from pydantic import BaseModel
from langchain_core.tools import tool

from .schemas import QueryDatabaseInput
from .db import get_connection, init_db

init_db()

DB_SCHEMA = {
    "description": "Phase 2 historian SQLite database for HP Metal Jet S100 Digital Twin telemetry",
    "table": "telemetry",
    "columns": {
        "id":           "INTEGER PRIMARY KEY — auto-increment row ID",
        "timestamp":    "TEXT — ISO-8601 datetime (YYYY-MM-DDTHH:MM:SS)",
        "run_id":       "TEXT — simulation run identifier (e.g. 'R1', 'R2')",
        "component":    "TEXT — recoater_blade | nozzle_plate | heating_element",
        "health_index": "REAL — component health [0.0–1.0], 1.0 = perfect",
        "status":       "TEXT — FUNCTIONAL | DEGRADED | CRITICAL | FAILED",
        "temperature":  "REAL — component temperature in Celsius",
        "pressure":     "REAL — operating pressure in bar",
        "fan_speed":    "REAL — cooling fan RPM",
        "metrics":      "TEXT — JSON object with component-specific fields (see component_metrics)",
    },
    "component_metrics": {
        "recoater_blade":  {"thickness_mm": "blade thickness (mm)", "wear_rate": "wear per cycle"},
        "nozzle_plate":    {"clog_percentage": "% nozzles clogged", "droplet_volume_pl": "droplet volume (pl)"},
        "heating_element": {"resistance_ohm": "resistance (Ω)", "power_draw_w": "power draw (W)"},
    },
    "available_runs": ["R1", "R2"],
    "query_parameters": {
        "run_identifier":  "Required — run ID to query (e.g. 'R1')",
        "timestamp_range": "Optional — time range filter 'HH:MM:SS-HH:MM:SS'",
        "component":       "Optional — filter by component name",
    },
}


class ThinkInput(BaseModel):
    thought: str


@tool(args_schema=ThinkInput)
def think(thought: str) -> str:
    """Private reasoning scratchpad. Write out your analysis, observations, or
    deliberation before taking action or generating a response. The content is
    not shown to the user — use it as many times as needed to reason carefully."""
    return ""


@tool
def get_db_schema() -> str:
    """Return the schema of the Phase 2 historian SQLite database.
    Call this first to understand the table structure, column types, available
    run IDs, and component metric definitions before querying with query_database."""
    return json.dumps(DB_SCHEMA, indent=2)


@tool(args_schema=QueryDatabaseInput)
def query_database(
    run_identifier: str,
    timestamp_range: str | None = None,
    component: str | None = None,
) -> str:
    """Query the Phase 2 historian SQLite database for machine telemetry data.
    Returns timestamped telemetry records for the specified run,
    optionally filtered by time range and component."""
    sql = """
        SELECT timestamp, run_id, component, health_index, status,
               temperature, pressure, fan_speed, metrics
        FROM telemetry
        WHERE run_id = ?
    """
    params: list = [run_identifier]

    if component:
        sql += " AND component = ?"
        params.append(component)

    if timestamp_range and "-" in timestamp_range:
        parts = timestamp_range.split("-", 1)
        if len(parts) == 2:
            start_t, end_t = parts[0].strip(), parts[1].strip()
            sql += " AND time(timestamp) >= ? AND time(timestamp) <= ?"
            params.extend([start_t, end_t])

    sql += " ORDER BY timestamp"

    try:
        with get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception as exc:
        return json.dumps({
            "error": "SQL execution failed",
            "detail": str(exc),
            "attempted_params": {
                "run_identifier": run_identifier,
                "timestamp_range": timestamp_range,
                "component": component,
            },
            "hint": "Check that run_identifier exists, component spelling is correct, "
                    "and timestamp_range uses HH:MM:SS-HH:MM:SS format.",
        })

    if not rows:
        return json.dumps({
            "error": "No records found",
            "attempted_params": {
                "run_identifier": run_identifier,
                "timestamp_range": timestamp_range,
                "component": component,
            },
            "hint": f"Run '{run_identifier}' may not exist or no records match the filters. "
                    "Call get_db_schema to verify available run IDs and component names.",
        })

    records = []
    for row in rows:
        try:
            r = dict(row)
            r["metrics"] = json.loads(r["metrics"])
            records.append(r)
        except Exception as exc:
            records.append({**dict(row), "metrics_parse_error": str(exc)})

    return json.dumps(records, indent=2)
