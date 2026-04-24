# BRIEF — HP HackUPC 2026 Battle Plan

> Distilled cheatsheet of the four `challenge-context/*.md` docs.
> Source-of-truth lives in `challenge-context/`; this file is for fast scanning during the sprint.

---

## 1. Vision (the elevator pitch)

Build a **Digital Co-Pilot for the HP Metal Jet S100** — an industrial binder-jetting metal 3D printer. The Co-Pilot is a digital twin that (a) **models** how components age and fail, (b) **simulates** that ageing forward in time, and (c) **talks** to the operator through a grounded conversational interface. Three phases, sequential and cumulative: **Brain → Clock → Voice**.

> Hard rule: every AI answer must trace back to a real data point in the simulation. No hallucinations.

---

## 2. Demo narrative (the 5-minute story)

Front-loaded so we always know what the final walkthrough has to show. Build everything backwards from this.

| Time | Beat | What the audience sees |
|---|---|---|
| 0:00–0:30 | Pitch | Problem: HP Metal Jet is too complex to monitor manually. Our answer: a Digital Co-Pilot. |
| 0:30–1:30 | Phase 1 | Three degradation models (recoater blade, nozzle plate, heating element) reacting live to driver inputs. |
| 1:30–3:00 | Phase 2 | Time-series chart of component health declining over simulated time; at least one component reaches `FAILED`. Failure analysis: when + why. |
| 3:00–4:30 | Phase 3 | Operator asks: *"Why did the nozzle plate fail?"* → AI answers with citation: *"Telemetry at 14:05:02, run_id=R2 — heat spike 12h prior accelerated clogging."* |
| 4:30–5:00 | Wrap | Recap: brain → clock → voice. Bonus features called out (chaos / RL / voice). |

---

## 3. Phase 1 — Model (the Brain)

Pure mathematical engine. Input vectors in, component state out. **No UI, no loop.**

### Must-haves (P0)
- [ ] **Recoater blade** model w/ ≥1 driver — *Recoating subsystem · scoring: Rigor*
- [ ] **Nozzle plate** model w/ ≥1 driver — *Printhead subsystem · scoring: Rigor*
- [ ] **Heating element** model w/ ≥1 driver — *Thermal subsystem · scoring: Rigor*
- [ ] **≥2 failure-math models applied** (Weibull, exponential decay, etc.) — *scoring: Rigor*
- [ ] All components react to **all 4 input drivers** (temp stress, humidity, load, maintenance) — *scoring: Systemic Interaction*
- [ ] Outputs match data contract: `health_index ∈ [0,1]`, status enum, custom metrics — *Data Contract*
- [ ] Engine is **deterministic**: same input → same output

### Physics hints (from stage-1)
- **Blade**: abrasive wear; contamination accelerates it.
- **Nozzle plate**: clogging + thermal fatigue; out-of-bounds temperature ↑ clog probability.
- **Heating element**: electrical degradation; ageing → more energy needed for same temp.

### Bonus (P1/P2)
- Cascading failures across subsystems (degraded blade → contaminated powder → clogged nozzle) — *Innovation*
- Stochastic shocks / sensor drift — *Innovation*
- Maintenance as input (partial health recovery, cooldown) — *Innovation*
- ML-driven degradation (LSTM / regressor) for one component — *Innovation*
- Live weather API for real temp/humidity — *Realism*

---

## 4. Phase 2 — Simulate (the Clock + Historian)

Time-advancing simulation that drives the Phase 1 engine and persists every state.

### Must-haves (P0)
- [ ] **Simulation loop** advances time consistently — *scoring: Time moves*
- [ ] **Phase 1 engine called every step** — *scoring: Systemic Integration*
- [ ] Every state **persisted** to CSV / JSON / SQLite with timestamp + driver values — *scoring: Systemic Integration*
- [ ] **Run/scenario IDs** so multiple runs stay queryable
- [ ] **Time-series visualization**, ≥1 component reaches `FAILED` — *deliverable*
- [ ] **Failure analysis**: when + why each component failed — *deliverable*

### Architectural choices (pick one — equally scored)
| Pattern | Tier | Logic |
|---|---|---|
| **A: Deterministic Replay** | Minimum | Loop reads sequential inputs from a file/sequence linearly. |
| **B: Informed Extrapolation** | Advanced | Sync phase from history → predict phase. |
| **C: Stochastic Simulation** | Advanced | Inject noise / random variables into the input loop. |

### Mode (pick one — equally scored)
- **Batch**: simulate end-to-end → export CSV/JSON.
- **Real-time streaming**: emit data points as the clock ticks.

### Bonus (P1/P2)
- What-if scenarios (high-humidity factory vs dry lab; 24/7 vs light usage) — *Innovation*
- Chaos engineering (sudden temp spike, contamination burst) — *Innovation*
- AI Maintenance Agent that decides *when* to trigger maintenance — *Innovation*
- RL policy across thousands of episodes — *Innovation*
- Twin sync against streamed "real" sensor readings — *Realism*

---

## 5. Phase 3 — Interact (the Voice)

Grounded AI interface that reads from the Phase 2 historian and explains the printer to a human.

### Must-haves (P0)
- [ ] Interface **reads from Phase 2 historian** (not memory, not hardcoded) — *Grounding Accuracy (zero-tolerance)*
- [ ] Every response cites **timestamp / component / run_id** — *Grounding Accuracy*
- [ ] **Severity tag** per response: `INFO` / `WARNING` / `CRITICAL`
- [ ] **No hallucinations** — every claim traceable to a data point

### Reasoning ladder (pick one)
| Pattern | Tier | Logic |
|---|---|---|
| **A: Simple Context Injection** | Mandatory baseline | Inject latest snapshot into the system prompt. Knows only "now". |
| **B: Contextual RAG** | Advanced | Query historian → feed relevant context → answer. |
| **C: Agentic Diagnosis** | Highest tier | Agent uses tools (`Query_Database`, etc.) in a ReAct loop to investigate. |

### Bonus (P1/P2)
- Proactive alerting (background watcher fires `CRITICAL` before operator asks) — *Autonomy*
- Voice I/O (speech-in, speech-out) — *Versatility*
- Root-cause chains (multi-event narrative explaining *why* failure happened) — *Reasoning Depth*
- Action paths (repair time, uptime impact, priority ranking) — *Reasoning Depth*
- Persistent collaborator memory across sessions — *Autonomy*

---

## 6. Data contracts (the inter-phase glue)

These are the **only** interfaces between phases. Lock them in hour 0–2; everyone codes against the contract, not the implementation.

### Phase 1 input — driver vector (per timestep)
| Field | Type | Notes |
|---|---|---|
| `temperature_stress` | float | °C, ambient |
| `humidity_contamination` | float | air moisture or powder purity |
| `operational_load` | float | total print hours / cycles |
| `maintenance_level` | float | 0..1 coefficient of how well-cared-for |

### Phase 1 output — state report (per component)
| Field | Type | Notes |
|---|---|---|
| `health_index` | float ∈ [0,1] | normalized remaining life |
| `status` | enum | `FUNCTIONAL` / `DEGRADED` / `CRITICAL` / `FAILED` |
| `metrics` | dict | component-specific (e.g. `thickness`, `resistance`) |

### Phase 2 historian — record (per row)
| Field | Type |
|---|---|
| `timestamp` | datetime |
| `run_id` / `scenario_id` | string |
| driver vector | (Phase 1 input above) |
| component states | (Phase 1 output above, per component) |

### Phase 3 query → response
- **Input**: natural language text (optional voice).
- **Output**: grounded text + **evidence citation** (timestamp / component / run_id) + **severity tag**.

---

## 7. Scoring rubric (condensed)

| Phase | Pillar | What earns points |
|---|---|---|
| 1 | Rigor | Math is logically consistent and physically plausible |
| 1 | Systemic Interaction | More drivers per component → richer behaviour |
| 1 | Complexity & Innovation *(bonus)* | Cascading failures, stochasticity, AI-driven degradation |
| 1 | Realism & Fidelity *(bonus)* | Behaviour mirrors the real machine |
| 2 | Time moves | Loop advances consistently |
| 2 | Systemic Integration | Phase 1 called every step, results persisted |
| 2 | Complexity & Innovation *(bonus)* | What-if scenarios, chaos, AI maintenance agent |
| 2 | Realism & Fidelity *(bonus)* | Plausible curves, graceful handling of non-linear events |
| 3 | Reliability — Grounding Accuracy | Zero hallucinations, strictly within Phase 1/2 data |
| 3 | Reliability — Communication Clarity | Clear, actionable, human-readable insights |
| 3 | Intelligence — Reasoning Depth | Diagnostic reasoning + root-cause analysis |
| 3 | Autonomy — Proactive Intelligence | Alerts the operator before they ask |
| 3 | Autonomy — Collaborative Memory | Persistent memory + skill automation across sessions |
| 3 | Versatility — Interaction Modality | Voice / multi-modal / dashboards |

> Phase 3 is scored on 4 pillars. A team can win there by being **exceptionally reliable** (Pillar 1) **or** exceptionally advanced (Pillars 3 & 4).

---

## 8. Deliverables (what we hand in)

- [ ] **Working demo**: Phase 1 + 2 minimum (Phase 3 is significant bonus)
- [ ] **Architecture slide deck**: math models + simulation loop + AI implementation (diagrams encouraged)
- [ ] **Technical report**: modeling, simulation design, AI implementation, challenges + how they were overcome
- [ ] **GitHub repo** with clean `README.md` setup instructions
- [ ] **Walkthrough**: short demo of the Digital Twin's "intelligence"
- [ ] **Phase 3 bonus demo** (if implemented): conversational interface in action + grounding explanation

---

## 9. 36-hour timeline (proposed)

| Hours | Focus | Notes for parallel work |
|---|---|---|
| **0–2** | Architecture lock-in | Pick Phase 2 pattern (A/B/C), Phase 3 pattern (A/B/C), tech stack. **Freeze the data contracts (§6)** so everyone codes against the interface, not the implementation. |
| **2–10** | Phase 1 (Brain) | Three components in parallel — one teammate per subsystem. Each writes a pure function matching §6. Stub data driver generator early. |
| **10–18** | Phase 2 (Clock + Historian) | One owns the loop, one owns persistence + visualization. Phase 1 authors stay on call for integration. Pick storage early (CSV is the safe bet). |
| **18–24** | Phase 3 (Voice) | Pattern A first to ensure groundedness; upgrade to B (RAG) or C (agent) if time. Voice I/O = stretch. |
| **24–30** | Polish & demo prep | Run failure analysis, build the what-if scenario for the demo, rehearse the 5-minute story (§2). |
| **30–36** | Deliverables | Slide deck + technical report + dry-run demo end-to-end. Reproducibility check. |

---

## 10. Pre-demo self-check (from `hackathon.md` §6)

### Phase 1: Model
- [ ] At least one component per subsystem modeled (Recoating, Printing, Thermal)
- [ ] Each modeled component uses ≥1 input driver
- [ ] ≥2 failure models implemented
- [ ] Component outputs include health index, operational status, metrics
- [ ] Team can explain how the degradation logic was designed

### Phase 2: Simulate
- [ ] Simulation loop advances time correctly and consistently
- [ ] Phase 1 engine called at every time step
- [ ] Every record saved to a historian with timestamp + driver values
- [ ] Runs/scenarios identifiable separately
- [ ] Time-series visualization shows component health evolving
- [ ] Team can identify when and why each component fails

### Phase 3: Interact
- [ ] Interface reads from the Phase 2 historian
- [ ] Responses grounded in simulation data, not hard-coded or hallucinated
- [ ] Every answer includes an explicit citation or timestamp reference
- [ ] Advanced reasoning remains traceable to underlying logs

### Demo readiness
- [ ] Team can explain how the three phases connect
- [ ] Demo can be reproduced end to end
- [ ] Team can show where any AI answer comes from in the data

---

## Quick links to source docs
- [`challenge-context/hackathon.md`](./challenge-context/hackathon.md) — main brief, vision, deliverables
- [`challenge-context/stage-1.md`](./challenge-context/stage-1.md) — Phase 1 (Model) full spec
- [`challenge-context/stage-2.md`](./challenge-context/stage-2.md) — Phase 2 (Simulate) full spec
- [`challenge-context/stage-3.md`](./challenge-context/stage-3.md) — Phase 3 (Interact) full spec
