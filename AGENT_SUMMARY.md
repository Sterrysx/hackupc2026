# AI Agent — How It Works

## Overview

The agent is the **Phase 3 "Interact"** layer of the Digital Twin. It is a grounded conversational AI that diagnoses printer issues by querying real telemetry from the historian database, then returning a structured, citation-backed report.

Built with **LangGraph** on top of **Groq/Llama** (configurable in `Ai_Agent/config.py`).

---

## Graph architecture

The agent uses a **LangGraph state machine** implementing Pattern C (Agentic Diagnosis) — the highest-tier reasoning pattern in the challenge spec.

```
START
  │
  ▼
gatherer ──(tool calls?)──► tools ──► gatherer   (ReAct loop)
  │
  │ (done fetching)
  ▼
extract_telemetry
  │
  ▼
synthesizer ──► guardrail ──(valid?)──► END
                    │
                    │ (invalid, retries < 3)
                    └──────────────► synthesizer
```

### Nodes

| Node | File | Responsibility |
|---|---|---|
| `gatherer` | `nodes.py` | Receives the user query and autonomously calls tools to retrieve the right telemetry. Loops until done. |
| `tools` | `graph.py` (ToolNode) | Executes tool calls requested by the gatherer. |
| `extract_telemetry` | `nodes.py` | Pulls retrieved data from the last ToolMessage into shared graph state. |
| `synthesizer` | `nodes.py` | Reasons over the telemetry using `think`, then produces a structured `DiagnosticReport` via `with_structured_output`. |
| `guardrail` | `nodes.py` | Validates the report: checks severity enum, priority enum, ≥1 recommended action, ISO-8601 timestamp, and run_id in citation. Retries up to 3 times. |

---

## Tools

The gatherer has access to three tools (`Ai_Agent/tools.py`):

| Tool | What it does |
|---|---|
| `think` | Private reasoning scratchpad — the model writes analysis before acting. Never shown to the user. |
| `get_existing_runs` | Lists all run IDs available in the historian SQLite database. |
| `query_database` | Queries telemetry by `run_id`, optional `component`, `status`, and `timestamp_range`. Returns JSON rows. |

The synthesizer only has access to `think`.

---

## Output contract — `DiagnosticReport`

Every agent response is a validated Pydantic model (`Ai_Agent/schemas.py`):

| Field | Type | Description |
|---|---|---|
| `grounded_text` | `str` | Plain-language root-cause explanation traceable to actual telemetry. |
| `evidence_citation` | `str` | Exact ISO-8601 timestamp + run_id from the historian (e.g. `"2024-01-15T14:05:02, run R2"`). |
| `severity_indicator` | `str` | `INFO` / `WARNING` / `CRITICAL` |
| `recommended_actions` | `list[str]` | 2–3 specific, actionable steps for the operator. |
| `priority_level` | `str` | `LOW` / `MEDIUM` / `HIGH` |

The guardrail enforces this contract and retries the synthesizer (up to 3 times) if validation fails.

---

## Session memory

The graph is compiled with `MemorySaver`. Passing the same `thread_id` across requests preserves conversation history within a session — the agent remembers earlier context in the thread.

---

## Proactive alerting

`app.py` triggers a background agent analysis whenever a `/telemetry` POST arrives with status `CRITICAL` or `FAILED`. The resulting report is broadcast over the `/ws/notifications` WebSocket to all connected dashboard clients — the agent alerts the operator before they ask.

---

## Entry points

| Surface | Where |
|---|---|
| REST API | `POST /agent/query` in `app.py` |
| Proactive alert | `analyze_and_notify` background task in `app.py` |
| CLI smoke test | `main.py` |
| Graph definition | `Ai_Agent/graph.py` → `build_graph()` |
