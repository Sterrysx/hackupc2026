# `backend/` — Python runtime

Single FastAPI process that serves the dashboard and the agent. The three
phases of the challenge (Model → Simulate → Interact) map to three submodules
below.

```
backend/
├── app.py          # FastAPI entrypoint — /twin/*, /agent/*, /telemetry, /stt/*, /tts/*, /ws/notifications
├── main.py         # CLI fallback — one agent query from stdin, used for smoke tests
├── agent/          # Phase 3 — LangGraph agent (Pattern C)   → see agent/README.md
├── simulator/      # Phase 1+2 — synthetic data generator + degradation simulator
└── voice/          # STT (faster-whisper) + TTS (edge-tts)
```

## Submodules

| Path | Role | Docs |
|---|---|---|
| [`agent/`](agent/) | LangGraph state machine: gatherer → tools → extract → synthesizer → guardrail. | [`agent/README.md`](agent/README.md) |
| `simulator/` | Generates `data/fleet_baseline.parquet` from `config/*.yaml`. | — |
| `voice/` | Thin STT + TTS wrappers wired to `/stt/*` and `/tts/*`. | — |

## Running

```bash
uv run python -m uvicorn backend.app:app --reload   # or: make run-back
```

## Extending

- **New endpoint** → add to `app.py`. Keep the `_CHAT_AGENT_AVAILABLE`
  try/except pattern around LangChain imports so the dashboard stays up when
  the LLM stack is broken.
- **New agent tool** → edit [`agent/tools.py`](agent/tools.py) *and* the
  gatherer prompt in [`agent/nodes.py`](agent/nodes.py).
- **New simulator component** → update `simulator/config/components.yaml` and
  the physics in `simulator/core/degradation.py`.

Data contracts (pydantic schemas) live in each submodule and are mirrored by
`frontend/src/types/telemetry.ts`. Change them in lockstep.
