"""Unit tests for sdg.weather.transform — pure functions only, no network."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.simulator.weather.transform import (
    apply_transfer_functions,
    build_city_frame,
    relabel_dates,
)


DEFAULTS = {
    "T_set": 22.0,
    "T_ext_ref": 20.0,
    "H_set": 45.0,
    "H_ext_ref": 60.0,
    "T_fab_clip": [18.0, 30.0],
    "H_fab_clip": [30.0, 70.0],
}


# ---------------------------------------------------------------------------
# relabel_dates
# ---------------------------------------------------------------------------


def test_relabel_basic_shift():
    out = relabel_dates(["2016-01-01", "2025-12-31"], shift_years=4)
    assert out == ["2020-01-01", "2029-12-31"]


def test_relabel_preserves_leap_years():
    leap_in = ["2016-02-29", "2020-02-29", "2024-02-29"]
    leap_out = relabel_dates(leap_in, shift_years=4)
    assert leap_out == ["2020-02-29", "2024-02-29", "2028-02-29"]


def test_relabel_length_preserved():
    full_range = pd.date_range("2016-01-01", "2025-12-31", freq="D")
    src = [d.strftime("%Y-%m-%d") for d in full_range]
    out = relabel_dates(src, shift_years=4)
    assert len(out) == len(src) == 3653


def test_relabel_zero_shift_is_identity():
    src = ["2016-03-15", "2023-07-04"]
    assert relabel_dates(src, shift_years=0) == src


# ---------------------------------------------------------------------------
# apply_transfer_functions
# ---------------------------------------------------------------------------


def _arr(x):
    return np.asarray([x], dtype=np.float64)


def test_T_fab_at_reference_returns_setpoint():
    T_fab, _, _ = apply_transfer_functions(
        _arr(20.0), _arr(60.0), _arr(1013.0),
        alpha_T=0.10, alpha_H=0.35, defaults=DEFAULTS,
    )
    assert T_fab[0] == pytest.approx(22.0)


def test_T_fab_singapore_hot_no_clip():
    # T_ext = 40, alpha_T = 0.10  ->  22 + 0.10 * (40 - 20) = 24.0
    T_fab, _, _ = apply_transfer_functions(
        _arr(40.0), _arr(80.0), _arr(1011.0),
        alpha_T=0.10, alpha_H=0.35, defaults=DEFAULTS,
    )
    assert T_fab[0] == pytest.approx(24.0)


def test_T_fab_moscow_extreme_cold_clipped_low():
    # T_ext = -25, alpha_T = 0.15  ->  22 + 0.15 * (-45) = 15.25 -> clip to 18.0
    T_fab, _, _ = apply_transfer_functions(
        _arr(-25.0), _arr(70.0), _arr(997.0),
        alpha_T=0.15, alpha_H=0.25, defaults=DEFAULTS,
    )
    assert T_fab[0] == pytest.approx(18.0)


def test_T_fab_extreme_heat_clipped_high():
    # alpha_T = 0.15, T_ext = 80  ->  22 + 0.15 * 60 = 31.0 -> clip to 30.0
    T_fab, _, _ = apply_transfer_functions(
        _arr(80.0), _arr(60.0), _arr(1013.0),
        alpha_T=0.15, alpha_H=0.25, defaults=DEFAULTS,
    )
    assert T_fab[0] == pytest.approx(30.0)


def test_H_fab_dubai_arid():
    # H_ext = 15, alpha_H = 0.20  ->  45 + 0.20 * (-45) = 36.0
    _, H_fab, _ = apply_transfer_functions(
        _arr(35.0), _arr(15.0), _arr(1013.0),
        alpha_T=0.12, alpha_H=0.20, defaults=DEFAULTS,
    )
    assert H_fab[0] == pytest.approx(36.0)


def test_H_fab_mumbai_monsoon_no_clip():
    # H_ext = 95, alpha_H = 0.40  ->  45 + 0.40 * 35 = 59.0
    _, H_fab, _ = apply_transfer_functions(
        _arr(30.0), _arr(95.0), _arr(1012.0),
        alpha_T=0.13, alpha_H=0.40, defaults=DEFAULTS,
    )
    assert H_fab[0] == pytest.approx(59.0)


def test_H_fab_clipped_high():
    # Force above 70: alpha_H=1.0, H_ext=200  ->  45 + 1.0 * 140 = 185 -> clip to 70.0
    _, H_fab, _ = apply_transfer_functions(
        _arr(25.0), _arr(200.0), _arr(1013.0),
        alpha_T=0.10, alpha_H=1.0, defaults=DEFAULTS,
    )
    assert H_fab[0] == pytest.approx(70.0)


def test_P_fab_passthrough():
    P_in = np.array([780.0, 1013.0, 1035.0], dtype=np.float64)
    _, _, P_fab = apply_transfer_functions(
        np.zeros(3), np.zeros(3), P_in,
        alpha_T=0.10, alpha_H=0.30, defaults=DEFAULTS,
    )
    np.testing.assert_array_equal(P_fab, P_in)


# ---------------------------------------------------------------------------
# build_city_frame
# ---------------------------------------------------------------------------


def _fake_payload(n: int = 5) -> dict:
    dates = pd.date_range("2016-06-01", periods=n, freq="D").strftime("%Y-%m-%d").tolist()
    rng = np.random.default_rng(seed=42)
    return {
        "daily": {
            "time": dates,
            "temperature_2m_mean": rng.uniform(20.0, 30.0, n).tolist(),
            "relative_humidity_2m_mean": rng.uniform(40.0, 80.0, n).tolist(),
            "surface_pressure_mean": rng.uniform(1005.0, 1020.0, n).tolist(),
        }
    }


def test_build_city_frame_schema():
    df = build_city_frame(
        city_key="singapore",
        raw=_fake_payload(),
        alpha_T=0.10,
        alpha_H=0.35,
        defaults=DEFAULTS,
        shift_years=4,
    )
    assert list(df.columns) == [
        "city", "date", "T_ext", "H_ext", "P_ext", "T_fab", "H_fab", "P_fab",
    ]
    assert (df["city"] == "singapore").all()
    assert df["T_fab"].dtype == np.float32
    assert df["P_fab"].dtype == np.float32


def test_build_city_frame_relabels_dates():
    df = build_city_frame(
        city_key="dubai",
        raw=_fake_payload(),
        alpha_T=0.12,
        alpha_H=0.20,
        defaults=DEFAULTS,
        shift_years=4,
    )
    # 2016-06-01 + 4 years = 2020-06-01
    assert df["date"].iloc[0] == pd.Timestamp("2020-06-01")
    assert df["date"].iloc[-1] == pd.Timestamp("2020-06-05")


def test_build_city_frame_length_matches_payload():
    raw = _fake_payload(n=12)
    df = build_city_frame(
        city_key="barcelona",
        raw=raw,
        alpha_T=0.08,
        alpha_H=0.18,
        defaults=DEFAULTS,
        shift_years=4,
    )
    assert len(df) == 12


def test_build_city_frame_validates_array_lengths():
    raw = {
        "daily": {
            "time": ["2016-01-01", "2016-01-02"],
            "temperature_2m_mean": [10.0, 11.0],
            "relative_humidity_2m_mean": [70.0],   # mismatched length
            "surface_pressure_mean": [1013.0, 1014.0],
        }
    }
    with pytest.raises(ValueError, match="length mismatch"):
        build_city_frame(
            city_key="bad",
            raw=raw,
            alpha_T=0.10,
            alpha_H=0.30,
            defaults=DEFAULTS,
            shift_years=4,
        )
