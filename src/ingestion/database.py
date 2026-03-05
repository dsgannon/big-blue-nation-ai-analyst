import sqlite3
import os
from datetime import datetime

# Database lives in data/processed folder
DB_PATH = "data/processed/kentucky_basketball.db"

def get_connection():
    """Get a connection to the database"""
    os.makedirs("data/processed", exist_ok=True)
    return sqlite3.connect(DB_PATH)

def create_tables():
    """Create all tables if they don't exist"""
    conn = get_connection()
    cursor = conn.cursor()

    #Players table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id TEXT PRIMARY KEY,
            name TEXT,
            position TEXT,
            jersey TEXT,
            height TEXT,
            weight TEXT,
            year TEXT,
            headshot TEXT,
            updated_at TEXT       
        )
    """)
    
    # Games table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            date TEXT,
            name TEXT,
            short_name TEXT,
            status TEXT,
            season_type TEXT,
            venue_name TEXT,
            venue_city TEXT,
            venue_state TEXT,
            neutral_site INTEGER,
            home_team TEXT,
            away_team TEXT,
            home_score TEXT,
            away_score TEXT,
            network TEXT,
            attendance INTEGER,
           updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Tables created successfully")

def save_players(players):
    """Save roster to database"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    for players in players:
        cursor.execute("""
            INSERT OR REPLACE INTO players
            (id, name, position, jersey, height, weight, year, headshot, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            players["id"],
            players["name"],
            players["position"],
            players["jersey"],
            players["height"],
            players["weight"],
            players["year"],
            players["headshot"],
            now
        ))

    conn.commit()
    conn.close()
    print(f"✅ Saved {len(players)} players to database")

def save_games(games):
    """Save schedule/results to database"""
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    for game in games:
        cursor.execute("""
            INSERT OR REPLACE INTO games
            (id, date, name, short_name, status, season_type,
             venue_name, venue_city, venue_state, neutral_site,
             home_team, away_team, home_score, away_score,
             network, attendance, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            game["id"],
            game["date"],
            game["name"],
            game.get("short_name"),
            game["status"],
            game["season_type"],
            game["venue_name"],
            game["venue_city"],
            game["venue_state"],
            1 if game["neutral_site"] else 0,
            game["home_team"],
            game["away_team"],
            game["home_score"],
            game["away_score"],
            game["network"],
            game["attendance"],
            now
        ))

    conn.commit()
    conn.close()
    print(f"✅ Saved {len(games)} games to database")

def get_all_players():
    """Fetch all players from database"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players ORDER BY jersey")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_games():
    """Fetch all games from database"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM games ORDER BY date")
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_completed_games():
    """Fetch only completed games"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM games 
        WHERE status = 'Final' 
        OR status = 'STATUS_FINAL'
        ORDER BY date
    """)
    rows = cursor.fetchall()
    conn.close()
    return rows

# Test it
if __name__ == "__main__":
    from espn_client import get_team_roster, get_team_schedule

    print("=" * 55)
    print("  KENTUCKY BASKETBALL — DATABASE TEST")
    print("=" * 55)

    # Create tables
    print("\n📁 Creating tables...")
    create_tables()

    # Fetch from ESPN
    print("\n📡 Fetching from ESPN...")
    roster = get_team_roster()
    schedule = get_team_schedule()

    # Save to database
    print("\n💾 Saving to database...")
    save_players(roster)
    save_games(schedule)

    # Read back from database
    print("\n📋 Reading from database...")
    players = get_all_players()
    print(f"  Players in database: {len(players)}")

    games = get_all_games()
    print(f"  Games in database: {len(games)}")

    completed = get_completed_games()
    print(f"  Completed games: {len(completed)}")

    print("\n✅ Database is working!")
    print(f"  Location: {DB_PATH}")


    