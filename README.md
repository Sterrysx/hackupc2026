# HackUPC 2026 — Digital Co-Pilot for the HP Metal Jet S100

A digital twin of HP's binder-jet metal printer that **models** component
degradation, **simulates** a 10-year fleet, and lets an operator **interact**
with it through a grounded LangGraph agent and a live React dashboard.

Entry for the HP challenge at HackUPC 2026. See [`ai-context/BRIEF.md`](ai-context/BRIEF.md) for the
scoring rubric and [`ai-context/CONTEXT.md`](ai-context/CONTEXT.md) for the full design.

---

## Repository map

| Path | What lives there | Docs |
|---|---|---|
| [`backend/`](backend/) | FastAPI app, simulator, agent, voice I/O — the whole Python runtime. | [`backend/README.md`](backend/README.md) |
| [`backend/agent/`](backend/agent/) | LangGraph agent (Pattern C — agentic diagnosis). | [`backend/agent/README.md`](backend/agent/README.md) |
| [`frontend/`](frontend/) | Vite + React 19 operator dashboard. | [`frontend/README.md`](frontend/README.md) |
| [`ml/`](ml/) | Maintenance-policy ladder: EDA → Optuna → SSL+RUL → PPO. | [`ml/README.md`](ml/README.md) |
| [`data/`](data/) | Simulator parquet + historian SQLite + weather cache. | — |
| [`tests/`](tests/) | Unit + integration + live-e2e suite. | — |

---

## Quickstart

```bash
cp .env.example .env       # fill in GITHUB_TOKEN, GEMINI_API_KEY, or GROQ_API_KEY
uv sync                    # install Python deps
cd frontend && npm install && cd ..
make run                   # backend on :8000, frontend on :5173
```

Full step-by-step — including prerequisites, the five-act judges' demo, and
troubleshooting — lives in [`WALKTHROUGH.md`](WALKTHROUGH.md).

---

## Common commands

| Task | Command |
|---|---|
| Run the full stack | `make run` |
| Run tests (offline) | `make test` |
| Live end-to-end test | `make test-e2e` |
| Judges' narrated demo | `make demo-e2e` |
| Train the ML ladder | `make train` |
| Start a feature branch | `make new-branch name=feat/...` |
| Open a PR | `make pr` |

Run `make` with no arguments for the full list.
