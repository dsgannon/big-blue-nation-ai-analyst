import schedule
import time
import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.briefing_agent import run_briefing
from ingestion.refresh import run_refresh

def morning_job():
    """Full morning pipeline - refesh data then send briefing"""
    print(f"\n⏰ Morning job started at {datetime.now().strftime('%A, %B %d @ %I:%M %p')}")

    try:
        # Step 1 — Refresh all ESPN data
        print("\n📡 Step 1: Refreshing ESPN data...")
        run_refresh()
        
        # Step 2 — Generate and email briefing
        print("\n📰 Step 2: Generating and emailing briefing...")
        run_briefing(tone="fan")
        
        print(f"\n✅ Morning job complete at {datetime.now().strftime('%I:%M %p')}")
        
    except Exception as e:
        print(f"\n❌ Morning job failed: {e}")

def run_scheduler():
    """Run the scheduler — keeps running until you stop it"""
    print("=" * 55)
    print("  BIG BLUE NATION SCHEDULER")
    print("=" * 55)
    print("\n📅 Scheduled jobs:")
    print("  • 7:00 AM daily — Morning briefing + data refresh")
    print("\nPress Ctrl+C to stop\n")

    # Schedule morning briefing at 7am daily
    schedule.every().day.at("07:00").do(morning_job)

    # Keep running
    while True:
        schedule.run_pending()
        time.sleep(60)  # check every minute

if __name__ == "__main__":
    # Check if we want to run immediately for testing
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        print("🧪 Running job immediately for testing...")
        morning_job()
    else:
        run_scheduler()