"""
src/dashboard/app.py
Big Blue Nation AI Analyst — Streamlit Dashboard
"""

import sys
import os
import sqlite3
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from PIL import Image

# ── Path setup ────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

from src.models.prediction_engine import PredictionEngine, CURRENT_ROSTER

DB_PATH    = os.path.join(BASE_DIR, 'data', 'processed', 'kentucky_basketball.db')
SHAP_PATH  = os.path.join(BASE_DIR, 'notebooks', 'shap_summary_v4.png')

# ── ESPN logo helper ───────────────────────────────────────────────────────────
def get_espn_logo_url(team_name: str) -> str | None:
    """Return ESPN CDN logo URL for a team, or None if unknown."""
    try:
        from src.ingestion.espn_client import ESPN_TEAM_IDS
        team_id = ESPN_TEAM_IDS.get(team_name)
        if team_id:
            return f"https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/{team_id}.png&w=80&h=80"
    except Exception:
        pass
    return None

UK_LOGO = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/ncaa/500/96.png&w=80&h=80"
MODELS_DIR = os.path.join(BASE_DIR, 'data', 'models')

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Big Blue Nation AI Analyst",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)
  #MainMenu, footer, header { visibility: hidden; }
# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@300;400;500&display=swap');

  html, body {
    font-family: 'Barlow', sans-serif;
    background-color: #0a0e1a;
    color: #e8eaf0;
  }
            
  /* Hide Streamlit chrome safely */
  [data-testid="stToolbar"] { display: none; }
  [data-testid="stStatusWidget"] { display: none; }
  footer { visibility: hidden; }

  /* Sidebar styling */
  [data-testid="stSidebar"] {
    background: #0d1220;
    border-right: 1px solid #1e2a4a;
  }

  .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }

  .bbn-header {
    background: linear-gradient(135deg, #0033A0 0%, #001f6b 60%, #0a0e1a 100%);
    border-bottom: 3px solid #0033A0;
    padding: 1.5rem 2rem;
    margin: -1.5rem -1rem 2rem -1rem;
    display: flex;
    align-items: center;
    gap: 1.5rem;
  }
  .bbn-header h1 {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #ffffff;
    margin: 0;
    line-height: 1;
  }
  .bbn-header .subtitle {
    font-size: 0.85rem;
    color: #7b9fd4;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-top: 0.3rem;
  }

  .section-title {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 1.1rem;
    font-weight: 700;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #4a90d9;
    border-bottom: 1px solid #1e2a4a;
    padding-bottom: 0.4rem;
    margin-bottom: 1rem;
  }

  .metric-card {
    background: #111827;
    border: 1px solid #1e2a4a;
    border-radius: 8px;
    padding: 1.2rem 1.5rem;
    text-align: center;
  }
  .metric-card .value {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 2.8rem;
    font-weight: 800;
    line-height: 1;
    color: #ffffff;
  }
  .metric-card .label {
    font-size: 0.72rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #5a7aa8;
    margin-top: 0.3rem;
  }

  .win-prob-uk { color: #4a90d9; }
  .win-prob-opp { color: #e05c5c; }

  [data-testid="stSidebar"] {
    background: #0d1220;
    border-right: 1px solid #1e2a4a;
  }
  [data-testid="stSidebar"] .sidebar-title {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 0.8rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #4a90d9;
    margin-bottom: 0.5rem;
  }

  .divider {
    border: none;
    border-top: 1px solid #1e2a4a;
    margin: 1.5rem 0;
  }

  .score-display {
    background: #111827;
    border: 1px solid #1e2a4a;
    border-radius: 8px;
    padding: 1.5rem;
    text-align: center;
  }
  .score-team {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 0.8rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #5a7aa8;
  }
  .score-pts {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 3.5rem;
    font-weight: 800;
    line-height: 1;
  }

  .val-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  .val-table th {
    font-family: 'Barlow Condensed', sans-serif;
    font-size: 0.72rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #5a7aa8;
    padding: 0.4rem 0.6rem;
    border-bottom: 1px solid #1e2a4a;
    text-align: right;
  }
  .val-table th:first-child { text-align: left; }
  .val-table td {
    padding: 0.45rem 0.6rem;
    text-align: right;
    border-bottom: 1px solid #111827;
    color: #c0cce0;
  }
  .val-table td:first-child { text-align: left; color: #e0e8f0; }
  .val-good { color: #4caf7d; }
  .val-bad  { color: #e05c5c; }
            
  /* ===== Tabs Styling ===== */

.stTabs [data-baseweb="tab-list"] {
  gap: 8px;
  border-bottom: 1px solid #1e2a4a;
  padding-bottom: 6px;
}

.stTabs [data-baseweb="tab"] {
  background-color: #0d1220;
  color: #aab4d6;
  padding: 10px 18px;
  border-radius: 8px 8px 0 0;
  border: 1px solid transparent;
  font-weight: 600;
}

.stTabs [aria-selected="true"] {
  background-color: #0033A0;
  color: white;
  border: 1px solid #1e2a4a;
  border-bottom: 1px solid #0033A0;
}

.stTabs [data-baseweb="tab"]:hover {
  color: white;
  background-color: #16213a;
}


</style>
""", unsafe_allow_html=True)

st.markdown('<div class="bbn-header">Big Blue Nation AI Analyst</div>', unsafe_allow_html=True)



# ── Cached engine load ─────────────────────────────────────────────────────────
@st.cache_resource
def load_engine():
    return PredictionEngine()


@st.cache_data
def load_opponents():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql(
        "SELECT DISTINCT team FROM opponent_game_totals ORDER BY team", conn
    )
    conn.close()
    return df['team'].tolist()


@st.cache_data(ttl=1800)
def load_uk_record():
    """Load Kentucky's current record and streak from the DB."""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("""
            SELECT overall_record, wins, losses, streak
            FROM sec_standings WHERE team_id='96'
            ORDER BY updated_at DESC LIMIT 1
        """, conn)
        conn.close()
        if len(df) == 0:
            return None
        row = df.iloc[0]
        streak_val = int(float(row['streak'])) if row['streak'] is not None else 0
        if streak_val > 0:
            streak_str = f"W{streak_val}"
            streak_color = "#4caf7d"
            streak_bg    = "#0a2a10"
            streak_border= "#1e4a2a"
        elif streak_val < 0:
            streak_str = f"L{abs(streak_val)}"
            streak_color = "#e05c5c"
            streak_bg    = "#2a0a0a"
            streak_border= "#4a1e1e"
        else:
            streak_str   = "—"
            streak_color = "#5a7aa8"
            streak_bg    = "#111827"
            streak_border= "#1e2a4a"
        return {
            'record':       row['overall_record'],
            'streak':       streak_str,
            'streak_color': streak_color,
            'streak_bg':    streak_bg,
            'streak_border':streak_border,
        }
    except Exception:
        return None


@st.cache_data
def load_validation_data():
    """Load past game predictions vs actuals if available."""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql(
            "SELECT * FROM prediction_validation ORDER BY game_date DESC LIMIT 10", conn
        )
        conn.close()
        return df
    except Exception:
        return None


# ── Sidebar controls ───────────────────────────────────────────────────────────
# Auto-load next game
@st.cache_data(ttl=3600)
def load_next_game():
    try:
        sys.path.insert(0, BASE_DIR)
        from src.ingestion.espn_client import get_next_game
        return get_next_game()
    except Exception:
        return None

@st.cache_data(ttl=3600)
def load_opponent_bpi(opponent_name):
    from src.ingestion.espn_client import get_opponent_bpi
    return get_opponent_bpi(opponent_name)


@st.cache_data(ttl=1800)
def load_game_odds():
    try:
        from src.ingestion.odds_scraper import get_next_game_odds
        return get_next_game_odds()
    except Exception:
        return None


@st.cache_data(ttl=600)
def load_player_game_log():
    """Load per-player per-game stats for sparklines."""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("""
            SELECT p.player_name, g.date as game_date, SUM(p.points) as points,
                   SUM(p.rebounds) as rebounds, SUM(p.assists) as assists
            FROM player_game_stats p
            JOIN games g ON g.id = p.game_id
            WHERE p.season = '2025-26' AND g.status = 'STATUS_FINAL'
            GROUP BY p.player_name, p.game_id, g.date
            ORDER BY p.player_name, g.date
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_season_game_log():
    """Load completed game results for the season game log tab."""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("""
            SELECT g.date, g.name, g.home_team, g.away_team,
                   g.home_score, g.away_score, g.neutral_site, g.season_type
            FROM games g
            WHERE g.season = '2025-26' AND g.status = 'STATUS_FINAL'
            ORDER BY g.date DESC
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_prediction_accuracy():
    """Load predicted vs actual scores for games with saved predictions."""
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql("""
            SELECT gp.game_id, gp.game_date, gp.opponent,
                   gp.predicted_uk_score, gp.predicted_opp_score,
                   g.home_team, g.home_score, g.away_score
            FROM game_predictions gp
            LEFT JOIN games g ON g.id = gp.game_id
            WHERE g.status = 'STATUS_FINAL'
            ORDER BY gp.game_date DESC
        """, conn)
        conn.close()
        return df
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def load_net_rankings():
    from src.ingestion.espn_client import get_net_rankings
    return get_net_rankings()

next_game    = load_next_game()
net_rankings = load_net_rankings()

# ── Game Day detection ─────────────────────────────────────────────────────────
from datetime import date as _date
_today = _date.today().isoformat()
_game_today = next_game and next_game.get('date', '')[:10] == _today

with st.sidebar:
    st.markdown('<div class="sidebar-title">🏀 Game Setup</div>', unsafe_allow_html=True)

    opponents = load_opponents()

    # Auto-select next opponent
    # Auto-select next opponent
    if next_game:
        auto_opponent = next_game.get('away_team') \
            if next_game.get('home_team') == 'Kentucky Wildcats' \
            else next_game.get('home_team')
        auto_neutral  = next_game.get('neutral_site', False)
        auto_is_home  = next_game.get('home_team') == 'Kentucky Wildcats' and not auto_neutral
        auto_venue    = next_game.get('venue_name', '')
        auto_date     = next_game.get('date', '')[:10]

        # Format date nicely
        from datetime import datetime, timezone
        import zoneinfo
        try:
            eastern  = zoneinfo.ZoneInfo("America/New_York")
            game_dt  = datetime.fromisoformat(next_game['date'].replace('Z', '+00:00'))
            game_str = game_dt.astimezone(eastern).strftime("%a %b %d @ %I:%M %p ET")
        except Exception:
            game_str = auto_date

        venue_icon  = '🏟️' if auto_neutral else ('🏠' if auto_is_home else '✈️')
        opp_logo    = get_espn_logo_url(auto_opponent)
        logo_html   = f'<img src="{opp_logo}" style="width:36px;height:36px;object-fit:contain;margin-right:0.5rem">' if opp_logo else ''
        today_badge = '<span style="background:#0033A0;color:#fff;font-size:0.65rem;font-weight:700;letter-spacing:0.1em;padding:0.1rem 0.4rem;border-radius:3px;margin-left:0.4rem">TODAY</span>' if _game_today else ''
        st.markdown(f"""
        <div style="background:#0d1f3c;border:1px solid {'#0033A0' if _game_today else '#1e2a4a'};border-radius:6px;
                    padding:0.8rem 1rem;margin-bottom:1rem">
        <div style="font-family:'Barlow Condensed';font-size:0.7rem;letter-spacing:0.12em;
                    text-transform:uppercase;color:#4a90d9">Next Game{today_badge}</div>
        <div style="display:flex;align-items:center;margin-top:0.4rem">
            {logo_html}
            <div>
                <div style="font-weight:600;color:#fff">{venue_icon} vs {auto_opponent}</div>
                <div style="font-size:0.75rem;color:#5a7aa8;margin-top:0.1rem">{game_str}</div>
                <div style="font-size:0.75rem;color:#5a7aa8">{auto_venue}</div>
            </div>
        </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        auto_opponent = opponents[0] if opponents else ''
        auto_is_home  = False
        auto_neutral  = False

    default_opp_idx = opponents.index(auto_opponent) \
        if auto_opponent in opponents else 0
    opponent = st.selectbox("Opponent", opponents, index=default_opp_idx)

    # Auto-fill venue based on next game
    venue_default = "Neutral" if auto_neutral else ("Home" if auto_is_home else "Away")
    is_home = st.radio("Venue", ["Away", "Home", "Neutral"],
                    index=["Away", "Home", "Neutral"].index(venue_default)) == "Home"
    # Auto-fill NET rank
    
    from src.ingestion.espn_client import get_opponent_net_rank
    auto_net = get_opponent_net_rank(opponent, net_rankings)
    net_rank    = st.number_input("NET Rank", min_value=1, max_value=365, value=int(auto_net))

    auto_bpi = load_opponent_bpi(opponent)
    opp_bpi = st.number_input("Opp BPI", min_value=0.0, max_value=35.0,
                             value=float(auto_bpi), step=0.1)

    days_rest = st.slider("Days Rest", 1, 10, 3)
    is_b2b    = st.checkbox("Back-to-Back", value=False)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-title">⚠️ Injuries / Out</div>',
                unsafe_allow_html=True)

    all_players = [p['name'] for p in CURRENT_ROSTER if not p.get('walk_on')]
    default_out = ['Jayden Quaintance', 'Jaland Lowe']
    injuries = []
    for player in all_players:
        if st.checkbox(player, value=(player in default_out)):
            injuries.append(player)

    # ── Vegas Odds ─────────────────────────────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-title">💰 Vegas Odds</div>', unsafe_allow_html=True)
    game_odds = load_game_odds()
    if game_odds:
        spread_str = f"{game_odds['spread']:+.1f}" if game_odds.get('spread') is not None else "N/A"
        ou_str     = str(game_odds['over_under']) if game_odds.get('over_under') is not None else "N/A"
        uk_ml_str  = f"{game_odds['uk_moneyline']:+d}" if game_odds.get('uk_moneyline') is not None else "N/A"
        spread_color = "#4caf7d" if game_odds.get('spread') is not None and game_odds['spread'] < 0 else "#e05c5c"
        st.markdown(f"""
        <div style="background:#0d1f3c;border:1px solid #1e2a4a;border-radius:6px;
                    padding:0.7rem 0.9rem;font-size:0.83rem">
          <div style="display:flex;justify-content:space-between;margin-bottom:0.3rem">
            <span style="color:#5a7aa8">Spread (UK)</span>
            <span style="color:{spread_color};font-weight:700">{spread_str}</span>
          </div>
          <div style="display:flex;justify-content:space-between;margin-bottom:0.3rem">
            <span style="color:#5a7aa8">Over/Under</span>
            <span style="color:#e8eaf0;font-weight:600">{ou_str}</span>
          </div>
          <div style="display:flex;justify-content:space-between">
            <span style="color:#5a7aa8">UK Moneyline</span>
            <span style="color:#e8eaf0;font-weight:600">{uk_ml_str}</span>
          </div>
          <div style="font-size:0.68rem;color:#3a4a6a;margin-top:0.4rem">{game_odds.get('provider','')}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.caption("Odds not yet available.")

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    run_btn = st.button("🔮 Run Prediction", use_container_width=True, type="primary")


# ── Header ─────────────────────────────────────────────────────────────────────
uk_rec = load_uk_record()
if uk_rec:
    record_html = f"""
    <div style="display:flex;gap:0.6rem;margin-top:0.5rem;align-items:center">
      <span style="background:#0a1a30;border:1px solid #1e3a6a;border-radius:4px;
                   padding:0.15rem 0.55rem;font-family:'Barlow Condensed',sans-serif;
                   font-size:1rem;color:#e0e8f0;font-weight:700;letter-spacing:0.04em">
        {uk_rec['record']}
      </span>
      <span style="background:{uk_rec['streak_bg']};border:1px solid {uk_rec['streak_border']};
                   border-radius:4px;padding:0.15rem 0.55rem;
                   font-family:'Barlow Condensed',sans-serif;font-size:1rem;
                   color:{uk_rec['streak_color']};font-weight:700;letter-spacing:0.04em">
        {uk_rec['streak']}
      </span>
    </div>"""
else:
    record_html = ""

game_day_banner = ""
if _game_today and next_game:
    try:
        from datetime import datetime as _dt
        import zoneinfo as _zi
        _et = _zi.ZoneInfo("America/New_York")
        _gdt = _dt.fromisoformat(next_game['date'].replace('Z', '+00:00'))
        _gtime = _gdt.astimezone(_et).strftime("%I:%M %p ET")
    except Exception:
        _gtime = "Today"
    _opp = auto_opponent if next_game else ""
    game_day_banner = f"""
    <div style="background:linear-gradient(90deg,#0033A0,#001f6b);
                border-bottom:2px solid #4a90d9;padding:0.5rem 2rem;
                margin:-1.5rem -1rem 0 -1rem;
                display:flex;align-items:center;gap:0.8rem">
        <span style="font-family:'Barlow Condensed';font-size:1rem;font-weight:800;
                     letter-spacing:0.15em;text-transform:uppercase;color:#fff">
            🏀 GAME DAY
        </span>
        <span style="font-size:0.85rem;color:#a0c4f0">
            vs {_opp} · {_gtime} · {next_game.get('venue_name','')}
        </span>
    </div>"""

st.markdown(f"""
{game_day_banner}
<div class="bbn-header">
  <img src="{UK_LOGO}" style="width:64px;height:64px;object-fit:contain">
  <div>
    <h1>Big Blue Nation</h1>
    <div class="subtitle">AI Game Analyst · Kentucky Wildcats Basketball</div>
    {record_html}
  </div>
</div>
""", unsafe_allow_html=True)


# ── Main content ───────────────────────────────────────────────────────────────
tab_game, tab_players, tab_sim, tab_models, tab_gamelog = st.tabs(
    ["🏀 Game Predictions", "👥 Player Predictions", "🎲 Simulation", "📊 Model Insights", "📋 Season Log"]
)
if 'result' not in st.session_state:
    st.session_state.result = None

if run_btn or st.session_state.result is None:
    with st.spinner("Running prediction models..."):
        try:
            engine = load_engine()
            result = engine.predict_game_with_ci(
                opponent        = opponent,
                is_home         = int(is_home),
                net_rank        = net_rank,
                opp_bpi         = opp_bpi,
                injuries        = injuries,
                days_rest       = days_rest,
                is_back_to_back = int(is_b2b),
            )
            st.session_state.result = result
        except Exception as e:
            st.error(f"Prediction failed: {e}")
            st.stop()

result = st.session_state.result
if result is None:
    st.info("Configure the game in the sidebar and click **Run Prediction**.")
    st.stop()

venue_str = "🏠 Home" if result['is_home'] else "✈️ Away"
inj_str   = ", ".join(result['injuries']) if result['injuries'] else "None"

# ── Score + Win Probability ────────────────────────────────────────────────────
with tab_game:
    st.markdown('<div class="section-title">Game Projection</div>', unsafe_allow_html=True)

    col_uk, col_vs, col_opp, col_prob = st.columns([2, 0.6, 2, 3])

    _opp_logo_url = get_espn_logo_url(result['opponent'])
    _opp_logo_tag = f'<img src="{_opp_logo_url}" style="width:48px;height:48px;object-fit:contain;margin-bottom:0.3rem"><br>' if _opp_logo_url else ''

    with col_uk:
        st.markdown(f"""
        <div class="score-display">
            <img src="{UK_LOGO}" style="width:48px;height:48px;object-fit:contain;margin-bottom:0.3rem"><br>
            <div class="score-team">Kentucky Wildcats</div>
            <div class="score-pts" style="color:#4a90d9">{result['uk_score']}</div>
            <div style="font-size:0.78rem;color:#5a7aa8;margin-top:0.3rem">{venue_str}</div>
        </div>
        """, unsafe_allow_html=True)

    with col_vs:
        st.markdown("""
        <div style="display:flex;align-items:center;justify-content:center;height:100%">
        <span style="font-family:'Barlow Condensed',sans-serif;font-size:1.4rem;
                   color:#3a4a6a;font-weight:700">VS</span>
        </div>
        """, unsafe_allow_html=True)

    with col_opp:
        st.markdown(f"""
        <div class="score-display">
        {_opp_logo_tag}
        <div class="score-team">{result['opponent']}</div>
        <div class="score-pts" style="color:#e05c5c">{result['opp_score']}</div>
        <div style="font-size:0.78rem;color:#5a7aa8;margin-top:0.3rem">
            NET #{net_rank} · BPI {opp_bpi}
        </div>
        </div>
        """, unsafe_allow_html=True)

    with col_prob:
        win_pct = result['win_probability']
        fig = go.Figure(go.Indicator(
            mode  = "gauge+number",
            value = win_pct,
            number= {'suffix': '%', 'font': {'size': 36, 'color': '#ffffff',
                                          'family': 'Barlow Condensed'}},
            title = {'text': "Kentucky Win Probability",
                    'font': {'size': 13, 'color': '#5a7aa8', 'family': 'Barlow'}},
            gauge = {
                'axis': {'range': [0, 100], 'tickcolor': '#3a4a6a',
                     'tickfont': {'color': '#3a4a6a', 'size': 10}},
                'bar':  {'color': '#0033A0', 'thickness': 0.25},
                'bgcolor': '#111827',
                'bordercolor': '#1e2a4a',
                'steps': [
                    {'range': [0,  40], 'color': '#1a0a0a'},
                    {'range': [40, 60], 'color': '#1a1a0a'},
                    {'range': [60, 100],'color': '#0a1a0a'},
                ],
                'threshold': {
                    'line': {'color': '#4a90d9', 'width': 2},
                    'thickness': 0.8,
                    'value': 50,
                }
            }
        ))
        fig.update_layout(
            height=200, margin=dict(t=40, b=10, l=20, r=20),
            paper_bgcolor='#111827', font_color='#ffffff',
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    diff_color = "#4caf7d" if result['point_diff'] >= 0 else "#e05c5c"
    diff_sign  = "+" if result['point_diff'] >= 0 else ""
    st.markdown(f"""
    <div style="display:flex;gap:2rem;margin:0.8rem 0 1.5rem;flex-wrap:wrap">
        <span style="font-family:'Barlow Condensed';font-size:1rem;color:{diff_color};
               font-weight:700;letter-spacing:0.05em">
        DIFF {diff_sign}{result['point_diff']}
    </span>
    <span style="font-size:0.82rem;color:#5a7aa8">
        ⚠️ OUT: {inj_str}
    </span>
</div>
""", unsafe_allow_html=True)


# ── Player Projections ─────────────────────────────────────────────────────────
with tab_players:
    st.markdown('<div class="section-title">Player Projections</div>', unsafe_allow_html=True)


    engine = load_engine()
    starters = sorted([p for p in result['projections'] if p['starter']],
                   key=lambda x: x['points'], reverse=True)
    bench    = sorted([p for p in result['projections'] if not p['starter']],
                   key=lambda x: x['points'], reverse=True)


    def get_status_emoji(player_name, pts, reb, ast):
        status, must_do = engine.get_threshold_status(player_name, pts, reb, ast)
        if '✅' in status:  return '🟢', must_do
        if '⚠' in status:  return '🟡', must_do
        return '🔴', must_do


    def _fmt_ci(val, lo, hi):
        return f"{val:.1f}  ({lo:.1f}–{hi:.1f})"

    def build_df(players):
        rows = []
        for p in players:
            dot, must_do = get_status_emoji(p['name'], p['points'], p['rebounds'], p['assists'])
            has_ci = 'points_lo' in p
            rows.append({
                'Status': dot,
                'Player': p['name'],
                'PTS': _fmt_ci(p['points'], p['points_lo'], p['points_hi']) if has_ci else f"{p['points']:.1f}",
                'REB': _fmt_ci(p['rebounds'], p['rebounds_lo'], p['rebounds_hi']) if has_ci else f"{p['rebounds']:.1f}",
                'AST': _fmt_ci(p['assists'], p['assists_lo'], p['assists_hi']) if has_ci else f"{p['assists']:.1f}",
                'MIN': f"{p['minutes']:.1f}",
                'Must Do': must_do,
            })
        return pd.DataFrame(rows)

    col_cfg = {
        'Status': st.column_config.TextColumn(width='small'),
        'Player': st.column_config.TextColumn(width='medium'),
        'PTS':    st.column_config.TextColumn(width='medium'),
        'REB':    st.column_config.TextColumn(width='medium'),
        'AST':    st.column_config.TextColumn(width='medium'),
        'MIN':    st.column_config.TextColumn(width='small'),
        'Must Do':st.column_config.TextColumn(width='large'),
    }

    st.caption("STARTERS  ·  80% prediction interval shown in parentheses")
    st.dataframe(build_df(starters), use_container_width=True,
                 hide_index=True, column_config=col_cfg)

    st.caption("BENCH")
    st.dataframe(build_df(bench), use_container_width=True,
                 hide_index=True, column_config=col_cfg)

    # Team totals
    tot_pts = sum(p['points']   for p in result['projections'])
    tot_reb = sum(p['rebounds'] for p in result['projections'])
    tot_ast = sum(p['assists']  for p in result['projections'])
    tot_min = sum(p['minutes']  for p in result['projections'])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Team Points",   f"{tot_pts:.1f}")
    col2.metric("Team Rebounds", f"{tot_reb:.1f}")
    col3.metric("Team Assists",  f"{tot_ast:.1f}")
    col4.metric("Team Minutes",  f"{tot_min:.0f}")

    # ── Player Sparklines (Item 8) ─────────────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Recent Scoring Trends — Last 8 Games</div>',
                unsafe_allow_html=True)
    player_log = load_player_game_log()
    if not player_log.empty:
        projected_names = [p['name'] for p in result['projections']]
        spark_players   = [p for p in result['projections']
                           if p['name'] in player_log['player_name'].values]

        if spark_players:
            from plotly.subplots import make_subplots

            n_cols  = min(4, len(spark_players))
            n_rows  = (len(spark_players) + n_cols - 1) // n_cols
            fig_sp  = make_subplots(rows=n_rows, cols=n_cols,
                                    subplot_titles=[p['name'].split()[-1] for p in spark_players],
                                    horizontal_spacing=0.06, vertical_spacing=0.18)

            for idx, p in enumerate(spark_players):
                r = idx // n_cols + 1
                c = idx % n_cols + 1
                hist = player_log[player_log['player_name'] == p['name']].tail(8)
                xs   = list(range(1, len(hist) + 1))
                ys   = hist['points'].tolist()
                pred = p['points']

                avg_y = sum(ys) / len(ys) if ys else pred
                line_color = '#4caf7d' if pred >= avg_y else '#e05c5c'

                fig_sp.add_trace(go.Scatter(
                    x=xs, y=ys,
                    mode='lines+markers',
                    line=dict(color='#4a90d9', width=1.5),
                    marker=dict(size=4, color='#4a90d9'),
                    showlegend=False,
                    hovertemplate='G%{x}: %{y} pts<extra></extra>',
                ), row=r, col=c)

                # Add projection point
                fig_sp.add_trace(go.Scatter(
                    x=[len(xs) + 1], y=[pred],
                    mode='markers',
                    marker=dict(size=8, color=line_color, symbol='diamond'),
                    showlegend=False,
                    hovertemplate=f'Proj: {pred:.1f} pts<extra></extra>',
                ), row=r, col=c)

                # Average line
                if ys:
                    fig_sp.add_hline(y=avg_y, line=dict(color='#2a3a5c', width=1, dash='dot'),
                                     row=r, col=c)

            fig_sp.update_layout(
                height=130 * n_rows + 40,
                paper_bgcolor='#111827',
                plot_bgcolor='#111827',
                font=dict(color='#5a7aa8', size=10),
                margin=dict(t=40, b=20, l=30, r=10),
            )
            for ax in fig_sp.layout:
                if ax.startswith('xaxis') or ax.startswith('yaxis'):
                    fig_sp.layout[ax].update(
                        gridcolor='#1e2a4a',
                        showticklabels=False,
                        zeroline=False,
                    )
            st.plotly_chart(fig_sp, use_container_width=True, config={'displayModeBar': False})
            st.caption("Blue line = last 8 games · Diamond = today's projection · Dotted = season avg")
    else:
        st.caption("No game history yet for sparklines.")


# ── Win Probability Simulator ──────────────────────────────────────────────────
with tab_sim:
    st.markdown('<div class="section-title">Win Probability Simulator</div>',
                unsafe_allow_html=True)
    st.caption(
        "Slide opponent BPI to explore how win probability shifts. "
        "Uses the simplified BPI model so the chart updates instantly."
    )

    sim_engine = load_engine()
    uk_score   = result['uk_score']
    opp_score  = result['opp_score']

    col_slider, col_gauge = st.columns([1.2, 1])

    with col_slider:
        sim_bpi = st.slider(
            "Opponent BPI", min_value=0.0, max_value=35.0,
            value=float(opp_bpi), step=0.5,
            help="Higher BPI = stronger opponent"
        )

        # Compute win prob curve across full BPI range
        bpi_range = [round(i * 0.5, 1) for i in range(71)]  # 0 → 35
        probs = [
            sim_engine._win_prob_hybrid(
                uk_score, opp_score, b, is_home, result['injuries']
            ) * 100
            for b in bpi_range
        ]

        # Find break-even BPI (where win prob crosses 50%)
        breakeven = None
        for i in range(len(probs) - 1):
            if (probs[i] >= 50) != (probs[i + 1] >= 50):
                breakeven = bpi_range[i]
                break

        sim_win_prob = sim_engine._win_prob_hybrid(
            uk_score, opp_score, sim_bpi, is_home, result['injuries']
        ) * 100

        fig_curve = go.Figure()
        fig_curve.add_trace(go.Scatter(
            x=bpi_range, y=probs,
            mode='lines',
            line=dict(color='#4a90d9', width=2),
            fill='tozeroy',
            fillcolor='rgba(74,144,217,0.08)',
            name='Win Prob',
            hovertemplate='BPI %{x:.1f} → %{y:.1f}%<extra></extra>',
        ))
        # 50% reference line
        fig_curve.add_hline(y=50, line=dict(color='#3a4a6a', width=1, dash='dash'))
        # Selected BPI marker
        fig_curve.add_vline(x=sim_bpi, line=dict(color='#ffffff', width=1, dash='dot'))
        fig_curve.add_trace(go.Scatter(
            x=[sim_bpi], y=[sim_win_prob],
            mode='markers',
            marker=dict(color='#ffffff', size=10, symbol='circle'),
            showlegend=False,
            hovertemplate=f'BPI {sim_bpi:.1f} → {sim_win_prob:.1f}%<extra></extra>',
        ))
        fig_curve.update_layout(
            height=260,
            margin=dict(t=20, b=40, l=50, r=20),
            paper_bgcolor='#111827',
            plot_bgcolor='#111827',
            font_color='#5a7aa8',
            xaxis=dict(title='Opponent BPI', gridcolor='#1e2a4a', range=[0, 35]),
            yaxis=dict(title='UK Win %', gridcolor='#1e2a4a', range=[0, 100]),
            showlegend=False,
        )
        st.plotly_chart(fig_curve, use_container_width=True,
                        config={'displayModeBar': False})

        if breakeven is not None:
            st.caption(f"Break-even: opponent BPI ≈ **{breakeven}** (50% win probability)")

    with col_gauge:
        wp_color  = "#4a90d9" if sim_win_prob >= 50 else "#e05c5c"
        fig_gauge = go.Figure(go.Indicator(
            mode  = "gauge+number",
            value = sim_win_prob,
            number= {'suffix': '%', 'font': {'size': 36, 'color': '#ffffff',
                                              'family': 'Barlow Condensed'}},
            title = {'text': f"UK Win Prob @ BPI {sim_bpi:.1f}",
                     'font': {'size': 12, 'color': '#5a7aa8', 'family': 'Barlow'}},
            gauge = {
                'axis': {'range': [0, 100], 'tickcolor': '#3a4a6a',
                         'tickfont': {'color': '#3a4a6a', 'size': 10}},
                'bar':  {'color': wp_color, 'thickness': 0.25},
                'bgcolor': '#111827',
                'bordercolor': '#1e2a4a',
                'steps': [
                    {'range': [0,  40], 'color': '#1a0a0a'},
                    {'range': [40, 60], 'color': '#1a1a0a'},
                    {'range': [60, 100],'color': '#0a1a0a'},
                ],
                'threshold': {
                    'line': {'color': '#4a90d9', 'width': 2},
                    'thickness': 0.8, 'value': 50,
                }
            }
        ))
        fig_gauge.update_layout(
            height=240, margin=dict(t=50, b=10, l=20, r=20),
            paper_bgcolor='#111827', font_color='#ffffff',
        )
        st.plotly_chart(fig_gauge, use_container_width=True,
                        config={'displayModeBar': False})

        # Quick comparison table
        st.markdown(f"""
        <table class="val-table" style="margin-top:0.5rem">
          <tr><th>Scenario</th><th>Opp BPI</th><th>UK Win %</th></tr>
          <tr><td>Current inputs</td><td>{opp_bpi:.1f}</td>
              <td>{result['win_probability']:.1f}%</td></tr>
          <tr><td>Simulated</td><td>{sim_bpi:.1f}</td>
              <td class="{'val-good' if sim_win_prob>=50 else 'val-bad'}">{sim_win_prob:.1f}%</td></tr>
        </table>
        """, unsafe_allow_html=True)


# ── SHAP Plot + Model Accuracy ─────────────────────────────────────────────────
with tab_models:
    col_shap, col_val = st.columns([1.2, 1])

    with col_shap:
        st.markdown('<div class="section-title">Feature Importance — V6 (SHAP)</div>',
                unsafe_allow_html=True)
        if os.path.exists(SHAP_PATH):
            img = Image.open(SHAP_PATH)
            st.image(img, use_container_width=True)
        else:
            st.info("SHAP plot not found. Run the notebook to generate it.")

    with col_val:
        st.markdown('<div class="section-title">Model Accuracy — V6</div>',
                unsafe_allow_html=True)

        st.markdown("""
        <table class="val-table">
        <thead>
            <tr><th>Model</th><th>MAE</th><th>Baseline</th><th>Improvement</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>Points — Guards</td>
            <td>4.18 pts</td><td>5.71 pts</td>
            <td class="val-good">+1.53 pts</td>
          </tr>
          <tr>
            <td>Points — F/C</td>
            <td>3.19 pts</td><td>3.82 pts</td>
            <td class="val-good">+0.63 pts</td>
          </tr>
          <tr>
            <td>Player Rebounds</td>
            <td>1.74 reb</td><td>2.02 reb</td>
            <td class="val-good">+0.28 reb</td>
          </tr>
          <tr>
            <td>Player Assists</td>
            <td>1.21 ast</td><td>1.50 ast</td>
            <td class="val-good">+0.29 ast</td>
          </tr>
          <tr>
            <td>Player Minutes</td>
            <td>4.82 min</td><td>7.86 min</td>
            <td class="val-good">+3.04 min</td>
          </tr>
          <tr>
            <td>Opponent Score (5-fold CV)</td>
            <td>7.89 pts</td><td>9.07 pts</td>
            <td class="val-good">+1.18 pts</td>
          </tr>
          <tr>
            <td>Win Probability (Pope era)</td>
            <td>86.6%</td><td>—</td>
            <td class="val-good">CV Accuracy</td>
          </tr>
        </tbody>
        </table>
        <div style="font-size:0.72rem;color:#3a4a6a;margin-top:0.5rem">
          V6: pace · off/def efficiency · team 3PT% · opp BPI · opp matchup · temporal decay · usage · SOS
        </div>
        """, unsafe_allow_html=True)

        # ── Pace / Efficiency Trend ────────────────────────────────────────────
        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Pace &amp; Efficiency Trends</div>',
                unsafe_allow_html=True)
        try:
            conn = sqlite3.connect(DB_PATH)
            pace_df = pd.read_sql("""
                SELECT g.date as game_date,
                       SUM(p.fg_att) - SUM(p.off_rebounds) + SUM(p.turnovers) + 0.44 * SUM(p.ft_att) as uk_poss,
                       CAST(SUM(p.points) AS REAL) / NULLIF(
                           SUM(p.fg_att) - SUM(p.off_rebounds) + SUM(p.turnovers) + 0.44 * SUM(p.ft_att), 0
                       ) * 100 as uk_off_eff
                FROM player_game_stats p
                JOIN games g ON g.id = p.game_id
                WHERE p.season = '2025-26'
                GROUP BY p.game_id, g.date
                ORDER BY g.date
            """, conn)
            conn.close()

            if len(pace_df) >= 3:
                pace_df['game_date'] = pd.to_datetime(pace_df['game_date'].str[:10])
                pace_df['uk_poss']   = pace_df['uk_poss'].clip(55, 90)
                pace_df['uk_off_eff']= pace_df['uk_off_eff'].clip(60, 140)

                fig_pace = go.Figure()
                fig_pace.add_trace(go.Scatter(
                    x=pace_df['game_date'], y=pace_df['uk_poss'],
                    mode='lines+markers', name='Possessions',
                    line=dict(color='#4a90d9', width=2),
                    marker=dict(size=5),
                    hovertemplate='%{x|%b %d}: %{y:.0f} poss<extra></extra>',
                ))
                fig_pace.update_layout(
                    height=150, margin=dict(t=10, b=30, l=40, r=10),
                    paper_bgcolor='#111827', plot_bgcolor='#111827',
                    font_color='#5a7aa8', showlegend=False,
                    yaxis=dict(title='Poss/Game', gridcolor='#1e2a4a'),
                    xaxis=dict(gridcolor='#1e2a4a'),
                )
                st.plotly_chart(fig_pace, use_container_width=True,
                                config={'displayModeBar': False})
                st.caption("Possessions per game (pace). Higher = faster-paced game.")

                fig_eff = go.Figure()
                fig_eff.add_trace(go.Scatter(
                    x=pace_df['game_date'], y=pace_df['uk_off_eff'],
                    mode='lines+markers', name='Off Eff',
                    line=dict(color='#4caf7d', width=2),
                    marker=dict(size=5),
                    hovertemplate='%{x|%b %d}: %{y:.1f} pts/100<extra></extra>',
                ))
                fig_eff.add_hline(y=pace_df['uk_off_eff'].mean(),
                                  line=dict(color='#3a4a6a', width=1, dash='dash'))
                fig_eff.update_layout(
                    height=150, margin=dict(t=10, b=30, l=40, r=10),
                    paper_bgcolor='#111827', plot_bgcolor='#111827',
                    font_color='#5a7aa8', showlegend=False,
                    yaxis=dict(title='Pts/100 Poss', gridcolor='#1e2a4a'),
                    xaxis=dict(gridcolor='#1e2a4a'),
                )
                st.plotly_chart(fig_eff, use_container_width=True,
                                config={'displayModeBar': False})
                st.caption(f"Offensive efficiency (pts per 100 possessions). Season avg: {pace_df['uk_off_eff'].mean():.1f}")
            else:
                st.caption("Not enough games yet for trend charts.")
        except Exception as _e:
            st.caption(f"Pace trend unavailable: {_e}")

        # ── NET Rank Trend ─────────────────────────────────────────────────────
        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">NET Rank History</div>',
                unsafe_allow_html=True)
        try:
            conn = sqlite3.connect(DB_PATH)
            net_hist = pd.read_sql("""
                SELECT date, team_name, net_rank
                FROM net_rankings_history
                WHERE season = '2025-26'
                ORDER BY date
            """, conn)
            conn.close()

            if len(net_hist) > 0:
                # Show UK trend
                uk_hist = net_hist[net_hist['team_name'] == 'Kentucky']
                if len(uk_hist) > 1:
                    fig_net = go.Figure()
                    fig_net.add_trace(go.Scatter(
                        x=uk_hist['date'], y=uk_hist['net_rank'],
                        mode='lines+markers',
                        line=dict(color='#0033A0', width=2),
                        marker=dict(size=6),
                        name='Kentucky NET'
                    ))
                    fig_net.update_layout(
                        height=180,
                        margin=dict(t=10, b=30, l=40, r=10),
                        paper_bgcolor='#111827',
                        plot_bgcolor='#111827',
                        font_color='#5a7aa8',
                        yaxis=dict(autorange='reversed',
                                   gridcolor='#1e2a4a',
                                   title='NET Rank'),
                        xaxis=dict(gridcolor='#1e2a4a'),
                    )
                    st.plotly_chart(fig_net, use_container_width=True,
                                    config={'displayModeBar': False})
                else:
                    st.caption("NET rank history builds up after each daily refresh.")
            else:
                st.caption("No NET rank history yet. Run refresh.py to start tracking.")
        except Exception:
            st.caption("NET rank history not available yet.")

        # ── Post-Game Validation ───────────────────────────────────────────────
        val_df = load_validation_data()
        if val_df is not None and len(val_df) > 0:
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Post-Game Validation</div>',
                    unsafe_allow_html=True)
            st.dataframe(val_df, use_container_width=True, hide_index=True)

        # ── Prediction Accuracy Chart (Item 10) ────────────────────────────────
        acc_df = load_prediction_accuracy()
        if acc_df is not None and len(acc_df) > 0:
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Score Prediction Accuracy</div>',
                    unsafe_allow_html=True)

            # Compute actual UK/opp scores
            acc_df['uk_actual']  = acc_df.apply(
                lambda r: int(r['home_score']) if r['home_team'] == 'Kentucky Wildcats'
                          else int(r['away_score']),
                axis=1
            )
            acc_df['opp_actual'] = acc_df.apply(
                lambda r: int(r['away_score']) if r['home_team'] == 'Kentucky Wildcats'
                          else int(r['home_score']),
                axis=1
            )
            acc_df['uk_error']   = acc_df['predicted_uk_score']  - acc_df['uk_actual']
            acc_df['opp_error']  = acc_df['predicted_opp_score'] - acc_df['opp_actual']
            acc_df['label']      = acc_df['opponent'].str.split().str[-1] + ' ' + \
                                   acc_df['game_date'].astype(str).str[:10]

            fig_acc = go.Figure()
            fig_acc.add_trace(go.Bar(
                x=acc_df['label'], y=acc_df['uk_error'],
                name='UK Error', marker_color='#4a90d9',
                hovertemplate='%{x}<br>UK Error: %{y:+.1f} pts<extra></extra>',
            ))
            fig_acc.add_trace(go.Bar(
                x=acc_df['label'], y=acc_df['opp_error'],
                name='Opp Error', marker_color='#e05c5c',
                hovertemplate='%{x}<br>Opp Error: %{y:+.1f} pts<extra></extra>',
            ))
            fig_acc.add_hline(y=0, line=dict(color='#3a4a6a', width=1))
            fig_acc.update_layout(
                height=220, barmode='group',
                margin=dict(t=10, b=50, l=40, r=10),
                paper_bgcolor='#111827', plot_bgcolor='#111827',
                font_color='#5a7aa8',
                xaxis=dict(gridcolor='#1e2a4a'),
                yaxis=dict(title='Pred − Actual (pts)', gridcolor='#1e2a4a'),
                legend=dict(font=dict(size=10), bgcolor='rgba(0,0,0,0)'),
            )
            st.plotly_chart(fig_acc, use_container_width=True, config={'displayModeBar': False})

            uk_mae  = acc_df['uk_error'].abs().mean()
            opp_mae = acc_df['opp_error'].abs().mean()
            st.caption(f"UK score MAE: {uk_mae:.1f} pts · Opp score MAE: {opp_mae:.1f} pts · "
                       f"n={len(acc_df)} validated games")

# ── Season Game Log Tab (Item 9) ───────────────────────────────────────────────
with tab_gamelog:
    st.markdown('<div class="section-title">2025-26 Season Game Log</div>',
                unsafe_allow_html=True)
    game_log_df = load_season_game_log()
    if not game_log_df.empty:
        rows = []
        for _, g in game_log_df.iterrows():
            uk_is_home = g['home_team'] == 'Kentucky Wildcats'
            opponent   = g['away_team'] if uk_is_home else g['home_team']
            try:
                uk_score_act  = int(g['home_score']) if uk_is_home else int(g['away_score'])
                opp_score_act = int(g['away_score']) if uk_is_home else int(g['home_score'])
                result_str    = 'W' if uk_score_act > opp_score_act else 'L'
                margin        = uk_score_act - opp_score_act
                score_str     = f"{uk_score_act}-{opp_score_act}"
            except (ValueError, TypeError):
                result_str = '?'
                margin     = 0
                score_str  = '—'

            venue = 'H' if uk_is_home else ('N' if g.get('neutral_site') else 'A')
            rows.append({
                'Date':     g['date'][:10] if g['date'] else '—',
                'Opponent': opponent or '—',
                'Venue':    venue,
                'Score':    score_str,
                'W/L':      result_str,
                'Margin':   f"+{margin}" if margin > 0 else str(margin),
                'Type':     g.get('season_type', '') or '',
            })

        log_display = pd.DataFrame(rows)

        def _color_wl(val):
            if val == 'W':
                return 'color: #4caf7d; font-weight: 700'
            elif val == 'L':
                return 'color: #e05c5c; font-weight: 700'
            return ''

        def _color_margin(val):
            try:
                v = int(val.replace('+', ''))
                return 'color: #4caf7d' if v > 0 else 'color: #e05c5c'
            except Exception:
                return ''

        wins   = len([r for r in rows if r['W/L'] == 'W'])
        losses = len([r for r in rows if r['W/L'] == 'L'])
        avg_margin = sum(int(r['Margin'].replace('+','')) for r in rows if r['Margin'] != '—') / max(len(rows), 1)

        c1, c2, c3 = st.columns(3)
        c1.metric("Record", f"{wins}-{losses}")
        c2.metric("Avg Margin", f"{avg_margin:+.1f}")
        c3.metric("Games Played", str(len(rows)))

        st.dataframe(
            log_display.style
                .applymap(_color_wl, subset=['W/L'])
                .applymap(_color_margin, subset=['Margin']),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No completed games yet this season.")


# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;color:#2a3a5c;font-size:0.75rem;
            letter-spacing:0.08em;text-transform:uppercase;padding:0.5rem 0">
  Big Blue Nation AI Analyst · Built with XGBoost + Streamlit · Go Cats 🐾
</div>
""", unsafe_allow_html=True)