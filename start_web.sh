#!/usr/bin/env bash
# Start the assistant API (port 8000) and the web interface (port 3000).
# Run from the project root with the Python venv active.
set -e
cd "$(dirname "$0")"
uvicorn server:app --port 8000 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null' EXIT
cd web
[ -d node_modules ] || npm install
npm run dev
