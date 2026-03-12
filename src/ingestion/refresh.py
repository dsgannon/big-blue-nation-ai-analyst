import sys
import os
import logging
from datetime import datetime

# Make sure imports work from project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.espn_client import (
    get_team_roster,
    get_team_schedule,
    get_kentucky_rankings,
    get_sec_standings,
    get_team_metrics,
    get_record_splits,
    get_next_game,
    get_all_sec_bpi,
    get_net_rankings,
)
from ingestion.boxscore_client import get_game_boxscore
from models.thresholds import compute_thresholds
from ingestion.database import (
    create_tables,
    get_connection,
    save_players,
    save_games,
    save_rankings,
    save_sec_standings,
    save_metrics,
    save_record_splits,
    save_player_game_stats,
    save_opponent_stats,
    save_opponent_bpi_history,
    save_net_rankings_history,
    save_team_advanced_stats,
)
from ingestion.barttorvik_client import get_all_team_stats

# Set up logging so we have a record of every refresh
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("data/processed/refresh.log"),
        logging.StreamHandler(),  # also print to terminal
    ]
)
log = logging.getLogger(__name__)

CURRENT_SEASON = "2025-26"


def _refresh_box_scores(schedule, season=CURRENT_SEASON):
    """Incrementally fetch box scores for completed games not yet in the DB."""
    conn = get_connection()
    already_done = {
        row[0] for row in
        conn.execute("SELECT DISTINCT game_id FROM player_game_stats").fetchall()
    }
    conn.close()

    completed = [g for g in schedule if g.get('status') in ('Final', 'STATUS_FINAL')]
    new_games  = [g for g in completed if g['id'] not in already_done]

    log.info(f"Box scores: {len(completed)} completed, {len(new_games)} new")

    saved = 0
    for game in new_games:
        try:
            result = get_game_boxscore(game['id'], game['date'][:10], season)
            if not result:
                continue
            player_stats, opp_totals, _ = result
            opp_name = (
                game.get('away_team')
                if game.get('home_team') == 'Kentucky Wildcats'
                else game.get('home_team')
            )
            opp_totals['game_id']   = game['id']
            opp_totals['game_date'] = game['date'][:10]
            opp_totals['opponent']  = opp_name
            save_player_game_stats(player_stats, season)
            save_opponent_stats([opp_totals], season)
            log.info(f"  ✅ Box score: {game['name'][:55]}")
            saved += 1
        except Exception as e:
            log.warning(f"  ⚠️  Box score failed: {game['name'][:45]} — {e}")

    if saved:
        log.info(f"Saved {saved} new box score(s)")
    return saved


def _refresh_opponent_bpi():
    """Snapshot current BPI for all SEC teams into opponent_bpi_history."""
    entries = get_all_sec_bpi()
    if entries:
        save_opponent_bpi_history(entries)
        log.info(f"Opponent BPI: saved {len(entries)} entries")
    return entries


def _refresh_net_rankings():
    """Snapshot current NET rankings for all teams into net_rankings_history."""
    net_rankings = get_net_rankings()
    if net_rankings:
        save_net_rankings_history(net_rankings)
        log.info(f"NET rankings: saved {len(net_rankings)} team entries")
    return net_rankings


def _refresh_barttorvik():
    """Snapshot BartTorvik advanced stats for all D1 teams."""
    stats = get_all_team_stats(year=2026)
    if stats:
        save_team_advanced_stats(stats)
        log.info(f"BartTorvik: saved {len(stats)} team entries")
    return stats


def run_refresh():
    """Full data refresh — fetches everything from ESPN and saves to database"""
    start = datetime.now()
    log.info("=" * 50)
    log.info("Starting Kentucky Basketball data refresh")
    log.info("=" * 50)

    try:
        # Make sure tables exist
        create_tables()

        # Fetch all data
        log.info("Fetching roster...")
        roster = get_team_roster()
        log.info(f"  Got {len(roster)} players")

        log.info("Fetching schedule...")
        schedule = get_team_schedule()
        log.info(f"  Got {len(schedule)} games")

        log.info("Fetching rankings...")
        rankings = get_kentucky_rankings()
        ap = rankings.get("ap_poll")
        coaches = rankings.get("coaches_poll")
        log.info(f"  AP: {'#' + str(ap['current']) if ap else 'Unranked'} | Coaches: {'#' + str(coaches['current']) if coaches else 'Unranked'}")

        log.info("Fetching SEC standings...")
        standings = get_sec_standings()
        uk = next((t for t in standings if t["team_id"] == "96"), None)
        log.info(f"  UK is #{uk['sec_seed']} in SEC ({uk['overall_record']})" if uk else "  UK not found")

        log.info("Fetching team metrics...")
        metrics = get_team_metrics()
        log.info(f"  BPI: {metrics.get('bpi')} (Rank: {metrics.get('bpi_rank')})")

        log.info("Fetching record splits...")
        splits = get_record_splits()
        log.info(f"  Got {len(splits)} split types")

        log.info("Fetching next game...")
        next_game = get_next_game()
        if next_game:
            log.info(f"  Next: {next_game['name']} on {next_game['date'][:10]}")
        else:
            log.info("  No upcoming games")

        # Save everything
        log.info("Saving to database...")
        save_players(roster)
        save_games(schedule)
        save_rankings(rankings)
        save_sec_standings(standings)
        save_metrics(metrics)
        save_record_splits(splits)

        # Box scores — incremental (only new completed games)
        log.info("Refreshing box scores...")
        _refresh_box_scores(schedule)

        # Opponent BPI snapshots
        log.info("Refreshing opponent BPI history...")
        _refresh_opponent_bpi()

        # NET rankings snapshot
        log.info("Refreshing NET rankings history...")
        _refresh_net_rankings()

        # BartTorvik advanced stats snapshot
        log.info("Refreshing BartTorvik advanced stats...")
        _refresh_barttorvik()

        # Recompute thresholds with latest game data
        log.info("Recomputing player thresholds...")
        compute_thresholds(verbose=False)
        log.info("Player thresholds updated ✅")

        # Summary
        elapsed = (datetime.now() - start).seconds
        log.info(f"Refresh complete in {elapsed}s ✅")
        return True

    except Exception as e:
        log.error(f"Refresh failed: {e}")
        raise

if __name__ == "__main__":
    run_refresh()