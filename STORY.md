# Aether: A Digital Co-Pilot for the HP Metal Jet S100

> HackUPC 2026 entry for the HP challenge: a digital twin of an industrial
> binder-jet metal printer that **models** component degradation,
> **simulates** it across a 10-year fleet, and **talks** to the operator
> through a grounded conversational agent that never hallucinates.

---

## The team

Four people, very different backgrounds, deliberately stretched:

- **Arnau** — ML/AI. Owned the LangGraph diagnostic agent.
- **Oriol** — ML/AI. Owned the four-stage ML ladder (Optuna → PatchTST SSL
  → PPO → comparison).
- **Adam** — cybersecurity background. Owned the React 19 + Tailwind
  dashboard and the websocket alert path.
- **Sergi** — industrial engineering, **first hackathon ever**. Defined
  the physics problem and wrote the component-degradation simulator
  (the hazard equations, the cross-coupling, the calibration).

We cross-pollinated on contracts, debugging, and the demo script.

---

## Idea & innovation

Most "AI for industry" demos are RAG over a PDF. We built something
different: a **physics-grounded digital twin** where the AI is on a leash,
the leash is tied to a deterministic simulator, and the simulator is tied
to **real historical weather** for the cities the printers live in.

What we believe is genuinely novel for a 36-hour build:

- **Coupled failure cascades.** Six components don't fail independently.
  A worn recoater lifts powder into the air, contaminating the motor and
  the nozzle plate; degraded insulation forces heaters to pull harder,
  accelerating their own wear. The dashboard tells a *story* (recoater
  is the root cause; nozzle just died first), not six disconnected charts.
- **Groundedness as an engineering property, not a prompt.** The agent
  cannot answer without citing an ISO-8601 timestamp *and* a `run_id`
  from the historian. A regex-level guardrail enforces this; non-compliant
  output is bounced back to the synthesizer up to three times. No
  citation, no answer.
- **Climate-aware predictive maintenance.** A printer in Phoenix degrades
  differently from one in Reykjavík, and the policy learns that. Each of
  100 virtual printers is seeded by id and placed in a real city with
  real Open-Meteo weather, so the same RL policy produces different
  maintenance thresholds depending on local climate.
- **Pattern C, Agentic Diagnosis** — the highest-tier reasoning pattern
  the HP rubric recognizes. Not RAG, not context injection: a ReAct loop
  that *decides what to look for*, queries SQL against the historian,
  and reasons over the result with a strict structured-output contract.

---

## Technology

**Three layers, one fleet.**

**Phase 1 — The Brain.** A deterministic degradation engine for six
components of the HP S100, using a shared **Weibull-style multiplicative
hazard on top of an exponential decay skeleton** (both failure-math
families the rubric asked for, in the same equation). Hazards depend on
temperature, humidity, maintenance debt, total life, print hours, firing
count, thermal cycles, powder recycle fraction, and setpoint temperature.
Cross-coupling between components is continuous (powder concentration
$c_p$, heater load $Q$) and discrete (a "matrix of multipliers" that
kicks in at $H \le 0.4$).

**Phase 2 — The Clock.** A fleet of **100 virtual printers**, each
deterministic per `printer_id`, each placed in a real city with real
historical weather pulled from Open-Meteo, simulated one day at a time
for **ten years**. Output: a parquet historian and a SQLite database
the agent can query. Every run has a `run_id`/`scenario_id` so what-if
scenarios stack side by side.

**Phase 3 — The Voice.** A LangGraph ReAct agent with exactly three
tools (`think`, `get_db_schema`/`get_existing_runs`, `query_database`).
No web search, no Python exec, no knowledge base. The fabrication
surface area is tiny by construction. Every answer is a validated
`DiagnosticReport` Pydantic model with `grounded_text`,
`evidence_citation` (timestamp + run_id, regex-checked),
`severity_indicator`, `priority_level`, and at least one
`recommended_action`.

```
gatherer ──► tools ──► gatherer       (ReAct loop)
   │
   ▼
extract_telemetry ──► synthesizer ──► guardrail ──► END
                                         │
                                         └──► synthesizer  (retry ≤ 3)
```

**The ML ladder — a real optimisation problem on top of the twin.**

| Stage | Method | What it buys |
|---|---|---|
| 01 | Optuna over a constant $\tau$ vector vs. the real simulator | Strong baseline, no ML |
| 02 | PatchTST self-supervised pretraining + frozen-encoder RUL head | Fast surrogate scoring |
| 03 | PPO on the frozen Stage 02 encoder, per-tick policy, 3-seed ensemble + SPR auxiliary loss | Per-printer, climate-aware policy |
| 04 | Bootstrap-CI comparison across all stages | Headline metrics |

Stage 03 cuts fleet annual cost by **62%** and lifts availability by
**70 points** vs. Stage 01 on held-out test printers.

**Stack:** FastAPI · Python 3.12 (uv) · NumPy/Pandas · PyTorch · HuggingFace
PatchTST · Stable-Baselines3 · Optuna · LangGraph · multi-provider LLM
(GitHub Models / Gemini / Groq, auto-detected) · Pydantic · SQLite ·
Open-Meteo · React 19 · Tailwind v4 · Zustand · framer-motion ·
faster-whisper (STT) · edge-tts (TTS) · websockets.

**Bonus surfaces the rubric rewards:** proactive alerts (a `/telemetry`
POST with status `CRITICAL` triggers a background agent analysis and
broadcasts a `PROACTIVE_ALERT` over websocket — the co-pilot speaks
first), a voice loop (STT → agent → TTS), and a dashboard with predictive
halos, health rings, and a ⌘K palette.

The "wow" moments we're proudest of: the **guardrail retry loop** that
turns LLM compliance into an engineering guarantee, and the **frozen
PatchTST encoder** reused in three places (RUL head, PPO observation
encoder, per-tick recurrent policy) — train once, exploit three times.

---

## Learning

This hackathon was deliberately uncomfortable for everyone:

- **Sergi (industrial engineering, first hackathon)** went from never
  having shipped code in a team setting to owning the entire physics
  layer: defining the failure modes, deriving the hazard equations,
  calibrating six baselines so failures land inside a 10-year window,
  and writing the cross-coupling that makes the twin actually
  interesting. He learned Git, Python, NumPy, YAML-driven configuration,
  and how to negotiate a data contract — in 36 hours.
- **Arnau and Oriol (ML/AI)** had never used **LangGraph** before. We
  learned the hard way that LLM compliance with a schema is best-effort,
  not deterministic, and ended up designing the guardrail-retry loop
  that became the backbone of the agent.
- **Oriol** had never trained a **PPO** policy before. Stage 03 (PPO on
  a frozen SSL encoder with SPR auxiliary loss and a 3-seed ensemble)
  was a deep dive into RL stability, reward shaping, and why "the
  surrogate is fast and wrong" is a real failure mode.
- **Adam (cybersecurity)** had not built a production-grade React
  frontend before. He shipped a React 19 + Tailwind v4 + Zustand
  dashboard with a websocket alert pipeline and a ⌘K palette, and
  brought a security mindset to the agent's tool surface (narrow
  contract, no exec, no web).
- **As a team**, we learned that **data contracts are the product**:
  freezing the driver vector, the per-component state schema, the
  historian row, and the `DiagnosticReport` model in hour 2 is the
  single decision that let four parallel workstreams ship without
  blocking each other.

We also learned to be **honest in the report**: our ML ladder did not
clear the rubric's 95% availability bar (we landed at 76%). We wrote
that explicitly and named the next step (reward design, not presentation
polish) instead of cherry-picking metrics.

---

## Challenges we ran into

- **Calibrating six hazard baselines** so failures happen on a
  demo-visible timescale without instant death.
- **Cascading failures break naive surrogates.** Our first Stage 02
  surrogate was a closed-form event-rate model — fast and wrong by ~40%.
  We rewrote it to re-evaluate top-5 candidates with the real simulator.
- **Groundedness is adversarial.** Asking a model not to hallucinate
  works as well as asking a cat not to knock things off tables. The
  guardrail retry loop is what made the "no hallucinations" claim real.
- **Fault-tolerant LLM imports.** The dashboard stays up even when the
  LLM stack is broken (returns 503 only on `/agent/*`). This decision
  kept the demo un-bricked through three API key rotations.
- **Time.** 36 hours, 6 components, 3 phases, 4 ML stages, a dashboard,
  a voice loop, a websocket. The contracts froze in hour 2 and never
  moved — that's the only reason we shipped all of it.

---

## What's next

- Close the voice loop end-to-end (STT → agent → TTS in one round-trip).
- Stream the agent's tool calls to the UI in real time, not just the
  conclusion.
- Persist agent memory across sessions with `SqliteSaver`.
- Close the 95% availability gap by reshaping the reward.
- Add a `compare_runs` tool: *"why did R2 fail faster than R1?"*

---

## Try it

```bash
cp .env.example .env      # one of GITHUB_TOKEN / GEMINI_API_KEY / GROQ_API_KEY
uv sync
cd frontend && npm install && cd ..
make run                  # backend :8000 + frontend :5173
```

Open <http://localhost:5173> and ask Aether: *"Why did the nozzle plate
on printer 42 fail?"* It will tell you — and show you exactly where in
the historian it got the answer.

---

## Appendix — the physics, formally

Each component's daily failure rate follows a shared skeleton:

$$
\lambda_i(t) = \lambda_{0,i} \cdot \alpha_i \cdot f_{\text{ext},i}(t) \cdot f_{\text{int},i}(t) \cdot f_{\text{cross},i}(t)
$$

where $\lambda_{0,i}$ is the calibrated baseline hazard, $\alpha_i \sim
\mathcal{N}(1, 0.05)$ is per-printer variability, and the three $f$
terms are products of power-law driver ratios: external (temperature,
humidity), internal (maintenance debt, total life, print hours), and
cross-component (cascading failures). Health updates in discrete daily
ticks:

$$
H_i(t+1) = H_i(t) - \min\bigl(\lambda_i(t),\ 1.2\bigr)
$$

The recoater blade (component C1), for example:

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

**Cross-coupling.** A worn recoater lifts powder into the environment,
raising the airborne powder concentration seen by the motor and nozzle:

$$
c_p = 50 \cdot \bigl(1 + (1 - H_{C1})^2\bigr)
$$

Degraded insulation panels leak heat, forcing heaters to pull harder:

$$
Q = 1.0 \cdot \bigl(1 + (1 - H_{C6})^2\bigr)
$$

These feed back into $f_{\text{ext}}$ and $f_{\text{int}}$ of the
downstream components continuously, while a discrete multiplier matrix
inflates neighbor hazards whenever a component crosses $H \le 0.4$
(`CRITICAL`). The system is nonlinear and has memory: a recoater that
degrades in July still shows up in the nozzle plate's clog rate in
August.
