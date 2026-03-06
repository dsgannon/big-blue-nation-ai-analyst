import ollama
import sys
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.news_scraper import get_top_stories
from ingestion.espn_client import(
    get_kentucky_rankings,
    get_team_metrics,
    get_next_game,
    get_sec_standings,
)

load_dotenv()

KENTUCKY_TEAM_ID = "96"

def build_context(stories, metrics, rankings, next_game, standings):
    """Build context string to feed to Mistral"""

    # Rankings
    ap = rankings.get("ap_poll")
    coaches = rankings.get("coaches_poll")
    ap_str = f"#{ap['current']}" if ap else "Unranked"
    coaches_str = f"#{coaches['current']}" if coaches else "Unranked"

    # SEC standing
    uk = next((t for t in standings if t["team_id"] == KENTUCKY_TEAM_ID), {})

    # Next game
    if next_game:
        from datetime import timezone
        import zoneinfo
        eastern = zoneinfo.ZoneInfo("America/New_York")
        from datetime import datetime as dt
        game_dt = dt.fromisoformat(next_game['date'].replace('Z', '+00:00'))
        game_time = game_dt.astimezone(eastern).strftime("%A, %B %d @ %I:%M %p ET")
        next_game_str = f"{next_game['name']} — {game_time} on {next_game['network'] or 'TBD'} at {next_game['venue_name']}"
    else:
        next_game_str = "No upcoming games scheduled"

    # News stories
    news_str = ""
    for i, story in enumerate(stories[:8], 1):
        news_str += f"{i}. [{story['source']}] {story['title']}\n"
        if story.get('summary'):
            news_str += f"   {story['summary'][:200]}\n"

    context = f"""
KENTUCKY WILDCATS BASKETBALL — DAILY BRIEFING DATA
Date: {datetime.now().strftime("%A, %B %d, %Y")}

CURRENT RECORD & STANDINGS:
- Overall Record: {metrics.get('overall_record', 'N/A')}
- Conference Record: {metrics.get('conf_record', 'N/A')}
- SEC Standing: #{uk.get('sec_seed', 'N/A')} in SEC
- Current Streak: {uk.get('streak', 'N/A')}

RANKINGS:
- AP Poll: {ap_str}
- Coaches Poll: {coaches_str}
- BPI: {metrics.get('bpi', 'N/A')} (Rank: {metrics.get('bpi_rank', 'N/A')})
- SOR Rank: {metrics.get('sor_rank', 'N/A')}

TOURNAMENT PICTURE:
- Projected Seed: {metrics.get('proj_seed') or 'On the bubble'}
- Quality Wins: {metrics.get('quality_wins', 'N/A')}
- Quality Losses: {metrics.get('quality_losses', 'N/A')}

NEXT GAME:
{next_game_str}

TOP STORIES:
{news_str}
"""
    return context

def generate_briefing(context, tone="fan"):
    """Use Minstral to generate the daily breifing"""

    if tone == "fan":
        tone_instruction = "You are an enthusiastic Kentucky Wildcats superfan and knowledgeable basketball analyst Write with energy and passion for Big Blue Nation. Use 'Cats' and 'BBN' naturally."
    else:
        tone_instruction = "You are a neurtral, professional college basketball analyst covering Kentucky Wildcasts Basketball."
    
    prompt = f"""{tone_instruction}

Using the data below, write a daily Kentucky Basketball morning briefing.
Structure it as:
1. Opening headline setence capturing the most important thing happening right now
2. Current situation - record, standings, how the season is going (2-3 sentences)
3. Top stories - cover the 3 most important new items with context (3-4 sentences each)
4. Next game preview - who they play, when, where, what to watch for (2-3 sentences)
5. Big picture - tournament outlook, what needs to happen (2-3 sentences)
6. Closing hype sentence for BBN

Keep the total briefing to around 300-400 words. Be specific with names, numbers and facts.

{context}

Write the briefing now:"""

    response = ollama.chat(
        model="mistral:7b",
        messages=[{"role": "user", "content": prompt}]
    )

    return response["message"]["content"]

def send_email(briefing):
    """Email the daily briefing"""
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    recipient = os.getenv("EMAIL_RECIPIENT")

    if not all([sender, password, recipient]):
        print("⚠️  Email credentials not found in .env — skipping email")
        return False
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🏀 UK Basketball Briefing — {datetime.now().strftime('%A, %B %d')}"
        msg["From"] = sender
        msg["To"] = recipient

        # Plain text version
        text_part = MIMEText(briefing, "plain")
        msg.attach(text_part)

        # Send via Gmail
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, recipient, msg.as_string())

        print(f"✅ Briefing emailed to {recipient}")
        return True

    except Exception as e:
        print(f"❌ Email failed: {e}")
        return False

def run_briefing(tone="fan"):
    """Generate and print the full daily briefing"""
    print("=" * 55)
    print("  KENTUCKY BASKETBALL MORNING BRIEFING")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y')}")
    print("=" * 55)

    print("\n📡 Gathering data...")
    stories = get_top_stories(limit=8)
    metrics = get_team_metrics()
    rankings = get_kentucky_rankings()
    next_game = get_next_game()
    standings = get_sec_standings()

    print("🤖 Generating briefing with Mistral...")
    context = build_context(stories, metrics, rankings, next_game, standings)
    briefing = generate_briefing(context, tone=tone)

    print("\n" + "=" * 55)
    print(briefing)
    print("=" * 55)

    send_email(briefing)
    return briefing

if __name__ == "__main__":
    run_briefing(tone="fan")

