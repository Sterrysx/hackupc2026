"""Per-tick maintenance Gymnasium env — strictly more expressive than the bandit.

Each step is one simulated day. The agent emits a 6-d binary maintenance
decision (one per component); the env steps the SDG simulator one tick
forward via :class:`sdg.core.simulator.PrinterStepper` and returns:

- per-day reward = -(daily preventive cost + daily corrective cost
  + ``downtime_lambda`` · daily downtime hours) / cost_scale
- terminated when the printer reaches the last date in ``dates``

A ``constant_τ`` bandit policy is a special case: emit ``True`` whenever
``tau_mant_h ≥ τ_C`` (and never otherwise). So the per-tick policy class
strictly contains Stage 03's bandit class.

Observation (raw, no encoder needed because the LSTM builds memory):

- Per-component current state: ``H_Ci``, ``tau_mant_Ci`` (normalised by
  ``L_nom_h``), ``L_Ci`` (normalised), ``lambda_Ci`` (log-scaled). 4 × 6 = 24.
- Counters (log1p of N_f, N_c, N_TC, N_on). 4.
- Weather/load: ambient_temp_c, humidity_pct, dust_concentration, Q_demand,
  jobs_today. 5.
- Calendar: sin/cos of doy + month. 4.
- City one-hot. 15.
- Optional: SSL embedding (encoder applied to first-360-day window once at
  reset). +d_model. Off by default.

Total without SSL: 52-d. With SSL (256-d): 308-d.
"""
from __future__ import annotations

from datetime import date as Date, timedelta
from typing import Any, Mapping, Sequence

import gymnasium as gym
import numpy as np
import pandas as pd
from gymnasium import spaces

from ml_models.lib.env_runner import default_dates, make_printer_stepper
from ml_models.lib.features import build_feature_matrix
from sdg.core.simulator import HOURS_PER_DAY
from sdg.generate import build_printer_city_map, load_configs
from sdg.schema import COMPONENT_IDS

from .encoder_loader import SSLEncoderBundle


# Per-component normalisers — derived from components.yaml ranges, fixed for
# determinism so observations don't drift between runs.
_TAU_NORM_HOURS: dict[str, float] = {
    "C1": 2_000.0,
    "C2": 20_000.0,
    "C3": 500.0,
    "C4": 2_000.0,
    "C5": 8_000.0,
    "C6": 20_000.0,
}
_LIFE_NORM_HOURS: float = 100_000.0
_LAMBDA_LOG_FLOOR: float = 1e-9


def _component_state_features(state_snapshot: Mapping[str, Mapping[str, float]],
                              lambda_values: Mapping[str, float]) -> np.ndarray:
    out = np.zeros(4 * len(COMPONENT_IDS), dtype=np.float32)
    for i, component_id in enumerate(COMPONENT_IDS):
        s = state_snapshot[component_id]
        out[4 * i + 0] = float(s["H"])
        out[4 * i + 1] = float(s["tau_mant_h"]) / float(_TAU_NORM_HOURS[component_id])
        out[4 * i + 2] = float(s["L_h"]) / float(_LIFE_NORM_HOURS)
        out[4 * i + 3] = float(np.log10(max(float(lambda_values[component_id]), _LAMBDA_LOG_FLOOR)))
    return out


def _counter_features(counters: Mapping[str, int]) -> np.ndarray:
    return np.log1p(np.array(
        [counters["N_f"], counters["N_c"], counters["N_TC"], counters["N_on"]],
        dtype=np.float64,
    )).astype(np.float32)


def _weather_features(row: Mapping[str, Any]) -> np.ndarray:
    return np.array(
        [
            float(row["ambient_temp_c"]),
            float(row["humidity_pct"]),
            float(row["dust_concentration"]),
            float(row["Q_demand"]),
            float(row["jobs_today"]),
        ],
        dtype=np.float32,
    )


def _calendar_features(current_date: Date) -> np.ndarray:
    doy = current_date.timetuple().tm_yday
    month = current_date.month
    return np.array(
        [
            float(np.sin(2.0 * np.pi * doy / 365.25)),
            float(np.cos(2.0 * np.pi * doy / 365.25)),
            float(np.sin(2.0 * np.pi * month / 12.0)),
            float(np.cos(2.0 * np.pi * month / 12.0)),
        ],
        dtype=np.float32,
    )


class MaintenancePerTickEnv(gym.Env):
    """Per-day binary-action maintenance env, recurrent-policy friendly."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        printer_ids: Sequence[int],
        *,
        components_cfg: Mapping[str, Any] | None = None,
        couplings_cfg: Mapping[str, Any] | None = None,
        cities_cfg: Mapping[str, Any] | None = None,
        dates: list[Date] | None = None,
        encoder_bundle: SSLEncoderBundle | None = None,
        feature_df: pd.DataFrame | None = None,
        availability_threshold: float = 0.95,
        downtime_lambda: float = 100.0,
        cost_scale: float = 1e3,
        use_ssl_observation: bool = False,
        max_steps: int | None = None,
    ) -> None:
        super().__init__()
        if not printer_ids:
            raise ValueError("printer_ids must be non-empty")
        if components_cfg is None or couplings_cfg is None or cities_cfg is None:
            c, k, ci = load_configs()
            components_cfg = components_cfg or c
            couplings_cfg = couplings_cfg or k
            cities_cfg = cities_cfg or ci
        if dates is None:
            dates = default_dates()
        self._printer_ids: tuple[int, ...] = tuple(int(pid) for pid in printer_ids)
        self._components_cfg = components_cfg
        self._couplings_cfg = couplings_cfg
        self._cities_cfg = cities_cfg
        self._dates: list[Date] = list(dates)
        self._availability_threshold = float(availability_threshold)
        self._downtime_lambda = float(downtime_lambda)
        self._cost_scale = float(cost_scale)
        self._max_steps = int(max_steps) if max_steps is not None else len(self._dates)
        if self._max_steps > len(self._dates):
            raise ValueError("max_steps cannot exceed len(dates)")

        cities = list(cities_cfg["cities"])
        self._city_names: list[str] = [str(city["name"]) for city in cities]
        self._city_index: dict[str, int] = {name: i for i, name in enumerate(self._city_names)}
        self._n_cities = len(self._city_names)
        self._printer_city_map = build_printer_city_map(cities)

        self._spec_costs: dict[str, dict[str, float]] = {
            component_id: {
                "preventive": float(components_cfg["components"][component_id]["cost_preventive_eur"]),
                "corrective": float(components_cfg["components"][component_id]["cost_corrective_eur"]),
                "downtime_preventive": float(components_cfg["components"][component_id]["downtime_preventive_h"]),
                "downtime_corrective": float(components_cfg["components"][component_id]["downtime_corrective_h"]),
            }
            for component_id in COMPONENT_IDS
        }

        # Optional SSL observation channel — encoder applied to the first
        # 360-day window once per episode and concatenated as a static
        # context vector. OFF by default; recurrent policy doesn't need it.
        self._use_ssl = bool(use_ssl_observation)
        self._encoder = encoder_bundle if self._use_ssl else None
        self._feature_df: pd.DataFrame | None = None
        self._feature_cols: list[str] | None = None
        if self._use_ssl:
            if encoder_bundle is None:
                raise ValueError("use_ssl_observation=True requires encoder_bundle")
            if feature_df is None:
                from ml_models.lib.data import DEFAULT_FLEET_PATH, filter_printers, load_fleet
                fleet = filter_printers(load_fleet(DEFAULT_FLEET_PATH), self._printer_ids)
                feat_df, feature_cols = build_feature_matrix(fleet)
            else:
                feat_df, feature_cols = build_feature_matrix(feature_df)
            self._feature_df = feat_df
            self._feature_cols = list(feature_cols)

        # Spaces.
        self.action_space = spaces.MultiBinary(len(COMPONENT_IDS))
        ssl_dim = self._encoder.d_model if self._encoder is not None else 0
        obs_dim = (
            4 * len(COMPONENT_IDS)  # per-component state
            + 4                      # counters
            + 5                      # weather + load
            + 4                      # calendar
            + self._n_cities         # city one-hot
            + ssl_dim
        )
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(obs_dim,), dtype=np.float32
        )

        # Episode state — set by reset().
        self._stepper = None
        self._current_pid: int | None = None
        self._date_idx: int = 0
        self._city_one_hot: np.ndarray | None = None
        self._ssl_context: np.ndarray | None = None
        self._last_lambda: dict[str, float] | None = None
        self._cum_cost: float = 0.0
        self._cum_downtime_hours: float = 0.0
        self._cum_preventive: int = 0
        self._cum_corrective: int = 0
        self._all_rows: list[dict] = []

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def printer_ids(self) -> tuple[int, ...]:
        return self._printer_ids

    @property
    def cost_scale(self) -> float:
        return self._cost_scale

    def _build_observation(
        self,
        state_snapshot: Mapping[str, Mapping[str, float]],
        lambda_values: Mapping[str, float],
        last_row: Mapping[str, Any] | None,
        current_date: Date,
    ) -> np.ndarray:
        if last_row is None:
            # Pre-step observation at reset() — no row yet, use zeros for
            # weather/jobs and lambda placeholder.
            weather = np.zeros(5, dtype=np.float32)
        else:
            weather = _weather_features(last_row)
        per_component = _component_state_features(state_snapshot, lambda_values)
        counters = _counter_features(
            self._stepper.counters if self._stepper is not None else
            {"N_f": 0, "N_c": 0, "N_TC": 0, "N_on": 0}
        )
        calendar = _calendar_features(current_date)
        parts = [per_component, counters, weather, calendar, self._city_one_hot]
        if self._ssl_context is not None:
            parts.append(self._ssl_context)
        return np.concatenate(parts).astype(np.float32)

    def _compute_ssl_context(self, printer_id: int) -> np.ndarray | None:
        if self._encoder is None or self._feature_df is None or self._feature_cols is None:
            return None
        rows = self._feature_df.loc[self._feature_df["printer_id"] == printer_id].sort_values("day")
        if len(rows) < self._encoder.context_length:
            raise ValueError(
                f"printer {printer_id} has {len(rows)} days < context_length "
                f"{self._encoder.context_length}"
            )
        window = rows.iloc[: self._encoder.context_length][self._feature_cols].to_numpy(dtype=np.float32)
        return self._encoder.embed(window).astype(np.float32)

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
            if pid not in self._printer_ids:
                raise KeyError(f"printer_id {pid} not in env")
        else:
            pid = int(self.np_random.choice(self._printer_ids))
        self._current_pid = pid
        self._stepper = make_printer_stepper(
            pid,
            components_cfg=self._components_cfg,
            couplings_cfg=self._couplings_cfg,
            cities_cfg=self._cities_cfg,
        )
        self._date_idx = 0
        self._cum_cost = 0.0
        self._cum_downtime_hours = 0.0
        self._cum_preventive = 0
        self._cum_corrective = 0
        self._all_rows = []

        city_name = str(self._printer_city_map[pid]["name"])
        self._city_one_hot = np.zeros(self._n_cities, dtype=np.float32)
        self._city_one_hot[self._city_index[city_name]] = 1.0
        self._ssl_context = self._compute_ssl_context(pid)

        state = self._stepper.state_snapshot
        zero_lambda = {c: 0.0 for c in COMPONENT_IDS}
        obs = self._build_observation(state, zero_lambda, last_row=None,
                                      current_date=self._dates[0])
        info = {"printer_id": pid}
        return obs, info

    def step(
        self, action: np.ndarray
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._stepper is None:
            raise RuntimeError("step() called before reset()")
        action_arr = np.asarray(action, dtype=np.int64).reshape(-1)
        if action_arr.shape != (len(COMPONENT_IDS),):
            raise ValueError(
                f"action shape {action_arr.shape} != ({len(COMPONENT_IDS)},)"
            )
        action_dict = {
            component_id: bool(action_arr[i] > 0)
            for i, component_id in enumerate(COMPONENT_IDS)
        }
        current_date = self._dates[self._date_idx]
        row = self._stepper.step(current_date, agent_action=action_dict)
        self._all_rows.append(row)

        # Compute today's cost contribution + downtime.
        daily_preventive_cost = 0.0
        daily_corrective_cost = 0.0
        daily_downtime_hours = 0.0
        n_pm = 0
        n_cm = 0
        for component_id in COMPONENT_IDS:
            spec = self._spec_costs[component_id]
            if bool(row[f"maint_{component_id}"]):
                daily_preventive_cost += spec["preventive"]
                daily_downtime_hours += spec["downtime_preventive"]
                n_pm += 1
            if bool(row[f"failure_{component_id}"]):
                daily_corrective_cost += spec["corrective"]
                daily_downtime_hours += spec["downtime_corrective"]
                n_cm += 1
        self._cum_cost += daily_preventive_cost + daily_corrective_cost
        self._cum_downtime_hours += daily_downtime_hours
        self._cum_preventive += n_pm
        self._cum_corrective += n_cm

        # Reward shaping: per-day cost in € and downtime hours, scaled.
        reward = -(
            (daily_preventive_cost + daily_corrective_cost) / self._cost_scale
            + self._downtime_lambda * (daily_downtime_hours / HOURS_PER_DAY)
        )

        # Build next observation from updated state + the row we just got.
        state = self._stepper.state_snapshot
        lambda_values = {c: float(row[f"lambda_{c}"]) for c in COMPONENT_IDS}
        self._last_lambda = lambda_values
        self._date_idx += 1
        terminated = self._date_idx >= self._max_steps
        next_date = (
            self._dates[self._date_idx] if self._date_idx < len(self._dates)
            else current_date + timedelta(days=1)
        )
        obs = self._build_observation(state, lambda_values, last_row=row, current_date=next_date)
        truncated = False

        info: dict[str, Any] = {
            "printer_id": int(self._current_pid),
            "day": int(row["day"]),
            "daily_cost": float(daily_preventive_cost + daily_corrective_cost),
            "daily_downtime_h": float(daily_downtime_hours),
            "cum_cost": float(self._cum_cost),
            "cum_downtime_h": float(self._cum_downtime_hours),
            "cum_preventive": int(self._cum_preventive),
            "cum_corrective": int(self._cum_corrective),
            "row": row,
        }
        if terminated:
            # Episode-level fleet-comparable KPIs (single printer).
            n_days = len(self._all_rows)
            total_hours = n_days * HOURS_PER_DAY
            availability = max(0.0, min(1.0, (total_hours - self._cum_downtime_hours) / total_hours))
            years = n_days / 365.25
            annual_cost = float(self._cum_cost / max(years, 1e-9))
            info["episode_summary"] = {
                "annual_cost": annual_cost,
                "availability": availability,
                "deficit": max(0.0, self._availability_threshold - availability),
                "n_preventive": int(self._cum_preventive),
                "n_corrective": int(self._cum_corrective),
                "horizon_days": n_days,
            }
        return obs, float(reward), terminated, truncated, info

    def render(self) -> None:
        return None

    def close(self) -> None:
        return None

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def episode_events(self) -> pd.DataFrame:
        """Return the row dicts collected since the last reset, as a DataFrame."""
        return pd.DataFrame.from_records(self._all_rows)


def make_per_tick_vec_env(
    printer_ids: Sequence[int],
    *,
    n_envs: int = 1,
    use_subproc: bool = True,
    **env_kwargs: Any,
):
    """Build a (sub)proc-parallel vector of per-tick envs.

    The training loop spends most of its wall-clock stepping the simulator
    one day at a time. Wrapping multiple ``MaintenancePerTickEnv`` instances
    in ``SubprocVecEnv`` lets SB3 step them concurrently across CPU
    processes — on a 12-core 9900X with ``n_envs=8`` that's a ~6–8×
    throughput win over the default single ``DummyVecEnv``.

    Printer IDs are partitioned into ``n_envs`` roughly-equal disjoint
    subsets, so worker processes don't sample the same printer at once.
    For ``n_envs == 1`` (or a single printer ID) we fall back to
    ``DummyVecEnv`` and skip the subprocess machinery.

    Notes
    -----
    - On Windows ``SubprocVecEnv`` uses ``spawn``; the env class lives
      in this module so it pickles cleanly.
    - All ``env_kwargs`` are forwarded to ``MaintenancePerTickEnv``
      (e.g. ``components_cfg``, ``dates``, ``encoder_bundle``).
    - ``train_per_tick`` accepts either an ``Env`` or a ``VecEnv``;
      pass the result of this helper directly as ``train_env`` to opt
      into parallelism.
    """
    from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

    pids = [int(p) for p in printer_ids]
    if not pids:
        raise ValueError("printer_ids must be non-empty")

    n = max(1, int(n_envs))
    if n == 1 or len(pids) == 1:
        return DummyVecEnv([lambda: MaintenancePerTickEnv(pids, **env_kwargs)])

    # Partition into roughly-equal disjoint chunks (drop empty trailing ones).
    n = min(n, len(pids))
    base, rem = divmod(len(pids), n)
    chunks: list[list[int]] = []
    cursor = 0
    for i in range(n):
        size = base + (1 if i < rem else 0)
        chunks.append(pids[cursor:cursor + size])
        cursor += size

    def make_factory(chunk: list[int]):
        # Closure over a fresh list copy so spawned workers don't share state.
        chunk_copy = list(chunk)
        return lambda: MaintenancePerTickEnv(chunk_copy, **env_kwargs)

    vec_cls = SubprocVecEnv if use_subproc else DummyVecEnv
    return vec_cls([make_factory(chunk) for chunk in chunks])
