"""
src/agents/chat_agent.py
Big Blue Nation AI Analyst — Conversational Chat Agent

Uses Claude Opus 4.6 with tool use to answer natural language questions
about Kentucky Basketball by querying the local SQLite database.
"""

import os
import sqlite3
import json
from typing import Any
import anthropic
from dotenv import load_dotenv
load_dotenv()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(BASE_DIR, "data", "processed", "kentucky_basketball.db")
HISTORY_PATH = os.path.join(BASE_DIR, "data", "history", "uk_basketball_history.md")

CURRENT_SEASON = "2025-26"


def _load_history_kb() -> str:
    """Load the UK basketball history knowledge base."""
    try:
        with open(HISTORY_PATH, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


HISTORY_KB = _load_history_kb()

# ── DB helpers ─────────────────────────────────────────────────────────────────

def _conn():
    return sqlite3.connect(DB_PATH)


def _rows_to_dict(cursor) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ── Tool implementations ────────────────────────────────────────────────────────

def query_player_recent_stats(player_name: str, n_games: int = 5) -> str:
    """Return last n_games box score lines for a player."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT s.game_date, s.opponent, s.home_away,
                   s.minutes, s.points, s.rebounds, s.assists,
                   s.steals, s.blocks, s.turnovers,
                   s.fg_made, s.fg_att, s.fg_pct,
                   s.three_made, s.three_att, s.three_pct,
                   s.ft_made, s.ft_att, s.ft_pct
            FROM player_game_stats s
            WHERE s.player_name LIKE ? AND s.season = ?
            ORDER BY s.game_date DESC
            LIMIT ?
        """, (f"%{player_name}%", CURRENT_SEASON, n_games))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return f"No stats found for '{player_name}' this season."
        return json.dumps(rows)
    except Exception as e:
        return f"Error: {e}"


def query_player_season_averages(player_name: str) -> str:
    """Return season averages for a player."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT player_name, position,
                   COUNT(*) as games_played,
                   ROUND(AVG(CAST(minutes AS REAL)), 1) as avg_min,
                   ROUND(AVG(CAST(points AS REAL)), 1) as ppg,
                   ROUND(AVG(CAST(rebounds AS REAL)), 1) as rpg,
                   ROUND(AVG(CAST(assists AS REAL)), 1) as apg,
                   ROUND(AVG(CAST(steals AS REAL)), 1) as spg,
                   ROUND(AVG(CAST(blocks AS REAL)), 1) as bpg,
                   ROUND(AVG(CAST(turnovers AS REAL)), 1) as topg,
                   ROUND(AVG(CAST(fg_pct AS REAL)), 1) as fg_pct,
                   ROUND(AVG(CAST(three_pct AS REAL)), 1) as three_pct
            FROM player_game_stats
            WHERE player_name LIKE ? AND season = ?
        """, (f"%{player_name}%", CURRENT_SEASON))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows or rows[0]['games_played'] == 0:
            return f"No stats found for '{player_name}' this season."
        return json.dumps(rows[0])
    except Exception as e:
        return f"Error: {e}"


def query_game_results(n_games: int = 10) -> str:
    """Return last n completed games with score and opponent."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT date,
                   CASE WHEN home_team='Kentucky Wildcats' THEN away_team ELSE home_team END as opponent,
                   CASE WHEN neutral_site=1 THEN 'neutral'
                        WHEN home_team='Kentucky Wildcats' THEN 'home' ELSE 'away' END as loc,
                   home_score, away_score,
                   CASE WHEN home_team='Kentucky Wildcats' AND CAST(home_score AS INT) > CAST(away_score AS INT) THEN 'W'
                        WHEN away_team='Kentucky Wildcats' AND CAST(away_score AS INT) > CAST(home_score AS INT) THEN 'W'
                        ELSE 'L' END as result,
                   CASE WHEN home_team='Kentucky Wildcats' THEN home_score ELSE away_score END as uk_score,
                   CASE WHEN home_team='Kentucky Wildcats' THEN away_score ELSE home_score END as opp_score,
                   CASE WHEN home_team='Kentucky Wildcats'
                        THEN CAST(home_score AS INT) - CAST(away_score AS INT)
                        ELSE CAST(away_score AS INT) - CAST(home_score AS INT)
                   END as margin
            FROM games
            WHERE season = ? AND status IN ('Final','STATUS_FINAL')
            ORDER BY date DESC
            LIMIT ?
        """, (CURRENT_SEASON, n_games))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return "No completed games found."
        return json.dumps(rows)
    except Exception as e:
        return f"Error: {e}"


def query_team_record() -> str:
    """Return UK's current overall record, conference record, and win/loss streaks."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT date, overall_record, conf_record, bpi, bpi_rank, sor, sor_rank, sos_rank
            FROM team_metrics
            WHERE season = ?
            ORDER BY date DESC
            LIMIT 1
        """, (CURRENT_SEASON,))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return "No team metrics available."
        return json.dumps(rows[0])
    except Exception as e:
        return f"Error: {e}"


def query_net_rank_history(n: int = 10) -> str:
    """Return NET rank history for Kentucky."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT date, net_rank, season
            FROM net_rankings_history
            WHERE season IN (?,?) AND team_name = 'Kentucky'
            ORDER BY date DESC
            LIMIT ?
        """, ("2024-25", CURRENT_SEASON, n))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return "No NET rank history available."
        return json.dumps(rows)
    except Exception as e:
        return f"Error: {e}"


def query_sec_standings() -> str:
    """Return current SEC standings."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT team_name, sec_seed, overall_record, wins, losses, win_pct,
                   ppg, opp_ppg, point_diff, streak, games_behind
            FROM sec_standings
            WHERE season = ?
            ORDER BY wins DESC, losses ASC
        """, (CURRENT_SEASON,))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return "No SEC standings available."
        return json.dumps(rows[:14])  # Top 14 teams
    except Exception as e:
        return f"Error: {e}"


def query_player_thresholds(player_name: str) -> str:
    """Return player prop bet thresholds for a player."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT player_name, thresholds_json
            FROM player_thresholds
            WHERE player_name LIKE ?
        """, (f"%{player_name}%",))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return f"No thresholds found for '{player_name}'."
        # Parse the JSON blob for readability
        result = []
        for row in rows:
            thresholds = json.loads(row["thresholds_json"])
            result.append({"player": row["player_name"], "thresholds": thresholds})
        return json.dumps(result)
    except Exception as e:
        return f"Error: {e}"


def query_next_game() -> str:
    """Return info about the next scheduled game."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT date, name, short_name, status, venue_name, venue_city, venue_state,
                   neutral_site, home_team, away_team, network
            FROM games
            WHERE season = ? AND status NOT IN ('Final','STATUS_FINAL')
              AND date >= date('now', '-1 day')
            ORDER BY date ASC
            LIMIT 1
        """, (CURRENT_SEASON,))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return "No upcoming games found."
        return json.dumps(rows[0])
    except Exception as e:
        return f"Error: {e}"


def query_opponent_advanced_stats(team_name: str) -> str:
    """Return BartTorvik advanced stats for any D1 team (adj_o, adj_d, adj_em, tempo, etc.)."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT team_name, conference, record, t_rank,
                   adj_o, adj_o_rank, adj_d, adj_d_rank, adj_em,
                   barthag, luck, tempo, date
            FROM team_advanced_stats
            WHERE team_name LIKE ?
            ORDER BY date DESC
            LIMIT 1
        """, (f"%{team_name}%",))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return f"No advanced stats found for '{team_name}'."
        return json.dumps(rows[0])
    except Exception as e:
        return f"Error: {e}"


def query_player_comparison(player_names: list[str]) -> str:
    """Compare season averages across multiple players."""
    results = []
    for name in player_names:
        data = json.loads(query_player_season_averages(name))
        results.append(data)
    return json.dumps(results)


def query_scoring_leaders() -> str:
    """Return top scorers on UK this season, sorted by PPG."""
    try:
        conn = _conn()
        cur = conn.execute("""
            SELECT player_name, position,
                   COUNT(*) as games_played,
                   ROUND(AVG(CAST(points AS REAL)), 1) as ppg,
                   ROUND(AVG(CAST(rebounds AS REAL)), 1) as rpg,
                   ROUND(AVG(CAST(assists AS REAL)), 1) as apg,
                   ROUND(AVG(CAST(minutes AS REAL)), 1) as mpg
            FROM player_game_stats
            WHERE season = ?
              AND player_name NOT IN ('Walker Horn','Zach Tow')
            GROUP BY player_name
            HAVING games_played >= 3
            ORDER BY ppg DESC
            LIMIT 10
        """, (CURRENT_SEASON,))
        rows = _rows_to_dict(cur)
        conn.close()
        if not rows:
            return "No data available."
        return json.dumps(rows)
    except Exception as e:
        return f"Error: {e}"


# ── Tool registry ───────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "query_player_recent_stats",
        "description": "Get a player's last N box score lines from completed games this season. Use this for questions about recent performance, trends, hot/cold streaks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {"type": "string", "description": "Player's name or partial name (e.g. 'Oweh', 'Chandler')"},
                "n_games": {"type": "integer", "description": "Number of recent games to fetch (default 5, max 15)", "default": 5}
            },
            "required": ["player_name"]
        }
    },
    {
        "name": "query_player_season_averages",
        "description": "Get a player's season averages (PPG, RPG, APG, FG%, etc.) for the current season.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {"type": "string", "description": "Player's name or partial name"}
            },
            "required": ["player_name"]
        }
    },
    {
        "name": "query_game_results",
        "description": "Get recent game results — scores, opponents, win/loss, margin. Use for questions about the season record, recent wins/losses, or how UK has been performing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "n_games": {"type": "integer", "description": "Number of recent games (default 10)", "default": 10}
            }
        }
    },
    {
        "name": "query_team_record",
        "description": "Get UK's current record (overall and conference), BPI rank, SOR rank, and strength of schedule. Use for general team performance questions.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "query_net_rank_history",
        "description": "Get Kentucky's NET ranking history to show how the team's national ranking has evolved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of historical data points (default 10)", "default": 10}
            }
        }
    },
    {
        "name": "query_sec_standings",
        "description": "Get the current SEC standings — all teams' conference records.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "query_player_thresholds",
        "description": "Get player prop bet thresholds — the suggested over/under lines and recent hit rates for a player's points, rebounds, assists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_name": {"type": "string", "description": "Player's name or partial name"}
            },
            "required": ["player_name"]
        }
    },
    {
        "name": "query_next_game",
        "description": "Get info about the next scheduled Kentucky game — opponent, date, location.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "query_scoring_leaders",
        "description": "Get UK's scoring leaders this season — top players sorted by PPG. Use for 'who leads the team in scoring' type questions.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "query_opponent_advanced_stats",
        "description": "Get BartTorvik advanced stats for any college basketball team — adjusted offensive/defensive efficiency (adj_o, adj_d), efficiency margin (adj_em), tempo/pace, and luck rating. Use for questions like 'how good is Missouri's defense?' or 'who has the best offense in the SEC?' or 'how does UK match up analytically?'",
        "input_schema": {
            "type": "object",
            "properties": {
                "team_name": {"type": "string", "description": "Team name or partial name (e.g. 'Missouri', 'Florida', 'Duke')"}
            },
            "required": ["team_name"]
        }
    },
]

TOOL_DISPATCH: dict[str, Any] = {
    "query_player_recent_stats": lambda inp: query_player_recent_stats(
        inp["player_name"], inp.get("n_games", 5)
    ),
    "query_player_season_averages": lambda inp: query_player_season_averages(inp["player_name"]),
    "query_game_results": lambda inp: query_game_results(inp.get("n_games", 10)),
    "query_team_record": lambda inp: query_team_record(),
    "query_net_rank_history": lambda inp: query_net_rank_history(inp.get("n", 10)),
    "query_sec_standings": lambda inp: query_sec_standings(),
    "query_player_thresholds": lambda inp: query_player_thresholds(inp["player_name"]),
    "query_next_game": lambda inp: query_next_game(),
    "query_scoring_leaders": lambda inp: query_scoring_leaders(),
    "query_opponent_advanced_stats": lambda inp: query_opponent_advanced_stats(inp["team_name"]),
}

def build_system_prompt() -> str:
    history_section = (
        f"\n\n---\n## Kentucky Basketball History Reference\n\n{HISTORY_KB}\n---\n"
        if HISTORY_KB else ""
    )
    return f"""You are the Big Blue Nation AI Analyst — a sharp, data-driven assistant AND passionate historian for Kentucky Wildcats Basketball. You have two modes:

**CURRENT SEASON MODE** — For questions about this season's stats, games, players, standings, or upcoming matchups: use the provided database query tools to fetch real data, then give a data-backed answer.

**HISTORY MODE** — For questions about Kentucky basketball history, legendary players, championships, famous games, coaches, or records: draw on the Kentucky Basketball History Reference below. Tell the stories with passion and detail. You are a storyteller and historian — bring these moments to life.

**Rules:**
- For current season questions: always query the database first, never make up numbers.
- For history questions: use the Knowledge Base as ground truth — do not hallucinate specific stats, dates, or scores beyond what's documented there.
- When a question spans both (e.g., "how does Oweh compare to past UK guards?"), use tools for current data AND the KB for historical context.
- Be conversational, specific, and enthusiastic. Speak as a lifelong UK fan who knows the history cold.
- Keep answers focused — 2-4 paragraphs for most questions, longer for rich historical stories.
- For projections and full pre-game analysis, mention the dashboard's Game Predictions tab.
- The current season is 2025-26. Head coach is Mark Pope (second season).
{history_section}"""

SYSTEM_PROMPT = build_system_prompt()


# ── Main entry point ────────────────────────────────────────────────────────────

def ask_analyst(
    user_message: str,
    conversation_history: list[dict],
) -> tuple[str, list[dict]]:
    """
    Send a message to the analyst, execute any tool calls, and return
    (assistant_reply_text, updated_conversation_history).

    conversation_history is the list of prior messages (role/content pairs).
    """
    client = anthropic.Anthropic()

    messages = conversation_history + [{"role": "user", "content": user_message}]

    # Agentic loop — keep calling until stop_reason == "end_turn"
    while True:
        with client.messages.stream(
            model="claude-opus-4-6",
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        ) as stream:
            response = stream.get_final_message()

        # Append assistant turn (preserves tool_use blocks)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    fn = TOOL_DISPATCH.get(block.name)
                    if fn:
                        result_text = fn(block.input)
                    else:
                        result_text = f"Unknown tool: {block.name}"
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            # pause_turn or unexpected — break to avoid infinite loop
            break

    # Extract final text response
    reply = next(
        (block.text for block in response.content if hasattr(block, "text") and block.type == "text"),
        "I wasn't able to generate a response. Please try again."
    )

    # Return updated history (excluding the last user message we just appended,
    # since the caller will manage that)
    updated_history = messages[:-1] if messages[-1].get("role") == "user" else messages

    # Actually return everything up to and including the final assistant turn
    # so the caller can persist it for multi-turn context
    return reply, messages
