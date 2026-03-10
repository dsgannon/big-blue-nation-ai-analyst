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
SHAP_PATH  = os.path.join(BASE_DIR, 'notebooks', 'shap_summary_v3.png')
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

@st.cache_data(ttl=3600)
def load_net_rankings():
    from src.ingestion.espn_client import get_net_rankings
    return get_net_rankings()

next_game = load_next_game()
net_rankings = load_net_rankings()

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

        venue_icon = '🏟️' if auto_neutral else ('🏠' if auto_is_home else '✈️')
        st.markdown(f"""
        <div style="background:#0d1f3c;border:1px solid #1e2a4a;border-radius:6px;
                    padding:0.8rem 1rem;margin-bottom:1rem">
        <div style="font-family:'Barlow Condensed';font-size:0.7rem;letter-spacing:0.12em;
                    text-transform:uppercase;color:#4a90d9">Next Game</div>
        <div style="font-weight:600;color:#fff;margin-top:0.2rem">
            {venue_icon} vs {auto_opponent}
        </div>
        <div style="font-size:0.75rem;color:#5a7aa8;margin-top:0.1rem">{game_str}</div>
        <div style="font-size:0.75rem;color:#5a7aa8">{auto_venue}</div>
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
    default_out = ['Jayden Quaintance', 'Jaland Lowe', 'Kam Williams']
    injuries = []
    for player in all_players:
        if st.checkbox(player, value=(player in default_out)):
            injuries.append(player)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    run_btn = st.button("🔮 Run Prediction", use_container_width=True, type="primary")


# ── Header ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="bbn-header">
  <div>
    <h1>🏀 Big Blue Nation</h1>
    <div class="subtitle">AI Game Analyst · Kentucky Wildcats Basketball</div>
  </div>
</div>
""", unsafe_allow_html=True)


# ── Main content ───────────────────────────────────────────────────────────────
tab_game, tab_players, tab_models = st.tabs(
    ["🏀 Game Predictions", "👥 Player Predictions", "📊 Model Insights"]
)
if 'result' not in st.session_state:
    st.session_state.result = None

if run_btn or st.session_state.result is None:
    with st.spinner("Running prediction models..."):
        try:
            engine = load_engine()
            result = engine.predict_game(
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

    with col_uk:
        st.markdown(f"""
        <div class="score-display">
            <div class="score-team">Kentucky Wildcats</div>
            <div class="score-pts" style="color:#4a90d9">{result['uk_score']}</div>
            <div style="font-size:0.78rem;color:#5a7aa8;margin-top:0.3rem">{venue_str}</div>
            </div>
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


    def build_df(players):
        rows = []
        for p in players:
            dot, must_do = get_status_emoji(p['name'], p['points'], p['rebounds'], p['assists'])
            rows.append({
                'Status': dot,
                'Player': p['name'],
                'PTS':    p['points'],
                'REB':    p['rebounds'],
                'AST':    p['assists'],
                'MIN':    p['minutes'],
                'Must Do': must_do,
            })
        return pd.DataFrame(rows)


    st.caption("STARTERS")
    st.dataframe(
        build_df(starters),
        use_container_width=True,
        hide_index=True,
        column_config={
            'Status': st.column_config.TextColumn(width='small'),
            'Player': st.column_config.TextColumn(width='medium'),
            'PTS':    st.column_config.NumberColumn(format="%.1f", width='small'),
            'REB':    st.column_config.NumberColumn(format="%.1f", width='small'),
            'AST':    st.column_config.NumberColumn(format="%.1f", width='small'),
            'MIN':    st.column_config.NumberColumn(format="%.1f", width='small'),
            'Must Do':st.column_config.TextColumn(width='large'),
        }
    )

    st.caption("BENCH")
    st.dataframe(
        build_df(bench),
        use_container_width=True,
        hide_index=True,
        column_config={
            'Status': st.column_config.TextColumn(width='small'),
            'Player': st.column_config.TextColumn(width='medium'),
            'PTS':    st.column_config.NumberColumn(format="%.1f", width='small'),
            'REB':    st.column_config.NumberColumn(format="%.1f", width='small'),
            'AST':    st.column_config.NumberColumn(format="%.1f", width='small'),
            'MIN':    st.column_config.NumberColumn(format="%.1f", width='small'),
            'Must Do':st.column_config.TextColumn(width='large'),
        }
    )

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


# ── SHAP Plot + Model Accuracy ─────────────────────────────────────────────────
with tab_models:
    col_shap, col_val = st.columns([1.2, 1])

    with col_shap:
        st.markdown('<div class="section-title">Feature Importance (SHAP)</div>',
                unsafe_allow_html=True)
        if os.path.exists(SHAP_PATH):
            img = Image.open(SHAP_PATH)
            st.image(img, use_container_width=True)
        else:
            st.info("SHAP plot not found. Run the notebook to generate it.")

    with col_val:
        st.markdown('<div class="section-title">Model Accuracy</div>',
                unsafe_allow_html=True)

        st.markdown("""
        <table class="val-table">
        <thead>
            <tr><th>Model</th><th>MAE</th><th>Baseline</th><th>Improvement</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>Player Points</td>
            <td>4.07 pts</td><td>5.85 pts</td>
            <td class="val-good">+1.78 pts</td>
          </tr>
          <tr>
            <td>Player Rebounds</td>
            <td>1.58 reb</td><td>2.00 reb</td>
            <td class="val-good">+0.42 reb</td>
          </tr>
          <tr>
            <td>Player Assists</td>
            <td>1.03 ast</td><td>1.36 ast</td>
            <td class="val-good">+0.33 ast</td>
          </tr>
          <tr>
            <td>Player Minutes</td>
            <td>4.1 min</td><td>9.1 min</td>
            <td class="val-good">+5.0 min</td>
          </tr>
          <tr>
            <td>Opponent Score</td>
            <td>6.3 pts</td><td>8.7 pts</td>
            <td class="val-good">+2.4 pts</td>
          </tr>
          <tr>
            <td>Win Probability</td>
            <td>78.5%</td><td>—</td>
            <td class="val-good">Accuracy</td>
          </tr>
        </tbody>
        </table>
        """, unsafe_allow_html=True)

        val_df = load_validation_data()
        if val_df is not None and len(val_df) > 0:
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Post-Game Validation</div>',
                    unsafe_allow_html=True)
            st.dataframe(val_df, use_container_width=True, hide_index=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;color:#2a3a5c;font-size:0.75rem;
            letter-spacing:0.08em;text-transform:uppercase;padding:0.5rem 0">
  Big Blue Nation AI Analyst · Built with XGBoost + Streamlit · Go Cats 🐾
</div>
""", unsafe_allow_html=True)
