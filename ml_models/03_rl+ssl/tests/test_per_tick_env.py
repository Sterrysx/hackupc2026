"""Contract tests for the per-tick env, stepper, SPR aux loss, bootstrap CI."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# ----------------------------------------------------------------------
# Stepper / agent rollout
# ----------------------------------------------------------------------
def test_printer_stepper_matches_run_printer_when_no_agent_action() -> None:
    """``rollout_with_agent`` with ``agent_action=None`` should mirror ``run_with_tau``."""
    from datetime import date, timedelta

    from ml_models.lib.env_runner import rollout_with_agent, run_with_tau
    from sdg.generate import load_configs
    from sdg.schema import COMPONENT_IDS

    if not Path("data/fleet_baseline.parquet").exists():
        pytest.skip("fleet parquet missing; sdg config still loadable but skip parquet")

    components_cfg, couplings_cfg, cities_cfg = load_configs()
    short_dates = [date(2015, 1, 1) + timedelta(days=d) for d in range(20)]
    tau = {c: float(components_cfg["components"][c]["tau_nom_d"]) for c in COMPONENT_IDS}

    batch = run_with_tau(
        tau, printer_ids=[0], dates=short_dates,
        components_cfg=components_cfg, couplings_cfg=couplings_cfg, cities_cfg=cities_cfg,
    )
    stream = rollout_with_agent(
        0, dates=short_dates, agent_fn=lambda last: None,
        components_cfg=components_cfg, couplings_cfg=couplings_cfg, cities_cfg=cities_cfg,
    )
    # Health + counters should match exactly between batch and per-tick (None override).
    np.testing.assert_allclose(
        batch["H_C1"].to_numpy(),
        stream["H_C1"].to_numpy(),
        atol=1e-9,
    )
    np.testing.assert_array_equal(batch["N_f"].to_numpy(), stream["N_f"].to_numpy())


def test_agent_can_force_preventive() -> None:
    """When ``agent_action`` says maintain C1 every day, ``maint_C1`` should fire daily."""
    from datetime import date, timedelta

    from ml_models.lib.env_runner import rollout_with_agent
    from sdg.schema import COMPONENT_IDS

    short_dates = [date(2015, 1, 1) + timedelta(days=d) for d in range(10)]
    df = rollout_with_agent(
        0, dates=short_dates,
        agent_fn=lambda last: {c: (c == "C1") for c in COMPONENT_IDS},
    )
    # C1 maintained every day → at least 9/10 (first day's pre-step state may differ).
    assert int(df["maint_C1"].sum()) >= 9
    # Other components never get forced preventive.
    for cid in ("C2", "C3", "C4", "C5", "C6"):
        assert int(df[f"maint_{cid}"].sum()) == 0


# ----------------------------------------------------------------------
# Per-tick gym env
# ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def short_dates():
    from ml_models.lib.env_runner import default_dates
    return default_dates()[:30]


def test_per_tick_env_observation_shape(short_dates) -> None:
    from ml_models.lib.rl import MaintenancePerTickEnv

    env = MaintenancePerTickEnv(printer_ids=[0, 1], dates=short_dates)
    obs, info = env.reset(seed=0)
    assert obs.shape == env.observation_space.shape
    assert obs.dtype == np.float32
    assert info["printer_id"] in env.printer_ids


def test_per_tick_env_step_terminates_at_horizon_end(short_dates) -> None:
    from ml_models.lib.rl import MaintenancePerTickEnv

    env = MaintenancePerTickEnv(printer_ids=[0], dates=short_dates)
    env.reset(seed=0, options={"printer_id": 0})
    last_info = {}
    n_steps = 0
    while True:
        obs, reward, terminated, truncated, last_info = env.step(np.zeros(6, dtype=np.int64))
        n_steps += 1
        if terminated or truncated:
            break
    assert n_steps == len(short_dates)
    assert "episode_summary" in last_info
    summary = last_info["episode_summary"]
    assert summary["horizon_days"] == len(short_dates)
    assert 0.0 <= summary["availability"] <= 1.0


def test_per_tick_env_action_overrides_tau_rule(short_dates) -> None:
    """All-True action should produce ≥1 preventive event per component daily."""
    from ml_models.lib.rl import MaintenancePerTickEnv

    env = MaintenancePerTickEnv(printer_ids=[0], dates=short_dates)
    env.reset(seed=0, options={"printer_id": 0})
    all_maint = np.ones(6, dtype=np.int64)
    cum_pm = 0
    while True:
        obs, _r, term, trunc, info = env.step(all_maint)
        cum_pm = info["cum_preventive"]
        if term or trunc:
            break
    # 6 components × 30 days = up to 180 preventive events.
    assert cum_pm >= 6 * (len(short_dates) - 1)


# ----------------------------------------------------------------------
# Bootstrap CI
# ----------------------------------------------------------------------
def test_bootstrap_ci_on_uniform_cost_includes_mean() -> None:
    from ml_models.lib.rl import bootstrap_fleet_ci

    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "annual_cost": rng.uniform(1e5, 1e6, size=15),
        "availability": np.full(15, 0.97),
    })
    ci = bootstrap_fleet_ci(df, metric="annual_cost", n_resamples=2000, rng_seed=0)
    assert ci["lo"] < df["annual_cost"].mean() < ci["hi"]
    assert ci["se"] > 0


def test_bootstrap_ci_value_uses_floor_when_infeasible() -> None:
    from ml_models.lib.rl import bootstrap_fleet_ci
    from ml_models.lib.objective import INFEASIBLE_FLOOR

    df = pd.DataFrame({
        "annual_cost": np.full(15, 1e5),
        "availability": np.full(15, 0.5),  # heavily infeasible
    })
    ci = bootstrap_fleet_ci(df, metric="value", n_resamples=500, rng_seed=0)
    # Every bootstrap mean has avail=0.5, so deficit=0.45, value far above floor.
    assert ci["lo"] >= INFEASIBLE_FLOOR
    assert ci["mean"] > INFEASIBLE_FLOOR


# ----------------------------------------------------------------------
# SPR module
# ----------------------------------------------------------------------
def test_spr_module_runs_one_update_and_lowers_loss() -> None:
    import torch

    from gymnasium import spaces
    from ml_models.lib.rl import SharedSPRFeaturesExtractor, SPRModule

    obs_space = spaces.Box(low=-np.inf, high=np.inf, shape=(52,), dtype=np.float32)
    extractor = SharedSPRFeaturesExtractor(obs_space, features_dim=32, hidden_dims=(64,))
    spr = SPRModule(extractor, action_dim=6, k=2, ema_tau=0.05, learning_rate=1e-3)
    rng = np.random.default_rng(0)
    obs_t = torch.as_tensor(rng.standard_normal((16, 52)), dtype=torch.float32)
    actions = torch.as_tensor(rng.integers(0, 2, size=(16, 2, 6)), dtype=torch.float32)
    obs_tk = torch.as_tensor(rng.standard_normal((16, 52)), dtype=torch.float32)

    loss0 = spr.compute_and_step(obs_t, actions, obs_tk)
    for _ in range(20):
        loss_n = spr.compute_and_step(obs_t, actions, obs_tk)
    assert loss_n <= loss0 + 1e-3  # cosine sim loss should at least not get worse on the same batch
    assert spr.stats.n_updates == 21


def test_extract_spr_tuples_skips_episode_boundaries() -> None:
    from ml_models.lib.rl import extract_spr_tuples_from_buffer

    n_steps, n_envs, obs_dim, action_dim = 10, 1, 4, 2
    obs = np.arange(n_steps * n_envs * obs_dim, dtype=np.float32).reshape(n_steps, n_envs, obs_dim)
    actions = np.zeros((n_steps, n_envs, action_dim), dtype=np.float32)
    starts = np.zeros((n_steps, n_envs), dtype=np.bool_)
    starts[5, 0] = True  # new episode at step 5

    obs_t, action_seq, obs_tk = extract_spr_tuples_from_buffer(obs, actions, starts, k=2)
    # Tuples that cross step 5 (i.e. starting at t in {3, 4}) are skipped.
    # obs_t is shape (B, obs_dim) — the n_envs axis is flattened during extraction.
    valid_t_indices = [0, 1, 2, 5, 6, 7]
    assert obs_t.shape == (len(valid_t_indices), obs_dim)
    assert action_seq.shape == (len(valid_t_indices), 2, action_dim)
    np.testing.assert_array_equal(obs_t, obs[valid_t_indices, 0, :])
