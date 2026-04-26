"""Tests for backend/agent/twin_data.py — parquet-backed snapshot/timeline accessors."""
from __future__ import annotations

import pytest

from backend.agent import twin_data
from backend.agent.component_map import COMPONENTS


@pytest.fixture(scope="module", autouse=True)
def _ensure_dataset_loaded():
    twin_data.reset_cache()
    df = twin_data.get_dataset()
    assert not df.empty
    yield
    twin_data.reset_cache()


def test_list_cities_matches_expected_15():
    cities = twin_data.list_cities()
    assert len(cities) == 15
    assert "Barcelona" in cities
    assert "Helsinki" in cities


def test_list_printers_returns_assigned_ids():
    printers = twin_data.list_printers("Barcelona")
    assert printers == sorted(printers)  # ascending
    assert all(0 <= p <= 99 for p in printers)
    # 10 cities have 7 printers, 5 have 6
    assert len(printers) in (6, 7)


def test_list_printers_unknown_city_raises():
    with pytest.raises(KeyError):
        twin_data.list_printers("Atlantis")


def test_day_range_matches_plan_md_calendar():
    lo, hi = twin_data.day_range()
    assert lo == 0
    assert hi == 3652  # 10 years incl. leap days, per PLAN.md


def test_get_snapshot_shape_matches_frontend_contract():
    printers = twin_data.list_printers("Barcelona")
    pid = printers[0]
    snap = twin_data.get_snapshot("Barcelona", pid, 100)

    assert set(snap.keys()) == {
        "timestamp", "tick", "drivers", "components",
        "forecasts", "forecastHorizonDays",
    }
    assert snap["tick"] == 100
    assert snap["forecastHorizonDays"] == pytest.approx(1.0)
    assert snap["forecasts"] == []
    assert "T" in snap["timestamp"]  # ISO


def test_get_snapshot_drivers_have_expected_keys():
    snap = twin_data.get_snapshot("Barcelona", twin_data.list_printers("Barcelona")[0], 100)
    drivers = snap["drivers"]
    expected = {"ambientTempC", "humidityPct", "contaminationPct", "loadPct", "maintenanceCoeff"}
    assert set(drivers.keys()) == expected
    assert all(isinstance(v, float) for v in drivers.values())


def test_get_snapshot_returns_six_components_with_full_metric_set():
    snap = twin_data.get_snapshot("Barcelona", twin_data.list_printers("Barcelona")[0], 100)
    components = snap["components"]
    assert len(components) == 6

    expected_ids = {c.frontend_id for c in COMPONENTS}
    assert {c["id"] for c in components} == expected_ids

    for c in components:
        assert {"id", "label", "subsystem", "healthIndex", "status",
                "metrics", "primaryMetricKey"} <= set(c.keys())
        assert 0.0 <= c["healthIndex"] <= 1.0
        assert c["status"] in {"FUNCTIONAL", "DEGRADED", "CRITICAL", "FAILED"}
        # Each component now ships exactly 3 distinctive metrics; the headline
        # metric is whichever one is listed first in its `derived_metrics` spec.
        assert len(c["metrics"]) == 3
        metric_keys = [m["key"] for m in c["metrics"]]
        assert c["primaryMetricKey"] == metric_keys[0]
        for m in c["metrics"]:
            assert {"key", "label", "value", "unit"} <= set(m.keys())


def test_get_snapshot_health_matches_underlying_parquet_value():
    pid = twin_data.list_printers("Helsinki")[0]
    df = twin_data.get_dataset()
    row = df.loc[
        (df["city"] == "Helsinki")
        & (df["printer_id"] == pid)
        & (df["day"] == 50)
    ].iloc[0]
    snap = twin_data.get_snapshot("Helsinki", pid, 50)

    blade = next(c for c in snap["components"] if c["id"] == "recoater_blade")
    assert blade["healthIndex"] == pytest.approx(float(row["H_C1"]))


def test_get_snapshot_unknown_day_raises():
    pid = twin_data.list_printers("Madrid")[0]
    with pytest.raises(KeyError):
        twin_data.get_snapshot("Madrid", pid, 99999)


def test_get_snapshot_unknown_printer_raises():
    with pytest.raises(KeyError):
        twin_data.get_snapshot("Madrid", 42_000, 100)


def test_get_timeline_returns_arrays_aligned_with_day_axis():
    pid = twin_data.list_printers("Athens")[0]
    timeline = twin_data.get_timeline(
        "Athens", pid,
        fields=["H_C1", "H_C5", "ambient_temp_c"],
        day_from=0, day_to=29,
    )
    assert "day" in timeline
    assert len(timeline["day"]) == 30
    for k in ("H_C1", "H_C5", "ambient_temp_c"):
        assert k in timeline
        assert len(timeline[k]) == 30
        assert all(isinstance(v, float) for v in timeline[k])


def test_get_timeline_full_range_has_3653_rows():
    pid = twin_data.list_printers("Athens")[0]
    timeline = twin_data.get_timeline("Athens", pid, fields=["H_C1"])
    assert len(timeline["day"]) == 3653
    assert timeline["day"][0] == 0
    assert timeline["day"][-1] == 3652


def test_get_timeline_failure_booleans_round_trip_as_bool():
    pid = twin_data.list_printers("Athens")[0]
    timeline = twin_data.get_timeline(
        "Athens", pid, fields=["failure_C1"], day_from=0, day_to=10,
    )
    assert all(isinstance(v, bool) for v in timeline["failure_C1"])


def test_get_timeline_rejects_unknown_fields():
    pid = twin_data.list_printers("Athens")[0]
    with pytest.raises(KeyError):
        twin_data.get_timeline("Athens", pid, fields=["bogus_field"])
