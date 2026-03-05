import requests
import json
from datetime import datetime

# Kentucky's team ID in ESPN's system
KENTUCKY_TEAM_ID = "96"
BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"

def get_team_roster():
    """Get current Kentucky Basketball roster"""
    url = f"{BASE_URL}/teams/{KENTUCKY_TEAM_ID}/roster"
    response = requests.get(url)
    data = response.json()

    players = []
    for athlete in data.get("athletes", []):
        player = {
            "id": athlete.get("id"),
            "name": athlete.get("fullName"),
            "position": athlete.get("position", {}).get("abbreviation"),
            "jersey": athlete.get("jersey"),
            "height": athlete.get("displayHeight"),
            "weight": athlete.get("displayWeight"),
            "year": athlete.get("experience", {}).get("displayValue"),
            "headshot": athlete.get("headshot", {}).get("href"),
        }
        players.append(player)
    return players

def  get_team_schedule():
    """Get Kentucky's current season schedule and results"""
    url =f"{BASE_URL}/teams/{KENTUCKY_TEAM_ID}/schedule"
    response = requests.get(url)
    data = response.json()

    games = []
    for event in data.get("events", []):

        # Get competition details
        competition = event.get("competitions", [{}])[0]

        # Get home and away teams
        competitors = competition.get("competitors", [])
        home_team = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away_team = next((c for c in competitors if c.get("homeAway") == "away"), {})

        # Extract scores cleanly
        home_score = home_team.get("score", {})
        away_score = away_team.get("score", {})
        home_score_display = home_score.get("displayValue") if isinstance(home_score, dict) else home_score
        away_score_display = away_score.get("displayValue") if isinstance(away_score, dict) else away_score


        venue = competition.get("venue", {})

        # Get TV network
        broadcasts = competition.get("broadcasts", [])
        network = broadcasts[0].get("media", {}).get("shortName") if broadcasts else None

        # get season type
        season_type = event.get("seasonType", {}).get("name")

        # Get attendance
        attendance = competition.get("attendance")


        game = {
            "id": event.get("id"),
            "date": event.get("date"),
            "name": event.get("name"),
            "status": competition.get("status", {}).get("type", {}).get("description"),
            "season_type": season_type,

            # Location
            "venue_name": venue.get("fullName"),
            "venue_city": venue.get("address", {}).get("city"),
            "venue_state": venue.get("address", {}).get("state"),
            # Home/Away/Neutral
            "neutral_site": competition.get("neutralSite", False),
            "home_team": home_team.get("team", {}).get("displayName"),
            "away_team": away_team.get("team", {}).get("displayName"),
            # Scores
            "home_score": home_score_display,
            "away_score": away_score_display,
            # Broadcast
            "network": network,
            "attendance": attendance,

        }
        games.append(game)
    return games

                            
def get_scoreboard():
    """Get today's college basketball scoreboard"""
    url = f"{BASE_URL}/scoreboard"
    response = requests.get(url)
    data = response.json()
    return data.get("events",[])


def get_rankings():
    """Get current AP Poll and Coaches Poll rankings"""
    url = f"{BASE_URL}/rankings"
    response = requests.get(url)
    data = response.json()
    
    rankings = {
        "ap_poll": {},
        "coaches_poll": {},
    }
    
    for poll in data.get("rankings", []):
        poll_type = poll.get("type")
        ranks = poll.get("ranks", [])
        
        for entry in ranks:
            team_id = entry.get("team", {}).get("id")
            team_name = f"{entry.get('team', {}).get('location')} {entry.get('team', {}).get('name')}"
            ranking = {
                "team_id": team_id,
                "team_name": team_name,
                "current": entry.get("current"),
                "previous": entry.get("previous"),
                "points": entry.get("points"),
                "first_place_votes": entry.get("firstPlaceVotes"),
                "trend": entry.get("trend"),
            }
            
            if poll_type == "ap":
                rankings["ap_poll"][team_id] = ranking
            elif poll_type == "usa":
                rankings["coaches_poll"][team_id] = ranking
    
    return rankings

def get_kentucky_rankings():
    """Get Kentucky's current rankings across all polls"""
    rankings = get_rankings()
    
    uk_rankings = {
        "ap_poll": rankings["ap_poll"].get(KENTUCKY_TEAM_ID),
        "coaches_poll": rankings["coaches_poll"].get(KENTUCKY_TEAM_ID),
    }
    return uk_rankings


# SEC conference ID
SEC_GROUP_ID = "23"

# SEC team IDs — so we know names without extra API calls
SEC_TEAMS = {
    "96": "Kentucky Wildcats",
    "2633": "Tennessee Volunteers",
    "333": "Alabama Crimson Tide",
    "57": "Florida Gators",
    "2": "Auburn Tigers",
    "61": "Georgia Bulldogs",
    "8": "Arkansas Razorbacks",
    "344": "Mississippi State Bulldogs",
    "99": "LSU Tigers",
    "142": "Missouri Tigers",
    "145": "Ole Miss Rebels",
    "2579": "South Carolina Gamecocks",
    "245": "Texas A&M Aggies",
    "238": "Vanderbilt Commodores",
    "201": "Oklahoma Sooners",
    "251": "Texas Longhorns",
}

def get_sec_standings():
    """Get full SEC standings with records and stats"""
    url = f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/seasons/2026/types/2/groups/{SEC_GROUP_ID}/standings/0"
    response = requests.get(url)
    data = response.json()

    standings = []

    for entry in data.get("standings", []):
        # Extract team ID from $ref URL
        team_ref = entry.get("team", {}).get("$ref", "")
        team_id = team_ref.split("/teams/")[1].split("?")[0] if "/teams/" in team_ref else None
        team_name = SEC_TEAMS.get(team_id, f"Unknown ({team_id})")

        # Get overall record (first record entry)
        overall = next((r for r in entry.get("records", []) if r.get("type") == "total"), {})
        home = next((r for r in entry.get("records", []) if r.get("type") == "home"), {})
        away = next((r for r in entry.get("records", []) if r.get("type") == "road"), {})
        vs_ap = next((r for r in entry.get("records", []) if r.get("type") == "vsaprankedteams"), {})

        # Helper to extract a stat value by name
        def get_stat(record, stat_name):
            for stat in record.get("stats", []):
                if stat.get("name") == stat_name:
                    return stat.get("displayValue")
            return None

        team_standing = {
            "team_id": team_id,
            "team_name": team_name,
            # Records
            "overall_record": overall.get("summary"),
            "home_record": home.get("summary"),
            "away_record": away.get("summary"),
            "vs_ap25_record": vs_ap.get("summary"),
            # Stats
            "wins": get_stat(overall, "wins"),
            "losses": get_stat(overall, "losses"),
            "win_pct": get_stat(overall, "winPercent"),
            "ppg": get_stat(overall, "avgPointsFor"),
            "opp_ppg": get_stat(overall, "avgPointsAgainst"),
            "point_diff": get_stat(overall, "differential"),
            "streak": get_stat(overall, "streak"),
            "sec_seed": get_stat(overall, "playoffSeed"),
            "games_behind": get_stat(overall, "gamesBehind"),
        }
        standings.append(team_standing)

    # Sort by SEC seed
    standings.sort(key=lambda x: float(x["sec_seed"]) if x["sec_seed"] else 99)
    return standings

def get_kentucky_sec_standing():
    """Get just Kentucky's SEC standing"""
    standings = get_sec_standings()
    return next((t for t in standings if t["team_id"] == KENTUCKY_TEAM_ID), None)
#### DEBUG ####
def debug_powerindex_full():
    """See all available power index metrics for Kentucky"""
    url = f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/seasons/2026/powerindex/{KENTUCKY_TEAM_ID}"
    response = requests.get(url)
    data = response.json()
    
    print("All available metrics:")
    for stat in data.get("stats", []):
        print(f"  {stat.get('name'):<20} | {stat.get('displayName'):<25} | {stat.get('displayValue')}")

def get_team_metrics():
    """Get Kentucky's BPI, SOR, SOS, tournament odds and projections"""
    url = f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/seasons/2026/powerindex/{KENTUCKY_TEAM_ID}"
    response = requests.get(url)
    data = response.json()

    # Helper to extract stat by name
    def get_stat(name):
        for stat in data.get("stats", []):
            if stat.get("name") == name:
                val = stat.get("displayValue")
                return val if val and val.strip() else None
        return None

    metrics = {
        # Power rankings
        "bpi": get_stat("bpi"),
        "bpi_rank": get_stat("bpirank"),
        "bpi_offense": get_stat("bpioffense"),
        "bpi_offense_rank": get_stat("bpioffenserank"),
        "bpi_defense": get_stat("bpidefense"),
        "bpi_defense_rank": get_stat("bpidefenserank"),
        "bpi_7day_rank_change": get_stat("bpisevendaychangerank"),
        # Strength metrics
        "sor": get_stat("sor"),
        "sor_rank": get_stat("sorrank"),
        "sos": get_stat("sospast"),
        "sos_rank": get_stat("sospastrank"),
        "non_conf_sos_rank": get_stat("sosoutofconfpastrank"),
        # Record
        "overall_record": f"{get_stat('wins')}-{get_stat('losses')}",
        "conf_record": f"{get_stat('confwins')}-{get_stat('conflosses')}",
        "conf_win_pct": get_stat("confwinpct"),
        # Quality wins
        "quality_wins": get_stat("top50bpiwins"),
        "quality_losses": get_stat("top50bpilosses"),
        # Projections
        "proj_record": f"{get_stat('projtotalwins')}-{get_stat('projtotallosses')}",
        "proj_conf_record": f"{get_stat('projconfwins')}-{get_stat('projconflosses')}",
        "proj_seed": get_stat("projectedtournamentseedactual"),
        "proj_scurve": get_stat("projectedtournamentorder"),
        "proj_region": get_stat("tournamentregion"),
        # Tournament probabilities
        "chance_r32": get_stat("chanceroundof32"),
        "chance_s16": get_stat("chancesweet16"),
        "chance_e8": get_stat("chanceelite8"),
        "chance_f4": get_stat("chancefinal4"),
        "chance_champ_game": get_stat("chancechampgame"),
        "chance_champion": get_stat("chancencaachampion"),
        # Remaining schedule
        "rem_sos_rank": get_stat("sosremrank"),
    }
    return metrics

def get_team_statistics():
    """Get Kentucky's season statistics"""
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{KENTUCKY_TEAM_ID}/statistics"
    response = requests.get(url)
    data = response.json()

    stats = {}
    categories = data.get("results", {}).get("stats", {}).get("categories", [])
    
    for category in categories:
        for stat in category.get("stats", []):
            stats[stat.get("name")] = {
                "value": stat.get("displayValue"),
                "label": stat.get("shortDisplayName"),
            }
    return stats


def get_next_game():
    """Get Kentucky's next scheduled game"""
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{KENTUCKY_TEAM_ID}"
    response = requests.get(url)
    data = response.json()
    
    next_events = data.get("team", {}).get("nextEvent", [])
    if not next_events:
        return None
    
    event = next_events[0]
    competition = event.get("competitions", [{}])[0]
    
    competitors = competition.get("competitors", [])
    home_team = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away_team = next((c for c in competitors if c.get("homeAway") == "away"), {})
    
    broadcasts = competition.get("broadcasts", [])
    network = broadcasts[0].get("media", {}).get("shortName") if broadcasts else None
    
    venue = competition.get("venue", {})
    
    # Get opponent info
    opponent = away_team if home_team.get("team", {}).get("id") == KENTUCKY_TEAM_ID else home_team
    opp_record = opponent.get("records", [{}])[0].get("summary") if opponent.get("records") else None

    return {
        "id": event.get("id"),
        "date": event.get("date"),
        "name": event.get("name"),
        "short_name": event.get("shortName"),
        "season_type": event.get("seasonType", {}).get("name"),
        "neutral_site": competition.get("neutralSite", False),
        "venue_name": venue.get("fullName"),
        "venue_city": venue.get("address", {}).get("city"),
        "venue_state": venue.get("address", {}).get("state"),
        "home_team": home_team.get("team", {}).get("displayName"),
        "away_team": away_team.get("team", {}).get("displayName"),
        "network": network,
        "opponent_record": opp_record,
        "tickets_available": competition.get("ticketsAvailable", False),
    }

def get_record_splits():
    """Get Kentucky's home/away/overall record splits"""
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{KENTUCKY_TEAM_ID}"
    response = requests.get(url)
    data = response.json()
    
    record = data.get("team", {}).get("record", {})
    splits = {}
    
    for item in record.get("items", []):
        record_type = item.get("type")
        
        # Extract key stats
        stats = {s["name"]: s["value"] for s in item.get("stats", [])}
        
        splits[record_type] = {
            "summary": item.get("summary"),
            "wins": int(stats.get("wins", 0)),
            "losses": int(stats.get("losses", 0)),
            "ppg": round(stats.get("avgPointsFor", 0), 1),
            "opp_ppg": round(stats.get("avgPointsAgainst", 0), 1),
            "diff": round(stats.get("differential", 0), 1),
            "streak": stats.get("streak", 0),
            "ot_wins": int(stats.get("OTWins", 0)),
            "ot_losses": int(stats.get("OTLosses", 0)),
        }
    
    return splits
#######################################
#######################################
# Test it
#######################################
#######################################
if __name__ == "__main__":
    print("=" * 55)
    print("  KENTUCKY BASKETBALL — ESPN DATA TEST")
    print("=" * 55)

    print("\n📋 ROSTER")
    print("-" * 45)
    roster = get_team_roster()
    for player in roster:
        print(f"  #{player['jersey']:>2} {player['name']:<25} {player['position']:>2} | {player['year']:<15} | {player['height']} {player['weight']}")
    print(f"\n  Total players: {len(roster)}")

    print("\n\n📅 SCHEDULE (first 5 games)")
    print("-" * 45)
    schedule = get_team_schedule()
    for game in schedule[:5]:
        location = "Neutral" if game['neutral_site'] else \
                   "Home" if game['home_team'] == "Kentucky Wildcats" else "Away"
        score = f"{game['away_score']}-{game['home_score']}" if game['home_score'] else "TBD"
        print(f"  {game['date'][:10]} | {location:7} | {game['name']}")
        print(f"             Score: {score} | TV: {game['network']} | {game['season_type']}")
        print(f"             Venue: {game['venue_name']}, {game['venue_city']}, {game['venue_state']}")
        attendance_display = f"{game['attendance']:,}" if game['attendance'] else "N/A"
        print(f"             Attendance: {attendance_display}")        
        print()

    print(f"  Total games: {len(schedule)}")

    print("\n🏆 KENTUCKY RANKINGS")
    print("-" * 45)
    uk_rankings = get_kentucky_rankings()

    ap = uk_rankings["ap_poll"]
    coaches = uk_rankings["coaches_poll"]

    if ap:
        trend = "↑" if ap['trend'] == "+" else "↓" if ap['trend'] == "-" else "→"
        print(f"  AP Poll:      #{ap['current']} (prev #{ap['previous']}) {trend}  | Points: {ap['points']}")
    else:
        print("  AP Poll:      Unranked")

    if coaches:
        trend = "↑" if coaches['trend'] == "+" else "↓" if coaches['trend'] == "-" else "→"
        print(f"  Coaches Poll: #{coaches['current']} (prev #{coaches['previous']}) {trend}  | Points: {coaches['points']}")
    else:
        print("  Coaches Poll: Unranked")


    print("\n📊 SEC STANDINGS")
    print("-" * 45)
    standings = get_sec_standings()
    print(f"  {'#':<3} {'Team':<25} {'W':<4} {'L':<4} {'PCT':<6} {'PPG':<6} {'OPP':<6} {'DIFF':<6} {'STRK':<6}")
    print(f"  {'-'*3} {'-'*25} {'-'*4} {'-'*4} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
    for team in standings:
        marker = " ←" if team["team_id"] == KENTUCKY_TEAM_ID else ""
        print(f"  {team['sec_seed']:<3} {team['team_name']:<25} {team['wins']:<4} {team['losses']:<4} {team['win_pct']:<6} {team['ppg']:<6} {team['opp_ppg']:<6} {team['point_diff']:<6} {team['streak']:<6}{marker}")

    print("\n🐾 KENTUCKY DETAILS")
    print("-" * 45)
    uk = get_kentucky_sec_standing()
    if uk:
        print(f"  Overall:      {uk['overall_record']}")
        print(f"  Home:         {uk['home_record']}")
        print(f"  Away:         {uk['away_record']}")
        print(f"  vs AP Top 25: {uk['vs_ap25_record']}")
        print(f"  SEC Seed:     #{uk['sec_seed']}")
        print(f"  Streak:       {uk['streak']}")
        print(f"  Games Behind: {uk['games_behind']}")
    
    print("\n📈 KENTUCKY METRICS & ANALYTICS")
    print("-" * 45)
    metrics = get_team_metrics()

    print(f"\n  Power Rankings:")
    print(f"    BPI:          {metrics['bpi']} (Rank: {metrics['bpi_rank']})")
    print(f"    BPI Offense:  {metrics['bpi_offense']} (Rank: {metrics['bpi_offense_rank']})")
    print(f"    BPI Defense:  {metrics['bpi_defense']} (Rank: {metrics['bpi_defense_rank']})")
    print(f"    SOR:          {metrics['sor']} (Rank: {metrics['sor_rank']})")
    print(f"    SOS:          {metrics['sos']} (Rank: {metrics['sos_rank']})")
    print(f"    Rem SOS Rank: {metrics['rem_sos_rank']}")
    print(f"    Non-Conf SOS: Rank {metrics['non_conf_sos_rank']}")
    print(f"    7-Day BPI Change: {metrics['bpi_7day_rank_change']}")

    print(f"\n  Records:")
    print(f"    Overall:      {metrics['overall_record']}")
    print(f"    Conference:   {metrics['conf_record']} ({metrics['conf_win_pct']})")
    print(f"    Quality W-L:  {metrics['quality_wins']}-{metrics['quality_losses']} (vs Top 50 BPI)")

    print(f"\n  Projections:")
    proj_w = str(metrics['proj_record']).split('-')[0].split('.')[0] if metrics['proj_record'] else 'N/A'
    proj_l = str(metrics['proj_record']).split('-')[1].split('.')[0] if metrics['proj_record'] else 'N/A'
    proj_cw = str(metrics['proj_conf_record']).split('-')[0].split('.')[0] if metrics['proj_conf_record'] else 'N/A'
    proj_cl = str(metrics['proj_conf_record']).split('-')[1].split('.')[0] if metrics['proj_conf_record'] else 'N/A'
    print(f"    Proj Record:  {proj_w}-{proj_l}")
    print(f"    Proj Conf:    {proj_cw}-{proj_cl}")    

    print(f"\n  Tournament Odds:")
    def fmt(val, default="Not projected"):
        return val if val else default

    print(f"    Proj Seed:    {fmt(metrics['proj_seed'], 'On the bubble')}")
    print(f"    S-Curve:      {fmt(metrics['proj_scurve'], 'On the bubble')}")
    print(f"    Region:       {fmt(metrics['proj_region'], 'TBD')}")
    print(f"    Round of 32:  {fmt(metrics['chance_r32'])}")
    print(f"    Sweet 16:     {fmt(metrics['chance_s16'])}")
    print(f"    Elite 8:      {fmt(metrics['chance_e8'])}")
    print(f"    Final Four:   {fmt(metrics['chance_f4'])}")
    print(f"    Champ Game:   {fmt(metrics['chance_champ_game'])}")
    print(f"    Champion:     {fmt(metrics['chance_champion'])}")

    print("\n🗓️  NEXT GAME")
    print("-" * 45)
    next_game = get_next_game()
    if next_game:
        from datetime import datetime, timezone
        import zoneinfo
        eastern = zoneinfo.ZoneInfo("America/New_York")
        game_dt = datetime.fromisoformat(next_game['date'].replace('Z', '+00:00'))
        local_dt = game_dt.astimezone(eastern).strftime("%A, %B %d @ %I:%M %p ET")
        location = "Neutral" if next_game['neutral_site'] else \
                   "Home" if next_game['home_team'] == "Kentucky Wildcats" else "Away"
        print(f"  {next_game['name']}")
        print(f"  Date:     {local_dt}")
        print(f"  Location: {location} — {next_game['venue_name']}, {next_game['venue_city']}, {next_game['venue_state']}")
        print(f"  TV:       {next_game['network'] or 'TBD'}")
        print(f"  Type:     {next_game['season_type']}")
        if next_game['opponent_record']:
            print(f"  Opp Record: {next_game['opponent_record']}")
        print(f"  Tickets:  {'Available' if next_game['tickets_available'] else 'Not available'}")
    else:
        print("  No upcoming games found")

    print("\n📊 RECORD SPLITS")
    print("-" * 45)
    splits = get_record_splits()
    for record_type, split in splits.items():
        ot = f" | OT: {split['ot_wins']}-{split['ot_losses']}" if split['ot_wins'] or split['ot_losses'] else ""
        streak = f"L{abs(int(split['streak']))}" if split['streak'] < 0 else f"W{int(split['streak'])}" if split['streak'] > 0 else "-"
        print(f"  {record_type:<8} {split['summary']:<8} | PPG: {split['ppg']:<6} OPP: {split['opp_ppg']:<6} DIFF: {split['diff']:<6} STRK: {streak}{ot}")