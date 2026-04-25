import json
import pytest
from Ai_Agent.tools import query_database, get_existing_runs, think


def _call(run_identifier, timestamp_range=None, component=None):
    return json.loads(query_database.invoke({
        "run_identifier": run_identifier,
        "timestamp_range": timestamp_range,
        "component": component,
    }))


def test_returns_records_for_known_run():
    result = _call("R1")
    assert isinstance(result, list)
    assert len(result) > 0


def test_returns_error_for_unknown_run():
    result = _call("UNKNOWN")
    assert "error" in result
    assert "hint" in result
    assert "attempted_params" in result


def test_error_includes_attempted_params():
    result = _call("BADRUN", component="nozzle_plate")
    assert result["attempted_params"]["run_identifier"] == "BADRUN"
    assert result["attempted_params"]["component"] == "nozzle_plate"


def test_no_records_error_includes_hint():
    result = _call("R1", component="nonexistent_component")
    assert "error" in result
    assert "hint" in result


def test_filters_by_component():
    result = _call("R1", component="nozzle_plate")
    assert all(r["component"] == "nozzle_plate" for r in result)


def test_r1_contains_critical_record():
    result = _call("R1")
    statuses = [r["status"] for r in result]
    assert "CRITICAL" in statuses


def test_r2_contains_failed_record():
    result = _call("R2")
    statuses = [r["status"] for r in result]
    assert "FAILED" in statuses


def test_timestamp_range_filter():
    result = _call("R1", timestamp_range="14:00:00-14:02:00")
    assert all("14:00" in r["timestamp"] for r in result)


def test_get_existing_runs_returns_run_ids():
    result = json.loads(get_existing_runs.invoke({}))
    assert "R1" in result["available_runs"]
    assert "R2" in result["available_runs"]


def test_think_returns_empty_string():
    result = think.invoke({"thought": "The nozzle plate temperature is very high, this is CRITICAL."})
    assert result == ""


def test_think_accepts_any_thought():
    result = think.invoke({"thought": "Comparing R1 and R2 to determine severity."})
    assert result == ""
