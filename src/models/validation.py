"""
src/models/validation.py

Post-game prediction validation workflow for Big Blue Nation AI Analyst.

Workflow:
  1. Before tip-off:  save_prediction(game_id, result)       — stores pre-game prediction
  2. After final:     validate_game(game_id)                  — compares to actual box scores
  3. Any time:        validation_report(n_games=10)            — aggregate MAE by player/stat

Usage:
  from src.models.validation import save_prediction, validate_game, validation_report

  # Pre-game (in briefing agent or notebook)
  engine = PredictionEngine()
  result = engine.predict_game(opponent='Arkansas Razorbacks', is_home=1, net_rank=55)
  save_prediction('401757123', result)

  # Post-game
  validate_game('401757123')
  validation_report()
"""

import json
import sqlite3
import os
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH  = os.path.join(BASE_DIR, 'data', 'processed', 'kentucky_basketball.db')


# ── Table setup ───────────────────────────────────────────────────────────────

def _ensure_tables(conn):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS game_predictions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id      TEXT UNIQUE,
            predicted_at TEXT,
            opponent     TEXT,
            is_home      INTEGER,
            predicted_uk_score   REAL,
            predicted_opp_score  REAL,
            predicted_win_prob   REAL,
            injuries_json        TEXT,
            projections_json     TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prediction_errors (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id      TEXT,
            validated_at TEXT,
            opponent     TEXT,
            player_name  TEXT,
            stat         TEXT,
            predicted    REAL,
            actual       REAL,
            error        REAL,
            abs_error    REAL
        )
    """)

    conn.commit()


# ── Save pre-game prediction ──────────────────────────────────────────────────

def save_prediction(game_id: str, prediction: dict) -> None:
    """
    Persist a pre-game prediction so it can be validated after the final buzzer.

    Parameters
    ----------
    game_id    : ESPN game ID (string) — find it in the `games` table or ESPN URLs
    prediction : dict returned by PredictionEngine.predict_game()
    """
    conn = sqlite3.connect(DB_PATH)
    _ensure_tables(conn)

    conn.execute("""
        INSERT OR REPLACE INTO game_predictions
            (game_id, predicted_at, opponent, is_home,
             predicted_uk_score, predicted_opp_score, predicted_win_prob,
             injuries_json, projections_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        game_id,
        datetime.now().isoformat(),
        prediction.get('opponent'),
        int(prediction.get('is_home', 0)),
        prediction.get('uk_score'),
        prediction.get('opp_score'),
        prediction.get('win_probability'),
        json.dumps(prediction.get('injuries', [])),
        json.dumps(prediction.get('projections', [])),
    ))

    conn.commit()
    conn.close()
    print(f"✅ Prediction saved for game {game_id} vs {prediction.get('opponent')}")


# ── Run validation after a completed game ────────────────────────────────────

def validate_game(game_id: str, verbose: bool = True) -> dict:
    """
    Compare pre-game predictions to actual box scores for a completed game.

    Writes per-player per-stat errors to `prediction_errors` table.

    Returns
    -------
    dict with keys: game_id, opponent, player_errors (list), team_summary
    """
    conn = sqlite3.connect(DB_PATH)
    _ensure_tables(conn)

    # ── Load saved prediction ─────────────────────────────────────────────────
    row = conn.execute(
        "SELECT * FROM game_predictions WHERE game_id = ?", (game_id,)
    ).fetchone()

    if row is None:
        conn.close()
        raise ValueError(
            f"No saved prediction for game_id='{game_id}'. "
            f"Call save_prediction() before the game."
        )

    cols = [d[0] for d in conn.execute(
        "SELECT * FROM game_predictions LIMIT 0"
    ).description]
    pred_row = dict(zip(cols, row))
    projections = json.loads(pred_row['projections_json'])

    # ── Load actual box scores ────────────────────────────────────────────────
    actuals_df = pd.read_sql(
        "SELECT player_name, points, rebounds, assists, minutes "
        "FROM player_game_stats WHERE game_id = ?",
        conn, params=(game_id,)
    )

    if actuals_df.empty:
        conn.close()
        raise ValueError(
            f"No box score data found for game_id='{game_id}'. "
            f"Run data refresh first: python -m src.ingestion.refresh"
        )

    # ── Compute per-player errors ─────────────────────────────────────────────
    STATS = ['points', 'rebounds', 'assists', 'minutes']
    validated_at = datetime.now().isoformat()
    opponent     = pred_row['opponent']
    player_errors = []

    for proj in projections:
        name   = proj['name']
        actual = actuals_df[actuals_df['player_name'] == name]

        if actual.empty:
            continue

        actual_row = actual.iloc[0]
        player_result = {'player': name, 'stats': {}}

        for stat in STATS:
            predicted  = float(proj.get(stat, 0))
            actual_val = float(actual_row.get(stat, 0))
            error      = predicted - actual_val
            abs_error  = abs(error)

            player_result['stats'][stat] = {
                'predicted':  round(predicted,  1),
                'actual':     round(actual_val, 1),
                'error':      round(error,      1),
                'abs_error':  round(abs_error,  1),
            }

            conn.execute("""
                INSERT INTO prediction_errors
                    (game_id, validated_at, opponent, player_name, stat,
                     predicted, actual, error, abs_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (game_id, validated_at, opponent, name, stat,
                  predicted, actual_val, error, abs_error))

        player_errors.append(player_result)

    conn.commit()
    conn.close()

    # ── Build team summary ────────────────────────────────────────────────────
    team_summary = {}
    for stat in STATS:
        errors = [
            p['stats'][stat]['abs_error']
            for p in player_errors if stat in p['stats']
        ]
        team_summary[stat] = {
            'mae':        round(sum(errors) / len(errors), 2) if errors else None,
            'max_error':  round(max(errors), 1) if errors else None,
            'n_players':  len(errors),
        }

    result = {
        'game_id':      game_id,
        'opponent':     opponent,
        'player_errors': player_errors,
        'team_summary': team_summary,
    }

    if verbose:
        _print_validation(result, pred_row)

    return result


def _print_validation(result: dict, pred_row: dict) -> None:
    """Pretty-print a single game validation result."""
    print(f"\n{'='*65}")
    print(f"📊 POST-GAME VALIDATION — vs {result['opponent'].upper()}")
    print(f"{'='*65}")

    pred_uk  = pred_row['predicted_uk_score']
    pred_opp = pred_row['predicted_opp_score']
    pred_wp  = pred_row['predicted_win_prob']
    print(f"  Predicted: Kentucky {pred_uk:.1f} — {result['opponent']} {pred_opp:.1f}  "
          f"(Win prob: {pred_wp:.1f}%)")
    print()

    header = f"  {'Player':<25} {'Stat':<10} {'Pred':>6} {'Actual':>7} {'Error':>7}"
    print(header)
    print(f"  {'-'*25} {'-'*10} {'-'*6} {'-'*7} {'-'*7}")

    for p in sorted(result['player_errors'],
                    key=lambda x: x['stats'].get('points', {}).get('abs_error', 0),
                    reverse=True):
        first = True
        for stat in ['points', 'rebounds', 'assists', 'minutes']:
            if stat not in p['stats']:
                continue
            s     = p['stats'][stat]
            name  = p['player'] if first else ''
            sign  = '+' if s['error'] >= 0 else ''
            print(f"  {name:<25} {stat:<10} {s['predicted']:>6.1f} {s['actual']:>7.1f} "
                  f"{sign}{s['error']:>6.1f}")
            first = False
        print()

    print(f"  {'─'*60}")
    print(f"  Team MAE Summary:")
    for stat, info in result['team_summary'].items():
        if info['mae'] is not None:
            print(f"    {stat:<12}  MAE = {info['mae']:.2f}  "
                  f"(max error: {info['max_error']:.1f}, n={info['n_players']})")
    print(f"{'='*65}\n")


# ── Aggregate validation report ───────────────────────────────────────────────

def validation_report(n_games: int = 10) -> pd.DataFrame:
    """
    Print and return aggregate MAE across the last n_games validated games,
    broken out by player and stat.

    Returns
    -------
    DataFrame with columns: player_name, stat, mae, bias, n_games
    """
    conn = sqlite3.connect(DB_PATH)
    _ensure_tables(conn)

    df = pd.read_sql("""
        SELECT player_name, stat, predicted, actual, error, abs_error, game_id
        FROM prediction_errors
        ORDER BY validated_at DESC
    """, conn)
    conn.close()

    if df.empty:
        print("No validation data yet. Run validate_game() after a completed game.")
        return df

    # Keep only the last n_games per player
    game_ids = df['game_id'].unique()
    if len(game_ids) > n_games:
        keep = game_ids[:n_games]
        df   = df[df['game_id'].isin(keep)]

    summary = (
        df.groupby(['player_name', 'stat'])
        .agg(
            mae    = ('abs_error', 'mean'),
            bias   = ('error',     'mean'),
            n_games= ('game_id',   'count'),
        )
        .round(2)
        .reset_index()
        .sort_values(['stat', 'mae'], ascending=[True, False])
    )

    print(f"\n{'='*65}")
    print(f"📈 PREDICTION VALIDATION REPORT  (last {n_games} games)")
    print(f"{'='*65}")
    for stat in ['points', 'rebounds', 'assists', 'minutes']:
        sub = summary[summary['stat'] == stat].head(10)
        if sub.empty:
            continue
        print(f"\n  {stat.upper()}")
        print(f"  {'Player':<25} {'MAE':>6}  {'Bias':>6}  {'N':>4}")
        print(f"  {'-'*25} {'-'*6}  {'-'*6}  {'-'*4}")
        for _, r in sub.iterrows():
            sign = '+' if r['bias'] >= 0 else ''
            print(f"  {r['player_name']:<25} {r['mae']:>6.2f}  "
                  f"{sign}{r['bias']:>5.2f}  {r['n_games']:>4}")
    print(f"{'='*65}\n")

    return summary


if __name__ == '__main__':
    validation_report()
