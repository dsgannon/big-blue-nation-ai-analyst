import requests
import feedparser
import praw
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

FEEDS = {
    "ESPN_UK": "https://www.espn.com/espn/rss/ncb/news",
    "CBS_UK": "https://www.cbssports.com/rss/headlines/college-basketball/",
    "WildcatBlueNation": "https://wildcatbluenation.com/feed/",
    "KSR": "https://kentuckysportsradio.com/feed/",
}


KENTUCKY_KEYWORDS = [
    "kentucky wildcats", "uk basketball", "big blue nation",
    "rupp arena", "mark pope", "wildcats basketball",
    "kentucky basketball", "kentucky hoops", "#bbn"
]

# Keywords that MUST appear for generic sports sources
STRONG_KEYWORDS = [
    "kentucky wildcats", "uk basketball", "rupp arena",
    "mark pope", "kentucky basketball"
]

def is_strongly_relevant(title, summary=""):
    """Stricter check for generic sources like ESPN"""
    text = (title + " " + summary).lower()
    return any(keyword in text for keyword in STRONG_KEYWORDS)

def is_relevant(title, summary=""):
    """Check if an article is relevant to Kentucky Basketball"""
    text = (title + " " + summary).lower()
    return any(keyword in text for keyword in KENTUCKY_KEYWORDS)

def scrape_rss_feeds():
    """Scrape all RSS feeds and return relevant articles"""
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    for source, url in FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "")
                link = entry.get("link", "")

                # Parse data
                published = entry.get("published_parsed")
                if published:
                    pub_date = datetime(*published[:6], tzinfo=timezone.utc)
                else:
                    pub_date = datetime.now(timezone.utc)

                # skip old articles
                if pub_date < cutoff:
                    continue

                # Use stricter filter for generic sports sources
                if source in ["ESPN_UK", "CBS_UK"]:
                    if not is_strongly_relevant(title, summary):
                        continue
                else:
                    if not is_relevant(title, summary):
                        continue

                articles.append({
                    "source": source,
                    "title": title,
                    "summary": summary[:500],
                    "url": link,
                    "published": pub_date.isoformat()
                })
                
            print(f"  ✅ {source}: {len([a for a in articles if a['source'] == source])} articles")

        except Exception as e:
            print(f"❌ {source}: Failed — {e}")

    return articles 


def scrape_reddit():
    """Scrape r/KentuckyWildcats for relevant posts"""
    articles = []

    try:
        # Use read-only mode — no credentials needed for public subreddits
        reddit = praw.Reddit(
            client_id="readonly",
            client_secret="readonly",
            user_agent="big-blue-nation-ai-analyst:v1.0"
        )

        subreddit = reddit.subreddit("KentuckyWildcats")
        cutoff = datetime.now(timezone.utc) - timedelta(days=2)

        for post in subreddit.hot(limit=25):
            pub_date = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)

            if pub_date < cutoff:
                continue

            # Only grab posts with meaningful engagement
            if post.score < 10:
                continue

            articles.append({
                "source": "Reddit",
                "title": post.title,
                "summary": post.selftext[:500] if post.selftext else "",
                "url": f"https://reddit.com{post.permalink}",
                "published": pub_date.isoformat(),
                "score": post.score,
                "comments": post.num_comments,
            })

        print(f"  ✅ Reddit: {len(articles)} posts")

    except Exception as e:
        print(f"  ❌ Reddit: Failed — {e}")

    return articles

def deduplicate(articles):
    """Remove duplicate stories based on title summary"""
    seen_titles = set()
    unique = []

    for article in articles:
        # Simple deduplication - normalize title
        normalized = article["title"].lower().strip()
        normalized = ''.join(c for c in normalized if c.isalnum() or c.isspace())

        if normalized not in seen_titles:
            seen_titles.add(normalized)
            unique.append(article)

    return unique
def score_relevance(article):
    """Score how relevant/important an article is (0-10)"""
    score = 5  # base score
    title = article["title"].lower()
    summary = article.get("summary", "").lower()
    text = title + " " + summary

    # Boost for high priority topics
    if any(w in text for w in ["injury", "injured", "out for"]):
        score += 3
    if any(w in text for w in ["recruit", "commit", "transfer"]):
        score += 2
    if any(w in text for w in ["game", "score", "win", "loss", "beat"]):
        score += 1
    if any(w in text for w in ["ranking", "ranked", "poll"]):
        score += 1
    if any(w in text for w in ["ncaa tournament", "march madness", "bracket"]):
        score += 2

    # Boost for Reddit engagement
    if article.get("score", 0) > 100:
        score += 1
    if article.get("score", 0) > 500:
        score += 1

    return min(score, 10)

def get_top_stories(limit=10):
    """Get top Kentucky Basketball stories from all sources"""
    print("📰 Scraping news sources...")

    # Scrape all sources
    rss_articles = scrape_rss_feeds()
    reddit_articles = scrape_reddit()

    # Combine and deduplicate
    all_articles = rss_articles + reddit_articles
    unique_articles = deduplicate(all_articles)

    # Score and sort
    for article in unique_articles:
        article["relevance_score"] = score_relevance(article)

    sorted_articles = sorted(
        unique_articles,
        key=lambda x: x["relevance_score"],
        reverse=True
    )

    top = sorted_articles[:limit]
    print(f"  📊 Total: {len(all_articles)} → Unique: {len(unique_articles)} → Top: {len(top)}")
    return top




# Test it
if __name__ == "__main__":
    print("=" * 55)
    print("  KENTUCKY BASKETBALL — NEWS SCRAPER TEST")
    print("=" * 55)

    stories = get_top_stories()

    print(f"\n📰 TOP STORIES")
    print("-" * 45)
    for i, story in enumerate(stories, 1):
        print(f"\n  {i}. [{story['source']}] Score: {story['relevance_score']}/10")
        print(f"     {story['title']}")
        print(f"     {story['published'][:10]}")
        if story.get('summary'):
            print(f"     {story['summary'][:100]}...")


  