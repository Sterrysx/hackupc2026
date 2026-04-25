.PHONY: help new-branch pr test-e2e demo-e2e

# Default target: show help
help:
	@echo ""
	@echo "  HackUPC 2026 — Git Workflow"
	@echo ""
	@echo "  STARTING A NEW FEATURE"
	@echo "    make new-branch name=feat/your-feature-name"
	@echo "    make new-branch name=fix/bug-you-are-fixing"
	@echo ""
	@echo "  OPENING A PULL REQUEST (when you are done)"
	@echo "    make pr"
	@echo ""
	@echo "  GETTING AN AI REVIEW (after the PR is open)"
	@echo "    In Claude Code, type:  /review <PR number>"
	@echo ""
	@echo "  JUDGES — LIVE END-TO-END PROOF (requires GROQ_API_KEY)"
	@echo "    make test-e2e   # pytest asserts groundedness end-to-end"
	@echo "    make demo-e2e   # narrated 5-act walkthrough, human-readable"
	@echo ""

new-branch:
ifndef name
	$(error Missing branch name. Usage: make new-branch name=feat/your-feature)
endif
	@bash scripts/new-branch.sh $(name)

pr:
	@bash scripts/create-pr.sh

# Live end-to-end test: real parquet + real LangGraph + real Groq LLM.
# Skips automatically if GROQ_API_KEY is missing.
test-e2e:
	@uv run pytest tests/test_integration_e2e.py -v -m live

# Narrated 5-act walkthrough for judges. Exits 0 on full grounding, 1 on
# any grounding miss, 2 when GROQ_API_KEY is not set.
demo-e2e:
	@uv run python scripts/demo_e2e.py
