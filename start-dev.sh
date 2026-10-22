#!/usr/bin/env bash
# Start backend (port 8000) and frontend (port 5173) together. Ctrl+C stops both.
# First run: install dependencies as described in README.md.
set -e
cd "$(dirname "$0")"
( cd backend && { [ -d .venv ] && source .venv/bin/activate || true; } && uvicorn app.main:app --reload --port 8000 ) &
BACK=$!
trap 'kill $BACK 2>/dev/null' EXIT
cd frontend && npm run dev
