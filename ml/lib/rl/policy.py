"""Policy helpers for the SSL+RL stage.

The default Stable-Baselines3 ``MlpPolicy`` is fine for our 275-d observation
→ 6-d continuous-action setup — the encoder pre-encodes inside the env, so
the policy only sees a fixed-size float vector. No custom features extractor
is needed.

What lives here are utilities to:
- **Warm-start** the policy mean to the τ vector found by Stages 01 / 02.
  This drastically shortens convergence by exploiting the surrogate prior.
- **Anchor regulariser** to keep the policy near a known-good τ during
  early training (optional, applied via callback).
"""
from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np
import torch
from torch import nn

from backend.simulator.schema import COMPONENT_IDS

from .gym_env import TAU_RANGES, tau_to_action


def warm_start_action_mean(policy: nn.Module, target_action: np.ndarray) -> None:
    """Overwrite the action-mean bias so the initial Gaussian is centred on ``target_action``.

    Works on Stable-Baselines3 ``ActorCriticPolicy`` whose ``action_net`` is a
    single ``Linear`` mapping shared features → action mean. We zero its
    weights and load the desired action into the bias — the policy then
    starts emitting ``target_action`` regardless of the observation, and PPO
    moves it from there. The action log-std is left untouched so the agent
    still explores around the warm-start.
    """
    if target_action.shape != (len(COMPONENT_IDS),):
        raise ValueError(
            f"target_action shape {target_action.shape} != ({len(COMPONENT_IDS)},)"
        )
    action_net = getattr(policy, "action_net", None)
    if not isinstance(action_net, nn.Linear):
        raise TypeError(
            f"expected policy.action_net to be nn.Linear, got {type(action_net)}"
        )
    with torch.no_grad():
        action_net.weight.zero_()
        bias = torch.from_numpy(np.asarray(target_action, dtype=np.float32))
        action_net.bias.copy_(bias.to(action_net.bias.device))


def warm_start_from_tau(
    policy: nn.Module,
    tau_vector: Mapping[str, float],
    *,
    tau_ranges: Mapping[str, tuple[float, float]] = TAU_RANGES,
) -> np.ndarray:
    """Convenience: warm-start the policy mean from a τ dict (e.g. Stage 02 winner)."""
    action = tau_to_action(tau_vector, tau_ranges)
    warm_start_action_mean(policy, action)
    return action


def make_mlp_policy_kwargs(
    *,
    net_arch: Sequence[int] = (128, 128),
    log_std_init: float = -1.0,
    activation_fn: type[nn.Module] = nn.Tanh,
) -> dict:
    """Default ``policy_kwargs`` for ``PPO("MlpPolicy", ...)``.

    A small Tanh-activated trunk on top of the pre-encoded 275-d observation.
    ``log_std_init=-1`` starts σ ≈ 0.37 in action units — broad enough to
    explore without immediately drifting outside [-1, 1].
    """
    return {
        "net_arch": dict(pi=list(net_arch), vf=list(net_arch)),
        "activation_fn": activation_fn,
        "log_std_init": float(log_std_init),
        "ortho_init": True,
    }
