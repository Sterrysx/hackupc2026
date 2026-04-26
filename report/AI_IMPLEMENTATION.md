# AI Implementation

## 1. Role in the system

The AI layer is **Phase 3 — Interact** of the Digital Twin. It answers operator
questions about the HP Metal Jet S100 fleet by querying the Phase 2 historian
and returning a structured, citation-backed diagnosis. The dashboard, the
simulator and the ML models are deliberately kept LLM-free — the agent is the
only surface that produces natural language, so every hallucination risk is
concentrated in, and defended against, this one module.

## 2. Architecture

The agent is a **LangGraph state machine** implementing Pattern C (Agentic
Diagnosis) from the challenge brief — the highest-tier reasoning pattern in the
rubric. It replaces a one-shot RAG call with a five-node pipeline:

```
gatherer  ──► tools ──► gatherer     (ReAct loop)
    │
    ▼
extract_telemetry ──► synthesizer ──► guardrail ──► END
                                            │
                                            └──► synthesizer   (retry ≤3)
```

| Node | Responsibility |
|---|---|
| `gatherer` | ReAct loop. Uses `think`, `get_existing_runs`, and `query_database` tools to fetch the right telemetry. |
| `extract_telemetry` | Copies the last `ToolMessage` payload into shared state so the synthesizer has a single, canonical input. |
| `synthesizer` | Reasons over the retrieved rows, then emits a `DiagnosticReport` via `with_structured_output`. |
| `guardrail` | Validates the report against the grounding contract. If it fails, feeds the error back to the synthesizer and retries up to three times. |

The graph is compiled with `MemorySaver`, so passing the same `thread_id`
preserves conversation context within a session.

## 3. The "no hallucinations" contract

The rubric grades the agent on traceability. Every response is a Pydantic
`DiagnosticReport` with:

- `grounded_text` — plain-language explanation.
- `evidence_citation` — must contain **both** an ISO-8601 timestamp
  (`YYYY-MM-DDTHH:MM:SS`) **and** a `run_id` (e.g. `run R2`).
- `severity_indicator ∈ {INFO, WARNING, CRITICAL}`.
- `priority_level ∈ {LOW, MEDIUM, HIGH}`.
- `recommended_actions` — at least one.

`guardrail_node` enforces this with regex checks on the citation and enum
checks on the categorical fields. Failures are not silently tolerated: the
node sends a targeted correction message back to the synthesizer and re-runs
it, up to `MAX_VALIDATION_ATTEMPTS = 3`. On the fourth failure it emits a
`CRITICAL` report that explicitly says validation failed, so the UI never
shows an unvalidated answer.

## 4. Grounding strategy

Two mechanisms keep the agent grounded in real telemetry:

1. **Tool restriction.** The gatherer has access to exactly three tools —
   `think`, `get_existing_runs`, `query_database` — and the synthesizer only
   to `think`. The SQL schema is fixed and every `query_database` call
   returns JSON rows straight from SQLite. There is no free-form web search
   or general-purpose code execution, so the surface area for fabrication is
   small.
2. **Prompt contract.** The gatherer prompt requires calling
   `get_existing_runs` before any query (no inventing run IDs) and explicitly
   forbids using training knowledge about printer state. The synthesizer
   prompt interpolates the retrieved telemetry into the system message and
   instructs the model to reason *only* over that block.

## 5. Proactive monitoring

`/telemetry` POSTs with `status ∈ {CRITICAL, FAILED}` schedule
`analyze_and_notify` as a FastAPI background task. It runs the agent over the
offending record and broadcasts a `PROACTIVE_ALERT` over the
`/ws/notifications` websocket. This is what makes the system a *co-pilot*
instead of a chatbot: the agent alerts the operator before they ask.

## 6. Multi-provider LLM backend

The client is resolved at runtime by `backend/agent/config.py::get_llm()`:

| Priority | Provider | Default model | Why |
|---|---|---|---|
| 1 | GitHub Models (OpenAI-compatible gateway) | `openai/gpt-4.1-mini` | Highest throughput on a hackathon PAT; full tool-calling. |
| 2 | Google Gemini | `gemini-3.1-flash-lite-preview` | Strong free tier as a fallback. |
| 3 | Groq | `qwen/qwen3-32b` | Legacy path for older `.env` files. |

Selection is driven by the first credential found in `.env`
(`GITHUB_TOKEN` → `GEMINI_API_KEY` → `GROQ_API_KEY`), overridable by
`LLM_PROVIDER`. The node code depends only on `.bind_tools` and
`.with_structured_output`, both of which all three LangChain clients expose,
so swapping providers does not touch the graph.

---

## 7. Challenges and how we overcame them

### 7.1 Keeping the agent grounded end-to-end

**Challenge.** A LangGraph ReAct loop can hallucinate in at least three
places: the gatherer can invent run IDs, the synthesizer can cite timestamps
that were never retrieved, and `with_structured_output` can return a
syntactically valid report whose citation is still empty.

**Solution.** We treat grounding as a *contract* enforced by code, not a
prompt hope:

- The gatherer prompt forces `get_existing_runs` before any query, so the
  agent always works from the real catalog of run IDs.
- `extract_telemetry` is a dedicated node (not a prompt instruction) that
  pulls the last `ToolMessage` into state. The synthesizer literally cannot
  answer without that block being populated.
- `guardrail_node` runs two regexes (`_TIMESTAMP_RE`, `_RUN_ID_RE`) over
  `evidence_citation` and rejects reports that don't embed both. Rejections
  are fed back as a correction `HumanMessage` so the model gets *targeted*
  feedback rather than a generic retry.

The live e2e test (`tests/test_integration_e2e.py`, `make test-e2e`) asserts
every rubric item — timestamp + run_id in the citation, tool-call trace
present, parquet-backed numbers — against a real LLM call, so this contract
is verified on CI, not just claimed in the README.

### 7.2 `with_structured_output` colliding with tool calls

**Challenge.** The synthesizer wants to *think* with a tool before producing
a structured report. Binding tools and `with_structured_output` to the same
call isn't reliably supported across providers, and on one occasion a
provider emitted an out-of-schema tool call that crashed the graph with
`"tool call validation failed … not in request.tools"`.

**Solution.** `synthesizer_node` runs a two-phase loop: while the model
issues tool calls we append synthetic empty `ToolMessage`s (the `think` tool
returns nothing by design) and re-invoke with tools bound. The moment the
model stops calling tools, we re-invoke the **same messages** against
`llm.with_structured_output(DiagnosticReport)` to get the final report. If
the bound-tools call raises the above out-of-schema error, we catch it and
fall through to the structured call directly rather than failing the
request. The effect is that the synthesizer always converges to a
`DiagnosticReport`, regardless of whether the provider interleaves reasoning
cleanly.

### 7.3 Provider volatility on hackathon credentials

**Challenge.** The original implementation was Groq-only. Mid-hack, Groq's
free-tier rate limits started throttling during demo rehearsals, and
switching to Gemini's preview endpoints exposed a different failure mode:
`gemini-3.1-flash-lite-preview` returns 503 under sustained load, and a
single agent run makes many LLM calls (ReAct loop + synthesizer + guardrail
retries).

**Solution.** We introduced a three-provider abstraction
(`backend/agent/config.py`) that auto-detects the available credential and
returns a raw chat client — not a `RunnableRetry` or
`RunnableWithFallbacks`, because those wrappers don't expose `.bind_tools`
or `.with_structured_output`, which the nodes need. Per-provider quirks are
localised in that one file:

- **GitHub Models.** Uses `ChatOpenAI` pointed at
  `https://models.github.ai/inference` with a GitHub PAT as the API key.
  `max_retries=4` is enough for transient 5xx.
- **Gemini.** Uses `ChatGoogleGenerativeAI` with `max_retries=10` to survive
  the 503 storms on preview endpoints. We also mirror `GEMINI_API_KEY` onto
  `GOOGLE_API_KEY` so either name works in `.env`.
- **Groq.** Kept as a legacy path. The Qwen-specific `reasoning_effort=none`
  kwarg is only passed when the model name contains `qwen` so future Groq
  models are not broken by it.

Every integration and e2e test was rewritten to skip on any of the three
keys rather than strictly on `GROQ_API_KEY`, keeping the default offline
`uv run pytest` green even on laptops with no LLM access.

### 7.4 Session memory without a database

**Challenge.** `MemorySaver` — LangGraph's in-process checkpointer — is
fast but loses state on restart. A richer store like `SqliteSaver` added
install-time complexity we couldn't afford before the demo.

**Solution.** We kept `MemorySaver` and scoped "memory" to a single
dashboard session via a deterministic `thread_id` passed from the client.
This gives the visible property the judges care about — the agent *remembers*
what you asked one turn ago — without persisting anything to disk. A follow-up
swap to `SqliteSaver` is a one-line change in `graph.build_graph`; it's
flagged in `backend/agent/README.md` as the next obvious upgrade.

### 7.5 Making reasoning observable

**Challenge.** Pattern C only impresses judges if they can *see* the
multi-step reasoning. A single chatbot reply that happens to cite a
timestamp looks the same as a grounded multi-tool trace.

**Solution.** We emit the full LangGraph trace into the `scripts/demo_e2e.py`
narrator script (`make demo-e2e`): every tool call, tool result, and guardrail
validation prints to stdout as the graph executes. The narrated run ends with
a checklist and an exit code (0 = all rubric items green, 1 = any grounding
miss, 2 = no API key), making the demo reproducible and falsifiable rather
than a sales pitch. The same script is wired into `tests/test_integration_e2e.py`
so the grounding claims are asserted, not just shown.

### 7.6 Wiring proactive monitoring without blocking the API

**Challenge.** The "watchdog" feature — LLM-analyse any `CRITICAL`/`FAILED`
telemetry POST and push a grounded alert to the UI — needed to run an entire
agent graph on the server, which can take several seconds. Doing that inline
would block the `/telemetry` response and timeout the simulator's ingest
loop.

**Solution.** `/telemetry` dispatches `analyze_and_notify` as a FastAPI
`BackgroundTask` and returns `200 OK` immediately. The background task owns
its own graph invocation and, when the report is ready, broadcasts a
`PROACTIVE_ALERT` over the `/ws/notifications` websocket to every connected
dashboard client. To keep the rest of the API usable when the LLM stack is
broken, the chat-agent import in `backend/app.py` is wrapped in
`try/except ImportError` and the watchdog short-circuits with a warning log
when `_CHAT_AGENT_AVAILABLE` is `False` — judges can run the dashboard
entirely offline if a credential goes bad on the demo day.

---

## 8. Summary

The AI implementation is small on purpose: ~400 lines of graph + node code,
three tools, one Pydantic schema. What makes it credible is that every piece
of "the model says so" is backed by a piece of code that *verifies* the
model said something real — the guardrail regexes, the tool-restricted
gatherer, the structured-output fallback in the synthesizer, the e2e test
that checks the same contract on a live LLM. Grounding is a property of the
graph, not a property of the prompt.
