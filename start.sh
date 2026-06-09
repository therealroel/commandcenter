#!/usr/bin/env bash
# CommandCenter crash-restart loop.
# Run this instead of `python server.py` directly.
# If the server exits for any reason it restarts after 3 seconds.
#
# Usage:  ./start.sh
#         ./start.sh &   # background

set -uo pipefail
cd "$(dirname "$0")"

source .venv/bin/activate 2>/dev/null || true

while true; do
    echo "[start.sh] $(date '+%T') starting commandcenter..."
    python server.py || true
    EXIT=$?
    echo "[start.sh] $(date '+%T') server exited (code $EXIT), restarting in 3s..."
    sleep 3
done
