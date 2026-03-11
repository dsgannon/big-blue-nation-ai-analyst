#!/usr/bin/env python3
"""
One-time script to backfill historical game results into the games table.
Fetches 2020-21 through 2024-25 from ESPN and inserts any missing games.
Run once: python scripts/backfill_historical_games.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import sqlite3
from src.ingestion.espn_client import get_historical_schedule
from src.ingestion.database import DB_PATH

def backfill(seasons=None):
    if seasons is None:
        seasons = [2020, 2021, 2022, 2023, 2024]  # fetches 2020-21 through 2024-25

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    total_inserted = 0
    for year in seasons:
        season_str = f"{year}-{str(year+1)[2:]}"
        games = get_historical_schedule(year)
        inserted = 0
        for g in games:
            try:
                cur.execute("""
                    INSERT OR IGNORE INTO games
                    (id, season, date, name, short_name, status, season_type,
                     venue_name, venue_city, venue_state, neutral_site,
                     home_team, away_team, home_score, away_score, network, attendance)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    g['id'], g['season'], g['date'], g['name'], g['short_name'],
                    g['status'], g['season_type'], g['venue_name'], g['venue_city'],
                    g['venue_state'], g['neutral_site'], g['home_team'], g['away_team'],
                    g['home_score'], g['away_score'], g['network'], g['attendance']
                ))
                if cur.rowcount > 0:
                    inserted += 1
            except Exception as e:
                print(f"  Error inserting game {g.get('id')}: {e}")
        print(f"  {season_str}: {len(games)} completed games fetched, {inserted} new rows inserted")
        total_inserted += inserted

    conn.commit()
    conn.close()
    print(f"\nTotal inserted: {total_inserted} historical games")

if __name__ == "__main__":
    print("Backfilling historical game results...")
    backfill()
    print("Done.")
