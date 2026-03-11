"""
src/models/thresholds.py

Standalone threshold recomputation — safe to run after every game.

Logic mirrors notebook cell 21: for each player in the current season,
find the stat level above which Kentucky wins at high rates. Results are
written to the `player_thresholds` table in the DB.

Usage:
  python -m src.models.thresholds              # recompute and save
  from src.models.thresholds import compute_thresholds
  compute_thresholds()
"""

import json
import os
import sqlite3

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH  = os.path.join(BASE_DIR, 'data', 'processed', 'kentucky_basketball.db')


def compute_thresholds(season: str = '2025-26', min_games: int = 8,
                        min_win_pct: float = 0.65, min_n_above: int = 4,
                        verbose: bool = True) -> dict:
    """
    Recompute player win-rate thresholds from current season data and
    overwrite the `player_thresholds` table in the DB.

    Parameters
    ----------
    season        : season string to filter on (default '2025-26')
    min_games     : minimum games needed for a player to get thresholds
    min_win_pct   : minimum win% above the threshold to be meaningful
    min_n_above   : minimum games above threshold for statistical credibility
    verbose       : print a summary

    Returns
    -------
    dict of {player_name: {stat: threshold_dict}}
    """
    conn = sqlite3.connect(DB_PATH)

    # ── Load player stats for the current season ───────────────────────────────
    player_df = pd.read_sql("""
        SELECT p.player_name, p.game_id, p.points, p.rebounds, p.assists
        FROM player_game_stats p
        WHERE p.season = ?
    """, conn, params=(season,))

    # ── Load game outcomes ─────────────────────────────────────────────────────
    games_df = pd.read_sql("""
        SELECT id AS game_id,
               home_team, away_team,
               CAST(home_score AS REAL) AS home_score,
               CAST(away_score AS REAL) AS away_score
        FROM games
        WHERE home_score IS NOT NULL AND away_score IS NOT NULL
        AND season = ?
    """, conn, params=(season,))

    games_df['uk_won'] = (
        ((games_df['home_team'] == 'Kentucky Wildcats') &
         (games_df['home_score'] > games_df['away_score'])) |
        ((games_df['away_team'] == 'Kentucky Wildcats') &
         (games_df['away_score'] > games_df['home_score']))
    ).astype(int)

    df = player_df.merge(games_df[['game_id', 'uk_won']], on='game_id', how='inner')

    # ── Compute thresholds per player ──────────────────────────────────────────
    all_thresholds = {}

    for player in df['player_name'].unique():
        pdata = df[df['player_name'] == player].dropna(subset=['uk_won'])
        if len(pdata) < min_games:
            continue

        player_thresholds = {}
        for stat in ['points', 'rebounds', 'assists']:
            vals = pdata[stat].dropna()
            if len(vals) < min_games:
                continue

            best      = None
            best_diff = 0.0

            for pct in [0.25, 0.40, 0.50, 0.60, 0.75]:
                thresh = vals.quantile(pct)
                if thresh < 1:
                    continue

                above = pdata[pdata[stat] >= thresh]
                below = pdata[pdata[stat] <  thresh]

                if len(above) < min_n_above or len(below) < 3:
                    continue

                win_above = above['uk_won'].mean()
                win_below = below['uk_won'].mean()
                diff      = win_above - win_below

                if diff > best_diff and win_above >= min_win_pct:
                    best_diff = diff
                    best = {
                        'threshold':      str(round(thresh, 1)),
                        'win_pct_above':  round(win_above, 3),
                        'win_pct_below':  round(win_below, 3),
                        'win_pct_diff':   round(diff, 3),
                        'n_games_above':  int(len(above)),
                        'label':          f'{stat.capitalize()} {round(thresh)}+',
                    }

            if best:
                player_thresholds[stat] = best

        if player_thresholds:
            all_thresholds[player] = player_thresholds

    # ── Write to DB ────────────────────────────────────────────────────────────
    thresh_rows = [
        {'player_name': p, 'thresholds_json': json.dumps(t)}
        for p, t in all_thresholds.items()
    ]
    pd.DataFrame(thresh_rows).to_sql(
        'player_thresholds', conn, if_exists='replace', index=False
    )
    conn.close()

    if verbose:
        print(f'✅ Thresholds recomputed for {len(all_thresholds)} players '
              f'({season}, {sum(len(v) for v in all_thresholds.values())} total thresholds)')
        for player, t in all_thresholds.items():
            for stat, info in t.items():
                print(f'   {player}: {info["label"]} → '
                      f'win% above {info["win_pct_above"]:.0%} '
                      f'(n={info["n_games_above"]})')

    return all_thresholds


if __name__ == '__main__':
    compute_thresholds()
