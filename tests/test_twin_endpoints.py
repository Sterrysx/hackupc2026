"""End-to-end tests for /twin/* HTTP endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_twin_cities_returns_15_cities():
    res = client.get("/twin/cities")
    assert res.status_code == 200
    body = res.json()
    assert "cities" in body
    assert len(body["cities"]) == 15
    assert "Barcelona" in body["cities"]


def test_twin_printers_lists_for_known_city():
    res = client.get("/twin/printers", params={"city": "Barcelona"})
    assert res.status_code == 200
    body = res.json()
    assert body["city"] == "Barcelona"
    assert isinstance(body["printers"], list)
    assert all(0 <= p <= 99 for p in body["printers"])
    assert len(body["printers"]) in (6, 7)


def test_twin_printers_unknown_city_404():
    res = client.get("/twin/printers", params={"city": "Atlantis"})
    assert res.status_code == 404


def test_twin_snapshot_returns_systemsnapshot_shape():
    pid = client.get("/twin/printers", params={"city": "Madrid"}).json()["printers"][0]
    res = client.get(
        "/twin/snapshot",
        params={"city": "Madrid", "printer_id": pid, "day": 200},
    )
    assert res.status_code == 200
    body = res.json()
    for key in ("timestamp", "tick", "drivers", "components", "forecasts", "forecastHorizonDays"):
        assert key in body
    assert body["tick"] == 200
    assert len(body["components"]) == 6
    statuses = {c["status"] for c in body["components"]}
    assert statuses <= {"FUNCTIONAL", "DEGRADED", "CRITICAL", "FAILED"}


def test_twin_snapshot_unknown_day_404():
    pid = client.get("/twin/printers", params={"city": "Madrid"}).json()["printers"][0]
    res = client.get(
        "/twin/snapshot",
        params={"city": "Madrid", "printer_id": pid, "day": 99999},
    )
    assert res.status_code == 404


def test_twin_state_returns_same_shape_as_snapshot():
    pid = client.get("/twin/printers", params={"city": "Helsinki"}).json()["printers"][0]
    snap = client.get(
        "/twin/snapshot",
        params={"city": "Helsinki", "printer_id": pid, "day": 50},
    ).json()
    state = client.get(
        "/twin/state",
        params={"city": "Helsinki", "printer_id": pid, "day": 50},
    ).json()
    assert set(state.keys()) == set(snap.keys())
    assert state["tick"] == snap["tick"]


def test_twin_state_now_includes_six_forecasts():
    pid = client.get("/twin/printers", params={"city": "Helsinki"}).json()["printers"][0]
    state = client.get(
        "/twin/state",
        params={"city": "Helsinki", "printer_id": pid, "day": 50},
    ).json()
    assert len(state["forecasts"]) == 6
    for f in state["forecasts"]:
        for key in ("id", "predictedHealthIndex", "predictedStatus",
                    "predictedMetrics", "daysUntilCritical",
                    "daysUntilFailure", "rationale", "confidence"):
            assert key in f


def test_twin_state_horizon_d_query_param_is_respected():
    pid = client.get("/twin/printers", params={"city": "Athens"}).json()["printers"][0]
    state = client.get(
        "/twin/state",
        params={"city": "Athens", "printer_id": pid, "day": 200, "horizon_d": 0},
    ).json()
    by_id_health = {c["id"]: c["healthIndex"] for c in state["components"]}
    for f in state["forecasts"]:
        assert f["predictedHealthIndex"] == by_id_health[f["id"]]
    assert state["forecastHorizonDays"] == 0.0


def test_twin_forecast_endpoint_returns_six_forecasts():
    pid = client.get("/twin/printers", params={"city": "Madrid"}).json()["printers"][0]
    res = client.get(
        "/twin/forecast",
        params={"city": "Madrid", "printer_id": pid, "day": 100},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["horizonDays"] == pytest.approx(1.0)
    assert len(body["forecasts"]) == 6


def test_twin_forecast_unknown_city_404():
    res = client.get(
        "/twin/forecast",
        params={"city": "Atlantis", "printer_id": 0, "day": 100},
    )
    assert res.status_code == 404


def test_twin_model_status_reports_active_path():
    res = client.get("/twin/model_status")
    assert res.status_code == 200
    body = res.json()
    assert body["active_path"] in {"ssl", "analytic"}
    assert isinstance(body["rul_head_present"], bool)


def test_twin_timeline_returns_aligned_arrays():
    pid = client.get("/twin/printers", params={"city": "Athens"}).json()["printers"][0]
    res = client.get(
        "/twin/timeline",
        params={
            "city": "Athens",
            "printer_id": pid,
            "fields": "H_C1,H_C5,ambient_temp_c",
            "day_from": 0,
            "day_to": 9,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["day"]) == 10
    for k in ("H_C1", "H_C5", "ambient_temp_c"):
        assert len(body[k]) == 10


def test_twin_timeline_rejects_empty_fields_param():
    pid = client.get("/twin/printers", params={"city": "Athens"}).json()["printers"][0]
    res = client.get(
        "/twin/timeline",
        params={"city": "Athens", "printer_id": pid, "fields": ""},
    )
    assert res.status_code == 400


def test_twin_timeline_rejects_unknown_field():
    pid = client.get("/twin/printers", params={"city": "Athens"}).json()["printers"][0]
    res = client.get(
        "/twin/timeline",
        params={"city": "Athens", "printer_id": pid, "fields": "bogus"},
    )
    assert res.status_code == 404
