import json
from pydantic import BaseModel
from langchain_core.tools import tool

from .schemas import QueryDatabaseInput
from .db import get_connection, init_db

init_db()

class ThinkInput(BaseModel):
    thought: str


@tool(args_schema=ThinkInput)
def think(thought: str) -> str:
    """Private reasoning scratchpad. Write out your analysis, observations, or
    deliberation before taking action or generating a response. The content is
    not shown to the user — use it as many times as needed to reason carefully."""
    return ""


@tool
def get_existing_runs() -> str:
    """Return a list of all existing run identifiers (run_ids) in the historian database.
    Call this first to know which simulation runs are available for analysis."""
    try:
        with get_connection() as conn:
            rows = conn.execute("SELECT DISTINCT run_id FROM telemetry ORDER BY run_id").fetchall()
            runs = [row["run_id"] for row in rows]
            return json.dumps({"available_runs": runs}, indent=2)
    except Exception as exc:
        return json.dumps({"error": "Failed to fetch runs", "detail": str(exc)})


@tool(args_schema=QueryDatabaseInput)
def query_database(
    run_identifier: str,
    timestamp_range: str | None = None,
    component: str | None = None,
    status: str | None = None,
) -> str:
    """Query the Phase 2 historian SQLite database for machine telemetry data.
    Returns timestamped telemetry records for the specified run,
    optionally filtered by time range, component, and status."""
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

    if status:
        sql += " AND status = ?"
        params.append(status.upper())

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
                "status": status,
            },
            "hint": "Check that run_identifier exists, component/status spelling is correct, "
                    "and timestamp_range uses HH:MM:SS-HH:MM:SS format.",
        })

    if not rows:
        return json.dumps({
            "error": "No records found",
            "attempted_params": {
                "run_identifier": run_identifier,
                "timestamp_range": timestamp_range,
                "component": component,
                "status": status,
            },
            "hint": f"Run '{run_identifier}' may not exist or no records match the filters. "
                    "Call get_existing_runs to verify available run IDs.",
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
