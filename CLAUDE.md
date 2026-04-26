# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

Python 3.12 in a conda env (`hackupc`), packages managed by `uv` against `pyproject.toml` + `uv.lock`. Frontend is Vite + React 19 under `frontend/` (separate `npm` toolchain).

```bash
uv sync                                              # (re-)install deps into .venv
uv run python -m uvicorn backend.app:app --reload    # run the FastAPI backend (port 8000)
cd frontend && npm install && npm run dev            # run the dashboard (port 5173)
uv run pytest                                        # offline test suite (live tests auto-skip)
uv run pytest tests/test_twin_data.py::test_name     # single test
uv run pytest -m live                                # live e2e — requires GROQ_API_KEY
make run                                             # both servers in one terminal
make run-back / make run-front                       # one process at a time
make test / make test-live / make test-e2e           # tagged test runs via Makefile
make demo-e2e                                        # narrated 5-act judges' walkthrough
make train / make train-fast                         # execute every ML notebook end-to-end
ml/train.sh 2                                        # one stage only (0|1|2|3|4)
uv add <pkg> / uv remove <pkg>                       # dependency changes (commit both files)
```

`pyproject.toml` pins two pytest behaviors that matter when adding tests:
- default selection is `-m "not live"`, so tests marked `@pytest.mark.live` only run when opted into.
- import mode is `importlib` with `pythonpath = ["."]` — `from backend.app import app` works, but new top-level packages must be added to `[tool.setuptools] packages` so `uv sync` keeps them importable.

## Git workflow

```bash
make new-branch name=feat/your-feature   # branch off latest main (feat/ or fix/ enforced)
make pr                                  # push + open PR interactively
```

`/review <PR#>` inside Claude Code posts an AI review on a PR.

## Architecture

This is a 36hr hackathon entry: a **Digital Co-Pilot for the HP Metal Jet S100** (binder-jet metal printer). The system is structured as the three phases the challenge brief mandates — **Model → Simulate → Interact** — plus a frontend dashboard. Read `BRIEF.md` (and `challenge-context/*.md`) for the scoring rubric and demo narrative; the data contracts there are load-bearing.

### Top-level layout

| Path | Role |
|---|---|
| `backend/app.py` | FastAPI entrypoint — single process exposing `/twin/*` (Stage 1+2 data), `/agent/*` (Stage 3 LLM), `/telemetry`, `/stt/*`, `/tts/*`, and a `/ws/notifications` websocket. |
| `backend/main.py` | CLI fallback that runs one agent query against stdin (used for smoke testing without the API). |
| `backend/simulator/` | **Phase 1+2 — synthetic data generator + simulator.** `backend/simulator/core/simulator.py` advances time and calls per-component degradation models from `core/component.py` & `core/degradation.py`. Configuration lives in `backend/simulator/config/*.yaml` (cities, components, couplings, climate). Output is `data/train/fleet_baseline.parquet`. |
| `backend/agent/` | **Phase 3 — grounded LangGraph agent.** Pattern C (agentic diagnosis): `gatherer → tools → extract_telemetry → synthesizer → guardrail`. See `backend/agent/README.md`. |
| `backend/voice/stt/`, `backend/voice/tts/` | Voice I/O — `faster-whisper` STT and `edge-tts` TTS, each one thin class. |
| `ml/` | **Maintenance-policy ladder over the SDG fleet.** Stages 00 EDA → 01 Optuna baseline → 02 PatchTST SSL + RUL head → 03 PPO + frozen encoder → 04 results. `ml/lib/` holds the shared importable code; `03_rl/` is *not* a Python package because the previous `03_rl+ssl/` name had a `+` (invalid in module names) — import via `ml.lib.rl`. See `ml/README.md`. |
| `frontend/` | Vite + React 19 + Tailwind v4 + Zustand operator dashboard. Talks to FastAPI over CORS (allowed origins are 5173/4173 plus LAN regex). See `frontend/README.md`. |
| `data/` | `train/fleet_baseline.parquet` (Stage 1+2 ground truth), `historian.db` (SQLite consumed by the agent), `prediction/fleet_2026_2035.parquet` (forward-projected fleet), `prediction/weather_projected.parquet`, `train/weather_real.parquet`. |
| `tests/` | pytest suite for the backend + agent (notebooks are out of scope for CI). `tests/simulator/` covers the simulator and `ml/*/tests/` cover the ML libs. |
| `scripts/` | `new-branch.sh`, `create-pr.sh` (workflow), `demo_e2e.py` (judges' narrated run), `diagnose_lifespans.py`, `migrate_notebook_imports.py`. |
| `challenge-context/`, `BRIEF.md`, `CONTEXT.md`, `PLAN.md`, `digital_twin_hp_metal_jet_s100_spec.md`, `climate_location_module.md` | Source-of-truth design docs. Do not delete; they encode the scoring rubric and inter-phase contracts. |

### Cross-cutting flow (what makes the system end-to-end)

1. `backend.simulator` produces a deterministic per-printer parquet (`data/train/fleet_baseline.parquet`). Stage 1+2 outputs.
2. `backend/agent/twin_data.py` and `backend/agent/forecast.py` read that parquet and shape it into the React store's `SystemSnapshot`. The forecast module auto-switches from analytic projection to the trained SSL+RUL head when `ml/02_ssl/models/rul_head_ssl.pt` exists — `/twin/model_status` reports which path is live.
3. `backend/agent/db.py` writes telemetry into `data/historian.db`; the LangGraph agent in `backend/agent/graph.py` is the *only* surface that reads it. Tools are restricted to `think`, `get_db_schema`, `query_database` — adding others means editing `backend/agent/tools.py` *and* the gatherer prompt.
4. Every agent response is a `DiagnosticReport` (`backend/agent/schemas.py`). The `guardrail` node enforces an ISO-8601 timestamp and a `run_id` in `evidence_citation` — this is the "no hallucinations" contract the rubric grades on. If you change schemas, change the guardrail in lockstep.
5. `backend/app.py` is wrapped in a try/except around the langchain imports: `_CHAT_AGENT_AVAILABLE = False` keeps `/twin/*` serving the dashboard even when the LLM stack is broken; `/agent/*` returns 503 in that mode. Don't tighten this — judges run the dashboard offline.
6. POSTing telemetry with `status` `CRITICAL`/`FAILED` schedules `analyze_and_notify` as a background task and broadcasts a `PROACTIVE_ALERT` over `/ws/notifications`. This is the proactive-monitoring rubric item.

### Data contracts (do not break casually)

- **Phase 1 input** (driver vector per timestep): `temperature_stress`, `humidity_contamination`, `operational_load`, `maintenance_level`.
- **Phase 1 output** (per component): `health_index ∈ [0,1]`, `status ∈ {FUNCTIONAL,DEGRADED,CRITICAL,FAILED}`, `metrics: dict`.
- **Historian row**: `timestamp`, `run_id`/`scenario_id`, driver vector, component states.
- **Phase 3 reply**: `DiagnosticReport` with `grounded_text`, `evidence_citation` (timestamp + run_id), `severity_indicator`, `recommended_actions`, `priority_level`.

The frontend's `src/types/telemetry.ts` mirrors these — keep them in sync when changing pydantic models.

### ML stage notes

- `ml/lib/data.py` defines the canonical printer split (train 0..69, val 70..84, test 85..99). Every stage uses it.
- Stage 02 expects CUDA. On Windows `uv add torch` resolves to a CPU wheel; install the cu124 wheel manually if training on the 3090s.
- Notebook execution is the supported entry — `ml/train.sh` runs them in order via `jupyter nbconvert --execute --inplace`. Notebook outputs are committed.

## Project conventions worth knowing

- Live tests (`-m live`) hit the real Groq API and only run when `GROQ_API_KEY` is set; `make test-e2e` is the gate. Never lift the `not live` default — offline `uv run pytest` must stay green.
- The chat-agent import in `backend/app.py` is intentionally fault-tolerant; preserve the `_CHAT_AGENT_AVAILABLE` pattern when refactoring.
- `scripts/` contains the git workflow helpers — only modify them if changing the branching/PR conventions themselves.
