#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  auto_post_game.sh — Called by cron after games end.
#  Detects if a game completed today (or yesterday for late tip-offs),
#  checks if a prediction was saved, and runs post_game.sh if needed.
#
#  Usage: ./scripts/auto_post_game.sh
# ─────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/venv/bin/python"
LOG_FILE="$PROJECT_DIR/data/processed/auto_post_game.log"

echo "$(date '+%Y-%m-%d %H:%M:%S') — auto_post_game.sh starting" >> "$LOG_FILE"

GAME_ID=$($PYTHON - <<'PYEOF'
import sqlite3
import os
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, 'data', 'processed', 'kentucky_basketball.db')

if not os.path.exists(DB_PATH):
    sys.exit(0)

conn = sqlite3.connect(DB_PATH)

# Look for games completed in the last 24 hours
cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime('%Y-%m-%d')

# Find completed games with a saved prediction but no validated errors yet
row = conn.execute("""
    SELECT gp.game_id
    FROM game_predictions gp
    JOIN games g ON g.id = gp.game_id
    WHERE g.status IN ('Final', 'STATUS_FINAL')
      AND g.date >= ?
      AND NOT EXISTS (
          SELECT 1 FROM prediction_errors pe WHERE pe.game_id = gp.game_id
      )
    ORDER BY g.date DESC
    LIMIT 1
""", (cutoff,)).fetchone()

conn.close()
if row:
    print(row[0])
PYEOF
)

if [ -z "$GAME_ID" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') — No pending validation found" >> "$LOG_FILE"
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') — Validating game $GAME_ID" >> "$LOG_FILE"
cd "$PROJECT_DIR"
"$SCRIPT_DIR/post_game.sh" "$GAME_ID" --report >> "$LOG_FILE" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') — Done" >> "$LOG_FILE"
