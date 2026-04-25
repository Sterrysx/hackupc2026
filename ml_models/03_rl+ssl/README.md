# Stage 03 — RL on top of the SSL encoder (deferred)

This folder is intentionally a **scaffold** for now. The user has chosen to
ship Stages 01 and 02 first.

## Planned approach

Reinforcement-learning policy that consumes representations from the SSL
encoder trained in `02_ssl/01_pretrain.ipynb` and outputs a maintenance
schedule for the HP Metal Jet S100.

Two action-space variants are on the table; both share the same SSL backbone:

1. **Static-τ policy** — outputs a 6-dim vector, optimised episode-wise.
   Apples-to-apples comparison with Stages 01 & 02.
2. **Per-tick policy** — observes daily telemetry, decides each day whether
   to trigger a preventive event per component. State-dependent, more
   powerful, harder to train.

## Open decisions before implementation

- Action space (static-τ vs per-tick) — see options above.
- Library (Stable-Baselines3 PPO/SAC vs hand-rolled PyTorch).
- Reward shaping — direct `−annual_cost` vs Lagrangian for the availability
  constraint.
- Episode length and printer sampling within each episode.

## Reusable building blocks already in place

- `ml_models/lib/env_runner.run_with_tau` — drop-in wrapper around the SDG
  simulator. A `gymnasium.Env` adapter on top of this gives the RL agent a
  deterministic-per-printer environment.
- `ml_models/lib/objective.scalar_objective` — single-scalar reward with the
  availability penalty already baked in.
- `ml_models/02_ssl/models/ssl_encoder.pt` — frozen feature extractor.

When work resumes, start by sketching the `gymnasium.Env` adapter inside
`lib/` (so it is reusable), then plug it into the chosen RL library.
