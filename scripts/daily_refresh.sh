#!/bin/bash
# daily_refresh.sh — run by launchd every morning
# Refreshes ESPN + BartTorvik data and recomputes thresholds.

set -e

PROJECT_DIR="/Users/sethgannon/Projects/big-blue-nation-ai-analyst"
PYTHON="$PROJECT_DIR/venv/bin/python"
LOG="$PROJECT_DIR/data/processed/refresh.log"

cd "$PROJECT_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') | INFO  | === Daily auto-refresh starting ===" >> "$LOG"

"$PYTHON" -m src.ingestion.refresh 2>> "$LOG"

EXIT_CODE=$?
if [ $EXIT_CODE -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') | INFO  | Daily refresh completed ✅" >> "$LOG"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') | ERROR | Daily refresh FAILED (exit $EXIT_CODE)" >> "$LOG"
fi

exit $EXIT_CODE
