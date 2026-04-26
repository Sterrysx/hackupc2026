"""Stage 2 forecast layer.

Returns a `ComponentForecast`-shaped list (matching the frontend telemetry
contract) for a single (city, printer, day) snapshot.

Two execution paths share one output shape:

  * **Analytic projection** (always available): uses the simulator's own
    per-day hazard rate ``lambda`` to extrapolate health forward over a
    configurable horizon. This is what runs when the Stage 2 SSL head
    isn't on disk.

  * **SSL + RUL head** (auto-detected): when
    ``ml_models/02_ssl/models/rul_head_ssl.pt`` and the SSL encoder are
    both present, the forecast module loads them once and predicts a
    per-component remaining-useful-life (in days) from a 360-day window of
    telemetry. The predicted RUL is then mapped onto the same
    ``daysUntilCritical`` / ``daysUntilFailure`` /
    ``predictedHealthIndex`` keys.

The frontend never needs to care which one produced a forecast.

UNIT CONTRACT: every time field on the wire is in **days**. There is no
hour-based or minute-based field anywhere on this layer.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from Ai_Agent import twin_data
from Ai_Agent.component_map import COMPONENTS, map_status
from Ai_Agent.derived_metrics import predicted_metrics
from sdg.schema import COMPONENT_IDS

logger = logging.getLogger(__name__)

DEFAULT_HORIZON_D = twin_data.DEFAULT_FORECAST_HORIZON_D

# Health thresholds — match `Component.status()` in `sdg/core/component.py`.
H_FAILED = 0.1
H_CRITICAL = 0.4
H_WARNING = 0.7

# Below this hazard rate, the part isn't measurably degrading on any
# operational timescale; emitting a multi-decade ETA is just numerical
# noise (a tiny float division by zero). Collapse to None instead.
# 2.4e-4 per day == ~1e-5 per hour, the legacy floor.
_LAMBDA_OPERATIONAL_FLOOR = 2.4e-4

# Outer horizon (in days): long enough that we expose the model's full
# predictive range, short enough to still kill numerical-instability
# infinities. The frontend decides URGENCY by colour-coding the ETA, so
# the backend should hand back the honest analytical answer.
_OPERATIONAL_HORIZON_D = 5 * 365   # ~5 years
_CRITICAL_HORIZON_D    = 2 * 365   # ~2 years

# Stage 2 artefact paths. The encoder + scaler come from `01_pretrain.ipynb`;
# the RUL head comes from `02_finetune_rul.ipynb` (or
# `ml_models/02_ssl/train_rul_head.py`).
_SSL_DIR = Path("ml_models") / "02_ssl" / "models"
_RUL_HEAD_PATH = _SSL_DIR / "rul_head_ssl.pt"
_SSL_ENCODER_PATH = _SSL_DIR / "ssl_encoder.pt"
_SSL_CONFIG_PATH = _SSL_DIR / "ssl_config.json"
_FEATURE_SCALER_PATH = _SSL_DIR / "feature_scaler.npz"

# Same RUL clip used at training time. Predictions are scaled by this
# factor to convert from the [0, 1] regression output to days.
_RUL_CLIP_DAYS = 365.0


def _has_rul_head() -> bool:
    return all(
        p.is_file()
        for p in (_RUL_HEAD_PATH, _SSL_ENCODER_PATH, _SSL_CONFIG_PATH, _FEATURE_SCALER_PATH)
    )


# ----------------------------------------------------- model lazy loader


class _ModelBundle:
    """Holds the trained PatchTST model + matching feature scaler.

    Loaded on first forecast that needs it; reused for every subsequent
    request. Thread-safe under the FastAPI worker pool.
    """

    def __init__(self) -> None:
        import json

        import torch

        from ml_models.lib.features import build_feature_matrix  # noqa: F401 (validates import)

        cfg = json.loads(_SSL_CONFIG_PATH.read_text())
        patch_cfg_dict = cfg["patch_cfg"]
        train_cfg = cfg["train_cfg"]

        from transformers import PatchTSTConfig, PatchTSTForRegression

        patch_cfg = PatchTSTConfig(**patch_cfg_dict)
        patch_cfg.num_targets = len(COMPONENT_IDS)
        patch_cfg.prediction_length = 1
        patch_cfg.use_cls_token = False
        model = PatchTSTForRegression(patch_cfg)

        state = torch.load(_RUL_HEAD_PATH, map_location="cpu", weights_only=True)
        model.load_state_dict(state, strict=False)
        model.eval()

        scaler = np.load(_FEATURE_SCALER_PATH, allow_pickle=True)

        self.torch = torch
        self.model = model
        self.context_length = int(train_cfg["context_length"])
        self.channel_mean = scaler["mean"].astype(np.float32)
        self.channel_std = scaler["std"].astype(np.float32)
        # 37 input channels — order set by `build_feature_matrix.base_feature_columns`.
        self.feature_cols: list[str] = list(scaler.get("feature_cols", []))
        if not self.feature_cols:
            from ml_models.lib.features import base_feature_columns
            self.feature_cols = base_feature_columns()


_BUNDLE: _ModelBundle | None = None
_BUNDLE_LOCK = threading.Lock()
_BUNDLE_LOAD_FAILED = False


def _get_bundle() -> _ModelBundle | None:
    """Return the loaded model bundle, or ``None`` if loading failed once.

    The first failure is sticky for the process — we don't want a million
    log lines on every tick if torch is broken on this host.
    """
    global _BUNDLE, _BUNDLE_LOAD_FAILED
    if _BUNDLE is not None:
        return _BUNDLE
    if _BUNDLE_LOAD_FAILED:
        return None
    with _BUNDLE_LOCK:
        if _BUNDLE is not None:
            return _BUNDLE
        if _BUNDLE_LOAD_FAILED:
            return None
        try:
            _BUNDLE = _ModelBundle()
            logger.info("Stage 2 RUL head loaded — predictions now learned.")
            return _BUNDLE
        except Exception as exc:  # broad: torch / transformers / IO
            _BUNDLE_LOAD_FAILED = True
            logger.warning("Failed to load Stage 2 RUL head, falling back to analytic: %s", exc)
            return None


def reset_model_cache() -> None:
    """Clear the cached model — for tests that swap artefacts mid-process."""
    global _BUNDLE, _BUNDLE_LOAD_FAILED
    _BUNDLE = None
    _BUNDLE_LOAD_FAILED = False


# --------------------------------------------------------- analytic forecast


def _predicted_status_from_health(h: float) -> str:
    """Mirror simulator status bands — but emit frontend OperationalStatus."""
    if h <= H_FAILED:
        sim = "FAILED"
    elif h <= H_CRITICAL:
        sim = "CRITICAL"
    elif h <= H_WARNING:
        sim = "WARNING"
    else:
        sim = "OK"
    return map_status(sim)


def _days_to_threshold(h: float, lam_per_d: float, threshold: float) -> float | None:
    """How many days until ``h`` decays linearly past ``threshold``?

    Returns ``None`` when:
    - the threshold has already been crossed (``h <= threshold``), OR
    - the hazard rate is below the operational floor (no measurable
      degradation in any actionable window), OR
    - the projected ETA exceeds the operational horizon (so the operator
      sees "stable" instead of a misleading multi-year number).
    """
    if h <= threshold:
        return None
    if lam_per_d <= _LAMBDA_OPERATIONAL_FLOOR:
        return None
    days = (h - threshold) / lam_per_d
    horizon = (
        _CRITICAL_HORIZON_D if threshold == H_CRITICAL else _OPERATIONAL_HORIZON_D
    )
    if days > horizon:
        return None
    return float(days)


def _project_health(h: float, lam_per_d: float, horizon_d: float) -> float:
    """Project health linearly over ``horizon_d`` days using the per-day hazard.

    Clamps to the simulator's [0, 1] range. Mirrors
    ``Component.apply_degradation`` semantics over a partial day.
    """
    projected = h - lam_per_d * float(horizon_d)
    return max(0.0, min(1.0, projected))


def _confidence(lam_per_d: float, h: float) -> float:
    """Coarse confidence proxy.

    The analytic projection is most trustworthy when there's a real degradation
    signal (lambda > 0) and the part isn't already past the failure threshold.
    """
    if lam_per_d <= 1e-9:
        return 0.4
    if h <= H_FAILED:
        return 0.5
    return 0.6


def _dominant_driver_text(row: pd.Series) -> str:
    """Pick the driver currently most outside its comfortable range and
    describe it in a sentence that includes the actual reading + the ratio
    against its nominal value.

    Why this matters: the previous heuristic compared every driver against
    a hand-set anchor of 1.0 / 18.0 / 55.0 — but ``dust_concentration``
    sits around 50 nominally (it's ``c_p0`` in the simulator config), so
    ``dust / 1.0 ≈ 50`` always dwarfed every other ratio and the rationale
    string always read "elevated dust contamination at 50.x nominal" no
    matter what was actually wrong. Refs below match the simulator's true
    nominal values so the dominant driver is whichever one is **really**
    most extreme right now.
    """
    candidates: list[tuple[str, float, float, str]] = [
        # (label, current value, nominal reference, formatter for the value)
        ("ambient temperature", float(row["ambient_temp_c"]),     22.0, f"{float(row['ambient_temp_c']):.1f} °C"),
        ("humidity",            float(row["humidity_pct"]),       50.0, f"{float(row['humidity_pct']):.0f} %"),
        ("dust contamination",  float(row["dust_concentration"]), 50.0, f"{float(row['dust_concentration']):.0f}"),
        ("thermal demand Q",    float(row["Q_demand"]),            1.0, f"{float(row['Q_demand']):.2f}"),
    ]
    # `daily_print_hours` only shows up on the predictions parquet and on
    # newly-regenerated baseline rows; keep it optional so a snapshot
    # missing the column still renders a rationale.
    if "daily_print_hours" in row.index:
        hours = float(row["daily_print_hours"])
        candidates.append(("daily print hours", hours, 4.0, f"{hours:.1f} h"))

    # Score by how far the reading is from nominal, normalised by the
    # nominal so percentages and °C compete on the same axis.
    label, value, ref, reading = max(
        candidates,
        key=lambda c: abs(c[1] - c[2]) / c[2] if c[2] else 0.0,
    )
    ratio = value / ref if ref else 0.0
    direction = "elevated" if value >= ref else "depressed"
    return f"{direction} {label} at {reading} ({ratio:.2f}× nominal)"


def _analytic_one_component(
    row: pd.Series,
    sim_id: str,
    horizon_d: float,
) -> dict[str, Any]:
    info = next(c for c in COMPONENTS if c.sim_id == sim_id)
    h_now = float(row[f"H_{sim_id}"])
    lam = max(0.0, float(row[f"lambda_{sim_id}"]))
    h_next = _project_health(h_now, lam, horizon_d)
    return {
        "id": info.frontend_id,
        "predictedHealthIndex": h_next,
        "predictedStatus": _predicted_status_from_health(h_next),
        "predictedMetrics": predicted_metrics(row, sim_id, h_next),
        "daysUntilCritical": _days_to_threshold(h_now, lam, H_CRITICAL),
        "daysUntilFailure":  _days_to_threshold(h_now, lam, H_FAILED),
        "rationale": (
            f"Projected from current lambda={lam:.4f}/d with "
            f"{_dominant_driver_text(row)}."
        ),
        "confidence": _confidence(lam, h_now),
    }


def analytic_forecasts(row: pd.Series, horizon_d: float) -> list[dict[str, Any]]:
    return [_analytic_one_component(row, sid, horizon_d) for sid in COMPONENT_IDS]


# ----------------------------------------------------- SSL/RUL forecast


def _build_window(
    df: pd.DataFrame,
    city: str,
    printer_id: int,
    day_end: int,
    feature_cols: list[str],
    context_length: int,
) -> np.ndarray | None:
    """Return a (context_length, 37) tensor ending on ``day_end`` for one printer.

    Returns ``None`` when the printer doesn't have enough history yet (early
    days < context_length); the analytic fallback handles those cases.
    """
    from ml_models.lib.features import build_feature_matrix

    mask = (
        (df["city"] == city)
        & (df["printer_id"] == int(printer_id))
        & (df["day"] <= int(day_end))
        & (df["day"] > int(day_end) - context_length)
    )
    sub = df.loc[mask].sort_values("day")
    if len(sub) < context_length:
        return None
    enriched, cols = build_feature_matrix(sub.reset_index(drop=True))
    if cols != feature_cols:
        # Defensive: feature ordering must match what the model was trained on.
        raise RuntimeError(
            "feature column mismatch between scaler and runtime "
            f"(scaler={feature_cols[:5]}..., runtime={cols[:5]}...)"
        )
    return enriched[cols].to_numpy(dtype=np.float32)


def _ssl_one_component(
    sim_id: str,
    row: pd.Series,
    rul_days: float,
    horizon_d: float,
) -> dict[str, Any]:
    info = next(c for c in COMPONENTS if c.sim_id == sim_id)
    h_now = float(row[f"H_{sim_id}"])
    lam = max(0.0, float(row[f"lambda_{sim_id}"]))

    # Map predicted RUL -> days to thresholds. The RUL the head learned is
    # "days until failure_C{i} fires", which is exactly the FAILED line. The
    # CRITICAL line lives further out, so we approximate it from the same
    # decay rate the simulator uses (analytic ``H / lambda``) until threshold.
    days_to_failure: float | None = (
        rul_days if rul_days <= _OPERATIONAL_HORIZON_D else None
    )
    if h_now > H_CRITICAL and lam > _LAMBDA_OPERATIONAL_FLOOR:
        raw_days_to_critical = float((h_now - H_CRITICAL) / lam)
        days_to_critical: float | None = (
            raw_days_to_critical
            if raw_days_to_critical <= _CRITICAL_HORIZON_D
            else None
        )
    else:
        days_to_critical = None

    h_next = _project_health(h_now, lam, horizon_d)
    return {
        "id": info.frontend_id,
        "predictedHealthIndex": h_next,
        "predictedStatus": _predicted_status_from_health(h_next),
        "predictedMetrics": predicted_metrics(row, sim_id, h_next),
        "daysUntilCritical": days_to_critical,
        "daysUntilFailure": days_to_failure,
        "rationale": (
            f"SSL+RUL model: {rul_days:.1f}d remaining (lambda={lam:.4f}/d, "
            f"{_dominant_driver_text(row)})."
        ),
        "confidence": 0.78,  # learned model — bumped above analytic baseline
    }


def ssl_forecasts(
    df: pd.DataFrame,
    city: str,
    printer_id: int,
    day: int,
    horizon_d: float,
    bundle: _ModelBundle,
) -> list[dict[str, Any]]:
    """Run the trained PatchTST RUL head for one (city, printer, day)."""
    window = _build_window(
        df, city, printer_id, day,
        bundle.feature_cols, bundle.context_length,
    )
    if window is None:
        # Not enough history -> fall back analytically for this call only.
        row = twin_data._row_for(city, printer_id, day, df)  # noqa: SLF001
        return analytic_forecasts(row, horizon_d)

    if window.shape[1] != bundle.channel_mean.shape[0]:
        # Trained head's feature width is stale vs. the current parquet schema
        # (e.g. SDG was refactored after the head was trained). Fall back to
        # analytic forecasts until Stage 02 is retrained.
        row = twin_data._row_for(city, printer_id, day, df)  # noqa: SLF001
        return analytic_forecasts(row, horizon_d)

    normed = (window - bundle.channel_mean) / bundle.channel_std
    torch = bundle.torch
    with torch.no_grad():
        x = torch.from_numpy(normed).unsqueeze(0)  # (1, T, F)
        out = bundle.model(past_values=x).regression_outputs.squeeze(-1)
        rul_normalised = out.view(-1).cpu().numpy()
    rul_days = np.clip(rul_normalised, 0.0, 1.0) * _RUL_CLIP_DAYS

    row = twin_data._row_for(city, printer_id, day, df)  # noqa: SLF001
    return [
        _ssl_one_component(sid, row, float(rul_days[i]), horizon_d)
        for i, sid in enumerate(COMPONENT_IDS)
    ]


# --------------------------------------------------------------- public API


def compute_forecasts(
    city: str,
    printer_id: int,
    day: int,
    *,
    horizon_d: float = DEFAULT_HORIZON_D,
    path: str | None = None,
) -> list[dict[str, Any]]:
    """Return one ComponentForecast per simulator component.

    Dispatch order:
    1. If the SSL+RUL artefacts are on disk and load successfully, use the
       learned model.
    2. Otherwise (or if model loading fails), fall back to the analytic
       per-day-hazard projection.
    Both paths emit the same output shape (with day-based ETA fields).
    """
    df = twin_data.get_dataset(path)
    if _has_rul_head():
        bundle = _get_bundle()
        if bundle is not None:
            return ssl_forecasts(df, city, printer_id, day, horizon_d, bundle)
    row = twin_data._row_for(city, printer_id, day, df)  # noqa: SLF001
    return analytic_forecasts(row, horizon_d)


def active_path() -> str:
    """Return the dispatch path that ``compute_forecasts`` would take right now.

    Useful for surfacing the model state in the UI or logs:
    ``"ssl"`` when the trained head is loaded *and compatible* with the live
    parquet schema, ``"analytic"`` otherwise.
    """
    if not _has_rul_head():
        return "analytic"
    bundle = _get_bundle()
    if bundle is None:
        return "analytic"
    from ml_models.lib.features import base_feature_columns
    if bundle.channel_mean.shape[0] != len(base_feature_columns()):
        # Trained head's feature width is stale vs. the current schema.
        return "analytic"
    return "ssl"
