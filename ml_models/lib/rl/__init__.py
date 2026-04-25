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
    bootstrap_fleet_ci,
    evaluate_constant_tau,
    evaluate_per_printer_policy,
    evaluate_per_tick_per_printer,
    kpi_comparison_table,
    kpi_comparison_table_with_ci,
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
from .per_tick_env import MaintenancePerTickEnv, make_per_tick_vec_env
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
from .recurrent_trainer import (
    EnsemblePolicy,
    PerTickHistory,
    PerTickPPOConfig,
    build_ppo,
    evaluate_per_tick_policy,
    train_multi_seed,
    train_per_tick,
)
from .spr import (
    SharedSPRFeaturesExtractor,
    SPRCallback,
    SPRModule,
    SPRPredictor,
    SPRStats,
    extract_spr_tuples_from_buffer,
)

__all__ = [
    # Encoder
    "DEFAULT_MODELS_DIR",
    "SSLEncoderBundle",
    "load_ssl_encoder",
    "random_encoder_bundle",
    # Bandit env
    "MaintenanceBanditEnv",
    "TAU_RANGES",
    "CLIMATE_FEATURE_COLS",
    "action_to_tau",
    "tau_to_action",
    # Per-tick env
    "MaintenancePerTickEnv",
    "make_per_tick_vec_env",
    # Policy / bandit trainer
    "make_mlp_policy_kwargs",
    "warm_start_action_mean",
    "warm_start_from_tau",
    "PPOConfig",
    "TrainHistory",
    "evaluate_policy_on_env",
    "set_torch_threads",
    "train_ppo",
    # SPR
    "SharedSPRFeaturesExtractor",
    "SPRCallback",
    "SPRModule",
    "SPRPredictor",
    "SPRStats",
    "extract_spr_tuples_from_buffer",
    # Per-tick trainer
    "EnsemblePolicy",
    "PerTickHistory",
    "PerTickPPOConfig",
    "build_ppo",
    "evaluate_per_tick_policy",
    "train_multi_seed",
    "train_per_tick",
    # Eval
    "bootstrap_fleet_ci",
    "evaluate_constant_tau",
    "evaluate_per_printer_policy",
    "evaluate_per_tick_per_printer",
    "kpi_comparison_table",
    "kpi_comparison_table_with_ci",
    "load_ppo",
    "per_printer_table_for_constant_tau",
]
