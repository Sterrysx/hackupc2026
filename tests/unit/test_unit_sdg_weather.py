"""Unit tests for the SDG weather pipeline (`sdg.weather.transform` and
`sdg.weather.real_weather`).

The transfer functions and date-handling helpers are pure — no external
dependencies. The end-to-end ``build_real_weather`` reads cached Open-Meteo
JSON from ``data/raw/`` so it's intentionally not exercised here (those
inputs are not guaranteed to ship in CI).

``build_projected_weather`` and ``load_lookup`` ARE testable in isolation
because they only need an in-memory ``real_df``.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sdg.weather import real_weather, transform


# ---------------------------------------------- transform.relabel_dates


def test_relabel_dates_default_shift_is_four_years():
    out = transform.relabel_dates(["2016-01-01", "2017-06-15"])
    assert out == ["2020-01-01", "2021-06-15"]


def test_relabel_dates_preserves_month_and_day():
    src = ["2018-02-28", "2020-12-31"]
    out = transform.relabel_dates(src, shift_years=4)
    assert all(o.split("-")[1:] == s.split("-")[1:] for o, s in zip(out, src))


def test_relabel_dates_supports_custom_shift():
    out = transform.relabel_dates(["2010-05-05"], shift_years=15)
    assert out == ["2025-05-05"]


# -------------------------------- transform.apply_transfer_functions


def _defaults() -> dict:
    return {
        "T_set": 25.0, "T_ext_ref": 20.0,
        "H_set": 50.0, "H_ext_ref": 50.0,
        "T_fab_clip": (18.0, 30.0),
        "H_fab_clip": (30.0, 70.0),
    }


def test_apply_transfer_functions_clips_extreme_temperature():
    """Feed a 100°C external temp; T_fab must clamp at the upper bound 30."""
    T_ext = np.asarray([100.0])
    H_ext = np.asarray([50.0])
    P_ext = np.asarray([1013.0])
    T_fab, _, _ = transform.apply_transfer_functions(
        T_ext, H_ext, P_ext, alpha_T=1.0, alpha_H=0.0, defaults=_defaults(),
    )
    assert T_fab[0] == 30.0


def test_apply_transfer_functions_clips_extreme_low_temperature():
    T_ext = np.asarray([-50.0])
    H_ext = np.asarray([50.0])
    P_ext = np.asarray([1013.0])
    T_fab, _, _ = transform.apply_transfer_functions(
        T_ext, H_ext, P_ext, alpha_T=1.0, alpha_H=0.0, defaults=_defaults(),
    )
    assert T_fab[0] == 18.0


def test_apply_transfer_functions_alpha_zero_yields_setpoint():
    """alpha_T = 0 -> T_fab = T_set (the indoor setpoint), regardless of T_ext."""
    T_ext = np.asarray([5.0, 25.0, 45.0])
    H_ext = np.asarray([10.0, 50.0, 90.0])
    P_ext = np.asarray([1010.0, 1013.0, 1020.0])
    T_fab, _, _ = transform.apply_transfer_functions(
        T_ext, H_ext, P_ext, alpha_T=0.0, alpha_H=0.0, defaults=_defaults(),
    )
    assert (T_fab == 25.0).all()


def test_apply_transfer_functions_pressure_passthrough_with_copy():
    P_ext = np.asarray([1010.0, 1013.0, 1020.0])
    _, _, P_fab = transform.apply_transfer_functions(
        np.zeros(3), np.zeros(3), P_ext,
        alpha_T=0.0, alpha_H=0.0, defaults=_defaults(),
    )
    # Values equal the source...
    assert np.array_equal(P_fab, P_ext)
    # ...but the array is a copy, not a shared reference.
    assert P_fab is not P_ext


# ------------------------------- real_weather._safe_shift_back


def test_safe_shift_back_normal_date():
    src = date(2026, 5, 15)
    assert real_weather._safe_shift_back(src) == date(2016, 5, 15)


def test_safe_shift_back_handles_feb_29_leap_to_non_leap():
    """Feb 29 of a leap year, shifted back 10 years, must clamp to Feb 28
    of the resulting non-leap year (calendar-correct)."""
    src = date(2024, 2, 29)
    out = real_weather._safe_shift_back(src)
    assert out == date(2014, 2, 28)


def test_safe_shift_back_preserves_year_offset_of_ten():
    """Implementation hardcodes a 10-year shift back."""
    src = date(2030, 7, 1)
    out = real_weather._safe_shift_back(src)
    assert out.year == src.year - 10
    assert out.month == src.month
    assert out.day == src.day


# ------------------------------- real_weather.build_projected_weather


def test_build_projected_weather_produces_correct_row_count_per_city():
    """Source spans 2016-2025 (10 years). The projected DataFrame covers
    2026-2035 (also 10 years = 3653 days incl. leap days). With 1 city in
    the source, the projected frame must have exactly 3653 rows."""
    days_2016_2025 = pd.date_range("2016-01-01", "2025-12-31", freq="D").date
    real_df = pd.DataFrame({
        "city": ["alpha"] * len(days_2016_2025),
        "date": pd.to_datetime(days_2016_2025),
        "T_fab": np.full(len(days_2016_2025), 25.0, dtype=np.float32),
        "H_fab": np.full(len(days_2016_2025), 50.0, dtype=np.float32),
        "P_fab": np.full(len(days_2016_2025), 1013.0, dtype=np.float32),
    })
    proj = real_weather.build_projected_weather(real_df)
    expected_days = len(pd.date_range("2026-01-01", "2035-12-31", freq="D"))
    assert len(proj) == expected_days  # 3653
    assert proj["city"].unique().tolist() == ["alpha"]
    # First and last dates fall in the projected window.
    assert proj["date"].min().year == 2026
    assert proj["date"].max().year == 2035


def test_build_projected_weather_carries_values_from_source():
    """A unique source row should appear in the projected output for the
    corresponding cycle date (any 2026 day shifted back 10 years lands on
    that 2016 day)."""
    days = pd.date_range("2016-01-01", "2025-12-31", freq="D").date
    real_df = pd.DataFrame({
        "city": ["alpha"] * len(days),
        "date": pd.to_datetime(days),
        "T_fab": np.arange(len(days), dtype=np.float32),
        "H_fab": np.full(len(days), 50.0, dtype=np.float32),
        "P_fab": np.full(len(days), 1013.0, dtype=np.float32),
    })
    proj = real_weather.build_projected_weather(real_df)
    # 2026-01-01 should map back to 2016-01-01, i.e. T_fab index 0.
    row = proj.loc[proj["date"] == pd.Timestamp("2026-01-01")].iloc[0]
    assert row["T_fab"] == pytest.approx(0.0)


# ------------------------------------------- real_weather.load_lookup


def test_load_lookup_round_trips_tiny_parquet(tmp_path):
    """Save a tiny parquet, load it, verify the {city: {date_iso: (T,H)}} shape."""
    df = pd.DataFrame({
        "city": ["alpha", "alpha", "beta"],
        "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-01"]),
        "T_fab": [22.5, 23.0, 18.0],
        "H_fab": [45.0, 47.0, 60.0],
        "P_fab": [1013.0, 1014.0, 1010.0],
    })
    parquet_path = tmp_path / "weather.parquet"
    df.to_parquet(parquet_path, compression="snappy", index=False)

    lookup = real_weather.load_lookup(parquet_path)

    # Outer dict keyed by city.
    assert set(lookup.keys()) == {"alpha", "beta"}
    # Inner dict keyed by ISO date string -> (T, H).
    assert lookup["alpha"]["2026-01-01"] == (pytest.approx(22.5), pytest.approx(45.0))
    assert lookup["alpha"]["2026-01-02"] == (pytest.approx(23.0), pytest.approx(47.0))
    assert lookup["beta"]["2026-01-01"] == (pytest.approx(18.0), pytest.approx(60.0))


def test_load_lookup_for_empty_parquet_returns_empty_dict(tmp_path):
    df = pd.DataFrame({
        "city": pd.Series([], dtype="object"),
        "date": pd.to_datetime(pd.Series([], dtype="object")),
        "T_fab": pd.Series([], dtype="float32"),
        "H_fab": pd.Series([], dtype="float32"),
        "P_fab": pd.Series([], dtype="float32"),
    })
    parquet_path = tmp_path / "empty.parquet"
    df.to_parquet(parquet_path, compression="snappy", index=False)

    lookup = real_weather.load_lookup(parquet_path)
    assert lookup == {}
