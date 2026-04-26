"""Self-Predictive Representations (SPR) auxiliary loss for joint SSL+RL.

SPR (Schwarzer et al., 2021 — *Data-Efficient Reinforcement Learning with
Self-Predictive Representations*) regularises the policy's representation by
asking the encoder to predict future latent states from current latent state
+ action history. An EMA of the online encoder produces the target embedding
(BYOL-style, no negatives), so the loss is a simple MSE in latent space.

This module is *coupled* to the PPO policy through a shared
``BaseFeaturesExtractor``: the same trunk that produces features for the
PPO policy heads also produces the SPR online embedding, so backprop from
the SPR auxiliary loss flows into the encoder weights — i.e. the encoder is
"unfrozen" during PPO and specialises toward the maintenance task.

Usage::

    extractor_kwargs = {"features_dim": 64}
    model = PPO(
        "MlpPolicy", env,
        policy_kwargs={
            "features_extractor_class": SharedSPRFeaturesExtractor,
            "features_extractor_kwargs": extractor_kwargs,
        },
    )
    spr = SPRModule.from_policy(model.policy, action_dim=6, k=1)
    callback = SPRCallback(spr, weight=0.5)
    model.learn(total_timesteps=N, callback=callback)
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import torch
from gymnasium import spaces
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from torch import nn
from torch.nn import functional as F


class SharedSPRFeaturesExtractor(BaseFeaturesExtractor):
    """Small MLP trunk that doubles as the SPR online encoder.

    Tanh activations match SB3's MlpPolicy default; output dim is the
    features_dim that the PPO policy heads then consume. Keeping the trunk
    small (~10k params) means SPR updates are cheap.
    """

    def __init__(
        self,
        observation_space: spaces.Box,
        features_dim: int = 64,
        hidden_dims: Iterable[int] = (128, 128),
    ) -> None:
        super().__init__(observation_space, features_dim)
        if not isinstance(observation_space, spaces.Box):
            raise TypeError("SharedSPRFeaturesExtractor expects a Box observation space")
        in_dim = int(np.prod(observation_space.shape))
        layers: list[nn.Module] = []
        last = in_dim
        for h in hidden_dims:
            layers += [nn.Linear(last, int(h)), nn.Tanh()]
            last = int(h)
        layers += [nn.Linear(last, features_dim), nn.Tanh()]
        self.trunk = nn.Sequential(*layers)

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        return self.trunk(observations)


class SPRPredictor(nn.Module):
    """Predict z_{t+k} from z_t plus the action sequence a_t..a_{t+k-1}.

    Implementation is a small GRU over the action sequence with z_t as
    initial hidden state, followed by an MLP head; for ``k=1`` this reduces
    to ``MLP([z_t, a_t]) → z_pred``.
    """

    def __init__(
        self,
        latent_dim: int,
        action_dim: int,
        hidden_dim: int = 128,
    ) -> None:
        super().__init__()
        self.latent_dim = int(latent_dim)
        self.action_dim = int(action_dim)
        self.action_to_hidden = nn.Linear(self.action_dim, self.latent_dim)
        self.gru = nn.GRUCell(self.latent_dim, self.latent_dim)
        self.head = nn.Sequential(
            nn.Linear(self.latent_dim, hidden_dim),
            nn.Tanh(),
            nn.Linear(hidden_dim, self.latent_dim),
        )

    def forward(self, z0: torch.Tensor, action_seq: torch.Tensor) -> torch.Tensor:
        """Predict z_{t+k} from z_t = z0 and a_t..a_{t+k-1} = action_seq.

        Parameters
        ----------
        z0 : (B, latent_dim)
        action_seq : (B, k, action_dim) float — actions are ints/bools cast to float.
        """
        if action_seq.ndim != 3:
            raise ValueError(f"action_seq must be (B, k, A); got {action_seq.shape}")
        h = z0
        steps = int(action_seq.shape[1])
        for t in range(steps):
            a = action_seq[:, t, :]
            inp = self.action_to_hidden(a)
            h = self.gru(inp, h)
        return self.head(h)


@dataclass
class SPRStats:
    last_loss: float = 0.0
    n_updates: int = 0
    n_samples_total: int = 0


class SPRModule:
    """Online encoder (= shared with policy trunk) + EMA target + predictor.

    The online encoder is the policy's ``features_extractor.trunk``. SPR
    updates it via gradients from the auxiliary loss, alongside PPO's
    gradient from the actor-critic loss. The target encoder is a copy of
    the trunk that lags behind via Polyak averaging.
    """

    def __init__(
        self,
        online_extractor: SharedSPRFeaturesExtractor,
        action_dim: int,
        *,
        k: int = 1,
        ema_tau: float = 0.01,
        learning_rate: float = 3e-4,
        device: torch.device | str | None = None,
    ) -> None:
        if not isinstance(online_extractor, SharedSPRFeaturesExtractor):
            raise TypeError(
                "SPRModule requires SharedSPRFeaturesExtractor; got "
                f"{type(online_extractor).__name__}"
            )
        if k < 1:
            raise ValueError("k must be >= 1")
        self.online_extractor = online_extractor
        self.k = int(k)
        self.ema_tau = float(ema_tau)
        if device is None:
            device = next(online_extractor.parameters()).device
        elif isinstance(device, str):
            device = torch.device(device)
        self.device = device

        # Frozen target — same architecture, no gradient flow.
        self.target_extractor = copy.deepcopy(online_extractor).to(device)
        for param in self.target_extractor.parameters():
            param.requires_grad_(False)

        latent_dim = int(online_extractor.features_dim)
        self.predictor = SPRPredictor(latent_dim=latent_dim, action_dim=action_dim).to(device)
        params = list(self.online_extractor.parameters()) + list(self.predictor.parameters())
        self.optimizer = torch.optim.Adam(params, lr=learning_rate)
        self.stats = SPRStats()

    # ------------------------------------------------------------------
    @classmethod
    def from_policy(cls, policy, action_dim: int, **kwargs) -> "SPRModule":
        return cls(policy.features_extractor, action_dim=action_dim, **kwargs)

    # ------------------------------------------------------------------
    @torch.no_grad()
    def soft_update_target(self) -> None:
        for online_p, target_p in zip(
            self.online_extractor.parameters(),
            self.target_extractor.parameters(),
            strict=True,
        ):
            target_p.data.mul_(1.0 - self.ema_tau).add_(online_p.data, alpha=self.ema_tau)

    def compute_and_step(
        self,
        obs_t: torch.Tensor,        # (B, obs_dim)
        action_seq: torch.Tensor,   # (B, k, action_dim)
        obs_tk: torch.Tensor,       # (B, obs_dim)
    ) -> float:
        """One SPR update: gradient step on the predictor + online encoder, EMA target update."""
        if obs_t.shape[0] == 0:
            return float("nan")
        obs_t = obs_t.to(self.device)
        action_seq = action_seq.to(self.device)
        obs_tk = obs_tk.to(self.device)

        z_t = self.online_extractor(obs_t)
        with torch.no_grad():
            z_target = self.target_extractor(obs_tk)
        z_pred = self.predictor(z_t, action_seq)

        # Cosine-similarity SPR loss (BYOL-style); equivalent to MSE on
        # ℓ2-normalised vectors but more numerically stable.
        z_pred_n = F.normalize(z_pred, dim=-1, eps=1e-8)
        z_target_n = F.normalize(z_target.detach(), dim=-1, eps=1e-8)
        loss = -(z_pred_n * z_target_n).sum(dim=-1).mean()

        self.optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            list(self.online_extractor.parameters()) + list(self.predictor.parameters()),
            max_norm=1.0,
        )
        self.optimizer.step()
        self.soft_update_target()

        loss_value = float(loss.detach().cpu().item())
        self.stats.last_loss = loss_value
        self.stats.n_updates += 1
        self.stats.n_samples_total += int(obs_t.shape[0])
        return loss_value


def extract_spr_tuples_from_buffer(
    obs_buffer: np.ndarray,
    action_buffer: np.ndarray,
    episode_starts: np.ndarray,
    *,
    k: int = 1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build (obs_t, action_seq, obs_{t+k}) tuples from an SB3 rollout buffer.

    Skips tuples that would span an episode boundary (i.e. any
    ``episode_starts`` flag set in [t+1, t+k]).

    Parameters
    ----------
    obs_buffer : (n_steps, n_envs, obs_dim)
    action_buffer : (n_steps, n_envs, action_dim)
    episode_starts : (n_steps, n_envs) — 1 where a new episode begins at that step.
    k : int — prediction horizon.
    """
    n_steps, n_envs = obs_buffer.shape[0], obs_buffer.shape[1]
    obs_t_list: list[np.ndarray] = []
    obs_tk_list: list[np.ndarray] = []
    action_seq_list: list[np.ndarray] = []
    for env_idx in range(n_envs):
        for t in range(n_steps - k):
            crosses_boundary = bool(np.any(episode_starts[t + 1: t + 1 + k, env_idx]))
            if crosses_boundary:
                continue
            obs_t_list.append(obs_buffer[t, env_idx])
            obs_tk_list.append(obs_buffer[t + k, env_idx])
            action_seq_list.append(action_buffer[t: t + k, env_idx])
    if not obs_t_list:
        empty = np.zeros((0, *obs_buffer.shape[2:]), dtype=obs_buffer.dtype)
        empty_a = np.zeros((0, k, action_buffer.shape[-1]), dtype=action_buffer.dtype)
        return empty, empty_a, empty
    return (
        np.stack(obs_t_list, axis=0),
        np.stack(action_seq_list, axis=0),
        np.stack(obs_tk_list, axis=0),
    )


class SPRCallback(BaseCallback):
    """Run a single SPR update at the end of each PPO rollout.

    The callback drains a (obs_t, action_seq, obs_{t+k}) batch from the SB3
    rollout buffer, computes the SPR loss + EMA-updates the target encoder.
    The online encoder is shared with the PPO policy via the features
    extractor, so its weights are updated by both PPO and SPR objectives.
    """

    def __init__(
        self,
        spr: SPRModule,
        *,
        weight: float = 1.0,
        max_batch: int = 1024,
        verbose: int = 0,
    ) -> None:
        super().__init__(verbose)
        self.spr = spr
        self.weight = float(weight)
        self.max_batch = int(max_batch)

    def _on_step(self) -> bool:
        return True

    def _on_rollout_end(self) -> None:
        if self.weight <= 0.0:
            return
        rb = self.model.rollout_buffer
        # SB3 stores observations as (n_steps, n_envs, obs_dim) for
        # OnPolicyAlgorithm Box obs.
        obs_buf = np.asarray(rb.observations)
        action_buf = np.asarray(rb.actions, dtype=np.float32)
        # SB3 stores episode_starts as (n_steps, n_envs).
        episode_starts = np.asarray(rb.episode_starts, dtype=np.bool_)

        obs_t, action_seq, obs_tk = extract_spr_tuples_from_buffer(
            obs_buf, action_buf, episode_starts, k=self.spr.k
        )
        if obs_t.shape[0] == 0:
            return
        if obs_t.shape[0] > self.max_batch:
            idx = self.model.rollout_buffer.swap_and_flatten if False else None  # unused
            rng = np.random.default_rng()
            keep = rng.choice(obs_t.shape[0], size=self.max_batch, replace=False)
            obs_t = obs_t[keep]
            action_seq = action_seq[keep]
            obs_tk = obs_tk[keep]

        loss = self.spr.compute_and_step(
            torch.as_tensor(obs_t, dtype=torch.float32),
            torch.as_tensor(action_seq, dtype=torch.float32),
            torch.as_tensor(obs_tk, dtype=torch.float32),
        )
        if self.verbose:
            print(
                f"[SPR @ rollout {self.spr.stats.n_updates}] "
                f"loss={loss:.4f}  samples={obs_t.shape[0]}"
            )
        self.logger.record("spr/loss", float(loss))
        self.logger.record("spr/n_samples", int(obs_t.shape[0]))
