.PHONY: help new-branch pr

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

new-branch:
ifndef name
	$(error Missing branch name. Usage: make new-branch name=feat/your-feature)
endif
	@bash scripts/new-branch.sh $(name)

pr:
	@bash scripts/create-pr.sh
