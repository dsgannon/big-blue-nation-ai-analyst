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

INJURIES="Jayden Quaintance,Jaland Lowe"
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

# ── Auto-detect back-to-back and days rest from schedule ──────────────────
import sqlite3
from datetime import datetime, timezone

def _parse_date(d):
    for fmt in ('%Y-%m-%dT%H:%MZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d'):
        try:
            return datetime.strptime(d[:len(fmt)-1] if fmt.endswith('Z') else d[:10], fmt.replace('Z',''))
        except ValueError:
            continue
    return None

today = _parse_date(game_date) or datetime.now()
_conn = sqlite3.connect(DB_PATH)
_prev = _conn.execute("""
    SELECT date FROM games
    WHERE (home_team = 'Kentucky Wildcats' OR away_team = 'Kentucky Wildcats')
      AND date < ?
    ORDER BY date DESC LIMIT 1
""", (game_date,)).fetchone()
_conn.close()

if _prev:
    prev_date  = _parse_date(_prev[0])
    days_rest  = max(1, (today - prev_date).days) if prev_date else 3
else:
    days_rest  = 3

is_back_to_back = 1 if days_rest <= 1 else 0
rest_label = "BACK-TO-BACK ⚠️" if is_back_to_back else f"{days_rest} days rest"

# Get live NET rank and BPI for opponent
from src.ingestion.espn_client import get_net_rankings, get_opponent_net_rank, get_opponent_bpi
try:
    net_rankings = get_net_rankings()
    net_rank = get_opponent_net_rank(opponent, net_rankings)
    print(f"  NET Rank:  #{net_rank} (live)")
except Exception as e:
    net_rank = 100
    print(f"  NET Rank:  #100 (fallback — {e})")

opp_bpi = None
try:
    opp_bpi = get_opponent_bpi(opponent)
    print(f"  Opp BPI:   {opp_bpi:.1f} (live)")
except Exception as e:
    print(f"  Opp BPI:   N/A (fallback — {e})")

injuries = [i.strip() for i in """${INJURIES}""".split(',') if i.strip()]

print(f"  Opponent:  {opponent}")
print(f"  Date:      {game_date}")
location = 'Neutral' if neutral else ('Home' if is_home else 'Away')
print(f"  Location:  {location} — {next_game.get('venue_name','')}")
print(f"  Rest:      {rest_label}")
if injuries:
    print(f"  Injuries:  {', '.join(injuries)}")
print()

engine = PredictionEngine()
predict_kwargs = dict(
    opponent        = opponent,
    is_home         = is_home,
    net_rank        = net_rank,
    injuries        = injuries,
    days_rest       = days_rest,
    is_back_to_back = is_back_to_back,
)
if opp_bpi is not None:
    predict_kwargs['opp_bpi'] = float(opp_bpi)
prediction = engine.predict_game(**predict_kwargs)

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
