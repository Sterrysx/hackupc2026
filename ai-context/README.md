# `ai-context/` — upfront design briefs

This folder archives the design briefs, challenge material, and agent-workflow
rules that were written **before** implementation and fed as context to the AI
coding agent that built the system. They describe *intent*, not the shipped
code.

For the shipped system and how to run it, start at the repo root:

- [`../README.md`](../README.md)
- [`../WALKTHROUGH.md`](../WALKTHROUGH.md)
- [`../report/AI_IMPLEMENTATION.md`](../report/AI_IMPLEMENTATION.md)

## Contents

| File | Purpose |
|---|---|
| `BRIEF.md` | Distilled sprint cheatsheet of the four `challenge-context/*.md` docs. |
| `CONTEXT.md` | Full system-design context fed to the agent. |
| `CLAUDE.md` | Workflow rules and architecture notes for the Claude Code agent. |
| `PLAN.md` | Phase-1 synthetic-data-generator build plan. |
| `digital_twin_hp_metal_jet_s100_spec.md` | Original technical spec (ES). |
| `digital_twin_degradation_functions.md` | Component degradation equations (ES). |
| `climate_location_module.md` | Climate-to-indoor transfer functions (ES). |
| `challenge-context/` | Hackathon organisers' brief material, verbatim. |

Implementation may have diverged from these docs in places (e.g. the shipped
simulator covers 10 years, not the 5 initially specified). Treat everything
here as historical input, not ground truth.
