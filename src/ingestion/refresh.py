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
)
from ingestion.database import (
    create_tables,
    save_players,
    save_games,
    save_rankings,
    save_sec_standings,
    save_metrics,
    save_record_splits,
)

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

        # Summary
        elapsed = (datetime.now() - start).seconds
        log.info(f"Refresh complete in {elapsed}s ✅")
        return True

    except Exception as e:
        log.error(f"Refresh failed: {e}")
        raise

if __name__ == "__main__":
    run_refresh()