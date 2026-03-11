#!/usr/bin/env bash
# scripts/post_game.sh
#
# Post-game pipeline: refresh data (including box scores) then run validation.
#
# Usage:
#   ./scripts/post_game.sh <game_id>            # refresh + validate specific game
#   ./scripts/post_game.sh <game_id> --report   # also print full MAE report
#   ./scripts/post_game.sh --list               # show games with saved predictions
#
# The game_id is the ESPN game ID — find it in the `games` table or from the
# URL on ESPN (e.g., gameId=401757123).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "❌  venv not found at $VENV_PYTHON"
  exit 1
fi

cd "$PROJECT_ROOT"

# ── --list: show games with saved predictions ─────────────────────────────────
if [[ "${1:-}" == "--list" ]]; then
  "$VENV_PYTHON" - <<'PYEOF'
import sqlite3, os
db = "data/processed/kentucky_basketball.db"
if not os.path.exists(db):
    print("No database found.")
    exit()
conn = sqlite3.connect(db)
try:
    rows = conn.execute("""
        SELECT game_id, opponent, predicted_at, predicted_uk_score, predicted_opp_score
        FROM game_predictions ORDER BY predicted_at DESC
    """).fetchall()
    if not rows:
        print("No saved predictions found. Call save_prediction() before a game.")
    else:
        print(f"\n  {'Game ID':<15} {'Opponent':<30} {'Predicted':<12} {'UK':>5} {'Opp':>5}")
        print(f"  {'-'*15} {'-'*30} {'-'*12} {'-'*5} {'-'*5}")
        for r in rows:
            print(f"  {r[0]:<15} {r[1]:<30} {r[2][:10]:<12} {r[3]:>5.1f} {r[4]:>5.1f}")
        print()
except Exception as e:
    print(f"Error: {e}")
conn.close()
PYEOF
  exit 0
fi

# ── Require game_id ───────────────────────────────────────────────────────────
if [[ $# -lt 1 ]]; then
  echo "Usage: ./scripts/post_game.sh <game_id> [--report]"
  echo "       ./scripts/post_game.sh --list"
  exit 1
fi

GAME_ID="$1"
DO_REPORT=0
[[ "${2:-}" == "--report" ]] && DO_REPORT=1

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    BIG BLUE NATION AI ANALYST — POST-GAME PIPELINE       ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Game ID: $GAME_ID"
echo "║  Date:    $(date '+%Y-%m-%d %H:%M:%S')"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Data refresh (picks up new box scores automatically) ──────────────
echo "━━━ Step 1: Data Refresh ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
"$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.ingestion.refresh import run_refresh
run_refresh()
"
echo ""

# ── Step 2: Validate the specific game ───────────────────────────────────────
echo "━━━ Step 2: Validation for game $GAME_ID ━━━━━━━━━━━━━━━━━━"
"$VENV_PYTHON" - <<PYEOF
import sys; sys.path.insert(0, '.')
from src.models.validation import validate_game
try:
    validate_game('$GAME_ID')
except ValueError as e:
    print(f"\n⚠️  {e}")
    print("\nDid you call save_prediction() before the game?")
    print("  from src.models.validation import save_prediction")
    print("  from src.models.prediction_engine import PredictionEngine")
    print("  engine = PredictionEngine()")
    print("  result = engine.predict_game(...)")
    print(f"  save_prediction('$GAME_ID', result)")
    sys.exit(1)
PYEOF
echo ""

# ── Step 3: Optional full report ─────────────────────────────────────────────
if [[ $DO_REPORT -eq 1 ]]; then
  echo "━━━ Step 3: Validation Report ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  "$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.models.validation import validation_report
validation_report()
"
  echo ""
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  Post-game pipeline complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
