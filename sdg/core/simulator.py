from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date as Date
from math import isinf

import numpy as np

from sdg.core.component import Component
from sdg.core.degradation import compute_cross_factors, compute_lambda
from sdg.core.weather import get_drivers
from sdg.schema import COMPONENT_IDS

HOURS_PER_DAY = 24.0
MAX_DH_PER_DAY = 1.2


def run_printer(
    printer_id: int,
    city_profile: Mapping,
    dates: Sequence[Date],
    components_cfg: Mapping,
    couplings_cfg: Mapping,
    rng: np.random.Generator,
    monthly_jobs: float,
    alphas: Mapping[str, float],
) -> list[dict]:
    """Return row dictionaries for one printer trajectory."""
    process = components_cfg["process_constants"]
    counters = {"N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0}
    components = {
        component_id: Component(
            id=component_id,
            spec=components_cfg["components"][component_id],
            counters=counters,
            alpha=float(alphas[component_id]),
        )
        for component_id in COMPONENT_IDS
    }

    rows: list[dict] = []
    start_date = dates[0]
    for current_date in dates:
        weather_drivers = get_drivers(city_profile["name"], current_date)
        jobs_today = int(rng.poisson(float(monthly_jobs) / 30.0))
        _update_counters(counters, jobs_today, process, rng)

        # Endogenous drivers use the pre-degradation health snapshot.
        c_p = float(process["c_p0"]) * (2.0 - components["C1"].H)
        q_demand = float(process["Q0"]) * (2.0 - components["C6"].H)
        drivers = _build_driver_namespace(weather_drivers, process, counters, c_p, q_demand)

        cross_factors = compute_cross_factors(components, couplings_cfg)
        lambda_values: dict[str, float] = {}
        for component_id in COMPONENT_IDS:
            component = components[component_id]
            lambda_i = compute_lambda(component, drivers, cross_factors[component_id])
            lambda_values[component_id] = lambda_i
            component.apply_degradation(min(lambda_i * HOURS_PER_DAY, MAX_DH_PER_DAY))

        maint_events, failure_events = apply_maintenance_and_safety(components, couplings_cfg)

        for component in components.values():
            component.advance_time(HOURS_PER_DAY)

        day = (current_date - start_date).days
        rows.append(
            _row_dict(
                printer_id=printer_id,
                city_profile=city_profile,
                current_date=current_date,
                day=day,
                weather_drivers=weather_drivers,
                c_p=c_p,
                q_demand=q_demand,
                jobs_today=jobs_today,
                components=components,
                counters=counters,
                lambda_values=lambda_values,
                maint_events=maint_events,
                failure_events=failure_events,
            )
        )
    return rows


def apply_maintenance_and_safety(
    components: Mapping[str, Component],
    couplings_cfg: Mapping,
) -> tuple[dict[str, bool], dict[str, bool]]:
    maint_events = {component_id: False for component_id in COMPONENT_IDS}
    failure_events = {component_id: False for component_id in COMPONENT_IDS}

    for component_id in COMPONENT_IDS:
        component = components[component_id]
        tau_nom = float(component.spec["tau_nom_h"])
        if not isinf(tau_nom) and component.tau_mant_h >= tau_nom:
            maint_events[component_id] = component.apply_preventive()

    for component_id in COMPONENT_IDS:
        component = components[component_id]
        if component.H <= 0.1:
            failure_events[component_id] = component.apply_corrective()

    threshold = float(couplings_cfg.get("critical_threshold", 0.4))
    if components["C5"].H < threshold and components["C6"].H < threshold:
        target_id = "C5" if components["C5"].H <= components["C6"].H else "C6"
        failure_events[target_id] = components[target_id].apply_corrective()

    return maint_events, failure_events


def _update_counters(
    counters: dict[str, int],
    jobs_today: int,
    process: Mapping,
    rng: np.random.Generator,
) -> None:
    counters["N_f"] += jobs_today * int(round(float(process["fires_per_job"])))
    counters["N_c"] += jobs_today * int(process["layers_per_job"])
    counters["N_TC"] += jobs_today
    if jobs_today > 0:
        counters["N_on"] += int(rng.integers(1, 3))


def _build_driver_namespace(
    weather_drivers: Mapping[str, float],
    process: Mapping,
    counters: Mapping[str, int],
    c_p: float,
    q_demand: float,
) -> dict[str, float]:
    return {
        "T": float(weather_drivers["ambient_temp_c"]),
        "H": float(weather_drivers["humidity_pct"]),
        "c_p": float(c_p),
        "Q": float(q_demand),
        "T_fab": float(process["T_fab"]),
        "T_set": float(process["T_set"]),
        "T_max": float(process.get("T_max", process["T_set"])),
        "v": float(process["v"]),
        "f_d": float(process["f_d"]),
        "E_d": float(process["E_d"]),
        "P_B": float(process["P_B"]),
        "layer_thickness_um": float(process["layer_thickness_um"]),
        "N_f": float(counters["N_f"]),
        "N_c": float(counters["N_c"]),
        "N_iv": float(counters["N_c"]),
        "N_TC": float(counters["N_TC"]),
        "N_on": float(counters["N_on"]),
        "phi_R": float(process["phi_R"]),
    }


def _row_dict(
    *,
    printer_id: int,
    city_profile: Mapping,
    current_date: Date,
    day: int,
    weather_drivers: Mapping[str, float],
    c_p: float,
    q_demand: float,
    jobs_today: int,
    components: Mapping[str, Component],
    counters: Mapping[str, int],
    lambda_values: Mapping[str, float],
    maint_events: Mapping[str, bool],
    failure_events: Mapping[str, bool],
) -> dict:
    row = {
        "printer_id": printer_id,
        "city": city_profile["name"],
        "climate_zone": city_profile["climate_zone"],
        "date": current_date,
        "day": day,
        "ambient_temp_c": weather_drivers["ambient_temp_c"],
        "humidity_pct": weather_drivers["humidity_pct"],
        "dust_concentration": c_p,
        "Q_demand": q_demand,
        "jobs_today": jobs_today,
    }
    for component_id in COMPONENT_IDS:
        row[f"H_{component_id}"] = components[component_id].H
    for component_id in COMPONENT_IDS:
        row[f"status_{component_id}"] = components[component_id].status()
    for component_id in COMPONENT_IDS:
        row[f"tau_{component_id}"] = components[component_id].tau_mant_h
    for component_id in COMPONENT_IDS:
        row[f"L_{component_id}"] = components[component_id].L_h
    row.update(
        {
            "N_f": counters["N_f"],
            "N_c": counters["N_c"],
            "N_TC": counters["N_TC"],
            "N_on": counters["N_on"],
        }
    )
    for component_id in COMPONENT_IDS:
        row[f"lambda_{component_id}"] = lambda_values[component_id]
    for component_id in COMPONENT_IDS:
        row[f"maint_{component_id}"] = maint_events[component_id]
    for component_id in COMPONENT_IDS:
        row[f"failure_{component_id}"] = failure_events[component_id]
    return row
