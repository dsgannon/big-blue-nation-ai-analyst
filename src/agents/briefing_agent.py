import anthropic
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
    get_net_rankings,
    get_opponent_net_rank,
    get_opponent_bpi,
)

from models.prediction_engine import PredictionEngine

load_dotenv()

KENTUCKY_TEAM_ID = "96"

def build_context(stories, metrics, rankings, next_game, standings,
                  prediction_text="", opp_net_rank=None, opp_bpi=None):
    """Build context string for the briefing prompt"""

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
        opp_context = ""
        if opp_net_rank is not None:
            opp_context += f" | Opponent NET Rank: #{opp_net_rank}"
        if opp_bpi is not None:
            opp_context += f" | Opponent BPI: {opp_bpi:.1f}"
        next_game_str = (
            f"{next_game['name']} — {game_time} on {next_game['network'] or 'TBD'}"
            f" at {next_game['venue_name']}{opp_context}"
        )
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
    
    if prediction_text:
        context += f"\nGAME PREDICTION:\n{prediction_text}\n"

    return context

def generate_briefing(context, tone="fan"):
    """Use Claude to generate the daily briefing"""

    if tone == "fan":
        tone_instruction = "You are an enthusiastic Kentucky Wildcats superfan and knowledgeable basketball analyst. Write with energy and passion for Big Blue Nation. Use 'Cats' and 'BBN' naturally."
    else:
        tone_instruction = "You are a neutral, professional college basketball analyst covering Kentucky Wildcats Basketball."

    prompt = f"""{tone_instruction}

Using the data below, write a daily Kentucky Basketball morning briefing.
Structure it as:
1. Opening headline sentence capturing the most important thing happening right now
2. Current situation - record, standings, how the season is going (2-3 sentences)
3. Top stories - cover the 3 most important news items with context (3-4 sentences each)
4. Next game preview - who they play, when, where, what to watch for (2-3 sentences)
5. Big picture - tournament outlook, what needs to happen (2-3 sentences)
6. Closing hype sentence for BBN

Keep the total briefing to around 300-400 words. Be specific with names, numbers and facts.

IMPORTANT: Use ONLY the exact numbers provided in the data below.
Do not invent stats, scores, injury reports, or records.
If the game prediction section shows a win probability, use that exact number.

{context}

Write the briefing now:"""

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system="You are a Kentucky basketball analyst. Use ONLY the exact stats provided. Do not invent or hallucinate any numbers.",
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text

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
    stories   = get_top_stories(limit=8)
    metrics   = get_team_metrics()
    rankings  = get_kentucky_rankings()
    standings = get_sec_standings()
    next_game = get_next_game()

    # ── Auto-fetch opponent NET rank and BPI ───────────────────────────────────
    opp_net_rank = None
    opp_bpi_val  = None
    prediction_text = ""
    try:
        if next_game:
            opponent = (
                next_game.get('away_team')
                if next_game.get('home_team') == 'Kentucky Wildcats'
                else next_game.get('home_team')
            )
            is_home = 1 if next_game.get('home_team') == 'Kentucky Wildcats' else 0

            print(f"📡 Fetching NET rank and BPI for {opponent}...")
            net_rankings  = get_net_rankings()
            opp_net_rank  = get_opponent_net_rank(opponent, net_rankings)
            opp_bpi_val   = get_opponent_bpi(opponent)
            print(f"   NET #{opp_net_rank} | BPI {opp_bpi_val:.1f}")

            engine = PredictionEngine()
            result = engine.predict_game(
                opponent        = opponent,
                is_home         = is_home,
                net_rank        = int(opp_net_rank),
                opp_bpi         = float(opp_bpi_val),
                injuries        = ['Jayden Quaintance', 'Jaland Lowe'],
            )
            prediction_text = engine.format_prediction(result)
            print("✅ Game prediction generated")
    except Exception as e:
        print(f"⚠️  Prediction failed: {e}")
        prediction_text = ""

    print("🤖 Generating briefing with Claude...")
    context = build_context(
        stories, metrics, rankings, next_game, standings,
        prediction_text=prediction_text,
        opp_net_rank=opp_net_rank,
        opp_bpi=opp_bpi_val,
    )
    briefing = generate_briefing(context, tone=tone)

    print("\n" + "=" * 55)
    print(briefing)
    print("=" * 55)

    send_email(briefing)
    return briefing

if __name__ == "__main__":
    run_briefing(tone="fan")

