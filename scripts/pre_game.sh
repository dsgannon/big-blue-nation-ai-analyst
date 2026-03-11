#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  pre_game.sh — Run before tip-off to refresh data and save
#  a pre-game prediction for post-game validation.
#
#  Usage:
#    ./scripts/pre_game.sh
#    ./scripts/pre_game.sh --injuries "Player A,Player B"
#    ./scripts/pre_game.sh --no-refresh
# ─────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/venv/bin/python"

INJURIES=""
SKIP_REFRESH=false

for arg in "$@"; do
    case $arg in
        --injuries=*) INJURIES="${arg#*=}" ;;
        --injuries)   shift; INJURIES="$1" ;;
        --no-refresh) SKIP_REFRESH=true ;;
    esac
done

echo "╔══════════════════════════════════════════════════════════╗"
echo "║    BIG BLUE NATION AI ANALYST — PRE-GAME                 ║"
echo "╠══════════════════════════════════════════════════════════╣"
echo "║  Project: $PROJECT_DIR"
echo "║  Date:    $(date '+%Y-%m-%d %H:%M:%S')"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Step 1: Refresh data ─────────────────────────────────────
if [ "$SKIP_REFRESH" = false ]; then
    echo "━━━ Step 1: Refreshing ESPN data ━━━━━━━━━━━━━━━━━━━━━━━━━"
    cd "$PROJECT_DIR"
    $PYTHON -m src.ingestion.refresh
    echo ""
else
    echo "━━━ Step 1: Data Refresh SKIPPED (--no-refresh) ━━━━━━━━━━"
    echo ""
fi

# ── Step 2: Save pre-game prediction ─────────────────────────
echo "━━━ Step 2: Saving pre-game prediction ━━━━━━━━━━━━━━━━━━━"
cd "$PROJECT_DIR"
$PYTHON - <<PYEOF
import sys
sys.path.insert(0, '.')
from src.ingestion.espn_client import get_next_game
from src.ingestion.database import DB_PATH
from src.models.prediction_engine import PredictionEngine
from src.models.validation import save_prediction
import sqlite3, json

# Get next game info
next_game = get_next_game()
if not next_game:
    print("  ⚠️  No upcoming game found.")
    sys.exit(0)

is_home   = next_game['home_team'] == 'Kentucky Wildcats'
opponent  = next_game['away_team'] if is_home else next_game['home_team']
neutral   = next_game.get('neutral_site', False)
game_date = next_game.get('date', 'TBD')
game_id   = next_game.get('id', '')

# Get NET rank from DB
conn = sqlite3.connect(DB_PATH)
try:
    row = conn.execute(
        "SELECT net_rank FROM rankings WHERE team_name LIKE ? ORDER BY date DESC LIMIT 1",
        (f"%{opponent.split()[0]}%",)
    ).fetchone()
    net_rank = int(row[0]) if row else 100
except Exception:
    net_rank = 100
conn.close()

injuries = [i.strip() for i in """${INJURIES}""".split(',') if i.strip()]

print(f"  Opponent:  {opponent}")
print(f"  Date:      {game_date}")
location = 'Neutral' if neutral else ('Home' if is_home else 'Away')
print(f"  Location:  {location} — {next_game.get('venue_name','')}")
print(f"  NET Rank:  #{net_rank}")
if injuries:
    print(f"  Injuries:  {', '.join(injuries)}")
print()

engine = PredictionEngine()
prediction = engine.predict_game(
    opponent  = opponent,
    is_home   = is_home,
    net_rank  = net_rank,
    injuries  = injuries,
)

save_prediction(game_id, prediction)

print(f"  ✅ Prediction saved  (game_id: {game_id})")
print(f"     UK projected:   {prediction['uk_score']} pts")
print(f"     Opp projected:  {prediction['opp_score']} pts")
print(f"     Win probability: {prediction['win_probability']}%")
print()
print("  Player projections:")
for p in prediction.get('projections', []):
    print(f"    {p['name']:<22} {p['points']:>5.1f} pts  {p['rebounds']:>4.1f} reb  {p['assists']:>4.1f} ast  {p['minutes']:>5.1f} min")
PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  Pre-game complete — $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo "  After the final buzzer, run:"
echo "    ./scripts/post_game.sh"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
