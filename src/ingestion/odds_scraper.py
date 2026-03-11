"""
src/ingestion/odds_scraper.py

Fetch Vegas odds (spread, total, moneyline) for Kentucky games via ESPN's
pickcenter data embedded in the game summary endpoint. No API key required.

Usage:
    from src.ingestion.odds_scraper import get_game_odds, get_next_game_odds

    # By ESPN game ID
    odds = get_game_odds("401851557")

    # Auto-detect next game
    odds = get_next_game_odds()
"""

import sqlite3
import os
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH  = os.path.join(BASE_DIR, 'data', 'processed', 'kentucky_basketball.db')
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary"
KENTUCKY_TEAM_ID = "96"


def get_game_odds(game_id: str) -> dict | None:
    """
    Fetch Vegas odds for a specific ESPN game ID.

    Returns dict with keys:
        spread         float   (negative = UK favored, e.g. -5.5)
        spread_favored str     ('Kentucky Wildcats' or opponent name)
        over_under     float   (e.g. 147.5)
        uk_moneyline   int     (e.g. -220)
        opp_moneyline  int     (e.g. +190)
        provider       str     (e.g. 'ESPN BET')

    Returns None if odds are not yet posted.
    """
    try:
        resp = requests.get(ESPN_URL, params={"event": game_id}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  ⚠️  Odds fetch failed for {game_id}: {e}")
        return None

    pickcenter = data.get("pickcenter", [])
    if not pickcenter:
        return None

    # Prefer ESPN BET; fall back to first provider
    entry = next(
        (p for p in pickcenter if "espn" in p.get("provider", {}).get("name", "").lower()),
        pickcenter[0]
    )

    # Identify which competitor is Kentucky
    header = data.get("header", {})
    competitions = header.get("competitions", [{}])
    competition  = competitions[0] if competitions else {}
    competitors  = competition.get("competitors", [])

    uk_comp  = next((c for c in competitors if c.get("team", {}).get("id") == KENTUCKY_TEAM_ID), None)
    opp_comp = next((c for c in competitors if c.get("team", {}).get("id") != KENTUCKY_TEAM_ID), None)

    opp_name = opp_comp.get("team", {}).get("displayName", "Opponent") if opp_comp else "Opponent"

    # Extract spread
    spread_line  = entry.get("spread") or entry.get("homeTeamOdds", {}).get("spreadLine")
    favorite_id  = entry.get("homeTeamOdds", {}).get("favoriteAbbrev")

    home_odds = entry.get("homeTeamOdds", {})
    away_odds = entry.get("awayTeamOdds", {})

    uk_home = uk_comp and uk_comp.get("homeAway") == "home"
    uk_team_odds  = home_odds if uk_home else away_odds
    opp_team_odds = away_odds if uk_home else home_odds

    uk_ml  = uk_team_odds.get("moneyLine") or uk_team_odds.get("moneyline")
    opp_ml = opp_team_odds.get("moneyLine") or opp_team_odds.get("moneyline")

    over_under = entry.get("overUnder")

    # Determine spread from UK's perspective
    uk_spread = None
    raw_spread = entry.get("spread")
    if raw_spread is not None:
        try:
            raw_spread = float(raw_spread)
            # ESPN spread is from home team perspective
            uk_spread = raw_spread if uk_home else -raw_spread
        except (ValueError, TypeError):
            pass

    if uk_spread is None and home_odds.get("spreadLine") is not None:
        try:
            uk_spread = float(home_odds["spreadLine"]) if uk_home else -float(away_odds.get("spreadLine", 0))
        except (ValueError, TypeError):
            pass

    provider = entry.get("provider", {}).get("name", "Unknown")

    return {
        "game_id":       game_id,
        "spread":        uk_spread,
        "over_under":    float(over_under) if over_under is not None else None,
        "uk_moneyline":  int(uk_ml)  if uk_ml  is not None else None,
        "opp_moneyline": int(opp_ml) if opp_ml is not None else None,
        "opponent":      opp_name,
        "provider":      provider,
    }


def get_next_game_odds() -> dict | None:
    """
    Look up the next scheduled game from the DB and return odds for it.
    Returns None if no upcoming game found or odds not yet available.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute("""
            SELECT id, home_team, away_team, date
            FROM games
            WHERE status NOT IN ('STATUS_FINAL', 'Final')
              AND date >= date('now', '-1 day')
            ORDER BY date
            LIMIT 1
        """).fetchone()
        conn.close()

        if not row:
            return None

        game_id, home_team, away_team, game_date = row
        odds = get_game_odds(game_id)
        if odds:
            odds["game_date"] = game_date
        return odds

    except Exception as e:
        print(f"  ⚠️  get_next_game_odds: {e}")
        return None


if __name__ == "__main__":
    print("Fetching next game odds...")
    odds = get_next_game_odds()
    if odds:
        spread_str = f"{odds['spread']:+.1f}" if odds["spread"] is not None else "N/A"
        ou_str     = str(odds["over_under"]) if odds["over_under"] is not None else "N/A"
        uk_ml_str  = f"{odds['uk_moneyline']:+d}" if odds["uk_moneyline"] is not None else "N/A"
        print(f"\n  {odds['opponent']}")
        print(f"  UK Spread:     {spread_str}")
        print(f"  Over/Under:    {ou_str}")
        print(f"  UK Moneyline:  {uk_ml_str}")
        print(f"  Provider:      {odds['provider']}")
    else:
        print("  No odds available.")
