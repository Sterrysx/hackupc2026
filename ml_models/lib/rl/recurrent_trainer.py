"""PPO trainer for the per-tick maintenance env, with SPR auxiliary loss.

Plain PPO (feedforward, no LSTM) over the 52-d per-tick observation. Uses
:class:`SharedSPRFeaturesExtractor` so the policy's trunk doubles as the
SPR online encoder — backprop from the SPR aux loss flows through the
trunk alongside PPO's actor/critic gradients.

The action space is ``MultiBinary(6)``; SB3 PPO handles this with a
Bernoulli distribution head.

Despite the file name, this is a feedforward PPO — the per-tick observation
is fully observable enough that an MLP works. A RecurrentPPO variant (LSTM
over the obs sequence) is a stretch goal kept for later because integrating
SPR with the LSTM features extractor adds non-trivial wiring.

Multi-seed training: :func:`train_multi_seed` runs the same config under
N different seeds, saves each model, and exposes :func:`ensemble_predict`
to average their actions at evaluation time.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CallbackList
from stable_baselines3.common.vec_env import DummyVecEnv, VecEnv

from sdg.schema import COMPONENT_IDS

from .per_tick_env import MaintenancePerTickEnv
from .spr import SharedSPRFeaturesExtractor, SPRCallback, SPRModule


@dataclass
class PerTickPPOConfig:
    """Hyperparameters for the per-tick PPO run."""

    total_timesteps: int = 50_000
    n_steps: int = 256
    batch_size: int = 64
    n_epochs: int = 6
    learning_rate: float = 3e-4
    clip_range: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    gamma: float = 0.995    # daily discount; ≈ 6-month effective horizon
    gae_lambda: float = 0.95
    seed: int = 0
    features_dim: int = 64
    hidden_dims: tuple[int, ...] = (128, 128)
    spr_weight: float = 0.5
    spr_k: int = 1
    spr_ema_tau: float = 0.01
    spr_lr: float = 3e-4
    val_eval_every: int = 5_000   # timesteps between val sweeps


@dataclass
class PerTickHistory:
    val_timesteps: list[int] = field(default_factory=list)
    val_annual_costs: list[float] = field(default_factory=list)
    val_availabilities: list[float] = field(default_factory=list)
    val_values: list[float] = field(default_factory=list)
    spr_losses: list[float] = field(default_factory=list)
    best_val_value: float = float("inf")
    best_val_at: int = -1

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class _PerTickValCallback(BaseCallback):
    """Run the policy deterministically on each val printer, log fleet KPIs."""

    def __init__(
        self,
        val_env: MaintenancePerTickEnv,
        every: int,
        save_path: Path | None,
        history: PerTickHistory,
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
        kpis = evaluate_per_tick_policy(self.model, self._val_env, deterministic=True)
        self._history.val_timesteps.append(int(self.num_timesteps))
        self._history.val_annual_costs.append(float(kpis["annual_cost"]))
        self._history.val_availabilities.append(float(kpis["availability"]))
        self._history.val_values.append(float(kpis["value"]))
        is_better = kpis["value"] < self._history.best_val_value
        if is_better:
            self._history.best_val_value = float(kpis["value"])
            self._history.best_val_at = int(self.num_timesteps)
            if self._save_path is not None:
                self.model.save(str(self._save_path))
        if self.verbose:
            tag = "feasible" if kpis["availability"] >= 0.95 else "INFEASIBLE"
            print(
                f"[val @ {self.num_timesteps:>6}ts] "
                f"value={kpis['value']:.3e}  cost={kpis['annual_cost']:.3e}  "
                f"avail={kpis['availability']:.4f}  ({tag})"
                + ("  <- best" if is_better else "")
            )
        return True


def evaluate_per_tick_policy(
    model: PPO,
    env: MaintenancePerTickEnv,
    *,
    deterministic: bool = True,
) -> dict[str, Any]:
    """Run one full episode per printer in ``env``, aggregate fleet KPIs.

    Episode summary (annual_cost, availability) is collected from each
    printer. Fleet annual_cost = mean across printers; fleet availability =
    mean across printers; value follows the Stage 01/02 contract — feasible
    trials report annual_cost, infeasible trials are pushed above
    ``INFEASIBLE_FLOOR``.
    """
    from ml_models.lib.objective import INFEASIBLE_FLOOR

    per_printer: list[dict[str, Any]] = []
    for printer_id in env.printer_ids:
        obs, _ = env.reset(seed=int(printer_id), options={"printer_id": int(printer_id)})
        terminated = False
        truncated = False
        last_info: dict[str, Any] = {}
        while not (terminated or truncated):
            action, _ = model.predict(obs, deterministic=deterministic)
            obs, _r, terminated, truncated, last_info = env.step(action)
        summary = last_info.get("episode_summary", {})
        per_printer.append(
            {
                "printer_id": int(printer_id),
                "annual_cost": float(summary.get("annual_cost", float("nan"))),
                "availability": float(summary.get("availability", float("nan"))),
                "deficit": float(summary.get("deficit", 0.0)),
                "n_preventive": int(summary.get("n_preventive", 0)),
                "n_corrective": int(summary.get("n_corrective", 0)),
            }
        )
    if not per_printer:
        return {"value": float("inf"), "annual_cost": float("nan"),
                "availability": 0.0, "deficit": 1.0, "per_printer": []}
    annual_cost = float(np.mean([p["annual_cost"] for p in per_printer]))
    availability = float(np.mean([p["availability"] for p in per_printer]))
    deficit = max(0.0, 0.95 - availability)
    if deficit > 0.0:
        value = float(INFEASIBLE_FLOOR + 1e10 * deficit)
    else:
        value = float(annual_cost)
    return {
        "value": value,
        "annual_cost": annual_cost,
        "availability": availability,
        "deficit": deficit,
        "per_printer": per_printer,
    }


def build_ppo(
    env: VecEnv,
    config: PerTickPPOConfig,
    *,
    device: torch.device | str = "auto",
) -> PPO:
    """Build PPO with SharedSPRFeaturesExtractor as the policy trunk."""
    policy_kwargs = {
        "features_extractor_class": SharedSPRFeaturesExtractor,
        "features_extractor_kwargs": {
            "features_dim": int(config.features_dim),
            "hidden_dims": tuple(config.hidden_dims),
        },
        # MlpPolicy heads sit on top of the (features_dim,) trunk output.
        "net_arch": dict(pi=[64], vf=[64]),
        "ortho_init": True,
    }
    return PPO(
        "MlpPolicy",
        env,
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
        device=device,
    )


def train_per_tick(
    train_env: MaintenancePerTickEnv | VecEnv,
    val_env: MaintenancePerTickEnv,
    config: PerTickPPOConfig | None = None,
    *,
    save_dir: str | Path | None = None,
    use_spr: bool = True,
) -> tuple[PPO, PerTickHistory, SPRModule | None]:
    """Train per-tick PPO with optional SPR auxiliary loss.

    ``train_env`` may be either a single ``MaintenancePerTickEnv`` (default
    DummyVecEnv wrap, sequential) or a pre-built ``VecEnv``. Pass the
    output of :func:`make_per_tick_vec_env` to step multiple envs across
    subprocesses for a ~Nx throughput win on multi-core CPUs.
    """
    if config is None:
        config = PerTickPPOConfig()
    save_dir_p = Path(save_dir) if save_dir is not None else None
    if save_dir_p is not None:
        save_dir_p.mkdir(parents=True, exist_ok=True)
    best_path = save_dir_p / "ppo_per_tick_best.zip" if save_dir_p else None

    if isinstance(train_env, VecEnv):
        vec_env = train_env
    else:
        vec_env = DummyVecEnv([lambda env=train_env: env])
    model = build_ppo(vec_env, config)

    spr: SPRModule | None = None
    history = PerTickHistory()
    callbacks: list[BaseCallback] = [
        _PerTickValCallback(val_env, config.val_eval_every, best_path, history),
    ]
    if use_spr:
        spr = SPRModule.from_policy(
            model.policy,
            action_dim=len(COMPONENT_IDS),
            k=config.spr_k,
            ema_tau=config.spr_ema_tau,
            learning_rate=config.spr_lr,
        )
        callbacks.append(SPRCallback(spr, weight=config.spr_weight))

    model.learn(total_timesteps=config.total_timesteps, callback=CallbackList(callbacks))

    # Final eval to guarantee history has at least one sample at the end.
    final = evaluate_per_tick_policy(model, val_env, deterministic=True)
    history.val_timesteps.append(int(config.total_timesteps))
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
        model.save(str(save_dir_p / "ppo_per_tick_final.zip"))
    return model, history, spr


def train_multi_seed(
    train_env_factory,
    val_env_factory,
    config: PerTickPPOConfig | None = None,
    *,
    seeds: Sequence[int] = (0, 1, 2),
    save_dir: str | Path,
    use_spr: bool = True,
) -> dict[str, Any]:
    """Train one PPO model per seed; return paths + per-seed histories.

    ``train_env_factory`` and ``val_env_factory`` are zero-arg callables
    that build a fresh ``MaintenancePerTickEnv`` (envs are not pickleable
    across SB3's seed re-seeding so we rebuild per seed).
    """
    if config is None:
        config = PerTickPPOConfig()
    save_dir_p = Path(save_dir)
    save_dir_p.mkdir(parents=True, exist_ok=True)
    seed_results: dict[str, Any] = {}
    for seed in seeds:
        seed_dir = save_dir_p / f"seed_{seed}"
        seed_dir.mkdir(parents=True, exist_ok=True)
        cfg = PerTickPPOConfig(**{**asdict(config), "seed": int(seed)})
        train_env = train_env_factory()
        val_env = val_env_factory()
        model, history, _spr = train_per_tick(
            train_env, val_env, cfg, save_dir=seed_dir, use_spr=use_spr
        )
        seed_results[str(seed)] = {
            "best_path": str(seed_dir / "ppo_per_tick_best.zip"),
            "final_path": str(seed_dir / "ppo_per_tick_final.zip"),
            "best_val_value": float(history.best_val_value),
            "best_val_at": int(history.best_val_at),
            "final_value": float(history.val_values[-1]) if history.val_values else float("inf"),
        }
    with (save_dir_p / "multi_seed_summary.json").open("w", encoding="utf-8") as handle:
        json.dump(seed_results, handle, indent=2)
    return seed_results


class EnsemblePolicy:
    """Average actions across multiple trained per-tick policies.

    For ``MultiBinary`` actions this means: predict logits-equivalent (the
    SB3 ``predict(deterministic=True)`` returns the argmax of the Bernoulli
    distribution per dim), so ensembling is majority-vote per component.
    For ``deterministic=False``, sample from the average distribution.
    """

    def __init__(self, models: Sequence[PPO]) -> None:
        if not models:
            raise ValueError("ensemble needs at least one model")
        self.models = list(models)

    @classmethod
    def load(cls, paths: Sequence[str | Path]) -> "EnsemblePolicy":
        models = [PPO.load(str(p)) for p in paths]
        return cls(models)

    def predict(
        self,
        observation: np.ndarray,
        *,
        deterministic: bool = True,
    ) -> tuple[np.ndarray, None]:
        votes = np.zeros(len(COMPONENT_IDS), dtype=np.float32)
        for model in self.models:
            action, _ = model.predict(observation, deterministic=deterministic)
            votes += np.asarray(action, dtype=np.float32).reshape(-1)
        # Majority vote per component (≥ half the models maintain → maintain).
        consensus = (votes >= (len(self.models) / 2.0)).astype(np.int64)
        return consensus, None
