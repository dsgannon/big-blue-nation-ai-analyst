#!/usr/bin/env python3
"""
One-time script to backfill historical game results into the games table.
ESPN season convention: season=Y covers the (Y-1)-(Y) season.
  e.g. season=2024 → 2023-24, season=2025 → 2024-25
Fetches regular season + postseason for each year.
Run once: python scripts/backfill_historical_games.py
"""
import sys, os, sqlite3, requests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion.database import DB_PATH

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
KENTUCKY_TEAM_ID = "96"

def fetch_season(espn_year, season_types=(2, 3)):
    """Fetch completed games for espn_year across given season types (2=regular, 3=postseason)."""
    season_label = f"{espn_year - 1}-{str(espn_year)[-2:]}"
    games = []
    for stype in season_types:
        r = requests.get(f"{BASE_URL}/teams/{KENTUCKY_TEAM_ID}/schedule",
                         params={"season": str(espn_year), "seasontype": stype})
        for event in r.json().get("events", []):
            comp = event.get("competitions", [{}])[0]
            status = comp.get("status", {}).get("type", {})
            if not status.get("completed", False):
                continue
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})
            hs  = home.get("score", {})
            aws = away.get("score", {})
            games.append({
                'id':          event.get("id"),
                'season':      season_label,
                'date':        event.get("date", "")[:10],
                'name':        event.get("name", ""),
                'short_name':  event.get("shortName", ""),
                'status':      status.get("name", ""),
                'season_type': event.get("seasonType", {}).get("name", ""),
                'venue_name':  comp.get("venue", {}).get("fullName", ""),
                'venue_city':  comp.get("venue", {}).get("address", {}).get("city", ""),
                'venue_state': comp.get("venue", {}).get("address", {}).get("state", ""),
                'neutral_site':int(comp.get("neutralSite", False)),
                'home_team':   home.get("team", {}).get("displayName", ""),
                'away_team':   away.get("team", {}).get("displayName", ""),
                'home_score':  hs.get("displayValue") if isinstance(hs, dict) else hs,
                'away_score':  aws.get("displayValue") if isinstance(aws, dict) else aws,
                'network':     None,
                'attendance':  None,
            })
    return games


def backfill(espn_years=None):
    """
    espn_years: list of ESPN season years to fetch.
    ESPN year Y → season label (Y-1)-(Y[-2:])
    Default: 2021-2025 → covers 2020-21 through 2024-25
    """
    if espn_years is None:
        espn_years = [2021, 2022, 2023, 2024, 2025]

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    total_inserted = 0

    for year in espn_years:
        games = fetch_season(year)
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
        season_label = f"{year - 1}-{str(year)[-2:]}"
        print(f"  {season_label}: {len(games)} completed games, {inserted} new rows inserted")
        total_inserted += inserted

    conn.commit()
    conn.close()
    print(f"\nTotal inserted: {total_inserted} games")


if __name__ == "__main__":
    print("Backfilling historical game results...")
    backfill()
    print("Done.")
