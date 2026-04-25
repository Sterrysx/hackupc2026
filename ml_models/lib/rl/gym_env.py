"""One-shot bandit Gymnasium env over the 6-dim maintenance-interval vector τ.

Why one-shot:
-------------
The simulator's action surface is per-printer τ ∈ ℝ⁶. An episode = one printer.
We reset by sampling a printer, deliver its SSL-encoded initial-year telemetry
window + city-one-hot + climate summary as the observation, then ``step`` runs
the full simulator under the chosen τ and returns the negated objective.

This strictly extends Stage 02's policy class: a constant policy that ignores
the observation recovers Stage 02's fleet-wide τ, so the worst case for
Stage 03 is a tie. The best case adapts τ to local conditions.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

from ml_models.lib.env_runner import default_dates, run_with_tau
from ml_models.lib.features import WEATHER_COLS, build_feature_matrix
from ml_models.lib.objective import scalar_objective
from sdg.generate import build_printer_city_map, load_configs
from sdg.schema import COMPONENT_IDS

from .encoder_loader import SSLEncoderBundle, load_ssl_encoder

# Same log-uniform priors used by Stage 01 (search.ipynb) and Stage 02
# (03_surrogate_search.ipynb). Keeping them aligned makes the RL policy's
# action space directly comparable to those stages.
TAU_RANGES: dict[str, tuple[float, float]] = {
    "C1": (50.0, 2_000.0),
    "C2": (500.0, 20_000.0),
    "C3": (24.0, 500.0),
    "C4": (100.0, 2_000.0),
    "C5": (500.0, 8_000.0),
    "C6": (1_000.0, 20_000.0),
}

CLIMATE_FEATURE_COLS: tuple[str, ...] = tuple(WEATHER_COLS)  # ("ambient_temp_c", "humidity_pct")


def action_to_tau(
    action: np.ndarray,
    tau_ranges: Mapping[str, tuple[float, float]] = TAU_RANGES,
) -> dict[str, float]:
    """Map a tanh-bounded action ∈ [-1, 1]^6 to a τ vector via per-component log-uniform scaling."""
    if action.shape != (len(COMPONENT_IDS),):
        raise ValueError(f"action shape {action.shape} != ({len(COMPONENT_IDS)},)")
    clipped = np.clip(action.astype(np.float64), -1.0, 1.0)
    tau: dict[str, float] = {}
    for i, component_id in enumerate(COMPONENT_IDS):
        lo, hi = tau_ranges[component_id]
        log_lo, log_hi = np.log(lo), np.log(hi)
        log_tau = log_lo + 0.5 * (clipped[i] + 1.0) * (log_hi - log_lo)
        tau[component_id] = float(np.exp(log_tau))
    return tau


def tau_to_action(
    tau: Mapping[str, float],
    tau_ranges: Mapping[str, tuple[float, float]] = TAU_RANGES,
) -> np.ndarray:
    """Inverse of action_to_tau — useful for warm-starting the policy mean from a known τ."""
    action = np.zeros(len(COMPONENT_IDS), dtype=np.float32)
    for i, component_id in enumerate(COMPONENT_IDS):
        lo, hi = tau_ranges[component_id]
        log_lo, log_hi = np.log(lo), np.log(hi)
        log_tau = float(np.log(max(float(tau[component_id]), 1e-9)))
        action[i] = float(2.0 * (log_tau - log_lo) / (log_hi - log_lo) - 1.0)
    return np.clip(action, -1.0, 1.0)


class MaintenanceBanditEnv(gym.Env):
    """Gymnasium env wrapping ``run_with_tau`` for one-shot τ optimisation.

    Observation
    -----------
    Concatenation of:
    - SSL encoder embedding of the first ``context_length`` days of telemetry
      (defaults to 256-d).
    - City one-hot (15-d, cities ordered as in ``cities.yaml``).
    - Climate summary (4-d): mean & std of ambient_temp_c, mean & std of
      humidity_pct over the same window.

    Action
    ------
    Box(-1, 1, (6,)). Mapped to per-component τ via log-uniform scaling
    inside ``TAU_RANGES`` (matching Stage 01/02).

    Reward
    ------
    During training (default)::

        reward = -(annual_cost / cost_scale + availability_lambda * deficit)

    where ``deficit = max(0, availability_threshold - availability)``. The
    soft Lagrangian is gradient-friendly near the constraint boundary. At
    evaluation time, callers should use ``scalar_objective`` directly via
    ``info["score"]`` to compare against Stages 01 & 02 (which use the hard
    ``INFEASIBLE_FLOOR`` rule).
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        printer_ids: Sequence[int],
        encoder_bundle: SSLEncoderBundle | None = None,
        *,
        feature_df: pd.DataFrame | None = None,
        components_cfg: Mapping[str, Any] | None = None,
        couplings_cfg: Mapping[str, Any] | None = None,
        cities_cfg: Mapping[str, Any] | None = None,
        dates: list[date] | None = None,
        tau_ranges: Mapping[str, tuple[float, float]] = TAU_RANGES,
        availability_threshold: float = 0.95,
        availability_lambda: float = 100.0,
        cost_scale: float = 1e6,
    ) -> None:
        super().__init__()
        if not printer_ids:
            raise ValueError("printer_ids must be non-empty")
        if encoder_bundle is None:
            encoder_bundle = load_ssl_encoder()
        if components_cfg is None or couplings_cfg is None or cities_cfg is None:
            c_cfg, k_cfg, city_cfg = load_configs()
            components_cfg = components_cfg or c_cfg
            couplings_cfg = couplings_cfg or k_cfg
            cities_cfg = cities_cfg or city_cfg
        if dates is None:
            dates = default_dates()
        self._printer_ids: tuple[int, ...] = tuple(int(pid) for pid in printer_ids)
        self._encoder = encoder_bundle
        self._components_cfg = components_cfg
        self._couplings_cfg = couplings_cfg
        self._cities_cfg = cities_cfg
        self._dates = dates
        self._tau_ranges = dict(tau_ranges)
        self._availability_threshold = float(availability_threshold)
        self._availability_lambda = float(availability_lambda)
        self._cost_scale = float(cost_scale)

        cities = list(cities_cfg["cities"])
        self._city_names: list[str] = [str(city["name"]) for city in cities]
        self._city_index: dict[str, int] = {name: i for i, name in enumerate(self._city_names)}
        self._printer_city_map = build_printer_city_map(cities)

        # Pre-compute SSL embedding + city one-hot + climate summary for every
        # printer in this env. Each observation is fixed (deterministic given
        # the locked fleet_baseline parquet) — pre-encoding once amortises the
        # per-step encoder cost across all PPO updates.
        if feature_df is None:
            from ml_models.lib.data import DEFAULT_FLEET_PATH, filter_printers, load_fleet
            fleet = filter_printers(load_fleet(DEFAULT_FLEET_PATH), self._printer_ids)
            feat_df, feature_cols = build_feature_matrix(fleet)
        else:
            feat_df, feature_cols = build_feature_matrix(feature_df)
        if list(feature_cols) != list(self._encoder.feature_columns):
            raise RuntimeError(
                "feature column ordering drifted vs Stage 02 — re-pretrain the encoder"
            )
        self._observations: dict[int, np.ndarray] = {}
        for printer_id in self._printer_ids:
            self._observations[printer_id] = self._build_observation(printer_id, feat_df, feature_cols)

        self._n_cities = len(self._city_names)
        obs_dim = self._encoder.d_model + self._n_cities + 2 * len(CLIMATE_FEATURE_COLS)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )
        self.action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(len(COMPONENT_IDS),), dtype=np.float32
        )
        self._current_pid: int | None = None
        self._current_obs: np.ndarray | None = None

    # ------------------------------------------------------------------
    # Pre-computation helpers
    # ------------------------------------------------------------------
    def _build_observation(
        self,
        printer_id: int,
        feat_df: pd.DataFrame,
        feature_cols: list[str],
    ) -> np.ndarray:
        rows = feat_df.loc[feat_df["printer_id"] == printer_id].sort_values("day")
        if len(rows) < self._encoder.context_length:
            raise ValueError(
                f"printer {printer_id} has {len(rows)} days < context_length "
                f"{self._encoder.context_length}"
            )
        window = rows.iloc[: self._encoder.context_length]
        feature_window = window[feature_cols].to_numpy(dtype=np.float32)
        embedding = self._encoder.embed(feature_window).astype(np.float32)

        # Climate summary on the *raw* (un-scaled) weather columns; gives the
        # policy explicit access to the local climate without relying on the
        # encoder to surface it.
        climate_window = window[list(CLIMATE_FEATURE_COLS)].to_numpy(dtype=np.float32)
        climate_summary = np.concatenate(
            [climate_window.mean(axis=0), climate_window.std(axis=0)]
        ).astype(np.float32)

        # City one-hot from the canonical printer→city map.
        city_name = str(self._printer_city_map[int(printer_id)]["name"])
        city_one_hot = np.zeros(len(self._city_names), dtype=np.float32)
        city_one_hot[self._city_index[city_name]] = 1.0

        return np.concatenate([embedding, city_one_hot, climate_summary]).astype(np.float32)

    # ------------------------------------------------------------------
    # Gym API
    # ------------------------------------------------------------------
    def reset(
        self,
        *,
        seed: int | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        if options is not None and "printer_id" in options:
            pid = int(options["printer_id"])
            if pid not in self._observations:
                raise KeyError(f"printer_id {pid} not in this env's printer set")
        else:
            pid = int(self.np_random.choice(self._printer_ids))
        self._current_pid = pid
        self._current_obs = self._observations[pid].copy()
        return self._current_obs, {"printer_id": pid}

    def step(
        self, action: np.ndarray
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._current_pid is None or self._current_obs is None:
            raise RuntimeError("step() called before reset()")
        tau_vector = action_to_tau(np.asarray(action, dtype=np.float32), self._tau_ranges)
        events = run_with_tau(
            tau_vector,
            printer_ids=[self._current_pid],
            dates=self._dates,
            components_cfg=self._components_cfg,
            couplings_cfg=self._couplings_cfg,
            cities_cfg=self._cities_cfg,
        )
        score = scalar_objective(
            events,
            self._components_cfg,
            availability_threshold=self._availability_threshold,
        )
        deficit = float(score["deficit"])
        reward = -(
            float(score["annual_cost"]) / self._cost_scale
            + self._availability_lambda * deficit
        )
        info: dict[str, Any] = {
            "printer_id": int(self._current_pid),
            "tau_vector": tau_vector,
            "annual_cost": float(score["annual_cost"]),
            "availability": float(score["availability"]),
            "deficit": deficit,
            "preventive_cost": float(score["preventive_cost"]),
            "corrective_cost": float(score["corrective_cost"]),
            "score": dict(score),
        }
        terminated = True
        truncated = False
        # Final obs is irrelevant for one-shot but Gym requires returning one;
        # we copy the reset obs to keep VecEnv code paths happy.
        return self._current_obs.copy(), float(reward), terminated, truncated, info

    def render(self) -> None:
        return None

    def close(self) -> None:
        return None

    # ------------------------------------------------------------------
    # Diagnostics / utilities
    # ------------------------------------------------------------------
    @property
    def printer_ids(self) -> tuple[int, ...]:
        return self._printer_ids

    @property
    def obs_dim(self) -> int:
        return int(self.observation_space.shape[0])

    @property
    def cost_scale(self) -> float:
        return self._cost_scale

    def evaluate_tau(
        self,
        tau_vector: Mapping[str, float],
        printer_ids: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        """Run the simulator on a fixed τ and return the raw scalar_objective dict.

        Useful for benchmarking Stages 01 & 02 inside the same env wrapper.
        """
        ids = list(printer_ids) if printer_ids is not None else list(self._printer_ids)
        events = run_with_tau(
            tau_vector,
            printer_ids=ids,
            dates=self._dates,
            components_cfg=self._components_cfg,
            couplings_cfg=self._couplings_cfg,
            cities_cfg=self._cities_cfg,
        )
        return dict(scalar_objective(
            events,
            self._components_cfg,
            availability_threshold=self._availability_threshold,
        ))

    def get_observation_for(self, printer_id: int) -> np.ndarray:
        if printer_id not in self._observations:
            raise KeyError(f"printer_id {printer_id} not in this env")
        return self._observations[printer_id].copy()
