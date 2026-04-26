"""Contract tests for the Stage 03 gymnasium env.

Exercises the env wiring without requiring a trained Stage 02 SSL encoder
(so the suite passes on a fresh checkout). For the simulator-bound tests we
use a 90-day horizon and 1–2 printers to keep wall-clock under a few seconds.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ml.lib.rl import (
    MaintenanceBanditEnv,
    MaintenancePerTickEnv,
    TAU_RANGES,
    action_to_tau,
    make_per_tick_vec_env,
    random_encoder_bundle,
    tau_to_action,
)


# ----------------------------------------------------------------------
# Pure-math tests — always run.
# ----------------------------------------------------------------------
def test_action_to_tau_round_trip() -> None:
    for a_scalar in np.linspace(-1.0, 1.0, 7, dtype=np.float32):
        action = np.full(6, a_scalar, dtype=np.float32)
        tau = action_to_tau(action)
        recovered = tau_to_action(tau)
        np.testing.assert_allclose(recovered, action, atol=1e-5)


def test_action_to_tau_centre_is_geometric_mean() -> None:
    tau = action_to_tau(np.zeros(6, dtype=np.float32))
    for component_id, (lo, hi) in TAU_RANGES.items():
        expected = float(np.sqrt(lo * hi))
        assert abs(tau[component_id] - expected) / expected < 1e-5


def test_action_to_tau_endpoints_match_bounds() -> None:
    tau_lo = action_to_tau(-np.ones(6, dtype=np.float32))
    tau_hi = action_to_tau(np.ones(6, dtype=np.float32))
    for component_id, (lo, hi) in TAU_RANGES.items():
        assert abs(tau_lo[component_id] - lo) / lo < 1e-5
        assert abs(tau_hi[component_id] - hi) / hi < 1e-5


def test_action_clipping_for_out_of_range_input() -> None:
    tau_clipped = action_to_tau(np.full(6, 5.0, dtype=np.float32))
    tau_at_one = action_to_tau(np.ones(6, dtype=np.float32))
    for component_id in tau_at_one:
        assert abs(tau_clipped[component_id] - tau_at_one[component_id]) < 1e-3


# ----------------------------------------------------------------------
# Env tests — skip if the SDG fleet parquet doesn't exist.
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def fleet_subset():
    from ml.lib.data import DEFAULT_FLEET_PATH, filter_printers, load_fleet

    if not Path(DEFAULT_FLEET_PATH).exists():
        pytest.skip(
            f"fleet parquet missing at {DEFAULT_FLEET_PATH}; run sdg.generate first"
        )
    fleet = load_fleet(DEFAULT_FLEET_PATH)
    return filter_printers(fleet, [0, 1])


@pytest.fixture(scope="module")
def small_env(fleet_subset):
    from ml.lib.env_runner import default_dates
    from ml.lib.features import build_feature_matrix
    from backend.simulator.generate import load_configs

    _, feature_cols = build_feature_matrix(fleet_subset)
    bundle = random_encoder_bundle(
        feature_columns=feature_cols,
        context_length=360,
        patch_length=30,
        d_model=32,
        n_layers=2,
        n_heads=4,
        device="cpu",
    )
    components_cfg, couplings_cfg, cities_cfg = load_configs()
    short_dates = default_dates()[:90]
    return MaintenanceBanditEnv(
        printer_ids=[0, 1],
        encoder_bundle=bundle,
        feature_df=fleet_subset,
        components_cfg=components_cfg,
        couplings_cfg=couplings_cfg,
        cities_cfg=cities_cfg,
        dates=short_dates,
    )


def test_env_observation_shape(small_env) -> None:
    obs, info = small_env.reset(seed=0)
    assert obs.shape == small_env.observation_space.shape
    assert obs.dtype == np.float32
    assert info["printer_id"] in small_env.printer_ids


def test_env_action_space(small_env) -> None:
    space = small_env.action_space
    assert space.shape == (6,)
    assert np.all(space.low == -1.0)
    assert np.all(space.high == 1.0)


def test_env_step_contract(small_env) -> None:
    small_env.reset(seed=0, options={"printer_id": 0})
    obs, reward, terminated, truncated, info = small_env.step(np.zeros(6, dtype=np.float32))

    assert obs.shape == small_env.observation_space.shape
    assert isinstance(reward, float)
    assert terminated is True
    assert truncated is False

    expected_keys = {
        "printer_id",
        "tau_vector",
        "annual_cost",
        "availability",
        "deficit",
        "preventive_cost",
        "corrective_cost",
        "score",
    }
    assert expected_keys.issubset(info.keys())
    score = info["score"]
    for key in (
        "value",
        "annual_cost",
        "availability",
        "preventive_cost",
        "corrective_cost",
        "deficit",
        "horizon_days",
        "n_printers",
    ):
        assert key in score


def test_env_step_determinism(small_env) -> None:
    small_env.reset(seed=42, options={"printer_id": 0})
    _, r1, _, _, info1 = small_env.step(np.zeros(6, dtype=np.float32))
    small_env.reset(seed=42, options={"printer_id": 0})
    _, r2, _, _, info2 = small_env.step(np.zeros(6, dtype=np.float32))
    assert abs(r1 - r2) < 1e-9
    assert abs(info1["annual_cost"] - info2["annual_cost"]) < 1e-6
    assert abs(info1["availability"] - info2["availability"]) < 1e-9


def test_env_evaluate_tau_matches_step(small_env) -> None:
    small_env.reset(seed=0, options={"printer_id": 0})
    _, _, _, _, info = small_env.step(np.zeros(6, dtype=np.float32))
    direct = small_env.evaluate_tau(info["tau_vector"], printer_ids=[0])
    assert abs(direct["annual_cost"] - info["annual_cost"]) < 1e-6
    assert abs(direct["availability"] - info["availability"]) < 1e-9


# ----------------------------------------------------------------------
# Vec-env helper — sanity only (we don't actually spawn subprocs in CI).
# ----------------------------------------------------------------------
def test_make_per_tick_vec_env_single_env_falls_back_to_dummy() -> None:
    from datetime import date, timedelta

    from stable_baselines3.common.vec_env import DummyVecEnv

    short = [date(2015, 1, 1) + timedelta(days=d) for d in range(40)]
    vec = make_per_tick_vec_env([0], n_envs=1, dates=short)
    assert isinstance(vec, DummyVecEnv)
    assert vec.num_envs == 1
    vec.close()


def test_make_per_tick_vec_env_partitions_disjoint() -> None:
    from datetime import date, timedelta

    from stable_baselines3.common.vec_env import DummyVecEnv

    short = [date(2015, 1, 1) + timedelta(days=d) for d in range(40)]
    # use_subproc=False so the test stays in-process and fast
    vec = make_per_tick_vec_env([0, 7, 14, 21], n_envs=2, use_subproc=False, dates=short)
    assert isinstance(vec, DummyVecEnv)
    assert vec.num_envs == 2
    seen: set[int] = set()
    for env_fn in vec.envs:  # DummyVecEnv exposes .envs
        ids = set(env_fn.printer_ids)
        assert ids.isdisjoint(seen), f"printer subsets overlap: {ids} vs {seen}"
        seen |= ids
    assert seen == {0, 7, 14, 21}
    vec.close()


def test_make_per_tick_vec_env_n_envs_capped_to_n_printers() -> None:
    from datetime import date, timedelta

    short = [date(2015, 1, 1) + timedelta(days=d) for d in range(40)]
    # asking for 5 envs over 3 printers should drop empties → 3 envs
    vec = make_per_tick_vec_env([0, 7, 14], n_envs=5, use_subproc=False, dates=short)
    assert vec.num_envs == 3
    vec.close()
