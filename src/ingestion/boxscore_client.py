import requests
import json

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
KENTUCKY_TEAM_ID = "96"

# Stat column order from ESPN
STAT_KEYS = [
    "minutes", "points", "fg", "three_pt", "ft",
    "rebounds", "assists", "turnovers", "steals", "blocks",
    "off_rebounds", "def_rebounds", "fouls"
]

def parse_player_stats(athlete, game_id, game_date, opponent, home_away, season):
    """Parse a single player's stats from ESPN boxscore format"""
    if athlete.get("didNotPlay") or not athlete.get("stats"):
        return None

    stats_raw = athlete.get("stats", [])
    
    # Map stats array to named fields
    def get_stat(index, default=0):
        try:
            val = stats_raw[index]
            # Handle made-attempted format like "5-10"
            if "-" in str(val):
                made, attempted = val.split("-")
                return int(made), int(attempted)
            return float(val) if "." in str(val) else int(val)
        except:
            return default

    # Parse shooting stats
    fg = get_stat(2)
    three_pt = get_stat(3)
    ft = get_stat(4)

    fg_made = fg[0] if isinstance(fg, tuple) else 0
    fg_att = fg[1] if isinstance(fg, tuple) else 0
    three_made = three_pt[0] if isinstance(three_pt, tuple) else 0
    three_att = three_pt[1] if isinstance(three_pt, tuple) else 0
    ft_made = ft[0] if isinstance(ft, tuple) else 0
    ft_att = ft[1] if isinstance(ft, tuple) else 0

    athlete_info = athlete.get("athlete", {})

    return {
        "game_id": game_id,
        "game_date": game_date,
        "season": season,
        "player_id": athlete_info.get("id"),
        "player_name": athlete_info.get("displayName"),
        "jersey": athlete_info.get("jersey"),
        "position": athlete_info.get("position", {}).get("abbreviation"),
        "opponent": opponent,
        "home_away": home_away,
        "starter": athlete.get("starter", False),
        # Core stats
        "minutes": get_stat(0),
        "points": get_stat(1),
        "rebounds": get_stat(5),
        "assists": get_stat(6),
        "turnovers": get_stat(7),
        "steals": get_stat(8),
        "blocks": get_stat(9),
        "off_rebounds": get_stat(10),
        "def_rebounds": get_stat(11),
        "fouls": get_stat(12),
        # Shooting
        "fg_made": fg_made,
        "fg_att": fg_att,
        "fg_pct": round(fg_made / fg_att, 3) if fg_att > 0 else 0,
        "three_made": three_made,
        "three_att": three_att,
        "three_pct": round(three_made / three_att, 3) if three_att > 0 else 0,
        "ft_made": ft_made,
        "ft_att": ft_att,
        "ft_pct": round(ft_made / ft_att, 3) if ft_att > 0 else 0,
    }

def get_game_boxscore(game_id, game_date, season="2025-26"):
    """Get full boxscore for a single game"""
    url = f"{BASE_URL}/summary?event={game_id}"
    response = requests.get(url)
    data = response.json()

    boxscore = data.get("boxscore", {})
    players_data = boxscore.get("players", [])

    # Find Kentucky and opponent
    uk_team = None
    opp_team = None
    for team in players_data:
        team_id = team.get("team", {}).get("id")
        if team_id == KENTUCKY_TEAM_ID:
            uk_team = team
        else:
            opp_team = team

    if not uk_team:
        return []

    opponent_name = opp_team.get("team", {}).get("displayName", "Unknown") if opp_team else "Unknown"

    # Determine home/away from header
    header = data.get("header", {})
    competitions = header.get("competitions", [{}])
    competition = competitions[0] if competitions else {}
    competitors = competition.get("competitors", [])
    home_away = "home"
    for comp in competitors:
        if comp.get("team", {}).get("id") == KENTUCKY_TEAM_ID:
            home_away = comp.get("homeAway", "home")
            break

    # Parse all Kentucky players
    player_stats = []
    for stats_group in uk_team.get("statistics", []):
        for athlete in stats_group.get("athletes", []):
            parsed = parse_player_stats(
                athlete, game_id, game_date,
                opponent_name, home_away, season
            )
            if parsed:
                player_stats.append(parsed)

    # Also grab team-level opponent stats for defensive features
    opp_stats = get_team_totals(opp_team) if opp_team else {}

    return player_stats, opp_stats

def get_team_totals(team_data):
    """Extract team totals from boxscore"""
    totals = {}
    for stats_group in team_data.get("statistics", []):
        totals_raw = stats_group.get("totals", [])
        if totals_raw:
            totals = {
                "points": int(totals_raw[1]) if len(totals_raw) > 1 else 0,
                "rebounds": int(totals_raw[5]) if len(totals_raw) > 5 else 0,
                "assists": int(totals_raw[6]) if len(totals_raw) > 6 else 0,
                "turnovers": int(totals_raw[7]) if len(totals_raw) > 7 else 0,
            }
    return totals

def get_season_boxscores(schedule, season="2025-26"):
    """Get box scores for all completed games in a schedule"""
    all_player_stats = []
    all_opp_stats = []
    completed = [g for g in schedule if g.get("status") in ["Final", "STATUS_FINAL"]]

    print(f"  Fetching box scores for {len(completed)} completed games...")

    for i, game in enumerate(completed):
        game_id = game["id"]
        game_date = game["date"][:10]

        try:
            result = get_game_boxscore(game_id, game_date, season)
            if result:
                player_stats, opp_stats = result
                all_player_stats.extend(player_stats)
                opp_stats["game_id"] = game_id
                opp_stats["opponent"] = game.get("away_team") if game.get("home_team") == "Kentucky Wildcats" else game.get("home_team")
                all_opp_stats.append(opp_stats)
                print(f"  ✅ {i+1}/{len(completed)} — {game['name'][:50]}")
        except Exception as e:
            print(f"  ❌ {i+1}/{len(completed)} — {game['name'][:50]} — {e}")

    return all_player_stats, all_opp_stats

# Test it
if __name__ == "__main__":
    from espn_client import get_team_schedule

    print("=" * 55)
    print("  KENTUCKY BASKETBALL — BOXSCORE TEST")
    print("=" * 55)

    # Test single game first
    print("\n🏀 Testing single game boxscore...")
    game_id = "401826746"  # Nicholls game
    result = get_game_boxscore(game_id, "2025-11-05")
    
    if result:
        player_stats, opp_stats = result
        print(f"\n  Players with stats: {len(player_stats)}")
        print(f"\n  {'Player':<25} {'MIN':<5} {'PTS':<5} {'REB':<5} {'AST':<5} {'FG':<8} {'3PT':<8}")
        print(f"  {'-'*25} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*8} {'-'*8}")
        for p in player_stats:
            fg_str = f"{p['fg_made']}/{p['fg_att']}"
            three_str = f"{p['three_made']}/{p['three_att']}"
            print(f"  {p['player_name']:<25} {str(p['minutes']):<5} {p['points']:<5} {p['rebounds']:<5} {p['assists']:<5} {fg_str:<8} {three_str:<8}")
        
        print(f"\n  Opponent totals: {opp_stats}")

        # Now pull all completed games
        print("\n📊 Pulling all season box scores...")
        schedule = get_team_schedule()
        all_stats, all_opp = get_season_boxscores(schedule)
        print(f"\n  Total player-game records: {len(all_stats)}")
        print(f"  Total games processed: {len(all_opp)}")
    
        # Show summary per player
        from collections import defaultdict
        player_totals = defaultdict(lambda: {"games": 0, "points": 0, "rebounds": 0, "assists": 0})
        for stat in all_stats:
            name = stat["player_name"]
            player_totals[name]["games"] += 1
            player_totals[name]["points"] += stat["points"]
            player_totals[name]["rebounds"] += stat["rebounds"]
            player_totals[name]["assists"] += stat["assists"]

        print(f"\n  {'Player':<25} {'GP':<5} {'PPG':<7} {'RPG':<7} {'APG':<7}")
        print(f"  {'-'*25} {'-'*5} {'-'*7} {'-'*7} {'-'*7}")
        for name, totals in sorted(player_totals.items(), key=lambda x: x[1]['points'], reverse=True):
            g = totals['games']
            print(f"  {name:<25} {g:<5} {totals['points']/g:<7.1f} {totals['rebounds']/g:<7.1f} {totals['assists']/g:<7.1f}")

