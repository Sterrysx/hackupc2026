"""PPO training loop for the SSL+RL maintenance-policy bandit.

Uses Stable-Baselines3's PPO on top of a single ``MaintenanceBanditEnv`` (or
a DummyVecEnv around it). The env pre-encodes telemetry windows once, so a
training step is dominated by the SDG simulator call in ``run_with_tau``;
SB3's vectorisation gives little speedup here on a single CPU because the
simulator is itself sequential per printer. Subproc workers help only when
multiple printers share the same env config.

Usage sketch::

    bundle = load_ssl_encoder()
    env = MaintenanceBanditEnv(printer_ids=TRAIN_PRINTERS, encoder_bundle=bundle)
    val_env = MaintenanceBanditEnv(printer_ids=VAL_PRINTERS, encoder_bundle=bundle)
    history = train_ppo(env, val_env, total_timesteps=5_000)
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import DummyVecEnv, VecEnv

from .gym_env import MaintenanceBanditEnv, action_to_tau
from .policy import make_mlp_policy_kwargs, warm_start_from_tau


@dataclass
class PPOConfig:
    """Hyperparameters with hackathon-friendly defaults.

    The defaults assume one CPU env worker, a 10-year horizon per simulator
    call, and a ~5k-timestep budget (≈80 PPO updates with n_steps=64) which
    matches a few hours of training on a laptop.
    """

    total_timesteps: int = 5_000
    n_steps: int = 64
    batch_size: int = 64
    n_epochs: int = 10
    learning_rate: float = 3e-4
    clip_range: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    gamma: float = 1.0  # one-shot bandit — no discount
    gae_lambda: float = 1.0
    seed: int = 0
    net_arch: tuple[int, ...] = (128, 128)
    log_std_init: float = -1.0
    val_eval_every: int = 320  # timesteps between val sweeps (5 PPO updates @ n_steps=64)


@dataclass
class TrainHistory:
    val_rewards: list[float] = field(default_factory=list)
    val_annual_costs: list[float] = field(default_factory=list)
    val_availabilities: list[float] = field(default_factory=list)
    val_values: list[float] = field(default_factory=list)
    val_timesteps: list[int] = field(default_factory=list)
    train_returns: list[float] = field(default_factory=list)
    best_val_value: float = float("inf")
    best_val_at: int = -1

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class _ValidationCallback(BaseCallback):
    """Periodically evaluate the policy deterministically on val printers and checkpoint."""

    def __init__(
        self,
        val_env: MaintenanceBanditEnv,
        every: int,
        save_path: Path | None,
        history: TrainHistory,
        verbose: int = 1,
    ) -> None:
        super().__init__(verbose)
        self._val_env = val_env
        self._every = max(1, int(every))
        self._save_path = Path(save_path) if save_path is not None else None
        self._history = history
        self._last_eval = 0

    def _on_step(self) -> bool:
        if self.num_timesteps - self._last_eval < self._every:
            return True
        self._last_eval = self.num_timesteps
        kpis = evaluate_policy_on_env(self.model, self._val_env, deterministic=True)
        self._history.val_timesteps.append(int(self.num_timesteps))
        self._history.val_rewards.append(float(kpis["mean_reward"]))
        self._history.val_annual_costs.append(float(kpis["annual_cost"]))
        self._history.val_availabilities.append(float(kpis["availability"]))
        self._history.val_values.append(float(kpis["value"]))
        is_feasible = kpis["availability"] >= 0.95
        is_better = kpis["value"] < self._history.best_val_value
        if is_better:
            self._history.best_val_value = float(kpis["value"])
            self._history.best_val_at = int(self.num_timesteps)
            if self._save_path is not None:
                self.model.save(str(self._save_path))
        if self.verbose:
            tag = "feasible" if is_feasible else "INFEASIBLE"
            print(
                f"[val @ {self.num_timesteps:>6}ts] "
                f"value={kpis['value']:.3e}  cost={kpis['annual_cost']:.3e}  "
                f"avail={kpis['availability']:.4f}  ({tag})"
                + ("  <- best" if is_better else "")
            )
        return True


def evaluate_policy_on_env(
    model: PPO,
    env: MaintenanceBanditEnv,
    *,
    deterministic: bool = True,
) -> dict[str, Any]:
    """Run the policy once per printer in ``env``; return aggregate fleet KPIs.

    Aggregation matches Stage 01/02: cost is averaged across printers (already
    per-printer-annual inside ``scalar_objective``); availability is the
    arithmetic mean over printers; the scalar ``value`` is recomputed against
    the fleet by replaying the best τ via ``env.evaluate_tau``.
    """
    actions: dict[int, np.ndarray] = {}
    per_printer: list[dict[str, Any]] = []
    for printer_id in env.printer_ids:
        obs = env.get_observation_for(printer_id)
        action, _ = model.predict(obs, deterministic=deterministic)
        action = np.asarray(action, dtype=np.float32)
        actions[printer_id] = action
        tau_vector = action_to_tau(action)
        score = env.evaluate_tau(tau_vector, printer_ids=[printer_id])
        per_printer.append(
            {
                "printer_id": int(printer_id),
                "annual_cost": float(score["annual_cost"]),
                "availability": float(score["availability"]),
                "deficit": float(score["deficit"]),
                "value": float(score["value"]),
                "tau_vector": tau_vector,
            }
        )

    # Fleet-level eval: re-simulate all printers in one batch so cost
    # normalisation matches Stage 01/02. We can't do this directly because
    # each printer gets its own τ — instead aggregate per-printer scores.
    annual_cost = float(np.mean([p["annual_cost"] for p in per_printer]))
    availability = float(np.mean([p["availability"] for p in per_printer]))
    deficit = max(0.0, 0.95 - availability)
    if deficit > 0.0:
        from ml_models.lib.objective import INFEASIBLE_FLOOR

        value = float(INFEASIBLE_FLOOR + 1e10 * deficit)
    else:
        value = float(annual_cost)

    rewards = [
        -(p["annual_cost"] / env.cost_scale + 100.0 * p["deficit"]) for p in per_printer
    ]
    return {
        "annual_cost": annual_cost,
        "availability": availability,
        "deficit": deficit,
        "value": value,
        "mean_reward": float(np.mean(rewards)),
        "per_printer": per_printer,
        "actions": actions,
    }


def train_ppo(
    train_env: MaintenanceBanditEnv,
    val_env: MaintenanceBanditEnv,
    config: PPOConfig | None = None,
    *,
    warm_start_tau: Mapping[str, float] | None = None,
    save_dir: str | Path | None = None,
) -> tuple[PPO, TrainHistory]:
    """Train PPO on ``train_env`` with periodic deterministic eval on ``val_env``."""
    if config is None:
        config = PPOConfig()

    save_dir_p = Path(save_dir) if save_dir is not None else None
    if save_dir_p is not None:
        save_dir_p.mkdir(parents=True, exist_ok=True)
    best_path = save_dir_p / "ppo_policy_best.zip" if save_dir_p else None

    vec_env: VecEnv = DummyVecEnv([lambda env=train_env: env])

    policy_kwargs = make_mlp_policy_kwargs(
        net_arch=config.net_arch,
        log_std_init=config.log_std_init,
    )
    model = PPO(
        "MlpPolicy",
        vec_env,
        learning_rate=config.learning_rate,
        n_steps=config.n_steps,
        batch_size=config.batch_size,
        n_epochs=config.n_epochs,
        gamma=config.gamma,
        gae_lambda=config.gae_lambda,
        clip_range=config.clip_range,
        ent_coef=config.ent_coef,
        vf_coef=config.vf_coef,
        max_grad_norm=config.max_grad_norm,
        policy_kwargs=policy_kwargs,
        seed=config.seed,
        verbose=0,
    )

    if warm_start_tau is not None:
        warm_start_from_tau(model.policy, dict(warm_start_tau))

    history = TrainHistory()
    callback = _ValidationCallback(
        val_env=val_env,
        every=config.val_eval_every,
        save_path=best_path,
        history=history,
    )
    model.learn(total_timesteps=config.total_timesteps, callback=callback, progress_bar=False)

    # Final eval — guarantees at least one entry in history at the end.
    final = evaluate_policy_on_env(model, val_env, deterministic=True)
    history.val_timesteps.append(int(config.total_timesteps))
    history.val_rewards.append(float(final["mean_reward"]))
    history.val_annual_costs.append(float(final["annual_cost"]))
    history.val_availabilities.append(float(final["availability"]))
    history.val_values.append(float(final["value"]))
    if final["value"] < history.best_val_value:
        history.best_val_value = float(final["value"])
        history.best_val_at = int(config.total_timesteps)
        if best_path is not None:
            model.save(str(best_path))

    if save_dir_p is not None:
        with (save_dir_p / "training_history.json").open("w", encoding="utf-8") as handle:
            json.dump(history.to_json(), handle, indent=2)
        model.save(str(save_dir_p / "ppo_policy_final.zip"))

    return model, history


def set_torch_threads(num: int = 1) -> None:
    """Limit torch CPU threads — helpful when the simulator is the bottleneck."""
    torch.set_num_threads(num)
