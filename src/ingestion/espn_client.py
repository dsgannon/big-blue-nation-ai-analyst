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
            "status": event.get("status", {}).get("type", {}).get("description"),
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

def debug_raw_data():
    """Peek at raw API responses to understand structure"""
    
    # Debug roster
    print("RAW ROSTER RESPONSE:")
    url = f"{BASE_URL}/teams/{KENTUCKY_TEAM_ID}/roster"
    response = requests.get(url)
    data = response.json()
    print(json.dumps(data, indent=2)[:2000])  # first 2000 characters
    
    # Debug one game
    print("\nRAW SCHEDULE RESPONSE (first game):")
    url = f"{BASE_URL}/teams/{KENTUCKY_TEAM_ID}/schedule"
    response = requests.get(url)
    data = response.json()
    first_event = data.get("events", [])[0]
    print(json.dumps(first_event, indent=2)[:3000])  # first 3000 characters


# Test it
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