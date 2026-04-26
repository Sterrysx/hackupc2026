"""Bidirectional mapping between simulator component ids (C1..C6) and the
frontend's friendly ids/labels.

The simulator emits 6 components by code (C1..C6); the React app uses
domain-specific names (recoater_blade, nozzle_plate, etc.). One source of
truth here keeps backend snapshots aligned with `frontend/src/types/telemetry.ts`.

Health-status enums also differ:
- simulator/`Component.status()` emits OK / WARNING / CRITICAL / FAILED
- frontend `OperationalStatus` is FUNCTIONAL / DEGRADED / CRITICAL / FAILED
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ComponentInfo:
    sim_id: str          # "C1".."C6"
    frontend_id: str     # e.g. "recoater_blade"
    label: str           # human-readable name used in the UI
    subsystem: str       # "recoating" | "printhead" | "thermal"


COMPONENTS: tuple[ComponentInfo, ...] = (
    ComponentInfo("C1", "recoater_blade",   "Recoater blade",    "recoating"),
    ComponentInfo("C2", "recoater_motor",   "Recoater motor",    "recoating"),
    ComponentInfo("C3", "nozzle_plate",     "Nozzle plate",      "printhead"),
    # C4 is the firing-array thermal resistor inside the HP TIJ printhead —
    # it's part of the printhead assembly (paired with C3 in the 3D model
    # and the 2D schematic). The backend used to mis-classify it under
    # "thermal" alongside the heater/insulation; corrected to "printhead"
    # so the dashboard groups it with the nozzle plate.
    ComponentInfo("C4", "thermal_resistor", "Thermal resistor",  "printhead"),
    ComponentInfo("C5", "heating_element",  "Heating element",   "thermal"),
    ComponentInfo("C6", "insulation_panel", "Insulation panel",  "thermal"),
)

_BY_SIM: Mapping[str, ComponentInfo] = {c.sim_id: c for c in COMPONENTS}
_BY_FRONTEND: Mapping[str, ComponentInfo] = {c.frontend_id: c for c in COMPONENTS}


# Status mapping — simulator -> frontend OperationalStatus.
_STATUS_MAP: Mapping[str, str] = {
    "OK": "FUNCTIONAL",
    "WARNING": "DEGRADED",
    "CRITICAL": "CRITICAL",
    "FAILED": "FAILED",
}


def by_sim_id(sim_id: str) -> ComponentInfo:
    try:
        return _BY_SIM[sim_id]
    except KeyError as e:
        raise KeyError(f"unknown simulator component id: {sim_id!r}") from e


def by_frontend_id(frontend_id: str) -> ComponentInfo:
    try:
        return _BY_FRONTEND[frontend_id]
    except KeyError as e:
        raise KeyError(f"unknown frontend component id: {frontend_id!r}") from e


def map_status(sim_status: str) -> str:
    """Convert simulator status (OK/WARNING/CRITICAL/FAILED) to frontend
    OperationalStatus (FUNCTIONAL/DEGRADED/CRITICAL/FAILED)."""
    try:
        return _STATUS_MAP[sim_status]
    except KeyError as e:
        raise KeyError(f"unknown simulator status: {sim_status!r}") from e


def all_components() -> tuple[ComponentInfo, ...]:
    return COMPONENTS
