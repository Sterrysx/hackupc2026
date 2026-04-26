"""True end-to-end integration tests.

No mocks on the critical path: real parquet, real SQLite historian, real
LangGraph agent hitting the real Groq LLM, real FastAPI app, real websocket.

These tests exist to prove to the judges that the Digital Co-Pilot is not a
visual shell — every arrow in the Brain -> Clock -> Voice pipeline is exercised
here and asserted against grounding rules (timestamp + run_id in every
citation, tool-call trace present, parquet-backed twin numbers).

Opt-in via `-m live`. Skips cleanly when `GROQ_API_KEY` is missing so the
default `uv run pytest` invocation stays green on laptops without secrets.
"""
from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

# conftest.py pre-stubs the native audio deps so `import app` is safe.
from backend.app import app
from backend.agent import twin_data

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("GROQ_API_KEY"),
        reason="GROQ_API_KEY not set — live end-to-end tests require a real LLM.",
    ),
]

# Same grounding rules the runtime guardrail applies. Duplicated here on
# purpose: if a future change loosens the guardrail, this test should still
# enforce the demo's hard promise ("every answer cites timestamp + run").
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_RUN_ID_RE = re.compile(r"run_id:\s*\w+|run\s+\w+", re.IGNORECASE)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _assert_grounded_citation(citation: str, *, expected_run_hint: str | None = None) -> None:
    assert _TIMESTAMP_RE.search(citation), (
        f"evidence_citation missing ISO timestamp: {citation!r}"
    )
    assert _RUN_ID_RE.search(citation), (
        f"evidence_citation missing run identifier: {citation!r}"
    )
    if expected_run_hint:
        assert expected_run_hint.lower() in citation.lower(), (
            f"evidence_citation does not reference expected run "
            f"{expected_run_hint!r}: {citation!r}"
        )


def test_agent_query_is_grounded_in_real_historian(client: TestClient) -> None:
    """Real Groq LLM over real SQLite seed must return a grounded report.

    We ask about R2, which the seed guarantees contains a FAILED nozzle plate
    row. A hallucination-free agent must cite that exact timestamp/run.
    """
    thread_id = f"e2e-grounding-{uuid.uuid4()}"
    payload = {
        "query": "Why did the nozzle plate fail in run R2? Cite the exact telemetry.",
        "thread_id": thread_id,
        "run_identifier": "R2",
    }

    res = client.post("/agent/query", json=payload)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["severity_indicator"] in {"INFO", "WARNING", "CRITICAL"}
    assert body["priority_level"] in {"LOW", "MEDIUM", "HIGH"}
    assert isinstance(body["recommended_actions"], list)
    assert len(body["recommended_actions"]) >= 1

    _assert_grounded_citation(body["evidence_citation"], expected_run_hint="R2")

    # The agent must actually talk about the failing component — not a
    # generic deflection. "nozzle" or "FAILED" must appear somewhere in the
    # grounded explanation.
    grounded = body["grounded_text"].lower()
    assert "nozzle" in grounded or "failed" in grounded, (
        f"grounded_text looks evasive: {body['grounded_text']!r}"
    )

    # The reasoning trace must include a real tool call against the historian.
    trace = body.get("reasoning_trace", [])
    assert trace, "reasoning_trace is empty — agent skipped its tools"
    tool_calls = [s for s in trace if s.get("kind") == "tool_call"]
    assert any("query_database" in s.get("label", "") for s in tool_calls), (
        "agent never called query_database — answer is not grounded in the DB"
    )


def test_watchdog_broadcasts_grounded_alert_over_websocket(client: TestClient) -> None:
    """CRITICAL telemetry must trigger a PROACTIVE_ALERT broadcast with
    the same grounding guarantees as the on-demand endpoint."""
    run_id = f"IT-{uuid.uuid4().hex[:8]}"
    component = "nozzle_plate"
    ts = "2026-04-25T17:00:00"

    with client.websocket_connect("/ws/notifications") as ws:
        telemetry = {
            "timestamp": ts,
            "run_id": run_id,
            "component": component,
            "health_index": 0.08,
            "status": "CRITICAL",
            "temperature": 355.0,
            "pressure": 1.7,
            "fan_speed": 900,
            "metrics": {"clog_percentage": 91.0, "droplet_volume_pl": 1.1},
        }
        res = client.post("/telemetry", json=telemetry)
        assert res.status_code == 200, res.text

        # The background task runs after the HTTP response returns and
        # needs to complete a full LLM round-trip. Wall-clock guard so a
        # hung LLM can't freeze the suite.
        deadline = time.monotonic() + 120.0
        message: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            try:
                message = ws.receive_json()
                break
            except Exception:
                continue
        assert message is not None, "watchdog did not broadcast within 120s"

    assert message["type"] == "PROACTIVE_ALERT"
    assert message["component"] == component
    assert message["status"] == "CRITICAL"

    report = message["report"]
    assert report["severity_indicator"] in {"INFO", "WARNING", "CRITICAL"}
    _assert_grounded_citation(report["evidence_citation"])

    trace = report.get("reasoning_trace", [])
    assert trace, "proactive alert has empty reasoning_trace"


def test_twin_state_matches_parquet_ground_truth(client: TestClient) -> None:
    """The numbers the UI renders must come from the real simulator parquet,
    not from a hardcoded fixture. Cross-check HTTP against the direct
    accessor byte for byte."""
    city = "Madrid"
    day = 200

    printers_res = client.get("/twin/printers", params={"city": city})
    assert printers_res.status_code == 200, printers_res.text
    printer_ids = printers_res.json()["printers"]
    assert printer_ids, "no printers returned for Madrid"
    printer_id = printer_ids[0]

    state_res = client.get(
        "/twin/state",
        params={"city": city, "printer_id": printer_id, "day": day, "horizon_min": 0},
    )
    assert state_res.status_code == 200, state_res.text
    state = state_res.json()

    truth = twin_data.get_snapshot(city, printer_id, day, forecast_horizon_min=0)

    assert state["tick"] == truth["tick"] == day
    assert state["timestamp"] == truth["timestamp"]
    assert state["drivers"] == truth["drivers"]

    http_components = {c["id"]: c for c in state["components"]}
    truth_components = {c["id"]: c for c in truth["components"]}
    assert http_components.keys() == truth_components.keys()
    for cid, truth_c in truth_components.items():
        http_c = http_components[cid]
        assert http_c["healthIndex"] == truth_c["healthIndex"], (
            f"{cid}: HTTP healthIndex {http_c['healthIndex']} "
            f"!= parquet {truth_c['healthIndex']}"
        )
        assert http_c["status"] == truth_c["status"]

    # With horizon_min=0 the forecast must exactly match the current health —
    # proving the forecast path is wired end-to-end and not inventing numbers.
    assert len(state["forecasts"]) == 6
    for f in state["forecasts"]:
        assert f["predictedHealthIndex"] == http_components[f["id"]]["healthIndex"]
