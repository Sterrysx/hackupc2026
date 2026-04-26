"""Unit tests for the SDG simulator core: component / degradation / simulator / schema."""
from __future__ import annotations

import pandas as pd
import pytest

from backend.simulator.core import simulator
from backend.simulator.core.component import Component
from backend.simulator.core.degradation import (
    compute_cross_factors,
    compute_lambda,
    validate_components_config,
)
from backend.simulator.schema import COMPONENT_IDS, coerce_dataframe


# ---------------------------------------------------------------- helpers


def _minimal_spec(**overrides) -> dict:
    """Smallest spec dict that satisfies compute_lambda's reads."""
    spec = {
        "lambda0_per_d": 0.01, "tau_nom_d": 100.0, "L_nom_d": 365.0,
        "b_M": 1.0, "b_L": 1.0, "ext_vars": (), "int_vars": (),
    }
    spec.update(overrides)
    return spec


def _make_component(spec: dict | None = None, *, H: float = 1.0) -> Component:
    return Component(
        id="C1", spec=spec or _minimal_spec(),
        counters={"N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0},
        alpha=1.0, H=H,
    )


def _full_components_cfg() -> dict:
    """6-component config that passes validate_components_config."""
    return {
        "components": {
            cid: {
                "lambda0_per_d": 0.001, "tau_nom_d": 100.0, "L_nom_d": 365.0,
                "b_M": 1.0, "b_L": 1.0, "ext_vars": (), "int_vars": (),
            }
            for cid in COMPONENT_IDS
        }
    }


# ----------------------------------------------------- Component.status()


def test_component_status_failed_at_h_0_1():
    assert _make_component(H=0.1).status() == "FAILED"
    assert _make_component(H=0.05).status() == "FAILED"


def test_component_status_critical_at_h_0_4():
    # 0.4 sits in the CRITICAL band (H<=0.4 inclusive).
    assert _make_component(H=0.4).status() == "CRITICAL"
    assert _make_component(H=0.3).status() == "CRITICAL"


def test_component_status_warning_at_h_0_7():
    assert _make_component(H=0.7).status() == "WARNING"
    assert _make_component(H=0.55).status() == "WARNING"


def test_component_status_ok_above_0_7():
    assert _make_component(H=0.95).status() == "OK"
    assert _make_component(H=1.0).status() == "OK"


# --------------------------------------------- Component degradation/repair


def test_apply_degradation_clamps_to_zero():
    comp = _make_component(H=0.05)
    comp.apply_degradation(1.0)
    assert comp.H == 0.0


def test_apply_degradation_clamps_to_one_for_negative_input():
    comp = _make_component(H=0.5)
    comp.apply_degradation(-2.0)  # treated as recovery; clamped at 1.0
    assert comp.H == 1.0


def test_apply_preventive_adds_half_capped_at_one_and_resets_tau():
    comp = _make_component(H=0.6)
    comp.tau_mant_d = 80.0
    assert comp.apply_preventive() is True
    assert comp.H == pytest.approx(1.0)  # 0.6 + 0.5 = 1.1 → capped at 1.0
    assert comp.tau_mant_d == 0.0


def test_apply_preventive_does_not_overshoot_for_low_health():
    comp = _make_component(H=0.2)
    comp.apply_preventive()
    assert comp.H == pytest.approx(0.7)


def test_apply_corrective_resets_to_full_health_and_zero_counters():
    comp = _make_component(H=0.05)
    comp.tau_mant_d = 50.0
    comp.L_d = 200.0
    comp.hours_since_failure = 1500.0
    assert comp.apply_corrective() is True
    assert comp.H == 1.0
    assert comp.tau_mant_d == 0.0
    assert comp.L_d == 0.0
    assert comp.hours_since_failure == 0.0


def test_accumulate_hours_and_advance_time_are_independent():
    comp = _make_component()
    comp.accumulate_hours(8.0)
    comp.advance_time(1.0)
    assert comp.hours_since_failure == 8.0
    assert comp.tau_mant_d == 1.0
    assert comp.L_d == 1.0


# ----------------------------------------------- compute_lambda product form


def test_compute_lambda_with_no_drivers_equals_lambda0():
    """lambda = lambda0 * f_ext * f_int * f_cross. With empty driver lists
    and L_d=tau_mant_d=0, both factors are 1.0; cross_factor=1.0 by default."""
    comp = _make_component()
    drivers = {}  # not consulted because ext_vars/int_vars are empty
    result = compute_lambda(comp, drivers, f_cross=1.0)
    assert result == pytest.approx(0.01)


def test_compute_lambda_scales_with_external_variable_above_reference():
    spec = _minimal_spec(ext_vars=({"name": "T", "ref": 25.0, "exp": 1.0},))
    comp = _make_component(spec)
    # Drivers at exactly the reference value -> factor = 1.0.
    nominal = compute_lambda(comp, {"T": 25.0}, f_cross=1.0)
    # Doubled driver -> factor = 2.0 (exp=1.0).
    doubled = compute_lambda(comp, {"T": 50.0}, f_cross=1.0)
    assert doubled == pytest.approx(2.0 * nominal)


def test_compute_lambda_applies_cross_factor_multiplicatively():
    comp = _make_component()
    base = compute_lambda(comp, {}, f_cross=1.0)
    boosted = compute_lambda(comp, {}, f_cross=3.0)
    assert boosted == pytest.approx(3.0 * base)


# ----------------------------- compute_cross_factors threshold gating


def _make_six_components(default_h: float = 0.9) -> dict:
    return {
        cid: _make_component(_full_components_cfg()["components"][cid], H=default_h)
        for cid in COMPONENT_IDS
    }


def test_compute_cross_factors_inactive_when_source_above_threshold():
    components = _make_six_components()
    couplings = {"critical_threshold": 0.4, "matrix": {"C1": {"C3": 1.5}}}
    factors = compute_cross_factors(components, couplings)
    assert factors["C3"] == 1.0


def test_compute_cross_factors_active_when_source_drops_below_threshold():
    components = _make_six_components()
    components["C1"].H = 0.2  # below threshold
    couplings = {"critical_threshold": 0.4, "matrix": {"C1": {"C3": 1.5}}}
    factors = compute_cross_factors(components, couplings)
    assert factors["C3"] == pytest.approx(1.5)


# ------------------------------------- validate_components_config rejects


def test_validate_rejects_zero_lambda0():
    cfg = _full_components_cfg()
    cfg["components"]["C1"]["lambda0_per_d"] = 0.0
    with pytest.raises(ValueError, match="lambda0_per_d"):
        validate_components_config(cfg)


def test_validate_rejects_negative_lambda0():
    cfg = _full_components_cfg()
    cfg["components"]["C2"]["lambda0_per_d"] = -0.5
    with pytest.raises(ValueError, match="lambda0_per_d"):
        validate_components_config(cfg)


def test_validate_rejects_zero_l_nom_d():
    cfg = _full_components_cfg()
    cfg["components"]["C3"]["L_nom_d"] = 0.0
    with pytest.raises(ValueError, match="L_nom_d"):
        validate_components_config(cfg)


def test_validate_rejects_zero_tau_nom_d():
    cfg = _full_components_cfg()
    cfg["components"]["C4"]["tau_nom_d"] = 0.0
    with pytest.raises(ValueError, match="tau_nom_d"):
        validate_components_config(cfg)


# --------------------------------------------- simulator._cascade_factor


def test_cascade_factor_unity_at_full_health():
    assert simulator._cascade_factor(1.0) == pytest.approx(1.0)


def test_cascade_factor_two_at_zero_health():
    assert simulator._cascade_factor(0.0) == pytest.approx(2.0)


def test_cascade_factor_monotonic_decreasing_in_health():
    """Higher health -> smaller cascade multiplier."""
    samples = [0.0, 0.25, 0.5, 0.75, 1.0]
    factors = [simulator._cascade_factor(h) for h in samples]
    assert factors == sorted(factors, reverse=True)


# -------------------------------- simulator.apply_maintenance_and_safety


def test_apply_maintenance_fires_corrective_when_health_below_floor():
    components = _make_six_components()
    components["C3"].H = 0.05  # at/below corrective floor
    _, failure_events = simulator.apply_maintenance_and_safety(
        components, {"critical_threshold": 0.4}
    )
    assert failure_events["C3"] is True
    assert components["C3"].H == 1.0


def test_apply_maintenance_critical_pair_targets_lower_health_component():
    """When BOTH C5 and C6 are below threshold, the LOWER-H one gets the
    corrective replacement (mass-failure safety rule)."""
    components = _make_six_components()
    components["C5"].H = 0.25  # lower
    components["C6"].H = 0.35
    _, failure_events = simulator.apply_maintenance_and_safety(
        components, {"critical_threshold": 0.4}
    )
    assert failure_events["C5"] is True
    assert failure_events["C6"] is False
    assert components["C5"].H == 1.0


# -------------------------------------------- schema.coerce_dataframe


def _build_minimal_dataframe() -> pd.DataFrame:
    row = {
        "printer_id": 0, "city": "barcelona", "climate_zone": "mediterranean",
        "date": pd.Timestamp("2026-04-25"), "day": 0,
        "ambient_temp_c": 22.0, "humidity_pct": 50.0, "dust_concentration": 50.0,
        "Q_demand": 1.0, "daily_print_hours": 4.0, "cumulative_print_hours": 4.0,
        "N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0,
    }
    for cid in COMPONENT_IDS:
        row[f"H_{cid}"] = 1.0
        row[f"status_{cid}"] = "OK"
        row[f"tau_{cid}"] = 0.0
        row[f"L_{cid}"] = 0.0
        row[f"lambda_{cid}"] = 0.001
        row[f"maint_{cid}"] = False
        row[f"failure_{cid}"] = False
        row[f"hours_since_{cid}_failure"] = 0.0
    return pd.DataFrame([row])


def test_coerce_dataframe_round_trip_preserves_data():
    df = _build_minimal_dataframe()
    coerced = coerce_dataframe(df, include_rul=False)
    assert int(coerced.iloc[0]["printer_id"]) == 0
    assert float(coerced.iloc[0]["H_C1"]) == pytest.approx(1.0)


def test_coerce_dataframe_raises_on_missing_required_column():
    df = _build_minimal_dataframe().drop(columns=["H_C1"])
    with pytest.raises(ValueError, match="missing required column"):
        coerce_dataframe(df, include_rul=False)
