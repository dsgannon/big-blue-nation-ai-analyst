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


def get_previous_season_schedule(season_year="2025"):
    """Get Kentucky's schedule for a previous season including tournament games"""
    all_events = []
    
    # Season types: 2 = regular season + conference tournament, 3 = NCAA tournament
    for season_type in [2, 3]:
        url = f"{BASE_URL}/teams/{KENTUCKY_TEAM_ID}/schedule?season={season_year}&seasontype={season_type}"
        response = requests.get(url)
        data = response.json()
        events = data.get("events", [])
        
        for event in events:
            competition = event.get("competitions", [{}])[0]
            competitors = competition.get("competitors", [])
            home_team = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away_team = next((c for c in competitors if c.get("homeAway") == "away"), {})
            
            # Only include completed games
            status = competition.get("status", {}).get("type", {}).get("description")
            if status not in ["Final", "STATUS_FINAL"]:
                continue
                
            all_events.append({
                "id": event.get("id"),
                "date": event.get("date"),
                "name": event.get("name"),
                "status": status,
                "season_type": "NCAA Tournament" if season_type == 3 else event.get("seasonType", {}).get("name"),
                "home_team": home_team.get("team", {}).get("displayName"),
                "away_team": away_team.get("team", {}).get("displayName"),
                "home_score": home_team.get("score", {}).get("displayValue") if isinstance(home_team.get("score"), dict) else home_team.get("score"),
                "away_score": away_team.get("score", {}).get("displayValue") if isinstance(away_team.get("score"), dict) else away_team.get("score"),
            })
    print(f"  Found {len(all_events)} completed games for {int(season_year)-1}-{season_year} season")    
    return all_events

def generate_synthetic_data(player_stats, noise_pct=0.15, multiplier=3):
    """Generate synthetic training data by adding controlled noise to real games"""
    import random
    random.seed(42)
    
    synthetic = []
    numeric_stats = [
        'minutes', 'points', 'rebounds', 'assists', 'turnovers',
        'steals', 'blocks', 'fg_made', 'fg_att', 'three_made',
        'three_att', 'ft_made', 'ft_att'
    ]
    
    for _ in range(multiplier):
        for stat in player_stats:
            new_stat = stat.copy()
            new_stat['synthetic'] = True
            
            # Add controlled noise to numeric stats
            for col in numeric_stats:
                val = stat[col]
                if val > 0:
                    noise = random.uniform(-noise_pct, noise_pct)
                    new_val = round(val * (1 + noise))
                    new_stat[col] = max(0, new_val)
            
            # Recalculate percentages
            new_stat['fg_pct'] = round(new_stat['fg_made'] / new_stat['fg_att'], 3) if new_stat['fg_att'] > 0 else 0
            new_stat['three_pct'] = round(new_stat['three_made'] / new_stat['three_att'], 3) if new_stat['three_att'] > 0 else 0
            new_stat['ft_pct'] = round(new_stat['ft_made'] / new_stat['ft_att'], 3) if new_stat['ft_att'] > 0 else 0
            
            synthetic.append(new_stat)
    
    print(f"  Generated {len(synthetic)} synthetic records from {len(player_stats)} real records")
    return synthetic

if __name__ == "__main__":
    from espn_client import get_team_schedule

    print("=" * 55)
    print("  KENTUCKY BASKETBALL — FULL DATA COLLECTION")
    print("=" * 55)

    # Current season
    print("\n📊 2025-26 Season (current)...")
    current_schedule = get_team_schedule()
    current_stats, current_opp = get_season_boxscores(current_schedule, season="2025-26")
    print(f"  Player records: {len(current_stats)}")

    # Previous season
    print("\n📊 2024-25 Season (previous)...")
    prev_schedule = get_previous_season_schedule("2025")
    prev_stats, prev_opp = get_season_boxscores(prev_schedule, season="2024-25")
    print(f"  Player records: {len(prev_stats)}")

    # Combine real data
    all_real_stats = current_stats + prev_stats
    print(f"\n✅ Total real records: {len(all_real_stats)}")

    # Generate synthetic data
    print("\n🔄 Generating synthetic data...")
    synthetic_stats = generate_synthetic_data(all_real_stats, noise_pct=0.15, multiplier=2)
    print(f"  Synthetic records: {len(synthetic_stats)}")

    # Final combined dataset
    all_stats = all_real_stats + synthetic_stats
    print(f"\n🎯 Total training records: {len(all_stats)}")

    # Show player breakdown
    from collections import defaultdict
    player_totals = defaultdict(int)
    for stat in all_real_stats:
        player_totals[stat['player_name']] += 1
    
    print(f"\n{'Player':<25} {'Real Games':<12}")
    print(f"{'-'*25} {'-'*12}")
    for name, count in sorted(player_totals.items(), key=lambda x: x[1], reverse=True):
        print(f"  {name:<25} {count:<12}")