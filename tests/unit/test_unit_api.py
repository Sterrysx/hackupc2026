"""Unit tests for the FastAPI surface in `app.py`.

All endpoint dependencies (twin_data, forecast, agent_graph, insert_telemetry)
are mocked so these tests exercise routing/serialization without touching
the parquet, SQLite historian, or LangGraph stack.

The conftest pre-stubs the audio modules; the additional patches here mock
the data-layer entry points before they're called.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import app


client = TestClient(app)


# ---------------------------------------------------------------- /health


def test_health_returns_ok_with_agent_ready_bool():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["agent_ready"], bool)


# --------------------------------------------------------- /twin/cities


def test_twin_cities_returns_list_under_cities_key():
    with patch.object(app_module.twin_data, "list_cities", return_value=["Barcelona", "Madrid"]):
        response = client.get("/twin/cities")
    assert response.status_code == 200
    data = response.json()
    assert "cities" in data
    assert isinstance(data["cities"], list)
    assert data["cities"] == ["Barcelona", "Madrid"]


# ------------------------------------------------------- /twin/snapshot


def test_twin_snapshot_happy_path_returns_payload(monkeypatch):
    fake_snap = {
        "timestamp": "2026-04-25T12:00:00",
        "tick": 100,
        "drivers": {
            "ambientTempC": 22.0, "humidityPct": 50.0, "contaminationPct": 50.0,
            "loadPct": 4.0, "maintenanceCoeff": 1.0,
        },
        "components": [],
        "forecasts": [],
        "forecastHorizonDays": 1.0,
    }
    monkeypatch.setattr(app_module.twin_data, "get_snapshot", lambda *a, **k: fake_snap)
    response = client.get("/twin/snapshot", params={
        "city": "Barcelona", "printer_id": 0, "day": 100,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["tick"] == 100
    assert body["timestamp"] == "2026-04-25T12:00:00"


def test_twin_snapshot_unknown_inputs_return_404(monkeypatch):
    def _raise(*_a, **_k):
        raise KeyError("unknown city: Atlantis")
    monkeypatch.setattr(app_module.twin_data, "get_snapshot", _raise)
    response = client.get("/twin/snapshot", params={
        "city": "Atlantis", "printer_id": 0, "day": 0,
    })
    assert response.status_code == 404


# --------------------------------------------------------- /twin/forecast


def test_twin_forecast_unknown_returns_404(monkeypatch):
    def _raise(*_a, **_k):
        raise KeyError("unknown city")
    monkeypatch.setattr(app_module.forecast, "compute_forecasts", _raise)
    response = client.get("/twin/forecast", params={
        "city": "Atlantis", "printer_id": 0, "day": 0,
    })
    assert response.status_code == 404


def test_twin_forecast_happy_path_returns_horizon_and_forecasts(monkeypatch):
    fake_forecasts = [
        {"id": "recoater_blade", "predictedHealthIndex": 0.85,
         "predictedStatus": "FUNCTIONAL", "predictedMetrics": [],
         "daysUntilCritical": None, "daysUntilFailure": None,
         "rationale": "stable", "confidence": 0.6},
    ]
    monkeypatch.setattr(
        app_module.forecast, "compute_forecasts",
        lambda *a, **k: fake_forecasts,
    )
    response = client.get("/twin/forecast", params={
        "city": "Barcelona", "printer_id": 0, "day": 100,
    })
    assert response.status_code == 200
    body = response.json()
    assert "horizonDays" in body
    assert body["forecasts"] == fake_forecasts


# ------------------------------------------------------ /twin/model_status


def test_twin_model_status_reports_active_path_and_rul_presence(monkeypatch):
    monkeypatch.setattr(app_module.forecast, "active_path", lambda: "analytic")
    monkeypatch.setattr(app_module.forecast, "_has_rul_head", lambda: False)
    response = client.get("/twin/model_status")
    assert response.status_code == 200
    body = response.json()
    assert body["active_path"] == "analytic"
    assert body["rul_head_present"] is False


def test_twin_model_status_reports_ssl_when_active(monkeypatch):
    monkeypatch.setattr(app_module.forecast, "active_path", lambda: "ssl")
    monkeypatch.setattr(app_module.forecast, "_has_rul_head", lambda: True)
    response = client.get("/twin/model_status")
    body = response.json()
    assert body["active_path"] == "ssl"
    assert body["rul_head_present"] is True


# ------------------------------------------------------ /telemetry POST


def _telemetry_payload(*, status: str = "FUNCTIONAL") -> dict:
    return {
        "timestamp": "2026-04-25T17:00:00",
        "run_id": "R1",
        "component": "nozzle_plate",
        "health_index": 0.05 if status == "FAILED" else 0.85,
        "status": status,
        "temperature": 200.0,
        "pressure": 1.01,
        "fan_speed": 2400.0,
        "metrics": {"clog_percentage": 95.0},
    }


@patch("app.insert_telemetry")
@patch("app.analyze_and_notify")
def test_telemetry_critical_status_schedules_watchdog(mock_analyze, mock_insert):
    mock_insert.return_value = 99
    response = client.post("/telemetry", json=_telemetry_payload(status="CRITICAL"))

    assert response.status_code == 200
    assert response.json() == {"id": 99, "message": "Telemetry data added successfully."}
    mock_insert.assert_called_once()
    mock_analyze.assert_called_once()


@patch("app.insert_telemetry")
@patch("app.analyze_and_notify")
def test_telemetry_failed_status_schedules_watchdog(mock_analyze, mock_insert):
    mock_insert.return_value = 100
    response = client.post("/telemetry", json=_telemetry_payload(status="FAILED"))

    assert response.status_code == 200
    mock_analyze.assert_called_once()


@patch("app.insert_telemetry")
@patch("app.analyze_and_notify")
def test_telemetry_functional_status_does_not_schedule_watchdog(mock_analyze, mock_insert):
    mock_insert.return_value = 101
    response = client.post("/telemetry", json=_telemetry_payload(status="FUNCTIONAL"))

    assert response.status_code == 200
    mock_analyze.assert_not_called()


@patch("app.insert_telemetry")
@patch("app.analyze_and_notify")
def test_telemetry_degraded_does_not_schedule_watchdog(mock_analyze, mock_insert):
    """Only CRITICAL / FAILED should fire the proactive watchdog."""
    mock_insert.return_value = 102
    response = client.post("/telemetry", json=_telemetry_payload(status="DEGRADED"))

    assert response.status_code == 200
    mock_analyze.assert_not_called()


# ------------------------------------------------------- /agent/query 503


def test_agent_query_returns_503_when_chat_agent_unavailable(monkeypatch):
    """When `_CHAT_AGENT_AVAILABLE` is False (e.g. langchain import broke),
    /twin/* must keep working but /agent/query must return 503."""
    monkeypatch.setattr(app_module, "_CHAT_AGENT_AVAILABLE", False)
    monkeypatch.setattr(app_module, "agent_graph", None)
    monkeypatch.setattr(
        app_module, "_CHAT_AGENT_IMPORT_ERROR",
        "test-injected: langchain not importable",
    )

    response = client.post(
        "/agent/query",
        json={"query": "What is the current status?", "thread_id": "t1"},
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Chat agent unavailable" in detail
