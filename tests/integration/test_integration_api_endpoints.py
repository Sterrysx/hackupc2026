"""Integration test: full sweep of /twin/* HTTP endpoints + /telemetry watchdog.

Spins up a single ``TestClient(app)`` (parent ``conftest.py`` pre-stubs the
audio modules so ``import app`` works on this Windows AppLocker box) and
walks every read-only twin endpoint plus the proactive-monitoring path on
``POST /telemetry``.

No real DB writes: ``app.insert_telemetry`` is patched. No real LLM
invocations: ``app.analyze_and_notify`` is patched too.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app import app

_PARQUET_PATH = Path("data") / "train" / "fleet_baseline.parquet"


@pytest.fixture(scope="module")
def client() -> TestClient:
    if not _PARQUET_PATH.exists():
        pytest.skip(
            f"{_PARQUET_PATH} not found — /twin/* endpoints can't serve."
        )
    return TestClient(app)


@pytest.fixture(scope="module")
def first_city_and_printer(client: TestClient) -> tuple[str, int]:
    cities = client.get("/twin/cities").json()["cities"]
    assert cities, "no cities in dataset"
    city = cities[0]
    printers = client.get("/twin/printers", params={"city": city}).json()["printers"]
    assert printers, f"no printers in {city}"
    return city, printers[0]


# ---------------------------------------------------------- read-only endpoints


def test_health_endpoint_returns_ok(client: TestClient):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert isinstance(body.get("agent_ready"), bool)


def test_twin_cities_endpoint_returns_non_empty_list(client: TestClient):
    res = client.get("/twin/cities")
    assert res.status_code == 200
    body = res.json()
    assert "cities" in body
    assert isinstance(body["cities"], list)
    assert len(body["cities"]) >= 1


def test_twin_printers_returns_sorted_ids(client: TestClient, first_city_and_printer):
    city, _ = first_city_and_printer
    res = client.get("/twin/printers", params={"city": city})
    assert res.status_code == 200
    body = res.json()
    assert body["city"] == city
    printers = body["printers"]
    assert printers == sorted(printers), f"printers for {city} not sorted: {printers}"


def test_twin_snapshot_returns_systemsnapshot_shape(client: TestClient, first_city_and_printer):
    city, pid = first_city_and_printer
    res = client.get("/twin/snapshot",
                     params={"city": city, "printer_id": pid, "day": 100})
    assert res.status_code == 200
    body = res.json()
    for key in ("timestamp", "tick", "drivers", "components",
                "forecasts", "forecastHorizonDays"):
        assert key in body, f"snapshot missing {key!r}"
    assert body["tick"] == 100
    assert len(body["components"]) == 6
    statuses = {c["status"] for c in body["components"]}
    assert statuses <= {"FUNCTIONAL", "DEGRADED", "CRITICAL", "FAILED"}


def test_twin_state_keys_are_superset_of_snapshot(client: TestClient, first_city_and_printer):
    city, pid = first_city_and_printer
    snap = client.get("/twin/snapshot",
                      params={"city": city, "printer_id": pid, "day": 100}).json()
    state = client.get("/twin/state",
                       params={"city": city, "printer_id": pid, "day": 100}).json()
    assert set(state.keys()) >= set(snap.keys()), (
        f"state keys {state.keys()} not a superset of snapshot {snap.keys()}"
    )
    assert state["tick"] == snap["tick"]


def test_twin_state_horizon_zero_pins_forecast_to_snapshot(
    client: TestClient, first_city_and_printer,
):
    """horizon_d=0 means the analytic projection can't decay health, so
    each forecast.predictedHealthIndex must equal the corresponding
    snapshot healthIndex."""
    city, pid = first_city_and_printer
    state = client.get("/twin/state",
                       params={"city": city, "printer_id": pid,
                               "day": 100, "horizon_d": 0}).json()
    health_by_id = {c["id"]: c["healthIndex"] for c in state["components"]}
    assert state["forecastHorizonDays"] == 0.0
    assert len(state["forecasts"]) == 6
    for f in state["forecasts"]:
        assert f["predictedHealthIndex"] == health_by_id[f["id"]], (
            f"{f['id']}: forecast {f['predictedHealthIndex']} != "
            f"snapshot {health_by_id[f['id']]}"
        )


def test_twin_forecast_endpoint_returns_six_forecasts(
    client: TestClient, first_city_and_printer,
):
    city, pid = first_city_and_printer
    res = client.get("/twin/forecast",
                     params={"city": city, "printer_id": pid, "day": 100})
    assert res.status_code == 200
    body = res.json()
    assert "horizonDays" in body
    assert "forecasts" in body
    assert len(body["forecasts"]) == 6


def test_twin_timeline_returns_aligned_arrays(
    client: TestClient, first_city_and_printer,
):
    city, pid = first_city_and_printer
    res = client.get(
        "/twin/timeline",
        params={"city": city, "printer_id": pid,
                "fields": "H_C1,H_C2,ambient_temp_c",
                "day_from": 0, "day_to": 9},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["day"]) == 10
    for k in ("H_C1", "H_C2", "ambient_temp_c"):
        assert k in body
        assert len(body[k]) == 10


def test_twin_model_status_reports_active_path(client: TestClient):
    res = client.get("/twin/model_status")
    assert res.status_code == 200
    body = res.json()
    assert body["active_path"] in {"ssl", "analytic"}
    assert isinstance(body["rul_head_present"], bool)


def test_twin_snapshot_unknown_city_404(client: TestClient):
    res = client.get("/twin/snapshot",
                     params={"city": "atlantis", "printer_id": 0, "day": 100})
    assert res.status_code == 404


# ---------------------------------------------------------- /telemetry watchdog


_BASE_TELEMETRY = {
    "timestamp": "2026-04-25T17:00:00",
    "run_id": "RTEST",
    "component": "nozzle_plate",
    "health_index": 0.08,
    "status": "CRITICAL",
    "temperature": 350.0,
    "pressure": 1.7,
    "fan_speed": 900.0,
    "metrics": {"clog_percentage": 91.0},
}


@patch("backend.app.insert_telemetry")
@patch("backend.app.analyze_and_notify")
def test_telemetry_critical_status_schedules_watchdog(
    mock_analyze: MagicMock,
    mock_insert: MagicMock,
    client: TestClient,
):
    """CRITICAL telemetry must add ``analyze_and_notify`` to background
    tasks. We don't care that the LLM ran — only that scheduling happened."""
    mock_insert.return_value = 42
    payload = dict(_BASE_TELEMETRY, status="CRITICAL")

    res = client.post("/telemetry", json=payload)
    assert res.status_code == 200, res.text
    assert res.json() == {"id": 42, "message": "Telemetry data added successfully."}
    mock_analyze.assert_called_once()
    mock_insert.assert_called_once()


@patch("backend.app.insert_telemetry")
@patch("backend.app.analyze_and_notify")
def test_telemetry_failed_status_also_schedules_watchdog(
    mock_analyze: MagicMock,
    mock_insert: MagicMock,
    client: TestClient,
):
    """FAILED is the second status that opts in to the proactive alert."""
    mock_insert.return_value = 7
    payload = dict(_BASE_TELEMETRY, status="FAILED")

    res = client.post("/telemetry", json=payload)
    assert res.status_code == 200, res.text
    mock_analyze.assert_called_once()


@patch("backend.app.insert_telemetry")
@patch("backend.app.analyze_and_notify")
def test_telemetry_functional_status_does_not_schedule_watchdog(
    mock_analyze: MagicMock,
    mock_insert: MagicMock,
    client: TestClient,
):
    """FUNCTIONAL telemetry is uneventful; the watchdog must stay quiet."""
    mock_insert.return_value = 99
    payload = dict(_BASE_TELEMETRY, status="FUNCTIONAL", health_index=0.95)

    res = client.post("/telemetry", json=payload)
    assert res.status_code == 200, res.text
    mock_analyze.assert_not_called()
    mock_insert.assert_called_once()
