import sqlite3
import os
from datetime import datetime

DB_PATH = "data/processed/kentucky_basketball.db"
CURRENT_SEASON = "2025-26"

def get_connection():
    os.makedirs("data/processed", exist_ok=True)
    return sqlite3.connect(DB_PATH)

def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id TEXT,
            season TEXT,
            name TEXT,
            position TEXT,
            jersey TEXT,
            height TEXT,
            weight TEXT,
            year TEXT,
            headshot TEXT,
            updated_at TEXT,
            PRIMARY KEY (id, season)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id TEXT,
            season TEXT,
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
            updated_at TEXT,
            PRIMARY KEY (id, season)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season TEXT,
            date TEXT,
            bpi TEXT,
            bpi_rank TEXT,
            bpi_offense TEXT,
            bpi_offense_rank TEXT,
            bpi_defense TEXT,
            bpi_defense_rank TEXT,
            bpi_7day_rank_change TEXT,
            sor TEXT,
            sor_rank TEXT,
            sos TEXT,
            sos_rank TEXT,
            non_conf_sos_rank TEXT,
            rem_sos_rank TEXT,
            overall_record TEXT,
            conf_record TEXT,
            conf_win_pct TEXT,
            quality_wins TEXT,
            quality_losses TEXT,
            proj_record TEXT,
            proj_conf_record TEXT,
            proj_seed TEXT,
            proj_scurve TEXT,
            proj_region TEXT,
            chance_r32 TEXT,
            chance_s16 TEXT,
            chance_e8 TEXT,
            chance_f4 TEXT,
            chance_champ_game TEXT,
            chance_champion TEXT,
            updated_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rankings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season TEXT,
            date TEXT,
            ap_rank TEXT,
            ap_prev_rank TEXT,
            ap_points TEXT,
            coaches_rank TEXT,
            coaches_prev_rank TEXT,
            coaches_points TEXT,
            updated_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sec_standings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season TEXT,
            date TEXT,
            team_id TEXT,
            team_name TEXT,
            sec_seed TEXT,
            overall_record TEXT,
            home_record TEXT,
            away_record TEXT,
            vs_ap25_record TEXT,
            wins TEXT,
            losses TEXT,
            win_pct TEXT,
            ppg TEXT,
            opp_ppg TEXT,
            point_diff TEXT,
            streak TEXT,
            games_behind TEXT,
            updated_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS record_splits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            season TEXT,
            date TEXT,
            record_type TEXT,
            summary TEXT,
            wins INTEGER,
            losses INTEGER,
            ppg REAL,
            opp_ppg REAL,
            diff REAL,
            streak REAL,
            ot_wins INTEGER,
            ot_losses INTEGER,
            updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()
    print("✅ Tables created successfully")

def save_players(players, season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    for player in players:
        cursor.execute("""
            INSERT OR REPLACE INTO players
            (id, season, name, position, jersey, height, weight, year, headshot, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            player["id"], season, player["name"], player["position"],
            player["jersey"], player["height"], player["weight"],
            player["year"], player["headshot"], now
        ))

    conn.commit()
    conn.close()
    print(f"✅ Saved {len(players)} players to database")

def save_games(games, season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    for game in games:
        cursor.execute("""
            INSERT OR REPLACE INTO games
            (id, season, date, name, short_name, status, season_type,
             venue_name, venue_city, venue_state, neutral_site,
             home_team, away_team, home_score, away_score,
             network, attendance, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            game["id"], season, game["date"], game["name"],
            game.get("short_name"), game["status"], game["season_type"],
            game["venue_name"], game["venue_city"], game["venue_state"],
            1 if game["neutral_site"] else 0,
            game["home_team"], game["away_team"],
            game["home_score"], game["away_score"],
            game["network"], game["attendance"], now
        ))

    conn.commit()
    conn.close()
    print(f"✅ Saved {len(games)} games to database")

def save_metrics(metrics, season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    cursor.execute("""
        INSERT INTO team_metrics
        (season, date, bpi, bpi_rank, bpi_offense, bpi_offense_rank,
         bpi_defense, bpi_defense_rank, bpi_7day_rank_change,
         sor, sor_rank, sos, sos_rank, non_conf_sos_rank, rem_sos_rank,
         overall_record, conf_record, conf_win_pct, quality_wins, quality_losses,
         proj_record, proj_conf_record, proj_seed, proj_scurve, proj_region,
         chance_r32, chance_s16, chance_e8, chance_f4, chance_champ_game,
         chance_champion, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        season, now[:10],
        metrics.get("bpi"), metrics.get("bpi_rank"),
        metrics.get("bpi_offense"), metrics.get("bpi_offense_rank"),
        metrics.get("bpi_defense"), metrics.get("bpi_defense_rank"),
        metrics.get("bpi_7day_rank_change"),
        metrics.get("sor"), metrics.get("sor_rank"),
        metrics.get("sos"), metrics.get("sos_rank"),
        metrics.get("non_conf_sos_rank"), metrics.get("rem_sos_rank"),
        metrics.get("overall_record"), metrics.get("conf_record"),
        metrics.get("conf_win_pct"), metrics.get("quality_wins"),
        metrics.get("quality_losses"), metrics.get("proj_record"),
        metrics.get("proj_conf_record"), metrics.get("proj_seed"),
        metrics.get("proj_scurve"), metrics.get("proj_region"),
        metrics.get("chance_r32"), metrics.get("chance_s16"),
        metrics.get("chance_e8"), metrics.get("chance_f4"),
        metrics.get("chance_champ_game"), metrics.get("chance_champion"),
        now
    ))

    conn.commit()
    conn.close()
    print("✅ Saved metrics to database")

def save_rankings(rankings, season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    ap = rankings.get("ap_poll") or {}
    coaches = rankings.get("coaches_poll") or {}

    cursor.execute("""
        INSERT INTO rankings
        (season, date, ap_rank, ap_prev_rank, ap_points,
         coaches_rank, coaches_prev_rank, coaches_points, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        season, now[:10],
        ap.get("current"), ap.get("previous"), ap.get("points"),
        coaches.get("current"), coaches.get("previous"), coaches.get("points"),
        now
    ))

    conn.commit()
    conn.close()
    print("✅ Saved rankings to database")

def save_sec_standings(standings, season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    for team in standings:
        cursor.execute("""
            INSERT INTO sec_standings
            (season, date, team_id, team_name, sec_seed,
             overall_record, home_record, away_record, vs_ap25_record,
             wins, losses, win_pct, ppg, opp_ppg, point_diff,
             streak, games_behind, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            season, now[:10],
            team.get("team_id"), team.get("team_name"), team.get("sec_seed"),
            team.get("overall_record"), team.get("home_record"),
            team.get("away_record"), team.get("vs_ap25_record"),
            team.get("wins"), team.get("losses"), team.get("win_pct"),
            team.get("ppg"), team.get("opp_ppg"), team.get("point_diff"),
            team.get("streak"), team.get("games_behind"), now
        ))

    conn.commit()
    conn.close()
    print(f"✅ Saved {len(standings)} SEC standings to database")

def save_record_splits(splits, season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()

    for record_type, split in splits.items():
        cursor.execute("""
            INSERT INTO record_splits
            (season, date, record_type, summary, wins, losses,
             ppg, opp_ppg, diff, streak, ot_wins, ot_losses, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            season, now[:10], record_type,
            split.get("summary"), split.get("wins"), split.get("losses"),
            split.get("ppg"), split.get("opp_ppg"), split.get("diff"),
            split.get("streak"), split.get("ot_wins"), split.get("ot_losses"),
            now
        ))

    conn.commit()
    conn.close()
    print(f"✅ Saved {len(splits)} record splits to database")

def get_all_players(season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM players WHERE season=? ORDER BY jersey", (season,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_all_games(season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM games WHERE season=? ORDER BY date", (season,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_completed_games(season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM games
        WHERE season=? AND (status='Final' OR status='STATUS_FINAL')
        ORDER BY date
    """, (season,))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_latest_metrics(season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM team_metrics
        WHERE season=?
        ORDER BY updated_at DESC LIMIT 1
    """, (season,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_latest_standings(season=CURRENT_SEASON):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM sec_standings
        WHERE season=?
        ORDER BY updated_at DESC, sec_seed ASC
    """, (season,))
    rows = cursor.fetchall()
    conn.close()
    return rows

# Test it
if __name__ == "__main__":
    from espn_client import (
        get_team_roster, get_team_schedule, get_kentucky_rankings,
        get_sec_standings, get_team_metrics, get_record_splits
    )

    print("=" * 55)
    print("  KENTUCKY BASKETBALL — DATABASE TEST")
    print("=" * 55)

    print("\n📁 Creating tables...")
    create_tables()

    print("\n📡 Fetching from ESPN...")
    roster = get_team_roster()
    schedule = get_team_schedule()
    rankings = get_kentucky_rankings()
    standings = get_sec_standings()
    metrics = get_team_metrics()
    splits = get_record_splits()

    print("\n💾 Saving to database...")
    save_players(roster)
    save_games(schedule)
    save_rankings(rankings)
    save_sec_standings(standings)
    save_metrics(metrics)
    save_record_splits(splits)

    print("\n📋 Verifying database...")
    print(f"  Players:       {len(get_all_players())}")
    print(f"  Games:         {len(get_all_games())}")
    print(f"  Completed:     {len(get_completed_games())}")
    print(f"  Standings:     {len(get_latest_standings())}")
    latest = get_latest_metrics()
    print(f"  Metrics saved: {'✅' if latest else '❌'}")

    print("\n✅ Database complete!")
    print(f"  Season: {CURRENT_SEASON}")
    print(f"  Location: {DB_PATH}")


    