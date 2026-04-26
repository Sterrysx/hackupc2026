"""Pure transform functions: date relabeling + climate transfer functions.

Implements the formulas in `climate_location_module.md` §2.1, §3.1, §4.1:

    T_fab = clip(T_set + alpha_T * (T_ext - T_ext_ref),  18, 30)
    H_fab = clip(H_set + alpha_H * (H_ext - H_ext_ref),  30, 70)
    P_fab = P_ext            (no indoor control of pressure)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def relabel_dates(dates: list[str], shift_years: int = 4) -> list[str]:
    """Shift each YYYY-MM-DD by +shift_years (string-level, no calendar math).

    A multiple-of-4 shift preserves the leap-year structure (2016->2020,
    2020->2024, etc.). Other shifts are accepted but the caller is
    responsible for ensuring the input has no Feb-29 entries that land on a
    non-leap year.
    """
    out: list[str] = []
    for d in dates:
        y, m, day = d.split("-")
        out.append(f"{int(y) + shift_years:04d}-{m}-{day}")
    return out


def apply_transfer_functions(
    T_ext: np.ndarray,
    H_ext: np.ndarray,
    P_ext: np.ndarray,
    alpha_T: float,
    alpha_H: float,
    defaults: dict,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    T_set = defaults["T_set"]
    T_ext_ref = defaults["T_ext_ref"]
    H_set = defaults["H_set"]
    H_ext_ref = defaults["H_ext_ref"]
    T_lo, T_hi = defaults["T_fab_clip"]
    H_lo, H_hi = defaults["H_fab_clip"]

    T_fab = np.clip(T_set + alpha_T * (T_ext - T_ext_ref), T_lo, T_hi)
    H_fab = np.clip(H_set + alpha_H * (H_ext - H_ext_ref), H_lo, H_hi)
    P_fab = P_ext.copy()
    return T_fab, H_fab, P_fab


def build_city_frame(
    city_key: str,
    raw: dict,
    alpha_T: float,
    alpha_H: float,
    defaults: dict,
    shift_years: int = 4,
) -> pd.DataFrame:
    daily = raw["daily"]
    dates_src = list(daily["time"])
    T_ext = np.asarray(daily["temperature_2m_mean"], dtype=np.float64)
    H_ext = np.asarray(daily["relative_humidity_2m_mean"], dtype=np.float64)
    P_ext = np.asarray(daily["surface_pressure_mean"], dtype=np.float64)

    if not (len(dates_src) == len(T_ext) == len(H_ext) == len(P_ext)):
        raise ValueError(
            f"{city_key}: array length mismatch in Open-Meteo payload "
            f"(time={len(dates_src)}, T={len(T_ext)}, H={len(H_ext)}, P={len(P_ext)})"
        )

    dates_tgt = relabel_dates(dates_src, shift_years=shift_years)
    T_fab, H_fab, P_fab = apply_transfer_functions(
        T_ext, H_ext, P_ext, alpha_T, alpha_H, defaults
    )

    return pd.DataFrame(
        {
            "city": city_key,
            "date": pd.to_datetime(dates_tgt),
            "T_ext": T_ext.astype(np.float32),
            "H_ext": H_ext.astype(np.float32),
            "P_ext": P_ext.astype(np.float32),
            "T_fab": T_fab.astype(np.float32),
            "H_fab": H_fab.astype(np.float32),
            "P_fab": P_fab.astype(np.float32),
        }
    )
