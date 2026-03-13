"""
scripts/seed_byu_pope.py
------------------------
Seeds Pope-era BYU opponent data into opponent_game_totals for use in
training the opponent scoring model.

Rationale: Mark Pope ran BYU from 2019-2024 before UK. His defensive system
is similar to what he runs at Kentucky, so BYU opponent scoring data provides
additional training signal for "how much will a team score against Pope's defense?"

Only touches opponent_game_totals — no player data is modified.

Usage:
    python scripts/seed_byu_pope.py           # seeds 2022-23 + 2023-24
    python scripts/seed_byu_pope.py --dry-run  # show what would be inserted
    python scripts/seed_byu_pope.py --wipe     # remove BYU rows and re-seed
"""

import sys
import os
import time
import sqlite3
import argparse
from datetime import datetime

import requests
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

DB_PATH      = os.path.join(BASE_DIR, "data", "processed", "kentucky_basketball.db")
ESPN_BASE    = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
BYU_TEAM_ID  = "252"

# Seasons to seed (season_year = year the season ends, e.g. 2024 = 2023-24)
BYU_SEASONS  = [2023, 2024]   # Pope's last two full seasons at BYU

# ── ESPN helpers ───────────────────────────────────────────────────────────────

def get_byu_schedule(season_year: int) -> list[dict]:
    """Fetch completed BYU games for a given season."""
    url = f"{ESPN_BASE}/teams/{BYU_TEAM_ID}/schedule"
    resp = requests.get(url, params={"season": str(season_year)}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for event in data.get("events", []):
        comp   = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {})
        if not status.get("completed"):
            continue

        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})

        season_str = f"{season_year - 1}-{str(season_year)[2:]}"
        games.append({
            "id":         event.get("id"),
            "season":     season_str,
            "date":       event.get("date", "")[:10],
            "home_team":  home.get("team", {}).get("displayName", ""),
            "away_team":  away.get("team", {}).get("displayName", ""),
            "home_id":    home.get("team", {}).get("id", ""),
            "away_id":    away.get("team", {}).get("id", ""),
        })
    return games


def _parse_totals(totals_raw: list) -> dict:
    """
    Parse ESPN totals array into stat dict.
    Layout: [_, pts, fg_made-att, 3pt_made-att, ft_made-att, reb, ast, tov,
             stl, blk, oreb, dreb, fouls]
    """
    def safe_int(val, default=0):
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def parse_split(val):
        """Returns (made, att) from 'x-y' string."""
        try:
            made, att = str(val).split("-")
            return int(made), int(att)
        except Exception:
            return 0, 0

    if not totals_raw or len(totals_raw) < 8:
        return {}

    fg_made, fg_att     = parse_split(totals_raw[2]) if len(totals_raw) > 2 else (0, 0)
    three_made, three_att = parse_split(totals_raw[3]) if len(totals_raw) > 3 else (0, 0)
    _, ft_att           = parse_split(totals_raw[4]) if len(totals_raw) > 4 else (0, 0)

    return {
        "points":       safe_int(totals_raw[1]),
        "rebounds":     safe_int(totals_raw[5]) if len(totals_raw) > 5  else 0,
        "assists":      safe_int(totals_raw[6]) if len(totals_raw) > 6  else 0,
        "turnovers":    safe_int(totals_raw[7]) if len(totals_raw) > 7  else 0,
        "ft_att":       ft_att,
        "off_rebounds": safe_int(totals_raw[10]) if len(totals_raw) > 10 else 0,
        "fg_made":      fg_made,
        "fg_att":       fg_att,
        "three_made":   three_made,
        "three_att":    three_att,
    }


def get_byu_game_boxscore(game_id: str) -> dict | None:
    """
    Fetch a BYU game boxscore and return the OPPONENT's stats
    (i.e., what the non-BYU team scored against Pope's defense).
    """
    url = f"{ESPN_BASE}/summary?event={game_id}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"    ⚠️  Boxscore fetch failed for game {game_id}: {e}")
        return None

    boxscore = data.get("boxscore", {})
    players_data = boxscore.get("players", [])

    byu_team  = None
    opp_team  = None
    for team in players_data:
        if team.get("team", {}).get("id") == BYU_TEAM_ID:
            byu_team = team
        else:
            opp_team = team

    if not byu_team or not opp_team:
        return None

    opp_name = opp_team.get("team", {}).get("displayName", "Unknown")

    # Get totals from the statistics > totals array
    def extract_totals(team_data):
        for sg in team_data.get("statistics", []):
            t = sg.get("totals", [])
            if t:
                return _parse_totals(t)
        return {}

    opp_totals = extract_totals(opp_team)
    byu_totals = extract_totals(byu_team)

    if not opp_totals.get("points"):
        return None

    return {
        "opp_name":   opp_name,
        "opp_stats":  opp_totals,
        "byu_stats":  byu_totals,  # BYU scoring = Pope's offense proxy
    }


# ── Rolling feature computation ────────────────────────────────────────────────

def compute_rolling_features(rows: list[dict]) -> list[dict]:
    """
    Given a chronologically sorted list of raw game rows, compute rolling
    stat columns that the opponent model expects.

    Each row needs: game_date, opp_name, opp_pts, opp_fg_pct, opp_3pt_pct,
                    opp_reb, byu_pts (defensive points allowed).
    """
    # Group rows by opponent so we compute per-opponent rolling avgs
    from collections import defaultdict
    opp_history = defaultdict(list)   # opp_name → list of pts
    byu_pts_history = []              # BYU pts allowed (for uk_def analog)

    result = []
    for row in rows:
        opp   = row["opp_name"]
        pts   = row["opp_pts"]
        fg    = row["opp_fg_pct"]
        three = row["opp_3pt_pct"]
        reb   = row["opp_reb"]
        byu_pts = row["byu_pts"]

        hist  = opp_history[opp]
        byu_h = byu_pts_history

        # Rolling averages (last 3/5 games for this opponent vs Pope-style D)
        roll3 = sum(hist[-3:]) / len(hist[-3:]) if hist else pts
        roll5 = sum(hist[-5:]) / len(hist[-5:]) if hist else pts

        # FG pct rolling (stored separately per opp)
        fg_h  = [r["opp_fg_pct"] for r in result if r["opp_name"] == opp]
        fg3   = sum(fg_h[-3:]) / len(fg_h[-3:]) if fg_h else fg

        three_h = [r["opp_3pt_pct"] for r in result if r["opp_name"] == opp]
        three3  = sum(three_h[-3:]) / len(three_h[-3:]) if three_h else three

        reb_h = [r["opp_reb"] for r in result if r["opp_name"] == opp]
        reb3  = sum(reb_h[-3:]) / len(reb_h[-3:]) if reb_h else reb

        # BYU defensive rolling (analog to uk_def_*)
        uk_def_roll3   = sum(byu_h[-3:]) / len(byu_h[-3:]) if byu_h else byu_pts
        uk_def_roll5   = sum(byu_h[-5:]) / len(byu_h[-5:]) if byu_h else byu_pts
        uk_def_season  = sum(byu_h) / len(byu_h) if byu_h else byu_pts

        # Pace/efficiency
        opp_poss = (
            row["opp_fg_att"] - row["opp_off_reb"]
            + row["opp_tov"]
            + 0.44 * row["opp_ft_att"]
        )
        opp_off_eff = (pts / opp_poss * 100) if opp_poss > 0 else 100.0

        # Pace rolling (last 3)
        pace_h = [r["opp_possessions"] for r in result if r["opp_name"] == opp]
        game_pace_roll3 = sum(pace_h[-3:]) / len(pace_h[-3:]) if pace_h else opp_poss

        eff_h  = [r["opp_off_eff"] for r in result if r["opp_name"] == opp]
        opp_off_eff_roll3 = sum(eff_h[-3:]) / len(eff_h[-3:]) if eff_h else opp_off_eff

        result.append({
            **row,
            "opp_pts_roll3":      round(roll3, 2),
            "opp_pts_roll5":      round(roll5, 2),
            "opp_fg_pct_roll3":   round(fg3, 3),
            "opp_three_pct_roll3":round(three3, 3),
            "opp_reb_roll3":      round(reb3, 2),
            "uk_def_roll3":       round(uk_def_roll3, 2),
            "uk_def_roll5":       round(uk_def_roll5, 2),
            "uk_def_season":      round(uk_def_season, 2),
            "opp_possessions":    round(opp_poss, 2),
            "opp_off_eff":        round(opp_off_eff, 2),
            "game_pace_roll3":    round(game_pace_roll3, 2),
            "opp_off_eff_roll3":  round(opp_off_eff_roll3, 2),
        })

        # Update histories AFTER computing (so this game isn't included in its own rolling avg)
        opp_history[opp].append(pts)
        byu_pts_history.append(byu_pts)

    return result


# ── Database writes ────────────────────────────────────────────────────────────

def wipe_byu_rows(conn: sqlite3.Connection):
    """Remove all rows seeded from BYU data."""
    cur = conn.cursor()
    cur.execute("DELETE FROM opponent_game_totals WHERE source = 'byu_pope'")
    n = cur.rowcount
    conn.commit()
    print(f"🗑️  Removed {n} existing BYU-Pope rows.")


def insert_rows(conn: sqlite3.Connection, rows: list[dict], dry_run: bool = False):
    """Insert computed rows into opponent_game_totals."""
    # Ensure source column exists
    try:
        conn.execute("ALTER TABLE opponent_game_totals ADD COLUMN source TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists

    cur = conn.cursor()
    inserted = 0
    skipped  = 0

    for row in rows:
        fg_pct    = row["opp_fg_made"] / row["opp_fg_att"] if row["opp_fg_att"] > 0 else 0.0
        three_pct = row["opp_three_made"] / row["opp_three_att"] if row["opp_three_att"] > 0 else 0.0

        values = (
            row["game_id"],
            row["game_date"],
            row["opp_name"],          # team = opponent name (who scored)
            row["opp_pts"],           # opp_team_points
            row["opp_reb"],           # opp_team_rebounds
            row["opp_assists"],       # opp_team_assists
            row["opp_tov"],           # opp_team_turnovers
            row["opp_fg_made"],       # opp_fg_made
            row["opp_fg_att"],        # opp_fg_att
            row["opp_three_made"],    # opp_three_made
            row["opp_three_att"],     # opp_three_att
            round(fg_pct, 3),         # opp_fg_pct
            round(three_pct, 3),      # opp_three_pct
            row["opp_pts_roll3"],     # opp_pts_roll3
            row["opp_pts_roll5"],     # opp_pts_roll5
            row["opp_fg_pct_roll3"],  # opp_fg_pct_roll3
            row["opp_three_pct_roll3"],# opp_three_pct_roll3
            row["opp_reb_roll3"],     # opp_reb_roll3
            row["uk_def_roll3"],      # uk_def_roll3  (= BYU pts allowed roll3)
            row["uk_def_roll5"],      # uk_def_roll5
            row["uk_def_season"],     # uk_def_season
            row["opp_ft_att"],        # opp_ft_att
            row["opp_off_reb"],       # opp_off_reb
            row["opp_possessions"],   # opp_possessions
            row["opp_off_eff"],       # opp_off_eff
            "byu_pope",              # source tag
        )

        if dry_run:
            print(f"  DRY RUN: {row['game_date']} | {row['opp_name']:30s} | "
                  f"pts={row['opp_pts']} | roll3={row['opp_pts_roll3']:.1f}")
            inserted += 1
            continue

        try:
            cur.execute("""
                INSERT OR IGNORE INTO opponent_game_totals
                (game_id, game_date, team,
                 opp_team_points, opp_team_rebounds, opp_team_assists, opp_team_turnovers,
                 opp_fg_made, opp_fg_att, opp_three_made, opp_three_att,
                 opp_fg_pct, opp_three_pct,
                 opp_pts_roll3, opp_pts_roll5,
                 opp_fg_pct_roll3, opp_three_pct_roll3, opp_reb_roll3,
                 uk_def_roll3, uk_def_roll5, uk_def_season,
                 opp_ft_att, opp_off_reb, opp_possessions, opp_off_eff,
                 source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, values)
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1
        except sqlite3.OperationalError as e:
            # source column may not exist in older schema — fall back without it
            cur.execute("""
                INSERT OR IGNORE INTO opponent_game_totals
                (game_id, game_date, team,
                 opp_team_points, opp_team_rebounds, opp_team_assists, opp_team_turnovers,
                 opp_fg_made, opp_fg_att, opp_three_made, opp_three_att,
                 opp_fg_pct, opp_three_pct,
                 opp_pts_roll3, opp_pts_roll5,
                 opp_fg_pct_roll3, opp_three_pct_roll3, opp_reb_roll3,
                 uk_def_roll3, uk_def_roll5, uk_def_season,
                 opp_ft_att, opp_off_reb, opp_possessions, opp_off_eff)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, values[:-1])
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1

    if not dry_run:
        conn.commit()
    return inserted, skipped


# ── Main pipeline ──────────────────────────────────────────────────────────────

def seed_byu_seasons(seasons: list[int], dry_run: bool = False, wipe: bool = False):
    conn = sqlite3.connect(DB_PATH)

    if wipe and not dry_run:
        wipe_byu_rows(conn)

    all_raw_rows = []

    for season_year in seasons:
        season_str = f"{season_year - 1}-{str(season_year)[2:]}"
        print(f"\n📅 Fetching BYU {season_str} schedule...")

        schedule = get_byu_schedule(season_year)
        print(f"   {len(schedule)} completed games found")

        raw_rows = []
        for i, game in enumerate(sorted(schedule, key=lambda g: g["date"])):
            game_id   = game["id"]
            game_date = game["date"]

            # Skip if already in DB (and not wiping)
            if not wipe and not dry_run:
                existing = conn.execute(
                    "SELECT 1 FROM opponent_game_totals WHERE game_id=?", (game_id,)
                ).fetchone()
                if existing:
                    continue

            result = get_byu_game_boxscore(game_id)
            if not result:
                print(f"   ⚠️  Game {game_id} ({game_date}): no boxscore")
                time.sleep(0.3)
                continue

            opp_s = result["opp_stats"]
            byu_s = result["byu_stats"]

            fg_att    = opp_s.get("fg_att", 0)
            off_reb   = opp_s.get("off_rebounds", 0)
            tov       = opp_s.get("turnovers", 0)
            ft_att    = opp_s.get("ft_att", 0)
            pts       = opp_s.get("points", 0)
            three_att = opp_s.get("three_att", 0)

            fg_pct    = opp_s["fg_made"] / fg_att if fg_att > 0 else 0.0
            three_pct = opp_s["three_made"] / three_att if three_att > 0 else 0.0

            raw_rows.append({
                "game_id":       game_id,
                "game_date":     game_date,
                "season":        season_str,
                "opp_name":      result["opp_name"],
                "opp_pts":       pts,
                "opp_reb":       opp_s.get("rebounds", 0),
                "opp_assists":   opp_s.get("assists", 0),
                "opp_tov":       tov,
                "opp_fg_made":   opp_s.get("fg_made", 0),
                "opp_fg_att":    fg_att,
                "opp_three_made":opp_s.get("three_made", 0),
                "opp_three_att": three_att,
                "opp_ft_att":    ft_att,
                "opp_off_reb":   off_reb,
                "opp_fg_pct":    round(fg_pct, 3),
                "opp_3pt_pct":   round(three_pct, 3),
                "byu_pts":       byu_s.get("points", 70),  # BYU scoring (Pope offense)
            })

            print(f"   ✓ {game_date} | {result['opp_name']:30s} | {pts} pts")
            time.sleep(0.25)   # be kind to ESPN API

        print(f"   Fetched {len(raw_rows)} boxscores for {season_str}")
        all_raw_rows.extend(raw_rows)

    if not all_raw_rows:
        print("\n✅ Nothing new to seed.")
        conn.close()
        return

    print(f"\n🔧 Computing rolling features for {len(all_raw_rows)} games...")
    # Sort by date so rolling averages are computed chronologically
    all_raw_rows.sort(key=lambda r: r["game_date"])
    computed_rows = compute_rolling_features(all_raw_rows)

    print(f"💾 Inserting into opponent_game_totals...")
    inserted, skipped = insert_rows(conn, computed_rows, dry_run=dry_run)

    conn.close()

    total_before = 67  # known count before BYU seeding
    print(f"\n✅ Done.")
    if dry_run:
        print(f"   DRY RUN: {inserted} rows would be inserted")
    else:
        print(f"   Inserted: {inserted} | Skipped (already existed): {skipped}")
        print(f"   opponent_game_totals: ~{total_before} → ~{total_before + inserted} rows")
        print(f"\n⚡ Retrain opponent model to apply: ./scripts/retrain.sh --no-refresh")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed Pope-era BYU opponent data into opponent_game_totals"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print rows without writing to DB")
    parser.add_argument("--wipe", action="store_true",
                        help="Remove existing BYU rows before re-seeding")
    parser.add_argument("--seasons", nargs="+", type=int, default=BYU_SEASONS,
                        help="Season years to fetch (default: 2023 2024)")
    args = parser.parse_args()

    seed_byu_seasons(
        seasons=args.seasons,
        dry_run=args.dry_run,
        wipe=args.wipe,
    )
