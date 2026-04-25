"""Tests for Ai_Agent/component_map.py — the C1..C6 ↔ frontend id mapping."""
import pytest

from Ai_Agent.component_map import (
    COMPONENTS,
    all_components,
    by_frontend_id,
    by_sim_id,
    map_status,
)
from sdg.schema import COMPONENT_IDS


def test_six_components_aligned_with_simulator():
    assert len(COMPONENTS) == 6
    sim_ids = tuple(c.sim_id for c in COMPONENTS)
    assert sim_ids == COMPONENT_IDS  # ("C1", ..., "C6")


def test_frontend_ids_are_unique_and_match_telemetry_contract():
    frontend_ids = {c.frontend_id for c in COMPONENTS}
    expected = {
        "recoater_blade", "recoater_motor",
        "nozzle_plate",
        "thermal_resistor", "heating_element", "insulation_panel",
    }
    assert frontend_ids == expected


def test_subsystems_partition_components():
    by_subsystem: dict[str, list[str]] = {}
    for c in COMPONENTS:
        by_subsystem.setdefault(c.subsystem, []).append(c.sim_id)
    assert by_subsystem["recoating"] == ["C1", "C2"]
    assert by_subsystem["printhead"] == ["C3"]
    assert by_subsystem["thermal"] == ["C4", "C5", "C6"]


def test_round_trip_sim_to_frontend_and_back():
    for c in COMPONENTS:
        assert by_sim_id(c.sim_id).frontend_id == c.frontend_id
        assert by_frontend_id(c.frontend_id).sim_id == c.sim_id


def test_unknown_ids_raise():
    with pytest.raises(KeyError):
        by_sim_id("C99")
    with pytest.raises(KeyError):
        by_frontend_id("nonexistent")


def test_status_mapping_covers_all_sim_states():
    assert map_status("OK") == "FUNCTIONAL"
    assert map_status("WARNING") == "DEGRADED"
    assert map_status("CRITICAL") == "CRITICAL"
    assert map_status("FAILED") == "FAILED"


def test_status_mapping_rejects_unknown():
    with pytest.raises(KeyError):
        map_status("BROKEN")


def test_all_components_returns_full_tuple():
    assert all_components() == COMPONENTS
