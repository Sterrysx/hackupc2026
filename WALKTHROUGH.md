# Walkthrough

End-to-end setup and operation guide for the HackUPC 2026 Digital Co-Pilot.
Start here after cloning the repo.

---

## 1. Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.12 | Runtime for the backend and ML code. |
| [`uv`](https://docs.astral.sh/uv/) | latest | Package manager driven by `pyproject.toml` + `uv.lock`. |
| Node.js | ≥ 20 | Frontend toolchain. |
| [conda](https://docs.conda.io/) | optional | Recommended for the Python 3.12 interpreter. |
| LLM API key | one of: `GITHUB_TOKEN`, `GEMINI_API_KEY`, `GROQ_API_KEY` | Needed only for agent answers; the dashboard and tests run without one. |

---

## 2. One-time setup

```bash
# Python interpreter (conda recommended)
conda create -n hackupc python=3.12 -y
conda activate hackupc

# Backend + ML dependencies
uv sync

# Frontend dependencies
cd frontend && npm install && cd ..

# Environment variables
cp .env.example .env      # then edit .env and fill in one LLM key
```

Provider auto-detection order: `GITHUB_TOKEN` → `GEMINI_API_KEY` → `GROQ_API_KEY`.
Override with `LLM_PROVIDER=github|gemini|groq`. See [`.env.example`](.env.example).

---

## 3. Run the stack

```bash
make run          # backend (:8000) + frontend (:5173) in one shell
```

Single-process variants when you want one on a debugger:

```bash
make run-back     # only FastAPI with hot reload
make run-front    # only Vite dev server
```

Open <http://localhost:5173> for the dashboard; <http://localhost:8000/docs> for
the OpenAPI explorer.

---

## 4. Tests

```bash
make test         # offline unit + integration (fast, no network)
make test-live    # opt-in live tests — require an LLM key
make test-e2e     # narrated five-act e2e gate (live)
```

Live tests auto-skip when no LLM key is set, so `make test` always stays green
on a fresh clone.

---

## 5. Judges' demo

```bash
make demo-e2e
```

Runs [`scripts/demo_e2e.py`](scripts/demo_e2e.py) and prints a five-act
narration proving the system is not a visual shell:

1. Historian SQLite is real (seeded runs `R1`, `R2`).
2. `/twin/state` numbers match `data/fleet_baseline.parquet` row-for-row.
3. The live LangGraph agent streams every tool call and returns a
   citation-backed `DiagnosticReport`.
4. A `CRITICAL` telemetry POST triggers a grounded `PROACTIVE_ALERT` over the
   `/ws/notifications` websocket.
5. Verdict + exit code (0 all-green, 1 any miss, 2 missing key).

---

## 6. ML training

The maintenance-policy ladder runs notebook-by-notebook:

```bash
make train        # full ladder: 00 EDA → 01 Optuna → 02 SSL → 03 PPO → 04 results
make train-fast   # same, fast-mode configs
```

Stage details and per-notebook invocations live in [`ml/README.md`](ml/README.md).

---

## 7. Git workflow

```bash
make new-branch name=feat/your-feature      # branches off latest main; prefix enforced
make pr                                     # push + open PR interactively
```

In Claude Code: `/review <PR number>` posts an AI review on the PR.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `uv run pytest` reports `ModuleNotFoundError` | `uv sync` — someone added a dep; re-install. |
| `/health` reports `agent_ready: false` | No LLM key in `.env`; agent endpoints will return 503 but the dashboard still works. |
| `make run-front` fails on a fresh clone | `cd frontend && npm install`. |
| Stage 02 trains on CPU despite a GPU | On Windows `uv add torch` pulls a CPU wheel; install the CUDA wheel manually (see [`ml/README.md`](ml/README.md)). |
| Dashboard shows 2015 as "now" | Regenerate the parquet — the date window is baked into `data/fleet_baseline.parquet`. |

---

## 9. Where to go next

- [`BRIEF.md`](BRIEF.md) — challenge rubric and demo narrative.
- [`CONTEXT.md`](CONTEXT.md) — full system design.
- [`CLAUDE.md`](CLAUDE.md) — conventions + architecture notes for AI contributors.
- [`backend/agent/README.md`](backend/agent/README.md) — agent internals.
- [`ml/README.md`](ml/README.md) — ML ladder internals.
