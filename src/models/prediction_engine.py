"""
src/models/prediction_engine.py

Big Blue Nation AI Analyst — Production Prediction Engine
Packages all models and prediction logic from player_predictions.ipynb

Models:
  - model_v3:        XGBoost player points predictor (MAE: 4.07)
  - minutes_model:   XGBoost player minutes predictor (MAE: 4.1)
  - opp_model_v4:    XGBoost opponent scoring predictor (MAE: 6.3)
  - win_probability: Hybrid point-diff (60%) + BPI (40%) model

Usage:
  from src.models.prediction_engine import PredictionEngine
  engine = PredictionEngine()
  result = engine.predict_game(opponent='LSU Tigers', is_home=0, net_rank=120)
  print(result)
"""

import os
import sqlite3
import joblib
import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.preprocessing import LabelEncoder

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH    = os.path.join(BASE_DIR, 'data', 'processed', 'kentucky_basketball.db')
MODELS_DIR = os.path.join(BASE_DIR, 'data', 'models')


# ── Feature lists (must match training) ───────────────────────────────────────
FEATURE_COLS = [
    'points_roll3', 'points_roll5', 'points_season_avg',
    'rebounds_roll3', 'assists_roll3',
    'minutes_roll3', 'minutes_roll5',
    'fg_pct_roll3', 'fg_pct_roll5', 'three_pct_roll3',
    'turnovers_roll3', 'points_trend', 'minutes_trend',
    'is_home', 'game_number', 'starter',
    'is_current_season', 'season_segment',
    'days_rest', 'is_back_to_back',
    'opp_avg_points_allowed', 'opp_avg_rebounds', 'opp_avg_turnovers_forced',
    'player_encoded', 'position_encoded', 'opponent_encoded'
]

MINUTES_FEATURES = [
    'minutes_roll3', 'minutes_roll5', 'minutes_season_avg', 'minutes_trend',
    'starter', 'is_home', 'game_number', 'is_current_season', 'season_segment',
    'days_rest', 'is_back_to_back', 'player_encoded', 'position_encoded'
]

OPP_FEATURES = [
    'net_rank', 'uk_is_home',
    'opp_pts_roll3', 'opp_pts_roll5',
    'opp_fg_pct_roll3', 'opp_three_pct_roll3', 'opp_reb_roll3',
    'uk_def_roll3', 'uk_def_roll5', 'uk_def_season'
]

# Kentucky BPI (update each season)
UK_BPI = 16.6

# Current roster
CURRENT_ROSTER = [
    {'name': 'Otega Oweh',        'starter': 1, 'walk_on': False},
    {'name': 'Denzel Aberdeen',   'starter': 1, 'walk_on': False},
    {'name': 'Collin Chandler',   'starter': 1, 'walk_on': False},
    {'name': 'Malachi Moreno',    'starter': 1, 'walk_on': False},
    {'name': 'Andrija Jelavic',   'starter': 1, 'walk_on': False},
    {'name': 'Mouhamed Dioubate', 'starter': 0, 'walk_on': False},
    {'name': 'Trent Noah',        'starter': 0, 'walk_on': False},
    {'name': 'Brandon Garrison',  'starter': 0, 'walk_on': False},
    {'name': 'Jasper Johnson',    'starter': 0, 'walk_on': False},
    {'name': 'Walker Horn',       'starter': 0, 'walk_on': True},
    {'name': 'Zach Tow',          'starter': 0, 'walk_on': True},
]


class PredictionEngine:
    """
    Full prediction pipeline for Kentucky basketball games.
    Loads trained models and data, then generates game predictions.
    """

    def __init__(self):
        self.model_v3      = None
        self.minutes_model = None
        self.opp_model_v4  = None
        self.le_player     = None
        self.le_position   = None
        self.le_opponent   = None
        self.df_model      = None
        self.opp_model_df  = None
        self.reb_model = None
        self.ast_model = None
        self.thresholds = {}
        self._load_models()
        self._load_data()

    # ── Model loading ──────────────────────────────────────────────────────────

    def _load_models(self):
        """Load trained models and encoders from disk."""
        try:
            self.model_v3      = joblib.load(os.path.join(MODELS_DIR, 'model_v3.joblib'))
            self.minutes_model = joblib.load(os.path.join(MODELS_DIR, 'minutes_model.joblib'))
            self.opp_model_v4  = joblib.load(os.path.join(MODELS_DIR, 'opp_model_v4.joblib'))
            self.le_player     = joblib.load(os.path.join(MODELS_DIR, 'le_player.joblib'))
            self.le_position   = joblib.load(os.path.join(MODELS_DIR, 'le_position.joblib'))
            self.le_opponent   = joblib.load(os.path.join(MODELS_DIR, 'le_opponent.joblib'))
            self.reb_model = joblib.load(os.path.join(MODELS_DIR, 'reb_model.joblib'))
            self.ast_model = joblib.load(os.path.join(MODELS_DIR, 'ast_model.joblib'))
            print("✅ Models loaded from disk")
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Models not found. Run the notebook to train and save models first.\n{e}"
            )

    # ── Data loading ───────────────────────────────────────────────────────────
    def _load_data(self):
        """Load pre-computed features directly from database."""
        conn = sqlite3.connect(DB_PATH)

        # Load fully prepared player features — matches notebook exactly
        self.df_model = pd.read_sql(
            "SELECT * FROM player_model_features", conn
        )
        self.df_model['game_date'] = pd.to_datetime(self.df_model['game_date'])
        self.df_model = self.df_model.sort_values(['player_name', 'game_date'])

        # Load opponent game totals with rolling features
        self.opp_model_df = pd.read_sql(
            "SELECT * FROM opponent_game_totals", conn
        )
        self.opp_model_df['game_date'] = pd.to_datetime(self.opp_model_df['game_date'])

        # Player thresholds
        import json
        thresholds_raw = pd.read_sql("SELECT * FROM player_thresholds", conn)
        self.thresholds = {
            row['player_name']: json.loads(row['thresholds_json'])
            for _, row in thresholds_raw.iterrows()
        }

        conn.close()

        print(f"✅ Data loaded: {len(self.df_model)} player records, "
              f"{len(self.opp_model_df)} opponent games")


    # ── Core prediction methods ────────────────────────────────────────────────

    def predict_player(self, player_name, opponent, is_home, net_rank,
                       days_rest=3, is_back_to_back=0, starter=None,
                       season_segment=3):
        """
        Predict points for a single player using chained minutes → points pipeline.
        Returns dict with name, predicted_minutes, predicted_points.
        """
        player_data = self.df_model[
            self.df_model['player_name'] == player_name
        ].sort_values('game_date').tail(1)

        if len(player_data) == 0:
            return None

        row = player_data.iloc[0].copy()

        # Get opponent context
        opp_def = self.df_model[self.df_model['opponent'] == opponent][
            ['opp_avg_points_allowed', 'opp_avg_rebounds', 'opp_avg_turnovers_forced']
        ].mean()

        opp_allowed   = opp_def['opp_avg_points_allowed']   if not opp_def.isna().all() else 75.6
        opp_rebounds  = opp_def['opp_avg_rebounds']         if not opp_def.isna().all() else 31.3
        opp_turnovers = opp_def['opp_avg_turnovers_forced'] if not opp_def.isna().all() else 12.0

        try:
            opp_encoded = self.le_opponent.transform([opponent])[0]
        except ValueError:
            opp_encoded = 0  # unknown opponent fallback

        # Override context features
        row['is_home']                  = int(is_home)
        row['days_rest']                = days_rest
        row['is_back_to_back']          = int(is_back_to_back)
        row['season_segment']           = season_segment
        row['opponent_encoded']         = opp_encoded
        row['opp_avg_points_allowed']   = opp_allowed
        row['opp_avg_rebounds']         = opp_rebounds
        row['opp_avg_turnovers_forced'] = opp_turnovers

        if starter is not None:
            row['starter'] = int(starter)

        # Step 1 — predict minutes
        X_min = pd.DataFrame([row[MINUTES_FEATURES]])
        pred_minutes = max(0, float(self.minutes_model.predict(X_min)[0]))

        # Step 2 — update rolling minutes with predicted value
        row['minutes_roll3'] = (row['minutes_roll3'] * 2 + pred_minutes) / 3
        row['minutes_roll5'] = (row['minutes_roll5'] * 4 + pred_minutes) / 5

        # Step 3 — predict points
        X_pts = pd.DataFrame([row[FEATURE_COLS]])
        pred_points = max(0, float(self.model_v3.predict(X_pts)[0]))
        pred_rebounds = max(0, float(self.reb_model.predict(X_pts)[0]))
        pred_assists  = max(0, float(self.ast_model.predict(X_pts)[0]))

        return {
            'name':    player_name,
            'minutes': round(pred_minutes, 1),
            'points':  round(pred_points, 1),
            'rebounds': round(pred_rebounds, 1),
            'assists':  round(pred_assists, 1),
            'starter': int(row['starter']),
        }

    def predict_opponent_score(self, opponent, is_home, net_rank):
        """Predict how many points the opponent will score against Kentucky."""
    
        # Look up last game against this opponent in opp_game_totals
        opp_games = self.opp_model_df[
            self.opp_model_df['team'] == opponent
        ].sort_values('game_date')

        global_pts_mean   = self.opp_model_df['opp_team_points'].mean()
        global_fg_mean    = self.opp_model_df['opp_fg_pct'].mean()
        global_three_mean = self.opp_model_df['opp_three_pct'].mean()
        global_reb_mean   = self.opp_model_df['opp_team_rebounds'].mean()
        global_def_mean   = self.opp_model_df['uk_def_roll3'].mean()

        if len(opp_games) > 0:
            row = opp_games.iloc[-1]
            opp_pts_roll3 = row['opp_pts_roll3']   if pd.notna(row['opp_pts_roll3'])   else global_pts_mean
            opp_pts_roll5 = row['opp_pts_roll5']   if pd.notna(row['opp_pts_roll5'])   else global_pts_mean
            opp_fg_roll3  = row['opp_fg_pct_roll3']   if pd.notna(row['opp_fg_pct_roll3'])   else global_fg_mean
            opp_3pt_roll3 = row['opp_three_pct_roll3'] if pd.notna(row['opp_three_pct_roll3']) else global_three_mean
            opp_reb_roll3 = row['opp_reb_roll3']   if pd.notna(row['opp_reb_roll3'])   else global_reb_mean
            uk_def_roll3  = row['uk_def_roll3']    if pd.notna(row['uk_def_roll3'])    else global_def_mean
            uk_def_roll5  = row['uk_def_roll5']    if pd.notna(row['uk_def_roll5'])    else global_def_mean
            uk_def_season = row['uk_def_season']   if pd.notna(row['uk_def_season'])   else global_def_mean
        else:
            # New opponent — use global averages
            opp_pts_roll3 = global_pts_mean
            opp_pts_roll5 = global_pts_mean
            opp_fg_roll3  = global_fg_mean
            opp_3pt_roll3 = global_three_mean
            opp_reb_roll3 = global_reb_mean
            uk_def_roll3  = global_def_mean
            uk_def_roll5  = global_def_mean
            uk_def_season = global_def_mean

        opp_input = pd.DataFrame([{
            'net_rank':            net_rank,
            'uk_is_home':          int(is_home),
            'opp_pts_roll3':       opp_pts_roll3,
            'opp_pts_roll5':       opp_pts_roll5,
            'opp_fg_pct_roll3':    opp_fg_roll3,
            'opp_three_pct_roll3': opp_3pt_roll3,
            'opp_reb_roll3':       opp_reb_roll3,
            'uk_def_roll3':        uk_def_roll3,
            'uk_def_roll5':        uk_def_roll5,
            'uk_def_season':       uk_def_season,
        }])

        return round(float(self.opp_model_v4.predict(opp_input)[0]), 1)

    def predict_game(self, opponent, is_home, net_rank, opp_bpi=10.0,
                     injuries=None, days_rest=3, is_back_to_back=0,
                     roster=None):
        """
        Full game prediction pipeline.
        Returns complete prediction dict with player projections and win probability.
        """
        injuries = injuries or []
        roster   = roster or CURRENT_ROSTER

        # Filter out injured players
        active_roster = [p for p in roster if p['name'] not in injuries and not p.get('walk_on', False)]

        # Player projections
        projections = []
        for p in active_roster:
            result = self.predict_player(
                player_name    = p['name'],
                opponent       = opponent,
                is_home        = is_home,
                net_rank       = net_rank,
                days_rest      = days_rest,
                is_back_to_back= is_back_to_back,
                starter        = p['starter'],
            )
            if result:
                if p.get('walk_on'):
                    result['points']  = 0.5
                    result['minutes'] = 1.0
                projections.append(result)

        uk_score  = sum(p['points'] for p in projections)
        opp_score = self.predict_opponent_score(opponent, is_home, net_rank)

        # Win probability
        point_diff    = uk_score - opp_score
        diff_win_prob = float(expit(point_diff * 0.12))

        bpi_diff    = UK_BPI - opp_bpi
        bpi_win_prob = float(expit(bpi_diff * 0.15))
        if is_home:
            bpi_win_prob = min(0.97, bpi_win_prob + 0.08)
        bpi_win_prob = max(0.05, bpi_win_prob - len(injuries) * 0.035)

        win_prob = round(0.60 * diff_win_prob + 0.40 * bpi_win_prob, 3)


        # Display SHAP plot
        import subprocess
        shap_plot = os.path.join(BASE_DIR, 'notebooks', 'shap_summary_v3.png')
        if os.path.exists(shap_plot):
            subprocess.Popen(['open', shap_plot])  # macOS — opens in Preview

        return {
            'opponent':       opponent,
            'is_home':        is_home,
            'uk_score':       round(uk_score, 1),
            'opp_score':      round(opp_score, 1),
            'point_diff':     round(point_diff, 1),
            'win_probability':round(win_prob * 100, 1),
            'injuries':       injuries,
            'projections':    projections,
        }

    def get_threshold_status(self, player_name, pred_points, pred_rebounds, pred_assists):
        """Return threshold status icon and must-do string for a player."""
        if player_name not in self.thresholds:
            return '✅', 'Contribute positively'

        t = self.thresholds[player_name]
        requirements = []
        met = []

        for stat, info in t.items():
            thresh   = info.get('threshold')
            win_rate = info.get('win_pct_above', 0)
            n        = info.get('n_games_above', 0)
            if thresh is None or n < 4 or win_rate < 0.75:
                continue

            thresh = float(thresh)  # stored as string in JSON
            pred_val = {'points': pred_points, 'rebounds': pred_rebounds,
                        'assists': pred_assists}.get(stat, 0)
            requirements.append((stat, thresh, win_rate, n))
            met.append(pred_val >= thresh)

        if not requirements:
            return '✅', 'Contribute positively'

        must_do = ' & '.join(
            f"{s.capitalize()} {int(t)}+ ({int(w*100)}% win, n={n})"
            for s, t, w, n in requirements
        )
        if all(met):   status = '✅'
        elif any(met): status = '⚠️ '
        else:          status = '❌'

        return status, must_do

    def format_prediction(self, result):
        """Pretty print a game prediction with thresholds and team totals."""
        venue = 'Home' if result['is_home'] else 'Away'
        inj   = ', '.join(result['injuries']) if result['injuries'] else 'None'

        lines = [
            f"{'='*75}",
            f"🏀 KENTUCKY vs {result['opponent'].upper()} — PREDICTION",
            f"{'='*75}",
            f"  {venue} | Injuries: {inj}",
            f"",
            f"  WIN PROBABILITY: Kentucky {result['win_probability']}% | "
            f"{result['opponent']} {round(100 - result['win_probability'], 1)}%",
            f"  Projected score: Kentucky {result['uk_score']} — "
            f"{result['opponent']} {result['opp_score']}",
            f"  Point differential: {result['point_diff']:+.1f}",
            f"",
            f"  {'Player':<25} {'PTS':>5}  {'REB':>5}  {'AST':>5}  {'MIN':>5}  {'Status':<6}  Must Do",
            f"  {'-'*25} {'-'*5}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*30}",
        ]

        starters = [p for p in result['projections'] if p['starter']]
        bench    = [p for p in result['projections'] if not p['starter']]

        lines.append(f"\n  STARTERS:")
        for p in sorted(starters, key=lambda x: x['points'], reverse=True):
            status, must_do = self.get_threshold_status(
                p['name'], p['points'], p['rebounds'], p['assists']
            )
            lines.append(
                f"  {p['name']:<25} {p['points']:>5.1f}  {p['rebounds']:>5.1f}"
                f"  {p['assists']:>5.1f}  {p['minutes']:>5.1f}  {status:<6}  {must_do}"
            )

        lines.append(f"\n  BENCH:")
        for p in sorted(bench, key=lambda x: x['points'], reverse=True):
            status, must_do = self.get_threshold_status(
                p['name'], p['points'], p['rebounds'], p['assists']
            )
            lines.append(
                f"  {p['name']:<25} {p['points']:>5.1f}  {p['rebounds']:>5.1f}"
                f"  {p['assists']:>5.1f}  {p['minutes']:>5.1f}  {status:<6}  {must_do}"
            )

        # Team totals
        tot_pts = sum(p['points']   for p in result['projections'])
        tot_reb = sum(p['rebounds'] for p in result['projections'])
        tot_ast = sum(p['assists']  for p in result['projections'])
        tot_min = sum(p['minutes']  for p in result['projections'])
        lines.append(f"\n  {'TEAM TOTAL':<25} {tot_pts:>5.1f}  {tot_reb:>5.1f}  {tot_ast:>5.1f}  {tot_min:>5.1f}")
        lines.append(f"{'='*75}")

        return '\n'.join(lines)


# ── Save models helper (run once from notebook) ────────────────────────────────

def save_models(model_v3, minutes_model, opp_model_v4,
                le_player, le_position, le_opponent):
    """
    Call this from the notebook to save all trained models to disk.
    Only needs to be run once after training.
    """
    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(model_v3,       os.path.join(MODELS_DIR, 'model_v3.joblib'))
    joblib.dump(minutes_model,  os.path.join(MODELS_DIR, 'minutes_model.joblib'))
    joblib.dump(opp_model_v4,   os.path.join(MODELS_DIR, 'opp_model_v4.joblib'))
    joblib.dump(le_player,      os.path.join(MODELS_DIR, 'le_player.joblib'))
    joblib.dump(le_position,    os.path.join(MODELS_DIR, 'le_position.joblib'))
    joblib.dump(le_opponent,    os.path.join(MODELS_DIR, 'le_opponent.joblib'))
    print(f"✅ Models saved to {MODELS_DIR}")
    print(f"   model_v3.joblib")
    print(f"   minutes_model.joblib")
    print(f"   opp_model_v4.joblib")
    print(f"   le_player.joblib")
    print(f"   le_position.joblib")
    print(f"   le_opponent.joblib")


if __name__ == '__main__':
    engine = PredictionEngine()
    result = engine.predict_game(
        opponent  = 'LSU Tigers',
        is_home   = 0,
        net_rank  = 120,
        opp_bpi   = 10.0,
        injuries  = ['Jayden Quaintance', 'Jaland Lowe', 'Kam Williams']
    )
    print(engine.format_prediction(result))