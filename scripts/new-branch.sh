#!/usr/bin/env bash
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${BLUE}[→] $*${NC}"; }
success() { echo -e "${GREEN}[✓] $*${NC}"; }
warn()    { echo -e "${YELLOW}[!] $*${NC}"; }
die()     { echo -e "${RED}[✗] $*${NC}"; exit 1; }

# ── Validate argument ──────────────────────────────────────────────────────────
BRANCH_NAME="${1:-}"
if [ -z "$BRANCH_NAME" ]; then
    die "Branch name is required.\n\nUsage:\n  make new-branch name=feat/your-feature\n  make new-branch name=fix/your-bug"
fi

# Enforce naming convention: feat/* or fix/*
if [[ ! "$BRANCH_NAME" =~ ^(feat|fix)/.+ ]]; then
    die "Branch name must start with 'feat/' or 'fix/'\n\nExamples:\n  feat/user-login\n  feat/dashboard-ui\n  fix/crash-on-submit"
fi

# ── Guard: don't run from a dirty working tree ─────────────────────────────────
if ! git diff --quiet || ! git diff --cached --quiet; then
    warn "You have uncommitted changes. Commit or stash them first."
    git status --short
    exit 1
fi

# ── Update main and branch ─────────────────────────────────────────────────────
info "Switching to main and pulling latest changes..."
git checkout main
git pull origin main

info "Creating branch: ${BRANCH_NAME}"
git checkout -b "$BRANCH_NAME"

info "Pushing branch to remote..."
git push -u origin "$BRANCH_NAME"

echo ""
success "You are now on branch: ${BRANCH_NAME}"
echo -e "  ${YELLOW}When you are done coding, run:  make pr${NC}"
