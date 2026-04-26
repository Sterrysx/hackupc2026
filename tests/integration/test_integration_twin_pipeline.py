"""Integration test: snapshot -> forecast pipeline over the real parquet.

Exercises the full end-to-end data flow that backs the dashboard:
``Ai_Agent.twin_data.get_dataset`` -> ``twin_data.get_snapshot`` ->
``forecast.compute_forecasts``. No HTTP layer here — this proves the data
contract holds *before* it touches FastAPI.

Skipped cleanly when ``data/fleet_baseline.parquet`` is absent (CI image
without the dataset). Live LLM access is not required.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.agent import forecast, twin_data

# Match the frontend telemetry contract (`frontend/src/types/telemetry.ts`).
_VALID_STATUSES = {"FUNCTIONAL", "DEGRADED", "CRITICAL", "FAILED"}
_EXPECTED_DRIVER_KEYS = {
    "ambientTempC", "humidityPct", "contaminationPct",
    "loadPct", "maintenanceCoeff",
}
_EXPECTED_SNAPSHOT_KEYS = {
    "timestamp", "tick", "drivers", "components",
    "forecasts", "forecastHorizonDays",
}
_EXPECTED_FORECAST_KEYS = {
    "id", "predictedHealthIndex", "predictedStatus", "predictedMetrics",
    "daysUntilCritical", "daysUntilFailure", "rationale", "confidence",
}

_PARQUET_PATH = Path("data") / "train" / "fleet_baseline.parquet"


@pytest.fixture(scope="module")
def _ensure_dataset():
    """Skip the whole module on CI images without the simulator parquet."""
    if not _PARQUET_PATH.exists():
        pytest.skip(
            f"{_PARQUET_PATH} not found — integration tests require the "
            "Stage 1 simulator output."
        )
    twin_data.reset_cache()
    df = twin_data.get_dataset()
    assert not df.empty
    yield
    twin_data.reset_cache()


@pytest.fixture(scope="module")
def sample_combos(_ensure_dataset) -> list[tuple[str, int, int]]:
    """Three (city, printer, day) triples spanning early/mid/late history.

    Picked dynamically from whatever the parquet actually contains so the
    tests adapt to fleet regenerations without a code change.
    """
    cities = twin_data.list_cities()
    assert len(cities) >= 3, "need at least 3 cities to span samples"
    lo, hi = twin_data.day_range()
    days = (lo + 5, (lo + hi) // 2, hi - 5)
    combos: list[tuple[str, int, int]] = []
    for city, day in zip(cities[:3], days):
        printers = twin_data.list_printers(city)
        combos.append((city, printers[0], day))
    return combos


def test_snapshot_shape_matches_frontend_contract(sample_combos):
    """Every (city, printer, day) snapshot must satisfy the wire shape."""
    for city, printer_id, day in sample_combos:
        snap = twin_data.get_snapshot(city, printer_id, day)

        assert set(snap.keys()) == _EXPECTED_SNAPSHOT_KEYS, (
            f"{city}/{printer_id}/{day}: snapshot keys mismatch"
        )
        assert snap["tick"] == day
        assert "T" in snap["timestamp"]  # ISO 8601

        components = snap["components"]
        assert len(components) == 6, f"{city}/{printer_id}/{day}: not 6 components"
        for c in components:
            assert 0.0 <= c["healthIndex"] <= 1.0, (
                f"{c['id']}: healthIndex {c['healthIndex']} out of [0,1]"
            )
            assert c["status"] in _VALID_STATUSES, (
                f"{c['id']}: bogus status {c['status']!r}"
            )


def test_drivers_have_exactly_the_five_required_keys(sample_combos):
    """The drivers dict on every snapshot is the operator panel's 5-knob input."""
    for city, printer_id, day in sample_combos:
        snap = twin_data.get_snapshot(city, printer_id, day)
        drivers = snap["drivers"]
        assert set(drivers.keys()) == _EXPECTED_DRIVER_KEYS, (
            f"{city}/{printer_id}/{day}: driver keys {sorted(drivers.keys())} "
            f"!= expected {sorted(_EXPECTED_DRIVER_KEYS)}"
        )
        assert all(isinstance(v, float) for v in drivers.values())


def test_forecast_shape_and_bounds(sample_combos):
    """compute_forecasts must return 6 forecasts with all required keys
    and confidence/predictedHealthIndex in [0, 1]."""
    for city, printer_id, day in sample_combos:
        forecasts = forecast.compute_forecasts(city, printer_id, day)
        assert len(forecasts) == 6, (
            f"{city}/{printer_id}/{day}: forecast count {len(forecasts)} != 6"
        )

        for f in forecasts:
            missing = _EXPECTED_FORECAST_KEYS - set(f.keys())
            assert not missing, (
                f"{city}/{printer_id}/{day}/{f.get('id')}: forecast missing {missing}"
            )
            assert 0.0 <= f["predictedHealthIndex"] <= 1.0
            assert 0.0 <= f["confidence"] <= 1.0
            assert f["predictedStatus"] in _VALID_STATUSES
            # daysUntilCritical/Failure are nullable but must be non-negative when set.
            for k in ("daysUntilCritical", "daysUntilFailure"):
                v = f[k]
                if v is not None:
                    assert isinstance(v, (int, float)) and v >= 0.0


def test_forecast_ids_match_snapshot_ids(sample_combos):
    """The forecast list and snapshot.components list refer to the same 6
    components 1:1 by frontend id — no orphans on either side."""
    for city, printer_id, day in sample_combos:
        snap = twin_data.get_snapshot(city, printer_id, day)
        forecasts = forecast.compute_forecasts(city, printer_id, day)
        snap_ids = {c["id"] for c in snap["components"]}
        forecast_ids = {f["id"] for f in forecasts}
        assert snap_ids == forecast_ids, (
            f"{city}/{printer_id}/{day}: snapshot ids {snap_ids} "
            f"!= forecast ids {forecast_ids}"
        )


def test_active_path_is_one_of_the_two_known_dispatch_modes(_ensure_dataset):
    """The forecast module either runs the trained SSL/RUL head or the
    analytic fallback — never anything else."""
    path = forecast.active_path()
    assert path in {"ssl", "analytic"}, (
        f"unexpected forecast.active_path() result: {path!r}"
    )


def test_horizon_zero_forecast_equals_current_health(sample_combos):
    """Sanity check: with horizon_d=0 the analytic projection cannot decay
    health, so each forecast's predictedHealthIndex must equal the current
    snapshot value. This pins the Stage 2 contract: zero horizon is a
    no-op rather than introducing noise."""
    for city, printer_id, day in sample_combos:
        snap = twin_data.get_snapshot(city, printer_id, day, forecast_horizon_d=0.0)
        forecasts = forecast.compute_forecasts(city, printer_id, day, horizon_d=0.0)
        by_id_health = {c["id"]: c["healthIndex"] for c in snap["components"]}
        for f in forecasts:
            assert f["predictedHealthIndex"] == by_id_health[f["id"]], (
                f"{city}/{printer_id}/{day}/{f['id']}: horizon=0 forecast "
                f"{f['predictedHealthIndex']} != snapshot {by_id_health[f['id']]}"
            )
