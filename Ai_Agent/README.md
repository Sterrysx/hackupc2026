# AI Agent — Digital Co-Pilot for HP Metal Jet S100

This module is the Phase 3 "Interact" layer of the Digital Twin. It exposes a grounded conversational AI agent that queries the Phase 2 historian database and answers operator questions with traceable, citation-backed diagnostic reports.

---

## What is built

### Architecture: Pattern C — Agentic Diagnosis

The agent implements the highest-tier reasoning pattern from the challenge spec. It uses a **LangGraph state machine** with a ReAct loop that autonomously decides what data to fetch, fetches it, and then reasons over it before generating a response.

```
START
  │
  ▼
gatherer ──── (has tool calls?) ──► tools ──► gatherer (loop)
  │
  │ (no tool calls)
  ▼
extract_telemetry
  │
  ▼
synthesizer
  │
  ▼
guardrail ──── (valid?) ──► END
  │
  │ (invalid, retries left)
  └──────────────────────► synthesizer
```

#### Node responsibilities

| Node | What it does |
|---|---|
| `gatherer` | Receives the user query. Uses `think`, `get_db_schema`, and `query_database` tools in a ReAct loop to retrieve the right telemetry. Retries on bad query parameters. |
| `tools` | Executes the tool calls requested by the gatherer. |
| `extract_telemetry` | Pulls the retrieved data out of the tool message into shared graph state so the synthesizer can access it. |
| `synthesizer` | Reasons over the retrieved telemetry using the `think` tool, then produces a structured `DiagnosticReport` via `with_structured_output`. |
| `guardrail` | Validates the report against the grounding protocol — checks for a timestamp, a run_id, and valid enum values. Retries up to 3 times by sending a correction message back to the synthesizer. |

### Tools available to the agent

| Tool | Description |
|---|---|
| `think` | Private reasoning scratchpad — the agent writes out its analysis before acting. Never shown to the user. |
| `get_db_schema` | Returns the full schema of the historian SQLite database: columns, types, available run IDs, and component metric definitions. |
| `query_database` | Queries the historian by `run_id`, optional `timestamp_range`, optional `component`, and optional `status` filter. Returns matching telemetry rows as JSON. |

### Structured output — `DiagnosticReport`

Every response from the agent is a validated `DiagnosticReport`:

| Field | Type | Description |
|---|---|---|
| `grounded_text` | str | Plain-language root-cause explanation, traceable to the telemetry. |
| `evidence_citation` | str | Exact timestamp + run_id from the historian (e.g. "telemetry at 2024-01-15T14:05:02, run R2"). |
| `severity_indicator` | str | `INFO` / `WARNING` / `CRITICAL` |
| `recommended_actions` | list[str] | 2–3 specific, actionable steps for the operator. |
| `priority_level` | str | `LOW` / `MEDIUM` / `HIGH` |

The guardrail enforces that `evidence_citation` contains both a valid ISO-8601 timestamp and a run identifier. If not, it sends a correction back to the synthesizer and retries.

### Persistent memory

The graph is compiled with `MemorySaver`. Passing the same `thread_id` in the API config preserves conversation history across multiple queries within the same session — the agent remembers what was discussed earlier in the thread.

### Proactive alerting (watchdog)

The `/telemetry` endpoint in `app.py` triggers a background agent analysis whenever a record with status `CRITICAL` or `FAILED` is ingested. The result is broadcast over WebSocket to all connected clients — the agent alerts the operator before they ask.

### Voice I/O

- **Speech-to-text**: Faster Whisper (`stt/transcriber.py`) — upload audio, get transcript.
- **Text-to-speech**: `tts/speaker.py` — send text, get MP3 back.

Both are wired into the FastAPI app as independent endpoints (`/stt/transcribe`, `/tts/speak`).

---

## Possible next steps to impress judges

### End-to-end voice loop
All three pieces exist (STT, agent, TTS) but are separate endpoints. Wiring them into a single round-trip — speak a question, hear the answer — would be the most visually striking demo moment on stage. One thin integration layer.

### Stream the reasoning chain to the UI
The gatherer's tool calls (think → get_db_schema → query_database) already happen step by step. Switching from `.invoke()` to `.stream()` and forwarding each step to the client would make the multi-step reasoning visible in real time:
```
[Thinking] I need to check temperature history...
[Tool] query_database(component=heating_element, run=R2)
[Thinking] I see a spike at 14:05. Checking fan logs...
[Tool] query_database(component=fan, timestamp=14:00-14:10)
[Conclusion] Fan failure preceded heat spike → root cause identified.
```
This visually proves Pattern C to judges who will not read the code.

### Richer root-cause narratives
The synthesizer prompt already asks for root-cause chains. Making it explicitly output a **chronological 3-act story** (early signal → cascading event → failure) would make every answer feel like a co-pilot rather than a query tool.

### Cross-run comparison tool
Add a `compare_runs` tool that queries two run IDs and returns the delta in health degradation rates per component. This enables questions like "Why did R2 fail faster than R1?" and demonstrates that the agent can reason across scenarios, not just single runs.

### Trend forecasting tool
Add a tool that fits a simple regression over the last N telemetry points and projects an estimated time-to-failure for a component. Return it as part of the report so the operator knows not just that something is degrading but *when* it will cross the critical threshold.

### Persistent collaborator memory across restarts
`MemorySaver` is in-process only and lost on restart. Replacing it with `SqliteSaver` (built into LangGraph) would give the agent genuine long-term memory — it could recall that "nozzle plate failures at this factory always follow heating element spikes" from a conversation three sessions ago.

### Scheduled proactive summaries
Run a background job every N minutes that scans the historian for trends and fires a WebSocket broadcast even when no threshold has been crossed. Turns the system from reactive (alerts on failure) to predictive (surfaces deterioration before it becomes critical).
