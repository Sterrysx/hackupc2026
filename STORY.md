# Aether: A Digital Co-Pilot for the HP Metal Jet S100

> HackUPC 2026 entry for the HP challenge: build a digital twin of an
> industrial binder-jet metal printer that **models** component degradation,
> **simulates** it across a 10-year fleet, and **talks** to the operator
> through a grounded conversational agent.

---

## Inspiration

The HP Metal Jet S100 is a beautiful, terrifying machine. It binder-jets
stainless steel at industrial scale, it costs as much as a house, and its
operators are asked to track six interacting subsystems (a recoater blade, a
linear motor, a nozzle plate with thousands of firing resistors, heaters,
insulation panels), each with its own degradation physics, its own failure
signature, and its own way of quietly taking the whole printer down when no
one is watching.

The brief asked us to build a *Digital Co-Pilot*: a twin that could model how
the machine ages, simulate that aging forward in time, and then *explain
itself* to a human, without hallucinating. That last constraint was the
hook. Most "AI assistant" demos are confidence theater: a language model
guessing plausibly over a dataset it barely saw. The HP rubric grades on the
opposite: **every answer must trace back to a real data point**. Zero
tolerance for fabrication.

That's the project we wanted to build. A system where the AI is on a leash,
the leash is tied to a physics simulator, and the physics simulator is tied
to real weather data from the cities the printers are installed in.

---

## What we learned

Building Aether forced us to rethink several things we thought we already
understood. The biggest takeaways, in roughly the order the lessons hit us:

- **Data contracts are the product.** When four workstreams (physics,
  simulator, ML, frontend) have to ship in parallel inside 36 hours, the
  interface matters more than the implementation. We froze the driver
  vector, the per-component state schema, the historian row, and the
  `DiagnosticReport` pydantic model in hour 2 of the hackathon and never
  touched them again. That single decision is the reason nothing blocked
  anything. A frozen schema is worth ten hours of refactoring avoided.
- **Groundedness is an engineering property, not a prompt property.**
  *Asking* a model not to hallucinate is about as effective as asking a cat
  not to knock things off tables. What actually works: a narrow tool
  surface, a pydantic schema on the output, regex/enum validation *after*
  generation, and a retry that hands the model its own error. The
  guardrail node ended up being the most important file in the repo.
- **Cross-coupling physics is what makes a twin interesting to watch.**
  Without the powder-concentration ($c_p$) and heater-load ($Q$) cascades
  between components, each one fails independently and the operator
  dashboard is six boring charts. With the cascades, the dashboard tells
  a *story* (the recoater is the root cause, the nozzle just happened to
  die first), and that story is exactly what the diagnostic agent is
  there to narrate. Coupling was the difference between a simulator and a
  twin.
- **The SSL-then-RL ladder is real, not academic.** A frozen PatchTST
  encoder pretrained on multivariate telemetry genuinely compresses a
  360-day window into a usable 256-d embedding. Stage 03's PPO head could
  not have learned on raw telemetry inside a 20k-timestep budget; it
  worked because the representation was already good. We saw transfer
  learning earn its keep on a problem that wasn't ImageNet.
- **Determinism is a user-visible feature.** Seeding the simulator per
  printer (`np.random.default_rng(printer_id)`) means the entire demo
  story ("look what happened to printer 42 on 2024-07-14") is reproducible
  from a clean clone. The first time a judge can re-run your exact failure
  on their laptop, the conversation changes.
- **Honesty in the report is a feature, not a liability.** Our ML ladder
  did not clear the 95% availability bar, and we wrote that explicitly in
  the comparison report instead of cherry-picking metrics. Naming the
  remaining gap (reward design, not presentation polish) made the work
  more credible, not less.
- **Most importantly:** an AI that cites its evidence is not less
  impressive than one that doesn't. It is the only kind worth shipping
  into a factory.

---

## What it does

Aether is a three-layer system (Brain, Clock, Voice) wrapped in an operator
dashboard.

**Phase 1, The Brain.** A deterministic degradation engine for six
components of the HP S100. Each component has its own failure-rate equation
built from a shared skeleton:

$$
\lambda_i(t) = \lambda_{0,i} \cdot \alpha_i \cdot f_{\text{ext},i}(t) \cdot f_{\text{int},i}(t) \cdot f_{\text{cross},i}(t)
$$

where $\lambda_{0,i}$ is a calibrated baseline hazard, $\alpha_i \sim
\mathcal{N}(1, 0.05)$ is per-printer variability, and the three $f$ terms are
products of power-law driver ratios: external (temperature, humidity),
internal (maintenance debt, total life, print hours), and cross-component
(cascading failures). The Health Index updates in discrete daily ticks:

$$
H_i(t+1) = H_i(t) - \min\bigl(\lambda_i(t),\ 1.2\bigr)
$$

The recoater blade, for instance, degrades as:

$$
\lambda_{C1} = 0.014097 \cdot \alpha_{C1}
\cdot \left(\tfrac{T}{25}\right)^{0.3}
\cdot \left(\tfrac{H}{40}\right)^{1.5}
\cdot \left(1 + \tfrac{\tau_{\text{mant}}}{25}\right)^{1.5}
\cdot \left(1 + \tfrac{L}{33.33}\right)^{1.2}
\cdot \left(\tfrac{v}{150}\right)^{1.2}
\cdot \left(\tfrac{N_c}{30{,}000}\right)^{0.8}
\cdot \left(\tfrac{\phi_R}{0.20}\right)^{1.0}
\cdot f_{\text{cross},C1}
$$

Every component responds to all four input drivers the brief required
(temperature stress, humidity/contamination, operational load, maintenance
level), plus component-specific physics (firing count $N_f$, thermal cycles
$N_{TC}$, powder recycle fraction $\phi_R$, setpoint temperature $T_{set}$).
The pipeline uses **Weibull-style multiplicative hazards** on top of an
**exponential decay skeleton**, so the two failure-math families the rubric
asks for are literally in the same equation.

The two we're proudest of are the **coupled failure modes**. They weren't in
the spec; they fell out of the physics. A worn recoater ($H_{C1} \downarrow$)
lifts more powder into the air, so the *environmental* powder concentration
for the motor and nozzle plate becomes:

$$
c_p = 50 \cdot \bigl(1 + (1 - H_{C1})^2\bigr)
$$

Degraded insulation panels ($H_{C6} \downarrow$) leak heat, so the heaters
have to pull harder:

$$
Q = 1.0 \cdot \bigl(1 + (1 - H_{C6})^2\bigr)
$$

These feed back into $f_{\text{ext}}$ and $f_{\text{int}}$ of the downstream
components *continuously*. On top of that, a discrete "matrix of
multipliers" kicks in when a component crosses $H \le 0.4$ (enters
`CRITICAL`), inflating the hazard of its neighbors. The system isn't linear
and it isn't memoryless: a recoater that degrades in July lives on in the
nozzle plate's clog rate in August.

**Phase 2, The Clock.** A fleet of **100 virtual printers**, each seeded by
printer id, each placed in a real city with real historical weather pulled
from Open-Meteo and clipped to realistic interior ranges. The simulator
advances one day at a time for ten years, calls Phase 1 at every tick, and
writes the entire state (drivers in, health out, status, per-component
metrics) to `data/fleet_baseline.parquet` and to a SQLite historian. Every
run is fully deterministic given a printer id, and every row has a
`run_id`/`scenario_id` so you can stack what-if scenarios side by side.

**Phase 3, The Voice.** A LangGraph agent implementing **Pattern C,
Agentic Diagnosis**, the highest-tier reasoning pattern the rubric
recognizes. Not RAG, not context injection: a ReAct state machine that
*decides what to look for*, calls SQL tools against the historian, pulls the
telemetry itself, and reasons over it with a strict structured-output
contract.

```
gatherer ──► tools ──► gatherer     (ReAct loop)
   │
   ▼
extract_telemetry ──► synthesizer ──► guardrail ──► END
                                          │
                                          └──► synthesizer  (retry ≤ 3)
```

Every answer is a validated `DiagnosticReport`:

- `grounded_text`: human-readable explanation.
- `evidence_citation`: must contain both an ISO-8601 timestamp *and* a
  `run_id`. A regex-level guardrail enforces this; if it fails, the
  synthesizer gets a correction message and retries up to three times.
- `severity_indicator ∈ \{\text{INFO}, \text{WARNING}, \text{CRITICAL}\}$
- `priority_level ∈ \{\text{LOW}, \text{MEDIUM}, \text{HIGH}\}$
- `recommended_actions`: at least one.

The gatherer is allowed exactly three tools: `think`,
`get_db_schema`/`get_existing_runs`, and `query_database`. No web search, no
Python exec, no knowledge-base lookup. The surface area for fabrication is
tiny by construction.

**Plus the bonuses the rubric rewards.** A `/telemetry` POST with status
`CRITICAL` or `FAILED` schedules a background agent analysis and broadcasts
a `PROACTIVE_ALERT` over a websocket. The co-pilot speaks first. A voice
loop (faster-whisper STT, edge-tts TTS) lets the operator talk to it. A
React 19 + Tailwind dashboard with predictive halos, health rings, and a
⌘K palette puts a face on all of it.

**The ML ladder.** Because a twin isn't useful if you can't *optimize over
it*, we also built a four-stage maintenance-policy ladder on top:

| Stage | Method | What it buys |
|---|---|---|
| 01 | Optuna over a constant $\tau$ vector, evaluated against the real simulator | Strong baseline, no ML |
| 02 | PatchTST self-supervised pretraining + frozen-encoder RUL head + surrogate $\tau$ search | Fast candidate scoring |
| 03 | PPO on top of the frozen Stage 02 encoder, per-tick policy with SPR auxiliary loss and 3-seed ensemble | Per-printer, climate-aware $\tau$ |
| 04 | Bootstrap-CI comparison across all three | Headline metrics |

The headline: Stage 03 cuts fleet annual cost by **62%** and raises
availability by **70 points** versus Stage 01 on held-out test printers.
Not a toy: a real optimisation win on a simulator that was never trained to
be easy.

---

## How we built it

**Hour 0–2: freeze the contracts.** We locked the data contracts (driver
vector, state report, historian row, `DiagnosticReport`) *before* anyone
wrote implementation code. That single decision is the reason four parallel
workstreams (physics, simulator, ML, frontend) never blocked each other.
The frontend built against a mock that implemented the backend's contract;
the ML built against the simulator's parquet; the agent built against the
historian's SQL schema. Everyone coded to the interface.

**Stack:**

- **Backend**: FastAPI, Python 3.12 on `uv`, a single process exposing
  `/twin/*`, `/agent/*`, `/telemetry`, `/stt/*`, `/tts/*` and a
  `/ws/notifications` websocket.
- **Simulator**: pure Python + NumPy + Pandas, config-driven via YAML
  (`components.yaml`, `cities.yaml`, `climate.yaml`). Deterministic per
  printer.
- **Weather**: Open-Meteo historical data, cached to parquet, transferred to
  interior conditions via a per-city transfer function.
- **Agent**: LangGraph state machine over a ReAct loop, Pydantic structured
  output, multi-provider LLM backend (GitHub Models / Gemini / Groq, auto-detected).
- **ML**: PyTorch + HuggingFace PatchTST for the SSL encoder; Stable-Baselines3
  for PPO; Optuna for Stage 01; everything stitched through a shared
  `ml/lib/` package so notebooks stay clean.
- **Frontend**: Vite + React 19 + Tailwind v4 + Zustand + framer-motion +
  hand-rolled SVG sparklines and health rings. No shadcn; the visual
  language is ours.
- **Voice**: faster-whisper for STT, edge-tts for TTS, each a thin class.

**What made the system actually hang together:**

1. *The guardrail retry loop.* We didn't realize on day one that LLM
   compliance with a schema is best-effort, not deterministic. Wrapping the
   synthesizer in a regex-checking guardrail that bounces non-compliant
   output back up to three times is what let us claim the "no
   hallucinations" property with a straight face.
2. *Fault-tolerant LLM import.* The FastAPI app wraps the LangChain import
   in a `try/except` that flips `_CHAT_AGENT_AVAILABLE = False` on failure.
   The dashboard stays up even if the LLM stack is broken, returning 503
   only on `/agent/*`. Judges can run the full twin offline. This was the
   single decision that kept our demo un-bricked through three API key
   rotations.
3. *The frozen encoder pipeline.* Stage 02's PatchTST encoder is used three
   times: once for the RUL head, once as the observation encoder for PPO,
   once for the per-tick recurrent policy. Training it once and freezing
   it bought us the right to treat Stage 03 as a pure RL problem rather
   than a joint SSL+RL problem we didn't have time for.
4. *Makefile-driven dev loop.* `make run`, `make test`, `make test-e2e`,
   `make demo-e2e`, `make train`, `make new-branch`, `make pr`. Every
   common action is one line. At 4 AM on day two this matters more than you
   think.

---

## Challenges we ran into

**1. Calibrating six hazard baselines so failures actually happen on a
demo-visible timescale.** The simulator has to produce `FAILED` states
within a 10-year window to satisfy the rubric, but can't fail instantly or
the time-series charts are boring. We calibrated each $\lambda_{0,i}$
empirically so that the mean time to first failure matches a
component-specific `first_failure_target_d`. That took more hours than any
single piece of code.

**2. The unit mismatch between "hazard rate per day" and "something that
looks like a probability."** We clip $\lambda_i(t)$ at 1.2 per day to
prevent numerical blow-up when a cascading failure spikes the product. The
clip is physically dishonest (nothing dies 120% in one day), but it
preserves the monotonicity of $H$ and keeps the downstream ML pipelines
happy. We documented it as a known tradeoff rather than pretending it
isn't there.

**3. The 95% availability constraint in the ML ladder.** Stage 01 (Optuna)
and Stage 02 (SSL surrogate) both converged to policies that are cheap but
drive availability to the floor. Only Stage 03's per-tick PPO ensemble
lifted availability meaningfully (to 76%), and even then we didn't clear
the 95% bar. We wrote that honestly in the report rather than massage the
numbers. The next useful work is reward design, not presentation.

**4. Cascading failures create a nonlinear backbone that breaks naive
surrogates.** Our first attempt at Stage 02's surrogate search used a
closed-form event-rate model. It was fast and wrong. Components that fail
together in the real simulator appeared independent in the surrogate, and
the chosen $\tau$ vectors were optimistic by ~40%. We rewrote the
surrogate to re-evaluate the top-5 candidates with the real simulator
before reporting a winner. Commit `7c803cf` ("replace closed-form
surrogate with real-simulator τ search") is the commit we are least proud
of the first version of.

**5. Groundedness as an adversarial property, not a prompt-engineering
property.** The agent is graded on zero hallucinations. We learned that
*asking the model not to hallucinate* is roughly as effective as asking a
cat to not knock things off tables. What actually works:

   - Give it one narrow tool contract.
   - Enforce a pydantic schema on the output.
   - Validate the schema with regex and enum checks *after* generation.
   - Retry with a correction message, not a rephrasing.

**6. Time.** Thirty-six hours. Six components, three phases, four ML
stages, a dashboard, a voice loop, a websocket, and a demo script. The
only reason we shipped all of it is that the contracts froze in hour 2 and
never moved.

---

## What's next

- Close the voice loop end-to-end (STT → agent → TTS in one round-trip).
  All three pieces exist; wiring them is one afternoon.
- Stream the agent's tool calls to the UI so the reasoning chain is
  visible in real time, not just the conclusion.
- Persist agent memory across sessions with `SqliteSaver`, so the co-pilot
  should remember that "nozzle plate failures at this factory always
  follow heating spikes" from a conversation three sessions ago.
- Close the 95% availability gap in the ML ladder by reshaping the reward
  so availability deficit dominates early, not only after cost is already
  down.
- Add a `compare_runs` tool so operators can ask "why did R2 fail faster
  than R1?" and get a cross-scenario diagnosis.

---

## Try it

```bash
cp .env.example .env      # one of GITHUB_TOKEN / GEMINI_API_KEY / GROQ_API_KEY
uv sync
cd frontend && npm install && cd ..
make run                  # backend :8000 + frontend :5173
```

Then open <http://localhost:5173> and ask Aether: *"Why did the nozzle
plate on printer 42 fail?"*

It will tell you. And it will show you where in the historian it got the
answer.
