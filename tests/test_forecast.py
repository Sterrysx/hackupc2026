"""Tests for Ai_Agent/forecast.py — analytic per-component projection."""
from __future__ import annotations

import pandas as pd
import pytest

from Ai_Agent import forecast, twin_data
from Ai_Agent.component_map import COMPONENTS


# ----------------------------------------------------------------- unit math


def test_predicted_status_bands_match_simulator():
    assert forecast._predicted_status_from_health(0.05) == "FAILED"
    assert forecast._predicted_status_from_health(0.30) == "CRITICAL"
    assert forecast._predicted_status_from_health(0.55) == "DEGRADED"
    assert forecast._predicted_status_from_health(0.95) == "FUNCTIONAL"


def test_minutes_to_threshold_returns_none_when_already_past():
    assert forecast._minutes_to_threshold(0.05, 0.01, threshold=0.1) is None
    assert forecast._minutes_to_threshold(0.40, 0.01, threshold=0.4) is None


def test_minutes_to_threshold_returns_none_when_no_hazard():
    assert forecast._minutes_to_threshold(0.9, 0.0, threshold=0.4) is None


def test_minutes_to_threshold_returns_none_when_lambda_below_operational_floor():
    """λ < 1e-5/h means no measurable degradation in any operational window —
    returning a 'failure in 5 years' ETA misleads the operator. None instead."""
    assert forecast._minutes_to_threshold(0.9, 1e-7, threshold=0.4) is None
    assert forecast._minutes_to_threshold(0.9, 9e-6, threshold=0.4) is None


def test_minutes_to_threshold_caps_at_operational_horizon():
    """ETA past _OPERATIONAL_HORIZON_MIN means 'stable' — emit None, not a
    technically-correct but visually-misleading multi-year value."""
    # H=0.95, λ=1e-4/h, threshold=0.1 → 510,000 minutes (~354 days). Way past horizon.
    assert forecast._minutes_to_threshold(0.95, 1e-4, threshold=0.1) is None


def test_minutes_to_threshold_basic_math():
    # H=0.7, λ=0.01/h → reaches 0.4 after 30 hours = 1800 min.
    assert forecast._minutes_to_threshold(0.7, 0.01, threshold=0.4) == pytest.approx(1800.0)


def test_minutes_to_threshold_keeps_short_horizons_intact():
    """Anything inside the operational horizon must come through unchanged."""
    # H=0.5, λ=0.05/h, threshold=0.1 → 8 hours = 480 min. Well inside horizon.
    assert forecast._minutes_to_threshold(0.5, 0.05, threshold=0.1) == pytest.approx(480.0)


def test_project_health_linear_with_lambda():
    # λ=0.02/h over 60 min → ΔH = 0.02 → H drops from 0.5 to 0.48.
    assert forecast._project_health(0.5, 0.02, horizon_min=60) == pytest.approx(0.48)


def test_project_health_clamps_to_zero():
    assert forecast._project_health(0.05, 1.0, horizon_min=60) == 0.0


def test_project_health_clamps_to_one():
    assert forecast._project_health(0.99, -1.0, horizon_min=60) == 1.0


def test_confidence_drops_when_lambda_is_zero():
    assert forecast._confidence(0.0, h=0.9) < forecast._confidence(0.01, h=0.9)


def test_dominant_driver_text_picks_extreme_value():
    row = pd.Series({
        "ambient_temp_c": 18.0,        # at nominal
        "humidity_pct": 55.0,          # at nominal
        "dust_concentration": 5.0,     # 5× nominal — should win
        "Q_demand": 1.0,
    })
    txt = forecast._dominant_driver_text(row)
    assert "dust" in txt
    assert "5" in txt  # ratio


# --------------------------------------------------------- integration tests


def test_compute_forecasts_returns_one_per_component():
    pid = twin_data.list_printers("Barcelona")[0]
    forecasts = forecast.compute_forecasts("Barcelona", pid, day=200)

    assert len(forecasts) == 6
    expected_ids = {c.frontend_id for c in COMPONENTS}
    assert {f["id"] for f in forecasts} == expected_ids


def test_compute_forecasts_payload_shape_matches_contract():
    pid = twin_data.list_printers("Barcelona")[0]
    forecasts = forecast.compute_forecasts("Barcelona", pid, day=200)

    expected_keys = {
        "id", "predictedHealthIndex", "predictedStatus", "predictedMetrics",
        "minutesUntilCritical", "minutesUntilFailure", "rationale", "confidence",
    }
    for f in forecasts:
        assert set(f.keys()) == expected_keys
        assert 0.0 <= f["predictedHealthIndex"] <= 1.0
        assert f["predictedStatus"] in {"FUNCTIONAL", "DEGRADED", "CRITICAL", "FAILED"}
        assert 0.0 <= f["confidence"] <= 1.0
        assert isinstance(f["rationale"], str) and f["rationale"]
        assert isinstance(f["predictedMetrics"], list) and len(f["predictedMetrics"]) == 3


def test_compute_forecasts_predicted_health_is_no_higher_than_current():
    """λ ≥ 0 by construction → projected health can't *increase* over horizon."""
    pid = twin_data.list_printers("Athens")[0]
    snap = twin_data.get_snapshot("Athens", pid, day=200)
    forecasts = forecast.compute_forecasts("Athens", pid, day=200)
    by_id = {c["id"]: c for c in snap["components"]}
    for f in forecasts:
        assert f["predictedHealthIndex"] <= by_id[f["id"]]["healthIndex"] + 1e-6


def test_compute_forecasts_horizon_zero_keeps_health_unchanged():
    pid = twin_data.list_printers("Athens")[0]
    snap = twin_data.get_snapshot("Athens", pid, day=200)
    forecasts = forecast.compute_forecasts("Athens", pid, day=200, horizon_min=0)
    by_id = {c["id"]: c for c in snap["components"]}
    for f in forecasts:
        assert f["predictedHealthIndex"] == pytest.approx(by_id[f["id"]]["healthIndex"])


def test_compute_forecasts_unknown_inputs_propagate_keyerror():
    with pytest.raises(KeyError):
        forecast.compute_forecasts("Atlantis", 0, day=10)


def test_compute_forecasts_never_emits_failure_eta_past_operational_horizon():
    """No forecast should claim a sub-30-day failure ETA that's actually
    months/years away — that's the perception bug operators called out."""
    cap_min = forecast._OPERATIONAL_HORIZON_MIN
    samples = [
        ("Barcelona", 50), ("Barcelona", 200), ("Barcelona", 800),
        ("Madrid", 100), ("Helsinki", 400), ("Athens", 1500),
        ("Athens", 2500), ("Athens", 3500),
    ]
    for city, day in samples:
        pid = twin_data.list_printers(city)[0]
        for f in forecast.compute_forecasts(city, pid, day=day):
            mtf = f["minutesUntilFailure"]
            assert mtf is None or mtf <= cap_min, (
                f"{city} day={day} {f['id']}: minutesUntilFailure={mtf} "
                f"exceeds operational horizon {cap_min}"
            )
            mtc = f["minutesUntilCritical"]
            assert mtc is None or mtc <= forecast._CRITICAL_HORIZON_MIN, (
                f"{city} day={day} {f['id']}: minutesUntilCritical={mtc} "
                f"exceeds critical horizon {forecast._CRITICAL_HORIZON_MIN}"
            )


def test_compute_forecasts_healthy_printer_mostly_reports_stable():
    """For a printer whose components are all H>0.9, almost none should have
    a non-None minutesUntilFailure — there's no measurable degradation."""
    pid = twin_data.list_printers("Helsinki")[0]
    snap = twin_data.get_snapshot("Helsinki", pid, day=10)  # very early life
    healthy_components = [c for c in snap["components"] if c["healthIndex"] > 0.9]
    if not healthy_components:
        pytest.skip("seed printer not healthy enough at day 10 for this assertion")

    forecasts = forecast.compute_forecasts("Helsinki", pid, day=10)
    by_id = {f["id"]: f for f in forecasts}
    flagged = [c["id"] for c in healthy_components
               if by_id[c["id"]]["minutesUntilFailure"] is not None]
    # Allow at most one healthy component to look "about to fail" — anything
    # more is the perception bug returning.
    assert len(flagged) <= 1, (
        f"Healthy printer flagged {flagged} as failing — perception bug regressed"
    )


# ----------------------------------- model dispatch path

def test_active_path_reports_current_dispatch_mode():
    # Either "ssl" (when rul_head_ssl.pt + encoder + scaler all present) or
    # "analytic" (anything missing). Both are valid — we just want a string.
    assert forecast.active_path() in {"ssl", "analytic"}


def test_compute_forecasts_falls_back_to_analytic_when_head_missing(monkeypatch):
    monkeypatch.setattr(forecast, "_has_rul_head", lambda: False)
    pid = twin_data.list_printers("Barcelona")[0]
    forecasts = forecast.compute_forecasts("Barcelona", pid, day=200)

    assert len(forecasts) == 6
    # Analytic confidence is always 0.4 or 0.6, never the SSL bump (0.78).
    assert all(f["confidence"] in {0.4, 0.5, 0.6} for f in forecasts)
    assert all("Projected from current λ=" in f["rationale"] for f in forecasts)


def test_ssl_forecasts_use_learned_rationale_when_head_present():
    if not forecast._has_rul_head():
        pytest.skip("rul_head_ssl.pt not on disk — analytic-only environment")
    # Force-clear cache so we exercise the load path.
    forecast.reset_model_cache()
    pid = twin_data.list_printers("Barcelona")[0]
    forecasts = forecast.compute_forecasts("Barcelona", pid, day=400)

    assert len(forecasts) == 6
    assert all(f["confidence"] == 0.78 for f in forecasts)
    assert all("SSL+RUL model" in f["rationale"] for f in forecasts)
    # Per the operational-horizon clamp: healthy components legitimately
    # return None for minutesUntilFailure. We only require the SSL path to
    # be running (rationale string above) — None is the *correct* answer
    # for "no failure in the actionable 30-day window".
    for f in forecasts:
        if f["minutesUntilFailure"] is not None:
            assert 0.0 <= f["minutesUntilFailure"] <= forecast._OPERATIONAL_HORIZON_MIN


def test_ssl_forecasts_falls_back_when_window_is_too_short():
    if not forecast._has_rul_head():
        pytest.skip("rul_head_ssl.pt not on disk")
    pid = twin_data.list_printers("Barcelona")[0]
    # Day 5 has only 6 days of history → less than 360-day context window.
    forecasts = forecast.compute_forecasts("Barcelona", pid, day=5)
    assert len(forecasts) == 6
    # Per-call analytic fallback kicks in for early days.
    assert all("Projected from current λ" in f["rationale"] for f in forecasts)
