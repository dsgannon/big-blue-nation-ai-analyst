"""
scripts/seed_transfer.py

Seed a transfer player's stats from their prior school into player_game_stats.
Fetches every completed game from the previous team's schedule, pulls the
player's individual box score, and inserts with their UK roster name.

Usage:
  python scripts/seed_transfer.py \
    --player "Denzel Aberdeen" \
    --team-id 57 \
    --season 2025           # 2025 = 2024-25 season
    --dry-run               # preview without writing

Examples:
  python scripts/seed_transfer.py --player "Denzel Aberdeen" --team-id 57 --season 2025
  python scripts/seed_transfer.py --player "Jaland Lowe"     --team-id 221 --season 2025
  python scripts/seed_transfer.py --player "Mouhamed Dioubate" --team-id 333 --season 2025
"""

import sys, os, argparse, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from difflib import SequenceMatcher
from src.ingestion.boxscore_client import parse_player_stats
from src.ingestion.database import get_connection

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"


def get_team_schedule(team_id: str, season_year: int) -> list[dict]:
    """Fetch all completed games for a team in a given season."""
    url = f"{BASE_URL}/teams/{team_id}/schedule"
    r = requests.get(url, params={"season": str(season_year)})
    r.raise_for_status()
    data = r.json()

    games = []
    season_str = f"{season_year - 1}-{str(season_year)[2:]}"
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {})
        if not status.get("completed", False):
            continue
        date = event.get("date", "")[:10]
        games.append({
            "id":   event.get("id"),
            "date": date,
            "name": event.get("name", ""),
            "season": season_str,
        })
    return games


def fuzzy_match(name: str, candidates: list[str], threshold=0.72) -> str | None:
    """Return best fuzzy match for name among candidates."""
    best, best_score = None, 0.0
    name_lower = name.lower()
    for c in candidates:
        score = SequenceMatcher(None, name_lower, c.lower()).ratio()
        if score > best_score:
            best, best_score = c, score
    return best if best_score >= threshold else None


def fetch_player_stats_from_game(game_id: str, game_date: str, season: str,
                                  team_id: str, target_name: str) -> dict | None:
    """
    Pull a specific player's box score line from a game.
    Returns a player_game_stats-compatible dict, or None if player not found.
    """
    url = f"{BASE_URL}/summary?event={game_id}"
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()

    boxscore = data.get("boxscore", {})
    players_data = boxscore.get("players", [])

    # Find the target team
    target_team = None
    for team in players_data:
        if str(team.get("team", {}).get("id")) == str(team_id):
            target_team = team
            break

    if not target_team:
        return None

    # Determine opponent and home/away for THIS team (not Kentucky)
    header = data.get("header", {})
    competitions = header.get("competitions", [{}])
    competition = competitions[0] if competitions else {}
    competitors = competition.get("competitors", [])

    home_away = "home"
    opponent_name = "Unknown"
    for comp in competitors:
        cid = str(comp.get("team", {}).get("id", ""))
        if cid == str(team_id):
            home_away = comp.get("homeAway", "home")
        else:
            opponent_name = comp.get("team", {}).get("displayName", "Unknown")

    # Find the player in this team's roster
    all_athletes = []
    for stats_group in target_team.get("statistics", []):
        for athlete in stats_group.get("athletes", []):
            athlete_info = athlete.get("athlete", {})
            all_athletes.append((athlete_info.get("displayName", ""), athlete))

    candidate_names = [name for name, _ in all_athletes]
    matched_name = fuzzy_match(target_name, candidate_names)
    if not matched_name:
        return None

    # Find the athlete dict for matched name
    for name, athlete in all_athletes:
        if name == matched_name:
            parsed = parse_player_stats(athlete, game_id, game_date, opponent_name, home_away, season)
            if parsed:
                # Override player_name with the canonical UK DB name
                parsed["player_name"] = target_name
                return parsed, matched_name
    return None


def save_player_stats_batch(rows: list[dict], season: str, dry_run=False) -> int:
    """Insert rows into player_game_stats. Returns count inserted."""
    if dry_run:
        return len(rows)

    conn = get_connection()
    inserted = 0
    for row in rows:
        try:
            conn.execute("""
                INSERT OR IGNORE INTO player_game_stats (
                    game_id, game_date, season, player_id, player_name,
                    jersey, position, opponent, home_away, starter,
                    minutes, points, rebounds, assists, turnovers,
                    steals, blocks, off_rebounds, def_rebounds, fouls,
                    fg_made, fg_att, fg_pct, three_made, three_att, three_pct,
                    ft_made, ft_att, ft_pct
                ) VALUES (
                    :game_id, :game_date, :season, :player_id, :player_name,
                    :jersey, :position, :opponent, :home_away, :starter,
                    :minutes, :points, :rebounds, :assists, :turnovers,
                    :steals, :blocks, :off_rebounds, :def_rebounds, :fouls,
                    :fg_made, :fg_att, :fg_pct, :three_made, :three_att, :three_pct,
                    :ft_made, :ft_att, :ft_pct
                )
            """, row)
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        except Exception as e:
            print(f"    ⚠️  Insert failed: {e}")
    conn.commit()
    conn.close()
    return inserted


def main():
    parser = argparse.ArgumentParser(description="Seed transfer player stats from prior school")
    parser.add_argument("--player",   required=True,  help="Player name as stored in UK DB")
    parser.add_argument("--team-id",  required=True,  help="ESPN team ID of prior school")
    parser.add_argument("--season",   required=True,  type=int,
                        help="Season end year (e.g. 2025 for 2024-25)")
    parser.add_argument("--dry-run",  action="store_true", help="Preview without writing to DB")
    args = parser.parse_args()

    season_str = f"{args.season - 1}-{str(args.season)[2:]}"
    print(f"\nSeeding transfer stats: {args.player}")
    print(f"  Prior school team ID: {args.team_id}")
    print(f"  Season: {season_str}")
    print(f"  Mode: {'DRY RUN' if args.dry_run else 'WRITE'}")
    print()

    print("Fetching schedule...")
    games = get_team_schedule(args.team_id, args.season)
    print(f"  {len(games)} completed games found")

    rows = []
    not_found = 0

    for i, game in enumerate(games):
        try:
            result = fetch_player_stats_from_game(
                game["id"], game["date"], season_str,
                args.team_id, args.player
            )
            if result:
                row, matched_as = result
                rows.append(row)
                pts = row.get("points", 0)
                reb = row.get("rebounds", 0)
                ast = row.get("assists", 0)
                min_ = row.get("minutes", 0)
                print(f"  ✅ {game['date']}  vs {row.get('opponent','?')[:25]:<25}  "
                      f"{pts:>3}pts {reb:>2}reb {ast:>2}ast  {min_:>2}min"
                      + (f"  (matched as '{matched_as}')" if matched_as != args.player else ""))
            else:
                not_found += 1
                if not_found <= 3:
                    print(f"  —  {game['date']}  {game['name'][:50]}  (not found)")
        except Exception as e:
            print(f"  ⚠️  {game['date']} failed: {e}")

        time.sleep(0.15)  # be polite to ESPN

    print(f"\nFound stats in {len(rows)}/{len(games)} games  ({not_found} not found)")

    if rows:
        inserted = save_player_stats_batch(rows, season_str, dry_run=args.dry_run)
        if args.dry_run:
            print(f"DRY RUN — would insert {inserted} rows")
        else:
            print(f"✅ Inserted {inserted} new rows into player_game_stats")
            print(f"   Run ./scripts/retrain.sh --no-refresh to retrain with new data")


if __name__ == "__main__":
    main()
