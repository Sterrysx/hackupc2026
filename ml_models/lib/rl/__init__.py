"""Reinforcement-learning building blocks for Stage 03 (`03_rl+ssl/`).

Importable as ``ml_models.lib.rl.*`` so the Stage 03 notebooks, tests and
downstream stages can all reach the same code path. Kept here (not inside
``ml_models/03_rl+ssl/``) because the stage folder name contains ``+`` and
is not a valid Python package identifier.
"""
from __future__ import annotations

from .encoder_loader import (
    DEFAULT_MODELS_DIR,
    SSLEncoderBundle,
    load_ssl_encoder,
    random_encoder_bundle,
)
from .eval import (
    evaluate_constant_tau,
    evaluate_per_printer_policy,
    kpi_comparison_table,
    load_ppo,
    per_printer_table_for_constant_tau,
)
from .gym_env import (
    CLIMATE_FEATURE_COLS,
    MaintenanceBanditEnv,
    TAU_RANGES,
    action_to_tau,
    tau_to_action,
)
from .policy import (
    make_mlp_policy_kwargs,
    warm_start_action_mean,
    warm_start_from_tau,
)
from .ppo_trainer import (
    PPOConfig,
    TrainHistory,
    evaluate_policy_on_env,
    set_torch_threads,
    train_ppo,
)

__all__ = [
    "DEFAULT_MODELS_DIR",
    "SSLEncoderBundle",
    "load_ssl_encoder",
    "random_encoder_bundle",
    "MaintenanceBanditEnv",
    "TAU_RANGES",
    "CLIMATE_FEATURE_COLS",
    "action_to_tau",
    "tau_to_action",
    "make_mlp_policy_kwargs",
    "warm_start_action_mean",
    "warm_start_from_tau",
    "PPOConfig",
    "TrainHistory",
    "evaluate_policy_on_env",
    "set_torch_threads",
    "train_ppo",
    "evaluate_constant_tau",
    "evaluate_per_printer_policy",
    "kpi_comparison_table",
    "load_ppo",
    "per_printer_table_for_constant_tau",
]
