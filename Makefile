.PHONY: help run dev run-back run-front test test-live test-e2e demo-e2e train train-fast new-branch pr

# Default target: show help
help:
	@echo ""
	@echo "  HackUPC 2026 — Common workflows"
	@echo ""
	@echo "  RUNNING THE STACK"
	@echo "    make run        # backend (:8000) + frontend (:5173) in one shell"
	@echo "    make run-back   # only the FastAPI backend (uv run uvicorn, hot reload)"
	@echo "    make run-front  # only the Vite dev server (npm run dev)"
	@echo ""
	@echo "  TESTS"
	@echo "    make test       # offline unit + integration"
	@echo "    make test-live  # opt-in live tests (needs GROQ_API_KEY)"
	@echo "    make test-e2e   # narrated live e2e gate"
	@echo "    make demo-e2e   # judges' walkthrough"
	@echo ""
	@echo "  ML TRAINING (executes ml/0X_*/*.ipynb in order)"
	@echo "    make train      # full ladder"
	@echo "    make train-fast # fast-mode ladder"
	@echo ""
	@echo "  GIT WORKFLOW"
	@echo "    make new-branch name=feat/your-feature-name"
	@echo "    make new-branch name=fix/bug-you-are-fixing"
	@echo "    make pr"
	@echo ""
	@echo "  GETTING AN AI REVIEW (after the PR is open)"
	@echo "    In Claude Code, type:  /review <PR number>"
	@echo ""

# ── Stack runner ─────────────────────────────────────────────────────────── #
# `make run` boots the full stack in one terminal: FastAPI on :8000 with hot
# reload, plus Vite on :5173. Both share stdout; Ctrl+C tears down cleanly.
# `make dev` is an alias so muscle memory works either way.
run:
	@bash scripts/run-stack.sh

dev: run

# Single-process variants — handy when you want one of the two on a debugger
# or you've got the other running in another terminal already.
run-back:
	@uv run --no-sync uvicorn backend.app:app --reload --port 8000

run-front:
	@cd frontend && npm run dev

# ── Tests ────────────────────────────────────────────────────────────────── #
test:
	@uv run --no-sync pytest -m "not live"

test-live:
	@uv run --no-sync pytest -m live

# Live end-to-end test: real parquet + real LangGraph + real Groq LLM.
# Skips automatically if GROQ_API_KEY is missing.
test-e2e:
	@uv run --no-sync pytest tests/test_integration_e2e.py -v -m live

# Narrated 5-act walkthrough for judges. Exits 0 on full grounding, 1 on
# any grounding miss, 2 when GROQ_API_KEY is not set.
demo-e2e:
	@uv run --no-sync python scripts/demo_e2e.py

# ── ML training ──────────────────────────────────────────────────────────── #
train:
	@bash ml/train.sh

train-fast:
	@bash ml/train.sh --fast

# ── Git workflow ─────────────────────────────────────────────────────────── #
new-branch:
ifndef name
	$(error Missing branch name. Usage: make new-branch name=feat/your-feature)
endif
	@bash scripts/new-branch.sh $(name)

pr:
	@bash scripts/create-pr.sh
