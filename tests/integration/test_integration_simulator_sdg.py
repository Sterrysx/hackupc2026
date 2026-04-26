"""Integration test: SDG simulator end-to-end on a small fleet.

Builds a 5-printer x 30-day fleet using ``sdg.core.simulator.run_printer``
with the real config files in ``sdg/config/``. No parquet I/O on disk;
no weather lookup either — the simulator falls back to the synthetic
cosine model from ``cities.yaml`` whenever ``_REAL_LOOKUP`` is unset, and
that's exactly the path we want to exercise here so the tests stay
self-contained.

After the simulation runs, ``sdg.schema.table_from_rows`` is exercised on
the row stream to prove the Arrow schema contract still holds.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pyarrow as pa
import pytest

from backend.simulator.core.simulator import run_printer
from backend.simulator.core.weather import clear_real_lookup
from backend.simulator.generate import load_configs
from backend.simulator.schema import COMPONENT_IDS, RAW_SCHEMA, raw_column_names, table_from_rows

_FLEET_SIZE = 5
_DAYS = 30
_VALID_STATUSES = {"OK", "WARNING", "CRITICAL", "FAILED"}


@pytest.fixture(scope="module")
def configs():
    """Load YAML configs once per module — these don't change between tests."""
    return load_configs()


@pytest.fixture(scope="module")
def fleet_rows(configs) -> list[list[dict]]:
    """Return one list[dict] of rows per simulated printer.

    Uses ``np.random.default_rng(0)`` and a fresh weather lookup for full
    determinism. Each printer gets a different RNG seed so we don't end up
    with five identical trajectories.
    """
    components_cfg, couplings_cfg, cities_cfg = configs
    # Defensive: if a previous test populated the real-weather lookup, the
    # simulator would short-circuit our synthetic path. Clear it.
    clear_real_lookup()

    city_profile = cities_cfg["cities"][0]  # singapore — deterministic, real entry
    dates = [date(2026, 1, 1) + timedelta(days=d) for d in range(_DAYS)]

    fleets: list[list[dict]] = []
    for printer_id in range(_FLEET_SIZE):
        rng = np.random.default_rng(printer_id)
        rows = run_printer(
            printer_id=printer_id,
            city_profile=city_profile,
            dates=dates,
            components_cfg=components_cfg,
            couplings_cfg=couplings_cfg,
            rng=rng,
            monthly_jobs=12.0,  # accepted for API compat; unused by simulator
            alphas={cid: 1.0 for cid in COMPONENT_IDS},
        )
        fleets.append(rows)
    yield fleets
    clear_real_lookup()


def test_every_row_has_full_raw_column_set(fleet_rows):
    """Each row dict must contain every column declared in ``RAW_SCHEMA``."""
    expected = set(raw_column_names())
    for printer_idx, rows in enumerate(fleet_rows):
        assert len(rows) == _DAYS, f"printer {printer_idx}: {len(rows)} rows != {_DAYS}"
        for day_idx, row in enumerate(rows):
            missing = expected - set(row.keys())
            assert not missing, (
                f"printer {printer_idx} day {day_idx}: missing columns {missing}"
            )


def test_health_indices_stay_in_unit_interval(fleet_rows):
    """``H_C1..H_C6`` must always be in [0, 1] — the simulator clamps but
    we re-verify because a regression elsewhere would silently break the
    downstream forecast layer (which assumes the same range)."""
    for printer_idx, rows in enumerate(fleet_rows):
        for day_idx, row in enumerate(rows):
            for cid in COMPONENT_IDS:
                h = float(row[f"H_{cid}"])
                assert 0.0 <= h <= 1.0, (
                    f"printer {printer_idx} day {day_idx} {cid}: "
                    f"health {h} outside [0,1]"
                )


def test_statuses_are_one_of_the_four_simulator_categories(fleet_rows):
    """status_C1..status_C6 must be in the simulator status enum."""
    for rows in fleet_rows:
        for row in rows:
            for cid in COMPONENT_IDS:
                status = row[f"status_{cid}"]
                assert status in _VALID_STATUSES, (
                    f"unexpected status {status!r} for {cid}"
                )


def test_daily_print_hours_are_non_negative(fleet_rows):
    """Workload sampling is Gamma(2, 2) — strictly non-negative."""
    for rows in fleet_rows:
        for row in rows:
            assert float(row["daily_print_hours"]) >= 0.0


def test_cumulative_print_hours_is_monotonically_non_decreasing(fleet_rows):
    """``cumulative_print_hours`` is a running sum; asserting it can never
    drop catches both an off-by-one and a "reset on failure" regression in
    one shot."""
    for printer_idx, rows in enumerate(fleet_rows):
        prev = 0.0
        for day_idx, row in enumerate(rows):
            cum = float(row["cumulative_print_hours"])
            assert cum >= prev - 1e-9, (
                f"printer {printer_idx} day {day_idx}: "
                f"cumulative {cum} < previous {prev}"
            )
            prev = cum


def test_table_from_rows_matches_raw_schema(fleet_rows):
    """``sdg.schema.table_from_rows`` must accept the simulator's raw row
    stream and produce a ``pa.Table`` whose schema equals ``RAW_SCHEMA``.

    This is the contract that the parquet writer in ``sdg.generate`` relies
    on; if it ever breaks the dataset on disk goes corrupt silently."""
    rows = fleet_rows[0]
    table = table_from_rows(rows, include_rul=False)
    assert isinstance(table, pa.Table)
    assert table.num_rows == _DAYS
    assert table.schema.equals(RAW_SCHEMA, check_metadata=False), (
        "table_from_rows produced a schema that doesn't match RAW_SCHEMA"
    )


def test_table_from_rows_passes_arrow_validation(fleet_rows):
    """Beyond schema equality, the produced Arrow table must self-validate
    (``Table.validate(full=True)`` catches dictionary-encoding issues that
    plain schema comparison misses)."""
    rows = fleet_rows[0]
    table = table_from_rows(rows, include_rul=False)
    # `table_from_rows` already calls validate(full=True) internally; doing
    # it again here makes the test fail loudly if that internal call is
    # ever weakened to validate(full=False).
    table.validate(full=True)
