#!/usr/bin/env bash
#
# Run the full HackUPC 2026 stack in one terminal:
#   • FastAPI backend at http://127.0.0.1:8000  (uv run uvicorn, hot reload)
#   • Vite frontend  at http://127.0.0.1:5173  (npm run dev)
#
# Both processes share this terminal's stdout. Ctrl+C kills both cleanly via
# the SIGINT/SIGTERM trap below — no orphaned uvicorn workers, no zombie node.
# Works on Git Bash for Windows, WSL, macOS, and Linux: every command in here
# is plain POSIX shell + `wait`.

set -e

# Resolve the repo root regardless of where the script was invoked from, so
# `make run` from the project root and `bash scripts/run-stack.sh` from
# anywhere both behave the same.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo
  echo "[run-stack] shutting down…"
  if [ -n "$BACKEND_PID" ]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [ -n "$FRONTEND_PID" ]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  # Reap children so the script doesn't return before they're actually gone.
  wait 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

# Sanity checks — fail fast with a useful message instead of letting the
# subprocess error half-startup.
command -v uv >/dev/null 2>&1 || {
  echo "[run-stack] ERROR: 'uv' is not on PATH. Install from https://docs.astral.sh/uv/." >&2
  exit 1
}
command -v npm >/dev/null 2>&1 || {
  echo "[run-stack] ERROR: 'npm' is not on PATH. Install Node.js first." >&2
  exit 1
}
if [ ! -d "frontend" ]; then
  echo "[run-stack] ERROR: 'frontend/' directory missing — run from the repo root." >&2
  exit 1
fi
if [ ! -d "frontend/node_modules" ]; then
  echo "[run-stack] note: frontend/node_modules missing — running 'npm install' first."
  ( cd frontend && npm install )
fi

echo "[run-stack] starting backend  → http://127.0.0.1:8000"
uv run --no-sync uvicorn app:app --reload --port 8000 &
BACKEND_PID=$!

echo "[run-stack] starting frontend → http://127.0.0.1:5173"
( cd frontend && npm run dev ) &
FRONTEND_PID=$!

echo "[run-stack] both processes up. Ctrl+C to stop."
echo

# `wait` blocks until BOTH children exit. If one crashes the other keeps
# running — we deliberately don't auto-kill the survivor so the user can
# read the stack trace before tearing the stack down with Ctrl+C.
wait
