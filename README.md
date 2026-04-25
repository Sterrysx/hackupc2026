# HackUPC 2026

## Judges — Live End-to-End Proof

Two commands show that the Digital Co-Pilot is not a visual shell — the real
simulator parquet, the real SQLite historian, the real LangGraph agent, and
the real Groq LLM all take part in every answer.

```bash
# 1) Prerequisite: a Groq API key (see .env.example).
cp .env.example .env   # then fill GROQ_API_KEY

# 2) Automated assertions: grounding, tool usage, websocket watchdog.
make test-e2e

# 3) Narrated 5-act walkthrough (human-readable, prints the reasoning trace).
make demo-e2e
```

`make test-e2e` runs `tests/test_integration_e2e.py` with `-m live`. The tests
auto-skip when `GROQ_API_KEY` is absent, so the default `uv run pytest` stays
offline and fast.

`make demo-e2e` runs `scripts/demo_e2e.py`, which prints:

1. **Seed check** — historian SQLite is real (`R1`, `R2`).
2. **Parquet ground truth** — `/twin/state` numbers match `fleet_baseline.parquet` row-for-row.
3. **Live agent reasoning** — every LangGraph step (tool calls, tool results, guardrail) is streamed; the final citation must include both an ISO timestamp and a `run_id`.
4. **Proactive watchdog** — a `CRITICAL` telemetry POST triggers a grounded `PROACTIVE_ALERT` over the websocket.
5. **Verdict** — checklist + exit code (0 all green, 1 any miss, 2 missing key).

---

## Git Workflow

### Starting a new feature

Always branch off `main`. Never commit directly to `main`.

```bash
make new-branch name=feat/your-feature-name
make new-branch name=fix/bug-you-are-fixing
```

Branch names must start with `feat/` or `fix/`. This is enforced by the script.

### Coding

Work on your branch normally — edit files, `git add`, `git commit`. Commit as often as you like.

### Opening a pull request

When your feature is ready:

```bash
make pr
```

The script will push your branch, ask you for a title and short description, create the PR, and open it in the browser.

### Getting an AI code review

After the PR is open, run this inside Claude Code:

```
/review <PR number>
```

The agent will read the diff and post a review report.

### Merging

Once the review looks good, merge into `main` via the GitHub UI.

---

## Python environment (conda + uv)

We use **conda** to manage the Python interpreter and **uv** to manage packages. Do both steps below once when you clone the repo.

### 1 — Create the conda environment (once)

```bash
conda create -n hackupc python=3.12 -y
conda activate hackupc
```

Activate it every time you open a new terminal before working on the project:

```bash
conda activate hackupc
```

### 2 — Install dependencies with uv (once, then after every pull)

```bash
uv sync
```

This reads `pyproject.toml` and `uv.lock`, and installs all packages into `.venv`. Run it again whenever someone adds or removes a package.

This reads `pyproject.toml`, creates a `.venv`, and installs all dependencies. Run this once after cloning and again whenever someone adds a new package.

### Running code

Always use `uv run` so the right Python and packages are used:

```bash
uv run main.py
uv run python          # open a REPL with project packages available
```

### Adding a new package

```bash
uv add requests
uv add pandas numpy
```

This updates `pyproject.toml` and `uv.lock` automatically. Commit both files so everyone gets the same versions.

### Removing a package

```bash
uv remove requests
```

### After pulling changes from main

If someone added or removed packages, re-sync:

```bash
uv sync
```

---

## Quick reference

| What you want to do | Command |
|---|---|
| See all available commands | `make` |
| Start a new feature | `make new-branch name=feat/name` |
| Open a pull request | `make pr` |
| Get an AI review | `/review <number>` in Claude Code |
| Set up Python environment | `uv sync` |
| Run a script | `uv run script.py` |
| Add a package | `uv add package-name` |
