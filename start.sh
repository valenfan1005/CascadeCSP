#!/bin/bash
# OptionScout Trading Tracker — Startup Script
# Starts both backend (FastAPI) and frontend (Vite dev server)

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "🚀 OptionScout Trading Tracker"
echo "================================"

# Start backend
echo "Starting FastAPI backend on http://localhost:8000..."
cd "$DIR"
PYTHONPATH="$DIR" python3 -m uvicorn server.app:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start frontend
echo "Starting Vite dev server on http://localhost:3000..."
cd "$DIR/frontend"
npx vite --port 3000 &
FRONTEND_PID=$!

echo ""
echo "================================"
echo "Backend:   http://localhost:8000  (API docs: http://localhost:8000/docs)"
echo "Frontend:  http://localhost:3000"
echo "================================"
echo ""
echo "Press Ctrl+C to stop both servers."

# Trap Ctrl+C to kill both
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM

# Wait for either process
wait
