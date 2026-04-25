from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date as Date
from math import isinf
from typing import MutableMapping

import numpy as np

from sdg.core.component import Component
from sdg.core.degradation import compute_cross_factors, compute_lambda
from sdg.core.weather import get_drivers
from sdg.schema import COMPONENT_IDS

# Per-day cap on health drop. Above this is non-physical jitter.
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
    counters, components = _initial_state(components_cfg, alphas)
    rows: list[dict] = []
    start_date = dates[0]
    for current_date in dates:
        row, _, _ = _simulate_one_day(
            printer_id=printer_id,
            city_profile=city_profile,
            current_date=current_date,
            start_date=start_date,
            counters=counters,
            components=components,
            components_cfg=components_cfg,
            couplings_cfg=couplings_cfg,
            rng=rng,
            monthly_jobs=monthly_jobs,
            agent_action=None,
        )
        rows.append(row)
    return rows


class PrinterStepper:
    """Stateful one-day-at-a-time wrapper around the simulator inner loop.

    Lets an RL policy drive the simulator one tick at a time. The agent's
    optional ``agent_action`` argument to :meth:`step` *overrides* the
    tau-based preventive-maintenance rule for that day:

    - If a component's ``agent_action`` value is truthy, that component
      receives a preventive maintenance today (regardless of ``tau_nom_d``).
    - If it's falsy or missing, **no preventive** is performed today, even
      if the tau rule would normally trigger one.
    - Corrective failures (``H <= 0.1``) and the C5/C6 critical-pair safety
      rule still fire automatically — the agent can't suppress those.

    When ``agent_action is None`` the original tau-based rule applies, so a
    plain replay of the historical schedule is recoverable.

    Use as::

        stepper = PrinterStepper(printer_id=0, ...)
        for d in dates:
            row = stepper.step(d, agent_action={"C1": True, "C2": False, ...})
    """

    def __init__(
        self,
        *,
        printer_id: int,
        city_profile: Mapping,
        components_cfg: Mapping,
        couplings_cfg: Mapping,
        rng: np.random.Generator,
        monthly_jobs: float,
        alphas: Mapping[str, float],
    ) -> None:
        self.printer_id = int(printer_id)
        self.city_profile = city_profile
        self.components_cfg = components_cfg
        self.couplings_cfg = couplings_cfg
        self.rng = rng
        self.monthly_jobs = float(monthly_jobs)
        self.alphas = dict(alphas)
        self.counters, self.components = _initial_state(components_cfg, self.alphas)
        self._start_date: Date | None = None
        self._steps_taken: int = 0

    def step(
        self,
        current_date: Date,
        agent_action: Mapping[str, bool] | None = None,
    ) -> dict:
        """Advance the simulator by one day. Returns the row dict + events in info."""
        if self._start_date is None:
            self._start_date = current_date
        row, _maint, _failure = _simulate_one_day(
            printer_id=self.printer_id,
            city_profile=self.city_profile,
            current_date=current_date,
            start_date=self._start_date,
            counters=self.counters,
            components=self.components,
            components_cfg=self.components_cfg,
            couplings_cfg=self.couplings_cfg,
            rng=self.rng,
            monthly_jobs=self.monthly_jobs,
            agent_action=agent_action,
        )
        self._steps_taken += 1
        return row

    @property
    def steps_taken(self) -> int:
        return self._steps_taken

    @property
    def state_snapshot(self) -> dict[str, dict[str, float]]:
        """Lightweight read-only state — useful for building RL observations."""
        return {
            cid: {
                "H": float(c.H),
                "tau_mant_d": float(c.tau_mant_d),
                "L_d": float(c.L_d),
            }
            for cid, c in self.components.items()
        }


def apply_maintenance_and_safety(
    components: Mapping[str, Component],
    couplings_cfg: Mapping,
) -> tuple[dict[str, bool], dict[str, bool]]:
    maint_events = {component_id: False for component_id in COMPONENT_IDS}
    failure_events = {component_id: False for component_id in COMPONENT_IDS}

    for component_id in COMPONENT_IDS:
        component = components[component_id]
        tau_nom = float(component.spec["tau_nom_d"])
        if not isinf(tau_nom) and component.tau_mant_d >= tau_nom:
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


def apply_agent_maintenance(
    components: Mapping[str, Component],
    couplings_cfg: Mapping,
    agent_action: Mapping[str, bool],
) -> tuple[dict[str, bool], dict[str, bool]]:
    """Maintenance rule when an agent makes per-day decisions.

    - Preventive maintenance fires *only* for components with truthy ``agent_action``.
    - Corrective failures still fire automatically when ``H <= 0.1`` (the agent
      cannot suppress safety responses).
    - The C5/C6 critical-pair safety rule still applies.
    """
    maint_events = {component_id: False for component_id in COMPONENT_IDS}
    failure_events = {component_id: False for component_id in COMPONENT_IDS}

    for component_id in COMPONENT_IDS:
        if bool(agent_action.get(component_id, False)):
            maint_events[component_id] = components[component_id].apply_preventive()

    for component_id in COMPONENT_IDS:
        if components[component_id].H <= 0.1:
            failure_events[component_id] = components[component_id].apply_corrective()

    threshold = float(couplings_cfg.get("critical_threshold", 0.4))
    if components["C5"].H < threshold and components["C6"].H < threshold:
        target_id = "C5" if components["C5"].H <= components["C6"].H else "C6"
        failure_events[target_id] = components[target_id].apply_corrective()

    return maint_events, failure_events


def _initial_state(
    components_cfg: Mapping,
    alphas: Mapping[str, float],
) -> tuple[dict[str, int], dict[str, Component]]:
    counters: dict[str, int] = {"N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0}
    components = {
        component_id: Component(
            id=component_id,
            spec=components_cfg["components"][component_id],
            counters=counters,
            alpha=float(alphas[component_id]),
        )
        for component_id in COMPONENT_IDS
    }
    return counters, components


def _cascade_factor(h: float) -> float:
    """Soft cascade modulator: ~1.0 for healthy parts, climbing toward 2.0 only
    when the upstream is severely degraded.

    Replaces the legacy linear ``2 - H`` rule (which doubled the cascade as soon
    as H slipped past 0.5). Now ``f(1.0) = 1.0`` exactly and ``f(0.0) = 2.0``,
    with a quadratic ramp that keeps healthy/moderately-degraded upstreams from
    dragging their downstream neighbours into early failure.
    """
    return 1.0 + (1.0 - max(0.0, min(1.0, h))) ** 2


def _simulate_one_day(
    *,
    printer_id: int,
    city_profile: Mapping,
    current_date: Date,
    start_date: Date,
    counters: MutableMapping[str, int],
    components: MutableMapping[str, Component],
    components_cfg: Mapping,
    couplings_cfg: Mapping,
    rng: np.random.Generator,
    monthly_jobs: float,
    agent_action: Mapping[str, bool] | None,
) -> tuple[dict, dict[str, bool], dict[str, bool]]:
    """Single-day simulator step shared by ``run_printer`` and ``PrinterStepper``.

    ``components`` and ``counters`` are mutated in place. ``agent_action``
    selects between the original tau-based rule (None) and the agent-driven
    rule (any mapping).
    """
    process = components_cfg["process_constants"]

    weather_drivers = get_drivers(city_profile["name"], current_date)
    jobs_today = int(rng.poisson(float(monthly_jobs) / 30.0))
    _update_counters(counters, jobs_today, process, rng)

    c_p = float(process["c_p0"]) * _cascade_factor(components["C1"].H)
    q_demand = float(process["Q0"]) * _cascade_factor(components["C6"].H)
    drivers = _build_driver_namespace(weather_drivers, process, counters, c_p, q_demand)

    cross_factors = compute_cross_factors(components, couplings_cfg)
    lambda_values: dict[str, float] = {}
    for component_id in COMPONENT_IDS:
        component = components[component_id]
        lambda_i = compute_lambda(component, drivers, cross_factors[component_id])
        lambda_values[component_id] = lambda_i
        component.apply_degradation(min(lambda_i, MAX_DH_PER_DAY))

    if agent_action is None:
        maint_events, failure_events = apply_maintenance_and_safety(
            components, couplings_cfg
        )
    else:
        maint_events, failure_events = apply_agent_maintenance(
            components, couplings_cfg, agent_action
        )

    for component in components.values():
        component.advance_time(1.0)

    day = (current_date - start_date).days
    row = _row_dict(
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
    return row, maint_events, failure_events


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
        row[f"tau_{component_id}"] = components[component_id].tau_mant_d
    for component_id in COMPONENT_IDS:
        row[f"L_{component_id}"] = components[component_id].L_d
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
