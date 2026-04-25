from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from sdg.core.component import Component
from sdg.core.degradation import compute_cross_factors, compute_lambda
from sdg.core.simulator import apply_maintenance_and_safety, run_printer
from sdg.generate import load_configs
from sdg.schema import COMPONENT_IDS, FINAL_SCHEMA


def test_nominal_driver_values_match_base_lambda() -> None:
    components_cfg, _couplings_cfg, _cities_cfg = load_configs()
    counters = {"N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0}

    for component_id in COMPONENT_IDS:
        spec = components_cfg["components"][component_id]
        component = Component(component_id, spec, counters, alpha=1.0)
        drivers = _nominal_drivers_for(spec)
        lambda_i = compute_lambda(component, drivers, f_cross=1.0)
        assert math.isclose(lambda_i, float(spec["lambda0_per_d"]), rel_tol=0.01)


def test_coupling_orientation_source_to_target() -> None:
    components_cfg, couplings_cfg, _cities_cfg = load_configs()
    components = _components(components_cfg)
    components["C1"].H = 0.3

    factors = compute_cross_factors(components, couplings_cfg)

    assert factors["C2"] == 1.4
    assert factors["C3"] == 2.0
    assert factors["C1"] == 1.0
    assert factors["C4"] == 1.0
    assert factors["C5"] == 1.0
    assert factors["C6"] == 1.0


def test_thermal_pair_cap_and_short_run_stability() -> None:
    components_cfg, couplings_cfg, cities_cfg = load_configs()
    components = _components(components_cfg)
    components["C5"].H = 0.3
    components["C6"].H = 0.3

    factors = compute_cross_factors(components, couplings_cfg)

    assert math.isclose(factors["C5"] * factors["C6"], 2.5, rel_tol=0.0, abs_tol=1e-12)

    dates = [date(2015, 1, 1) + timedelta(days=day) for day in range(100)]
    rows = run_printer(
        printer_id=0,
        city_profile=cities_cfg["cities"][0],
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        rng=np.random.default_rng(0),
        monthly_jobs=12.0,
        alphas={component_id: 1.0 for component_id in COMPONENT_IDS},
    )
    for row in rows:
        for component_id in COMPONENT_IDS:
            assert 0.0 <= row[f"H_{component_id}"] <= 1.0


def test_preventive_happens_before_corrective_on_same_day() -> None:
    components_cfg, couplings_cfg, _cities_cfg = load_configs()
    components = _components(components_cfg)
    components["C1"].H = 0.05
    components["C1"].tau_mant_d = float(components["C1"].spec["tau_nom_d"])

    maint, failure = apply_maintenance_and_safety(components, couplings_cfg)

    assert maint["C1"] is True
    assert failure["C1"] is False
    assert math.isclose(components["C1"].H, 0.55)


def test_apply_corrective_resets_hours_since_failure() -> None:
    components_cfg, _couplings_cfg, _cities_cfg = load_configs()
    component = _components(components_cfg)["C1"]
    component.hours_since_failure = 100.0

    component.apply_corrective()

    assert component.hours_since_failure == 0.0


def test_apply_preventive_does_not_reset_hours_since_failure() -> None:
    components_cfg, _couplings_cfg, _cities_cfg = load_configs()
    component = _components(components_cfg)["C1"]
    component.hours_since_failure = 100.0

    component.apply_preventive()

    assert component.hours_since_failure == 100.0


def test_lambda0_per_d_is_positive_finite() -> None:
    # lambda0_per_d is empirically calibrated against the simulator so it no
    # longer matches the analytic 0.9/first_failure_target_d. Just check it
    # is a sensible positive value and that first_failure_target_d, when set,
    # is positive too.
    components_cfg, _couplings_cfg, _cities_cfg = load_configs()
    for component_id in COMPONENT_IDS:
        spec = components_cfg["components"][component_id]
        lambda0 = float(spec["lambda0_per_d"])
        assert math.isfinite(lambda0) and lambda0 > 0, f"{component_id}: bad lambda0_per_d"
        target = spec.get("first_failure_target_d")
        if target is not None:
            assert float(target) > 0, f"{component_id}: bad first_failure_target_d"


def test_schema_includes_new_columns() -> None:
    names = set(FINAL_SCHEMA.names)
    assert "daily_print_hours" in names
    assert "cumulative_print_hours" in names
    for component_id in COMPONENT_IDS:
        assert f"hours_since_{component_id}_failure" in names
    assert "jobs_today" not in names


def test_daily_print_hours_distribution() -> None:
    components_cfg, couplings_cfg, cities_cfg = load_configs()
    dates = [date(2015, 1, 1) + timedelta(days=day) for day in range(720)]
    rows = run_printer(
        printer_id=0,
        city_profile=cities_cfg["cities"][0],
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        rng=np.random.default_rng(0),
        monthly_jobs=12.0,
        alphas={component_id: 1.0 for component_id in COMPONENT_IDS},
    )

    hours = np.array([row["daily_print_hours"] for row in rows], dtype=np.float64)
    # Gamma(2, 2) has mean 4, std 2*sqrt(2) ≈ 2.83. 720-day SE on the mean ≈ 0.106.
    assert hours.min() >= 0.0
    assert abs(hours.mean() - 4.0) < 0.5
    assert abs(hours.std() - 2 * math.sqrt(2)) < 0.5


def test_cumulative_print_hours_is_running_sum() -> None:
    components_cfg, couplings_cfg, cities_cfg = load_configs()
    dates = [date(2015, 1, 1) + timedelta(days=day) for day in range(30)]
    rows = run_printer(
        printer_id=0,
        city_profile=cities_cfg["cities"][0],
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        rng=np.random.default_rng(0),
        monthly_jobs=12.0,
        alphas={component_id: 1.0 for component_id in COMPONENT_IDS},
    )

    expected = 0.0
    for row in rows:
        expected += float(row["daily_print_hours"])
        assert math.isclose(float(row["cumulative_print_hours"]), expected, rel_tol=1e-6)


def test_hours_since_failure_resets_on_failure_event() -> None:
    components_cfg, couplings_cfg, cities_cfg = load_configs()
    # Long enough that C1 fails at least once under nominal-ish driving.
    dates = [date(2015, 1, 1) + timedelta(days=day) for day in range(300)]
    rows = run_printer(
        printer_id=0,
        city_profile=cities_cfg["cities"][0],
        dates=dates,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        rng=np.random.default_rng(0),
        monthly_jobs=12.0,
        alphas={component_id: 1.0 for component_id in COMPONENT_IDS},
    )

    # Find a row where C1 fails, assert hours_since_C1_failure is small (= today's hours).
    for row in rows:
        if bool(row["failure_C1"]):
            assert float(row["hours_since_C1_failure"]) <= float(row["daily_print_hours"]) + 1e-6
            return
    raise AssertionError("expected at least one C1 failure within 300-day run")


def test_alpha_sigma_is_validated() -> None:
    from sdg.core.degradation import validate_components_config

    components_cfg, _couplings_cfg, _cities_cfg = load_configs()
    # Spec is valid as-is.
    validate_components_config(components_cfg)
    # Mutate one component to have an invalid alpha_sigma and expect a raise.
    bad = {**components_cfg, "components": {**components_cfg["components"]}}
    bad["components"]["C1"] = {**bad["components"]["C1"], "alpha_sigma": 1.5}
    try:
        validate_components_config(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for alpha_sigma >= 1.0")


def _components(components_cfg: dict) -> dict[str, Component]:
    counters = {"N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0}
    return {
        component_id: Component(component_id, components_cfg["components"][component_id], counters)
        for component_id in COMPONENT_IDS
    }


def _nominal_drivers_for(spec: dict) -> dict[str, float]:
    drivers = {
        "T": 25.0,
        "H": 40.0,
        "c_p": 50.0,
        "Q": 1.0,
        "T_fab": 25.0,
        "T_set": 180.0,
        "T_max": 180.0,
        "v": 150.0,
        "f_d": 20.0,
        "E_d": 3.0,
        "P_B": 0.0,
        "layer_thickness_um": 50.0,
        "N_f": 50000000000.0,
        "N_c": 30000.0,
        "N_iv": 500000.0,
        "N_TC": 10000.0,
        "N_on": 5000.0,
        "phi_R": 0.20,
    }
    for variable in (*spec.get("ext_vars", ()), *spec.get("int_vars", ())):
        if variable.get("enabled", True):
            drivers[variable["name"]] = float(variable["ref"])
    return drivers
