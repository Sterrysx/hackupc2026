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

# ── Guard: must not be on main ─────────────────────────────────────────────────
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" = "main" ]; then
    die "You are on main. Switch to your feature branch first.\n\nRun:  git checkout your-branch-name"
fi

# ── Guard: must have commits ahead of main ─────────────────────────────────────
COMMITS_AHEAD=$(git rev-list --count main..HEAD)
if [ "$COMMITS_AHEAD" -eq 0 ]; then
    die "No new commits on this branch yet. Make some changes and commit them first."
fi

info "Branch:   ${CURRENT_BRANCH}"
info "Commits ahead of main: ${COMMITS_AHEAD}"

# ── Push latest commits ────────────────────────────────────────────────────────
if ! git diff --quiet || ! git diff --cached --quiet; then
    warn "You have uncommitted changes — they will NOT be included in the PR."
    warn "Commit them now if you want them included, or press Enter to continue."
    read -r
fi

info "Pushing latest commits to remote..."
git push origin HEAD

# ── Check if PR already exists ────────────────────────────────────────────────
EXISTING_PR=$(gh pr list --head "$CURRENT_BRANCH" --json number,url -q '.[0].url' 2>/dev/null || true)
if [ -n "$EXISTING_PR" ]; then
    warn "A PR already exists for this branch: ${EXISTING_PR}"
    warn "Opening it in your browser..."
    gh pr view --web
    exit 0
fi

# ── Collect PR details ─────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}What did you build? (short title, e.g. 'Add login page')${NC}"
read -r PR_TITLE

echo ""
echo -e "${BLUE}Briefly describe what changed (press Enter twice when done):${NC}"
PR_BODY=""
while IFS= read -r line; do
    [ -z "$line" ] && break
    PR_BODY+="$line"$'\n'
done

# ── Create the PR ──────────────────────────────────────────────────────────────
info "Creating pull request..."
PR_URL=$(gh pr create \
    --base main \
    --head "$CURRENT_BRANCH" \
    --title "$PR_TITLE" \
    --body "$(cat <<EOF
## What this PR does
${PR_BODY:-_No description provided._}

## Checklist
- [ ] Tested locally
- [ ] No debug logs left behind
- [ ] Doesn't break main
EOF
)")

echo ""
success "Pull request created: ${PR_URL}"

PR_NUMBER=$(gh pr view --json number -q '.number')

echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}  Next: get the AI code review report${NC}"
echo -e "${YELLOW}  In Claude Code, run:  /review ${PR_NUMBER}${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

info "Opening PR in browser..."
gh pr view --web
