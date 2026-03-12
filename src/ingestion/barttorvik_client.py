"""
src/ingestion/barttorvik_client.py
Fetches team advanced stats from BartTorvik's public JSON endpoint.

Endpoint: https://barttorvik.com/2026_team_results.json
No Cloudflare block on this raw JSON file (only the HTML pages are gated).

Column mapping (0-indexed, verified against known team values):
  0  = t_rank
  1  = team_name
  2  = conference
  3  = record
  4  = adj_o          (offensive efficiency per 100 possessions, adjusted)
  5  = adj_o_rank
  6  = adj_d          (defensive efficiency per 100 possessions, adjusted; lower = better)
  7  = adj_d_rank
  8  = barthag        (probability of beating average D1 team; proxy for adj_em)
  9  = games
  10 = proj_wins
  11 = proj_losses
  12 = conf_wins
  13 = conf_losses
  14 = conf_record
  33 = luck           (positive = lucky, negative = unlucky)
  44 = tempo          (adjusted possessions per 40 minutes)
"""

import requests
import logging
from datetime import datetime

log = logging.getLogger(__name__)

# Column indices
COL_RANK        = 0
COL_TEAM        = 1
COL_CONF        = 2
COL_RECORD      = 3
COL_ADJ_O       = 4
COL_ADJ_O_RANK  = 5
COL_ADJ_D       = 6
COL_ADJ_D_RANK  = 7
COL_BARTHAG     = 8
COL_GAMES       = 9
COL_LUCK        = 33
COL_TEMPO       = 44

BASE_URL = "https://barttorvik.com/{year}_team_results.json"
HEADERS  = {"User-Agent": "Mozilla/5.0 (compatible; BBN-AI-Analyst/1.0)"}


def get_all_team_stats(year: int = 2026) -> list[dict]:
    """
    Fetch all teams' advanced stats for the given season year.
    Returns a list of dicts with parsed fields.
    """
    url = BASE_URL.format(year=year)
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        log.error(f"BartTorvik fetch failed: {e}")
        return []

    results = []
    for row in raw:
        try:
            results.append({
                "team_name":   row[COL_TEAM],
                "conference":  row[COL_CONF],
                "record":      row[COL_RECORD],
                "t_rank":      int(row[COL_RANK]),
                "adj_o":       round(float(row[COL_ADJ_O]), 2),
                "adj_o_rank":  int(row[COL_ADJ_O_RANK]),
                "adj_d":       round(float(row[COL_ADJ_D]), 2),
                "adj_d_rank":  int(row[COL_ADJ_D_RANK]),
                "adj_em":      round(float(row[COL_ADJ_O]) - float(row[COL_ADJ_D]), 2),
                "barthag":     round(float(row[COL_BARTHAG]), 4),
                "luck":        round(float(row[COL_LUCK]), 4),
                "tempo":       round(float(row[COL_TEMPO]), 2),
                "fetched_at":  datetime.utcnow().isoformat(),
            })
        except (IndexError, TypeError, ValueError):
            continue  # skip malformed rows

    log.info(f"BartTorvik: fetched {len(results)} teams for {year}")
    return results


def get_team_stats(team_name: str, year: int = 2026) -> dict | None:
    """Return advanced stats for a single team (partial name match)."""
    all_teams = get_all_team_stats(year)
    name_lower = team_name.lower()
    matches = [t for t in all_teams if name_lower in t["team_name"].lower()]
    if not matches:
        return None
    # Prefer exact match, fall back to first partial
    exact = [m for m in matches if m["team_name"].lower() == name_lower]
    return exact[0] if exact else matches[0]


if __name__ == "__main__":
    import json
    ky = get_team_stats("Kentucky")
    print(json.dumps(ky, indent=2))
