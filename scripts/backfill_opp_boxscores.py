#!/usr/bin/env python3
"""
Backfill opponent ft_att and off_rebounds for all historical games in opponent_game_stats.
Re-fetches box scores and patches the new columns.
Also rebuilds opponent_game_totals with opp_possessions and opp_off_eff.

Run once: python scripts/backfill_opp_boxscores.py
"""
import sys, os, sqlite3
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion.database import DB_PATH
from src.ingestion.boxscore_client import get_game_boxscore

def backfill():
    conn = sqlite3.connect(DB_PATH)

    # Find games already in opponent_game_stats missing ft_att
    rows = conn.execute("""
        SELECT ogs.game_id, ogs.game_date, ogs.season, ogs.opponent
        FROM opponent_game_stats ogs
        WHERE ogs.ft_att IS NULL OR ogs.ft_att = 0
        ORDER BY ogs.game_date
    """).fetchall()

    print(f"Games missing opp ft_att/off_rebounds: {len(rows)}")
    updated = 0

    for game_id, game_date, season, opponent in rows:
        try:
            result = get_game_boxscore(game_id, game_date[:10], season or '2025-26')
            if not result:
                continue
            _, opp_stats, _ = result
            ft_att       = opp_stats.get('ft_att', 0)
            off_rebounds = opp_stats.get('off_rebounds', 0)
            conn.execute("""
                UPDATE opponent_game_stats
                SET ft_att = ?, off_rebounds = ?
                WHERE game_id = ?
            """, (ft_att, off_rebounds, game_id))
            updated += 1
            print(f"  ✅ {opponent[:35]:<35} ft_att={ft_att}  orb={off_rebounds}")
        except Exception as e:
            print(f"  ⚠️  {game_id}: {e}")

    conn.commit()
    print(f"\nUpdated {updated} / {len(rows)} games")

    # Rebuild opponent_game_totals with new opp_possession + opp_off_eff columns
    print("\nRebuilding opponent_game_totals with possession data...")
    try:
        import pandas as pd

        ogt = pd.read_sql("SELECT * FROM opponent_game_totals", conn)
        ogs = pd.read_sql("""
            SELECT game_id, ft_att as opp_ft_att, off_rebounds as opp_off_reb
            FROM opponent_game_stats
            WHERE ft_att IS NOT NULL
        """, conn)

        ogt = ogt.merge(ogs, on='game_id', how='left')
        ogt['opp_ft_att']  = ogt['opp_ft_att'].fillna(0)
        ogt['opp_off_reb'] = ogt['opp_off_reb'].fillna(0)
        ogt['opp_possessions'] = (
            ogt['opp_fg_att'].fillna(0)
            - ogt['opp_off_reb']
            + ogt['opp_team_turnovers'].fillna(0)
            + 0.44 * ogt['opp_ft_att']
        ).clip(lower=55)
        ogt['opp_off_eff'] = (
            ogt['opp_team_points'] / ogt['opp_possessions'] * 100
        ).clip(60, 140)
        ogt.to_sql('opponent_game_totals', conn, if_exists='replace', index=False)
        print(f"✅ Rebuilt opponent_game_totals with opp_possessions + opp_off_eff ({len(ogt)} rows)")
        print(f"   opp_off_eff mean: {ogt['opp_off_eff'].mean():.1f}, range: {ogt['opp_off_eff'].min():.1f}–{ogt['opp_off_eff'].max():.1f}")
    except Exception as e:
        print(f"⚠️  Could not rebuild opponent_game_totals: {e}")

    conn.close()

if __name__ == '__main__':
    backfill()
