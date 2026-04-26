"""Unit tests for the Ai_Agent surface (twin_data, forecast, schemas, component_map).

Covers private helpers and pydantic validation that aren't exercised by the
broader integration tests in `tests/test_*.py`. Parquet I/O is mocked via
``_load_parquet`` monkeypatching so these tests stay fast and offline.
"""
from __future__ import annotations

from datetime import date as Date, datetime
from unittest.mock import patch

import pandas as pd
import pytest
from pydantic import ValidationError

from Ai_Agent import component_map, forecast, twin_data
from Ai_Agent.schemas import DiagnosticReport


# -------------------------------------------------------------- fixtures


def _build_synthetic_row() -> pd.Series:
    """One row with every column twin_data expects, hand-crafted for tests."""
    data = {
        "city": "Barcelona",
        "printer_id": 0,
        "day": 100,
        "date": Date(2026, 4, 11),
        "ambient_temp_c": 22.0,
        "humidity_pct": 50.0,
        "dust_concentration": 50.0,
        "Q_demand": 1.0,
        "daily_print_hours": 4.0,
        "cumulative_print_hours": 400.0,
        "N_f": 0,
        "N_c": 0,
        "N_TC": 0,
        "N_on": 0,
    }
    for cid in ("C1", "C2", "C3", "C4", "C5", "C6"):
        data[f"H_{cid}"] = 0.85
        data[f"status_{cid}"] = "OK"
        data[f"tau_{cid}"] = 1.0
        data[f"L_{cid}"] = 1.0
        data[f"lambda_{cid}"] = 0.001
        data[f"maint_{cid}"] = False
        data[f"failure_{cid}"] = False
        data[f"hours_since_{cid}_failure"] = 0.0
    return pd.Series(data)


@pytest.fixture
def synthetic_parquet_df() -> pd.DataFrame:
    return pd.DataFrame([_build_synthetic_row().to_dict()])


# --------------------------------------------------- twin_data._iso_timestamp


def test_iso_timestamp_from_date_uses_noon():
    iso = twin_data._iso_timestamp(Date(2026, 4, 25))
    assert iso == "2026-04-25T12:00:00"
    assert "T" in iso  # ISO contract assumed by frontend


def test_iso_timestamp_from_datetime_preserves_full_precision():
    dt = datetime(2026, 4, 25, 14, 30, 15)
    assert twin_data._iso_timestamp(dt) == "2026-04-25T14:30:15"


# --------------------------------------------------- twin_data._build_drivers


def test_build_drivers_maps_simulator_columns_to_frontend_keys():
    row = _build_synthetic_row()
    drivers = twin_data._build_drivers(row)

    assert set(drivers.keys()) == {
        "ambientTempC", "humidityPct", "contaminationPct", "loadPct",
        "maintenanceCoeff",
    }
    assert drivers["ambientTempC"] == 22.0
    assert drivers["humidityPct"] == 50.0
    assert drivers["contaminationPct"] == 50.0
    assert drivers["loadPct"] == 4.0
    assert drivers["maintenanceCoeff"] == 1.0


def test_build_drivers_returns_floats():
    row = _build_synthetic_row()
    drivers = twin_data._build_drivers(row)
    assert all(isinstance(v, float) for v in drivers.values())


# ------------------------------------------------- twin_data._build_components


def test_build_components_returns_six_components_with_status_mapped():
    row = _build_synthetic_row()
    components = twin_data._build_components(row)

    assert len(components) == 6
    # Status "OK" must be translated to frontend "FUNCTIONAL".
    assert all(c["status"] == "FUNCTIONAL" for c in components)
    # Frontend ids match the canonical mapping.
    assert {c["id"] for c in components} == {
        "recoater_blade", "recoater_motor", "nozzle_plate",
        "thermal_resistor", "heating_element", "insulation_panel",
    }


def test_build_components_each_has_three_metrics():
    row = _build_synthetic_row()
    components = twin_data._build_components(row)
    for c in components:
        assert len(c["metrics"]) == 3
        assert c["primaryMetricKey"] == c["metrics"][0]["key"]


# ----------------------------------------- twin_data with mocked parquet


def test_get_dataset_uses_mocked_parquet(synthetic_parquet_df, monkeypatch):
    """Patches `_load_parquet` so no real parquet I/O happens."""
    twin_data.reset_cache()
    # Replace the cached loader with a plain stub. Once monkeypatch swaps
    # in the lambda the lru_cache wrapper is gone, so we must NOT call
    # reset_cache() afterwards.
    monkeypatch.setattr(twin_data, "_load_parquet", lambda _path: synthetic_parquet_df)

    df = twin_data.get_dataset()
    assert len(df) == 1
    assert df.iloc[0]["city"] == "Barcelona"


# --------------------------------- forecast._predicted_status_from_health


def test_predicted_status_at_exact_threshold_0_1_is_failed():
    # 0.1 boundary: simulator's `Component.status()` returns FAILED for H<=0.1.
    assert forecast._predicted_status_from_health(0.1) == "FAILED"


def test_predicted_status_at_exact_threshold_0_4_is_critical():
    assert forecast._predicted_status_from_health(0.4) == "CRITICAL"


def test_predicted_status_at_exact_threshold_0_7_is_degraded():
    # 0.7 boundary: WARNING band -> mapped to frontend DEGRADED.
    assert forecast._predicted_status_from_health(0.7) == "DEGRADED"


def test_predicted_status_just_above_thresholds_steps_up_band():
    assert forecast._predicted_status_from_health(0.1001) == "CRITICAL"
    assert forecast._predicted_status_from_health(0.4001) == "DEGRADED"
    assert forecast._predicted_status_from_health(0.7001) == "FUNCTIONAL"


# --------------------------------------------- forecast.active_path()


def test_active_path_returns_analytic_when_head_missing(monkeypatch):
    monkeypatch.setattr(forecast, "_has_rul_head", lambda: False)
    assert forecast.active_path() == "analytic"


def test_active_path_returns_analytic_when_bundle_load_fails(monkeypatch):
    monkeypatch.setattr(forecast, "_has_rul_head", lambda: True)
    monkeypatch.setattr(forecast, "_get_bundle", lambda: None)
    assert forecast.active_path() == "analytic"


# ----------------------------------------------- DiagnosticReport schema


def test_diagnostic_report_requires_grounded_text_evidence_severity_priority():
    """All four scalar fields are required; pydantic must reject when missing."""
    with pytest.raises(ValidationError):
        DiagnosticReport()  # type: ignore[call-arg]


def test_diagnostic_report_default_recommended_actions_is_empty_list():
    """`recommended_actions` defaults to empty list — guardrail enforces ≥1
    elsewhere; the model itself must allow zero so the synthesizer can build
    incrementally."""
    report = DiagnosticReport(
        grounded_text="Nominal",
        evidence_citation="2026-04-25T14:00:00, run_id: R1",
        severity_indicator="INFO",
        priority_level="LOW",
    )
    assert report.recommended_actions == []


def test_diagnostic_report_field_types_are_enforced():
    report = DiagnosticReport(
        grounded_text="Nozzle dropout climbing.",
        evidence_citation="2026-04-25T14:05:02, run_id: R1",
        severity_indicator="WARNING",
        recommended_actions=["Replace plate"],
        priority_level="MEDIUM",
    )
    assert isinstance(report.grounded_text, str)
    assert isinstance(report.recommended_actions, list)
    assert all(isinstance(a, str) for a in report.recommended_actions)


def test_diagnostic_report_accepts_multiple_recommended_actions():
    report = DiagnosticReport(
        grounded_text="Multi-component degradation.",
        evidence_citation="timestamp: 2026-04-25T14:10:00, run_id: R2",
        severity_indicator="CRITICAL",
        recommended_actions=["Stop print", "Cool element", "Inspect blade"],
        priority_level="HIGH",
    )
    assert len(report.recommended_actions) == 3


# --------------------------------------------- component_map case sensitivity


def test_by_sim_id_is_case_sensitive_and_raises_on_lowercase():
    """The simulator emits literal "C1".."C6". A lowercase id must raise so
    callers don't paper over a contract drift silently."""
    with pytest.raises(KeyError) as exc:
        component_map.by_sim_id("c1")
    assert "c1" in str(exc.value)


def test_by_frontend_id_case_sensitive():
    with pytest.raises(KeyError):
        component_map.by_frontend_id("RECOATER_BLADE")


def test_by_sim_id_error_includes_unknown_id():
    with pytest.raises(KeyError) as exc:
        component_map.by_sim_id("C99")
    # error must surface the offending value to make debugging easy.
    assert "C99" in str(exc.value)


def test_by_frontend_id_error_includes_unknown_id():
    with pytest.raises(KeyError) as exc:
        component_map.by_frontend_id("flux_capacitor")
    assert "flux_capacitor" in str(exc.value)


def test_map_status_rejects_unknown_with_descriptive_message():
    with pytest.raises(KeyError) as exc:
        component_map.map_status("BROKEN_BEYOND_REPAIR")
    assert "BROKEN_BEYOND_REPAIR" in str(exc.value)


def test_map_status_is_case_sensitive():
    """Lowercase 'ok' must raise — the simulator strictly emits uppercase."""
    with pytest.raises(KeyError):
        component_map.map_status("ok")
