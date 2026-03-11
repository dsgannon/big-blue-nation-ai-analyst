"""
src/models/prediction_engine.py

Big Blue Nation AI Analyst — Production Prediction Engine V2

Improvements over V1:
  - Temporal decay rolling averages (recent games weight more)
  - Hot/cold streak indicator
  - Injury-adjusted opponent score (uk_bpi_defense feature)
  - Logistic regression win probability (replaces hybrid fixed-weight model)
  - Falls back gracefully if win_prob_model not found

Models:
  - model_v3.joblib        XGBoost player points (trained in model_v2.ipynb)
  - minutes_model.joblib   XGBoost player minutes
  - reb_model.joblib       XGBoost player rebounds
  - ast_model.joblib       XGBoost player assists
  - opp_model_v4.joblib    XGBoost opponent scoring (injury-aware via BPI defense)
  - win_prob_model.joblib  Logistic regression win probability
  - win_prob_scaler.joblib StandardScaler for win prob features

Usage:
  from src.models.prediction_engine import PredictionEngine
  engine = PredictionEngine()
  result = engine.predict_game(opponent='LSU Tigers', is_home=0, net_rank=78)
"""

import os
import json
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


# ── Feature lists (must match training in model_v2.ipynb) ─────────────────────

# V2 player points/rebounds/assists features (includes decay + hot_streak)
FEATURE_COLS = [
    # Standard rolling
    'points_roll3', 'points_roll5', 'points_season_avg',
    'rebounds_roll3', 'assists_roll3',
    'minutes_roll3', 'minutes_roll5',
    'fg_pct_roll3', 'fg_pct_roll5', 'three_pct_roll3',
    'turnovers_roll3', 'points_trend', 'minutes_trend',
    # V2: temporal decay
    'points_decay3', 'points_decay5',
    'minutes_decay3', 'minutes_decay5',
    'rebounds_decay3', 'assists_decay3',
    # V2: hot/cold streak
    'hot_streak', 'usage_trend',
    # Context
    'is_home', 'game_number', 'starter',
    'is_current_season', 'season_segment',
    'days_rest', 'is_back_to_back',
    'opp_avg_points_allowed', 'opp_avg_rebounds', 'opp_avg_turnovers_forced',
    'player_encoded', 'position_encoded', 'opponent_encoded',
    # Chained minutes
    'predicted_minutes',
]

MINUTES_FEATURES = [
    'minutes_roll3', 'minutes_roll5', 'minutes_season_avg', 'minutes_trend',
    'minutes_decay3', 'minutes_decay5',
    'starter', 'is_home', 'game_number',
    'is_current_season', 'season_segment',
    'days_rest', 'is_back_to_back',
    'player_encoded', 'position_encoded',
]

OPP_FEATURES = [
    'uk_is_home',
    'opp_pts_roll3', 'opp_pts_roll5',
    'opp_fg_pct_roll3', 'opp_three_pct_roll3', 'opp_reb_roll3',
    'uk_def_roll3', 'uk_def_roll5', 'uk_def_season',
    'uk_bpi_defense',   # V2: injury-aware via Kentucky's current BPI defense
]

WIN_PROB_FEATURES = [
    'pts_diff', 'reb_diff',
    'uk_team_ast', 'uk_team_to', 'uk_team_fg_pct', 'uk_team_3pt_pct',
    'opp_pts_roll3', 'opp_fg_pct_roll3', 'uk_def_roll3',
    'uk_is_home',
]

# Kentucky constants (update each season from team_metrics table)
UK_BPI = 16.6


# Current roster (update each season)
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
    {'name': 'Kam Williams',      'starter': 0, 'walk_on': False},
    {'name': 'Jayden Quaintance', 'starter': 0, 'walk_on': False},
    {'name': 'Jaland Lowe',       'starter': 0, 'walk_on': False},
    {'name': 'Walker Horn',       'starter': 0, 'walk_on': True},
    {'name': 'Zach Tow',          'starter': 0, 'walk_on': True},
]


class PredictionEngine:
    """
    Full prediction pipeline for Kentucky basketball games.
    Loads trained models and data, generates game predictions.

    V2 improvements:
    - Temporal decay features (recent games weight more)
    - Hot/cold streak indicator
    - Injury-adjusted opponent score via UK BPI defense
    - Logistic regression win probability
    """

    def __init__(self):
        self.model_v3         = None
        self.minutes_model    = None
        self.opp_model_v4     = None
        self.reb_model        = None
        self.ast_model        = None
        self.win_prob_model   = None
        self.win_prob_scaler  = None
        self.le_player        = None
        self.le_position      = None
        self.le_opponent      = None
        self.df_model         = None
        self.opp_model_df     = None
        self.thresholds       = {}
        self.uk_bpi_defense   = 7.5   # fallback; loaded from DB
        self._load_models()
        self._load_data()

    # ── Model loading ──────────────────────────────────────────────────────────

    def _load_models(self):
        """Load trained models and encoders from disk."""
        try:
            self.model_v3      = joblib.load(os.path.join(MODELS_DIR, 'model_v3.joblib'))
            self.minutes_model = joblib.load(os.path.join(MODELS_DIR, 'minutes_model.joblib'))
            self.opp_model_v4  = joblib.load(os.path.join(MODELS_DIR, 'opp_model_v4.joblib'))
            self.reb_model     = joblib.load(os.path.join(MODELS_DIR, 'reb_model.joblib'))
            self.ast_model     = joblib.load(os.path.join(MODELS_DIR, 'ast_model.joblib'))
            self.le_player     = joblib.load(os.path.join(MODELS_DIR, 'le_player.joblib'))
            self.le_position   = joblib.load(os.path.join(MODELS_DIR, 'le_position.joblib'))
            self.le_opponent   = joblib.load(os.path.join(MODELS_DIR, 'le_opponent.joblib'))
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Models not found. Run model_v2.ipynb to train and save models first.\n{e}"
            )

        # Win prob model — optional (falls back to hybrid if not found)
        try:
            self.win_prob_model  = joblib.load(os.path.join(MODELS_DIR, 'win_prob_model.joblib'))
            self.win_prob_scaler = joblib.load(os.path.join(MODELS_DIR, 'win_prob_scaler.joblib'))
            self._win_prob_v2 = True
        except FileNotFoundError:
            self._win_prob_v2 = False

        print("✅ Models loaded from disk")

    # ── Data loading ───────────────────────────────────────────────────────────

    def _load_data(self):
        """Load pre-computed features from database."""
        conn = sqlite3.connect(DB_PATH)

        self.df_model = pd.read_sql("SELECT * FROM player_model_features", conn)
        self.df_model['game_date'] = pd.to_datetime(self.df_model['game_date'])
        self.df_model = self.df_model.sort_values(['player_name', 'game_date'])

        self.opp_model_df = pd.read_sql("SELECT * FROM opponent_game_totals", conn)
        self.opp_model_df['game_date'] = pd.to_datetime(self.opp_model_df['game_date'])

        # Load UK BPI defense from team_metrics (most recent)
        try:
            metrics = pd.read_sql(
                "SELECT bpi_defense FROM team_metrics ORDER BY date DESC LIMIT 1", conn
            )
            if len(metrics) > 0:
                self.uk_bpi_defense = float(metrics['bpi_defense'].iloc[0])
        except Exception:
            pass

        # Player thresholds
        thresholds_raw = pd.read_sql("SELECT * FROM player_thresholds", conn)
        self.thresholds = {
            row['player_name']: json.loads(row['thresholds_json'])
            for _, row in thresholds_raw.iterrows()
        }

        conn.close()
        print(f"✅ Data loaded: {len(self.df_model)} player records, "
              f"{len(self.opp_model_df)} opponent games")
        print(f"   UK BPI Defense: {self.uk_bpi_defense} | "
              f"Win prob model: {'V2 logistic' if self._win_prob_v2 else 'hybrid fallback'}")

    # ── Decay feature helpers ──────────────────────────────────────────────────

    def _decay3(self, series_vals):
        """3-game decay weighted average. Weights: [0.2, 0.3, 0.5]"""
        if len(series_vals) < 3:
            return np.mean(series_vals) if len(series_vals) > 0 else 0.0
        v = np.array(series_vals[-3:], dtype=float)
        return float(np.dot(v, [0.2, 0.3, 0.5]))

    def _decay5(self, series_vals):
        """5-game decay weighted average. Weights: [0.05, 0.10, 0.15, 0.30, 0.40]"""
        if len(series_vals) < 5:
            return np.mean(series_vals) if len(series_vals) > 0 else 0.0
        v = np.array(series_vals[-5:], dtype=float)
        return float(np.dot(v, [0.05, 0.10, 0.15, 0.30, 0.40]))

    def _get_decay_features(self, player_history):
        """Compute all decay features from a player's game history."""
        pts  = player_history['points'].tolist()
        mins = player_history['minutes'].tolist()
        reb  = player_history['rebounds'].tolist()
        ast  = player_history['assists'].tolist()

        pts_d3  = self._decay3(pts)
        pts_d5  = self._decay5(pts)
        min_d3  = self._decay3(mins)
        min_d5  = self._decay5(mins)
        reb_d3  = self._decay3(reb)
        ast_d3  = self._decay3(ast)

        # Hot/cold streak: +1 hot, -1 cold, 0 neutral
        pts_avg = np.mean(pts) if pts else 0
        hot_streak = 0
        if pts_avg > 0 and len(pts) >= 3:
            roll3_avg = np.mean(pts[-3:])
            if roll3_avg > pts_avg * 1.15:
                hot_streak = 1
            elif roll3_avg < pts_avg * 0.85:
                hot_streak = -1

        usage_trend = pts_d3 - pts_d5

        return {
            'points_decay3':  pts_d3,
            'points_decay5':  pts_d5,
            'minutes_decay3': min_d3,
            'minutes_decay5': min_d5,
            'rebounds_decay3': reb_d3,
            'assists_decay3':  ast_d3,
            'hot_streak':     hot_streak,
            'usage_trend':    usage_trend,
        }

    # ── Core prediction methods ────────────────────────────────────────────────

    # ── Confidence interval helpers ────────────────────────────────────────────

    def _stat_std(self, player_history, stat: str, n_games: int = 10) -> float:
        """
        Return the std dev of a player's last n_games for `stat`.
        Used to build prediction intervals without retraining.
        """
        vals = player_history[stat].dropna().tolist()
        if len(vals) < 2:
            return 0.0
        recent = vals[-n_games:]
        mean   = sum(recent) / len(recent)
        var    = sum((v - mean) ** 2 for v in recent) / len(recent)
        return var ** 0.5

    def predict_player_with_ci(self, player_name, opponent, is_home, net_rank,
                                days_rest=3, is_back_to_back=0, starter=None,
                                season_segment=3, z: float = 1.28) -> dict | None:
        """
        Predict player stats and include prediction interval bounds.

        The interval is  prediction ± z * rolling_std(last 10 games).
        Default z=1.28 gives ~80% coverage assuming roughly normal game-to-game
        variance. Use z=1.645 for 90% or z=1.96 for 95%.

        Returns the same dict as predict_player() with extra keys:
          points_lo,   points_hi
          rebounds_lo, rebounds_hi
          assists_lo,  assists_hi
          minutes_lo,  minutes_hi
          ci_z         (the z value used)
        """
        result = self.predict_player(
            player_name, opponent, is_home, net_rank,
            days_rest=days_rest, is_back_to_back=is_back_to_back,
            starter=starter, season_segment=season_segment,
        )
        if result is None:
            return None

        player_history = self.df_model[
            self.df_model['player_name'] == player_name
        ].sort_values('game_date')

        for stat in ['points', 'rebounds', 'assists', 'minutes']:
            std   = self._stat_std(player_history, stat)
            half  = round(z * std, 1)
            pred  = result[stat]
            result[f'{stat}_lo'] = round(max(0.0, pred - half), 1)
            result[f'{stat}_hi'] = round(pred + half, 1)

        result['ci_z'] = z
        return result

    def predict_game_with_ci(self, opponent, is_home, net_rank, opp_bpi=10.0,
                              injuries=None, days_rest=3, is_back_to_back=0,
                              roster=None, z: float = 1.28) -> dict:
        """
        Full game prediction with confidence intervals on every player projection.

        Returns the same dict as predict_game() but each projection in
        `projections` has _lo / _hi bounds on points, rebounds, assists, minutes.
        """
        injuries = injuries or []
        roster   = roster or CURRENT_ROSTER

        active_roster = [
            p for p in roster
            if p['name'] not in injuries and not p.get('walk_on', False)
        ]

        projections = []
        for p in active_roster:
            result = self.predict_player_with_ci(
                player_name     = p['name'],
                opponent        = opponent,
                is_home         = is_home,
                net_rank        = net_rank,
                days_rest       = days_rest,
                is_back_to_back = is_back_to_back,
                starter         = p['starter'],
                z               = z,
            )
            if result:
                projections.append(result)

        uk_score = sum(p['points'] for p in projections)

        injury_bpi_penalty   = len(injuries) * 0.4
        adjusted_bpi_defense = self.uk_bpi_defense + injury_bpi_penalty
        opp_score = self.predict_opponent_score(
            opponent, is_home, net_rank,
            uk_bpi_defense=adjusted_bpi_defense
        )

        opp_games = self.opp_model_df[
            self.opp_model_df['team'] == opponent
        ].sort_values('game_date')

        if len(opp_games) > 0:
            last = opp_games.iloc[-1]
            opp_pts_roll3    = last.get('opp_pts_roll3',    self.opp_model_df['opp_team_points'].mean())
            opp_fg_pct_roll3 = last.get('opp_fg_pct_roll3', self.opp_model_df['opp_fg_pct'].mean())
            uk_def_roll3     = last.get('uk_def_roll3',     self.opp_model_df['uk_def_roll3'].mean())
        else:
            opp_pts_roll3    = self.opp_model_df['opp_team_points'].mean()
            opp_fg_pct_roll3 = self.opp_model_df['opp_fg_pct'].mean()
            uk_def_roll3     = self.opp_model_df['uk_def_roll3'].mean()

        if self._win_prob_v2:
            win_prob = self._win_prob_logistic(
                projections, opp_score, is_home,
                opp_pts_roll3, opp_fg_pct_roll3, uk_def_roll3
            )
        else:
            win_prob = self._win_prob_hybrid(
                uk_score, opp_score, opp_bpi, is_home, injuries
            )

        point_diff = round(uk_score - opp_score, 1)

        return {
            'opponent':        opponent,
            'is_home':         is_home,
            'uk_score':        round(uk_score, 1),
            'opp_score':       round(opp_score, 1),
            'point_diff':      point_diff,
            'win_probability': round(win_prob * 100, 1),
            'injuries':        injuries,
            'projections':     projections,
            'ci_z':            z,
        }

    def predict_player(self, player_name, opponent, is_home, net_rank,
                       days_rest=3, is_back_to_back=0, starter=None,
                       season_segment=3):
        """
        Predict points/rebounds/assists/minutes for a single player.
        Uses chained minutes → stats pipeline with V2 decay features.
        """
        player_data = self.df_model[
            self.df_model['player_name'] == player_name
        ].sort_values('game_date')

        if len(player_data) == 0:
            return None

        row = player_data.iloc[-1].copy()

        # ── Compute V2 decay features from full history ────────────────────────
        decay_feats = self._get_decay_features(player_data)
        for k, v in decay_feats.items():
            row[k] = v

        # Fill V2 features if missing from DB (old data pre-V2 training)
        for col in ['points_decay3', 'points_decay5', 'minutes_decay3',
                    'minutes_decay5', 'rebounds_decay3', 'assists_decay3',
                    'hot_streak', 'usage_trend']:
            if col not in row or pd.isna(row.get(col)):
                row[col] = decay_feats.get(col, 0.0)

        # ── Opponent defensive context ─────────────────────────────────────────
        opp_def = self.df_model[self.df_model['opponent'] == opponent][
            ['opp_avg_points_allowed', 'opp_avg_rebounds', 'opp_avg_turnovers_forced']
        ].mean()

        row['opp_avg_points_allowed']   = opp_def['opp_avg_points_allowed']   if not opp_def.isna().all() else 75.6
        row['opp_avg_rebounds']         = opp_def['opp_avg_rebounds']         if not opp_def.isna().all() else 31.3
        row['opp_avg_turnovers_forced'] = opp_def['opp_avg_turnovers_forced'] if not opp_def.isna().all() else 12.0

        try:
            row['opponent_encoded'] = self.le_opponent.transform([opponent])[0]
        except ValueError:
            row['opponent_encoded'] = 0

        # ── Override context features ──────────────────────────────────────────
        row['is_home']         = int(is_home)
        row['days_rest']       = days_rest
        row['is_back_to_back'] = int(is_back_to_back)
        row['season_segment']  = season_segment
        if starter is not None:
            row['starter'] = int(starter)

        # ── Step 1: Predict minutes ────────────────────────────────────────────
        X_min = pd.DataFrame([row[MINUTES_FEATURES]])
        pred_minutes = max(0.0, float(self.minutes_model.predict(X_min)[0]))

        # ── Step 2: Update rolling minutes with predicted value ────────────────
        row['minutes_roll3'] = (row['minutes_roll3'] * 2 + pred_minutes) / 3
        row['minutes_roll5'] = (row['minutes_roll5'] * 4 + pred_minutes) / 5
        row['predicted_minutes'] = pred_minutes

        # ── Step 3: Predict points/rebounds/assists ────────────────────────────
        X_pts = pd.DataFrame([row[FEATURE_COLS]])
        pred_points   = max(0.0, float(self.model_v3.predict(X_pts)[0]))
        pred_rebounds = max(0.0, float(self.reb_model.predict(X_pts)[0]))
        pred_assists  = max(0.0, float(self.ast_model.predict(X_pts)[0]))

        return {
            'name':     player_name,
            'minutes':  round(pred_minutes, 1),
            'points':   round(pred_points, 1),
            'rebounds': round(pred_rebounds, 1),
            'assists':  round(pred_assists, 1),
            'starter':  int(row['starter']),
        }

    def predict_opponent_score(self, opponent, is_home, net_rank,
                                uk_bpi_defense=None):
        """
        Predict opponent score. V2 adds uk_bpi_defense so the model
        reacts to Kentucky's current defensive strength (and implicitly
        to injuries — weaker defense = higher BPI defense number = more pts allowed).
        """
        if uk_bpi_defense is None:
            uk_bpi_defense = self.uk_bpi_defense

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
            opp_pts_roll3 = row['opp_pts_roll3']      if pd.notna(row['opp_pts_roll3'])      else global_pts_mean
            opp_pts_roll5 = row['opp_pts_roll5']      if pd.notna(row['opp_pts_roll5'])      else global_pts_mean
            opp_fg_roll3  = row['opp_fg_pct_roll3']   if pd.notna(row['opp_fg_pct_roll3'])   else global_fg_mean
            opp_3pt_roll3 = row['opp_three_pct_roll3']if pd.notna(row['opp_three_pct_roll3'])else global_three_mean
            opp_reb_roll3 = row['opp_reb_roll3']      if pd.notna(row['opp_reb_roll3'])      else global_reb_mean
            uk_def_roll3  = row['uk_def_roll3']       if pd.notna(row['uk_def_roll3'])       else global_def_mean
            uk_def_roll5  = row['uk_def_roll5']       if pd.notna(row['uk_def_roll5'])       else global_def_mean
            uk_def_season = row['uk_def_season']      if pd.notna(row['uk_def_season'])      else global_def_mean
        else:
            opp_pts_roll3 = global_pts_mean
            opp_pts_roll5 = global_pts_mean
            opp_fg_roll3  = global_fg_mean
            opp_3pt_roll3 = global_three_mean
            opp_reb_roll3 = global_reb_mean
            uk_def_roll3  = global_def_mean
            uk_def_roll5  = global_def_mean
            uk_def_season = global_def_mean

        opp_input = pd.DataFrame([{
            'uk_is_home':          int(is_home),
            'opp_pts_roll3':       opp_pts_roll3,
            'opp_pts_roll5':       opp_pts_roll5,
            'opp_fg_pct_roll3':    opp_fg_roll3,
            'opp_three_pct_roll3': opp_3pt_roll3,
            'opp_reb_roll3':       opp_reb_roll3,
            'uk_def_roll3':        uk_def_roll3,
            'uk_def_roll5':        uk_def_roll5,
            'uk_def_season':       uk_def_season,
            'uk_bpi_defense':      uk_bpi_defense,
        }])

        # Handle old model that doesn't have uk_bpi_defense feature
        try:
            return round(float(self.opp_model_v4.predict(opp_input)[0]), 1)
        except Exception:
            # Fallback: drop the new feature for old model
            opp_input_old = opp_input.drop(columns=['uk_bpi_defense'])
            return round(float(self.opp_model_v4.predict(opp_input_old)[0]), 1)

    def _win_prob_logistic(self, projections, opp_score, is_home,
                            opp_pts_roll3, opp_fg_pct_roll3, uk_def_roll3):
        """
        V2 win probability using trained logistic regression.
        Falls back to hybrid model if win_prob_model not available.
        """
        uk_pts   = sum(p['points']   for p in projections)
        uk_reb   = sum(p['rebounds'] for p in projections)
        uk_ast   = sum(p['assists']  for p in projections)
        uk_to    = 12.0  # season average fallback
        uk_fg    = 0.46  # season average fallback
        uk_3pt   = 0.34  # season average fallback

        pts_diff = uk_pts - opp_score
        reb_diff = uk_reb - 31.0   # opponent average rebounds

        features = pd.DataFrame([{
            'pts_diff':        pts_diff,
            'reb_diff':        reb_diff,
            'uk_team_ast':     uk_ast,
            'uk_team_to':      uk_to,
            'uk_team_fg_pct':  uk_fg,
            'uk_team_3pt_pct': uk_3pt,
            'opp_pts_roll3':   opp_pts_roll3,
            'opp_fg_pct_roll3':opp_fg_pct_roll3,
            'uk_def_roll3':    uk_def_roll3,
            'uk_is_home':      int(is_home),
        }])

        X_scaled = self.win_prob_scaler.transform(features)
        prob = float(self.win_prob_model.predict_proba(X_scaled)[0][1])
        return round(prob, 3)

    def _win_prob_hybrid(self, uk_score, opp_score, opp_bpi, is_home, injuries):
        """
        Fallback hybrid win probability (V1 method).
        Used if logistic regression model not available.
        """
        point_diff   = uk_score - opp_score
        diff_win_prob = float(expit(point_diff * 0.12))

        bpi_diff     = UK_BPI - opp_bpi
        bpi_win_prob = float(expit(bpi_diff * 0.15))
        if is_home:
            bpi_win_prob = min(0.97, bpi_win_prob + 0.08)
        bpi_win_prob = max(0.05, bpi_win_prob - len(injuries) * 0.035)

        return round(0.60 * diff_win_prob + 0.40 * bpi_win_prob, 3)

    def predict_game(self, opponent, is_home, net_rank, opp_bpi=10.0,
                     injuries=None, days_rest=3, is_back_to_back=0,
                     roster=None):
        """
        Full game prediction pipeline.
        Returns complete prediction dict with player projections and win probability.
        """
        injuries = injuries or []
        roster   = roster or CURRENT_ROSTER

        # Filter out injured and walk-on players
        active_roster = [
            p for p in roster
            if p['name'] not in injuries and not p.get('walk_on', False)
        ]

        # ── Player projections ─────────────────────────────────────────────────
        projections = []
        for p in active_roster:
            result = self.predict_player(
                player_name     = p['name'],
                opponent        = opponent,
                is_home         = is_home,
                net_rank        = net_rank,
                days_rest       = days_rest,
                is_back_to_back = is_back_to_back,
                starter         = p['starter'],
            )
            if result:
                projections.append(result)

        uk_score = sum(p['points'] for p in projections)

        # ── Opponent score — injury-adjusted via BPI defense ───────────────────
        # Injury penalty: each missing non-walk-on increases effective BPI defense
        # (higher BPI defense = weaker defense = more pts allowed)
        injury_bpi_penalty = len(injuries) * 0.4
        adjusted_bpi_defense = self.uk_bpi_defense + injury_bpi_penalty
        opp_score = self.predict_opponent_score(
            opponent, is_home, net_rank,
            uk_bpi_defense=adjusted_bpi_defense
        )

        # ── Win probability ────────────────────────────────────────────────────
        # Get opponent rolling stats for logistic model
        opp_games = self.opp_model_df[
            self.opp_model_df['team'] == opponent
        ].sort_values('game_date')

        if len(opp_games) > 0:
            last = opp_games.iloc[-1]
            opp_pts_roll3    = last.get('opp_pts_roll3',    self.opp_model_df['opp_team_points'].mean())
            opp_fg_pct_roll3 = last.get('opp_fg_pct_roll3', self.opp_model_df['opp_fg_pct'].mean())
            uk_def_roll3     = last.get('uk_def_roll3',     self.opp_model_df['uk_def_roll3'].mean())
        else:
            opp_pts_roll3    = self.opp_model_df['opp_team_points'].mean()
            opp_fg_pct_roll3 = self.opp_model_df['opp_fg_pct'].mean()
            uk_def_roll3     = self.opp_model_df['uk_def_roll3'].mean()

        if self._win_prob_v2:
            win_prob = self._win_prob_logistic(
                projections, opp_score, is_home,
                opp_pts_roll3, opp_fg_pct_roll3, uk_def_roll3
            )
        else:
            win_prob = self._win_prob_hybrid(
                uk_score, opp_score, opp_bpi, is_home, injuries
            )

        point_diff = round(uk_score - opp_score, 1)

        return {
            'opponent':        opponent,
            'is_home':         is_home,
            'uk_score':        round(uk_score, 1),
            'opp_score':       round(opp_score, 1),
            'point_diff':      point_diff,
            'win_probability': round(win_prob * 100, 1),
            'injuries':        injuries,
            'projections':     projections,
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

            thresh   = float(thresh)
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

        tot_pts = sum(p['points']   for p in result['projections'])
        tot_reb = sum(p['rebounds'] for p in result['projections'])
        tot_ast = sum(p['assists']  for p in result['projections'])
        tot_min = sum(p['minutes']  for p in result['projections'])
        lines.append(
            f"\n  {'TEAM TOTAL':<25} {tot_pts:>5.1f}  {tot_reb:>5.1f}"
            f"  {tot_ast:>5.1f}  {tot_min:>5.1f}"
        )
        lines.append(f"{'='*75}")

        return '\n'.join(lines)


# ── Save models helper (called from notebook) ──────────────────────────────────

def save_models(model_v3, minutes_model, opp_model_v4,
                le_player, le_position, le_opponent,
                reb_model=None, ast_model=None,
                win_prob_model=None, win_prob_scaler=None):
    """Save all trained models to disk."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    joblib.dump(model_v3,      os.path.join(MODELS_DIR, 'model_v3.joblib'))
    joblib.dump(minutes_model, os.path.join(MODELS_DIR, 'minutes_model.joblib'))
    #joblib.dump(opp_model_v4,  os.path.join(MODELS_DIR, 'opp_model_v4.joblib'))
    joblib.dump(le_player,     os.path.join(MODELS_DIR, 'le_player.joblib'))
    joblib.dump(le_position,   os.path.join(MODELS_DIR, 'le_position.joblib'))
    joblib.dump(le_opponent,   os.path.join(MODELS_DIR, 'le_opponent.joblib'))
    if reb_model:
        joblib.dump(reb_model, os.path.join(MODELS_DIR, 'reb_model.joblib'))
    if ast_model:
        joblib.dump(ast_model, os.path.join(MODELS_DIR, 'ast_model.joblib'))
    if win_prob_model:
        joblib.dump(win_prob_model,  os.path.join(MODELS_DIR, 'win_prob_model.joblib'))
    if win_prob_scaler:
        joblib.dump(win_prob_scaler, os.path.join(MODELS_DIR, 'win_prob_scaler.joblib'))
    print(f"✅ Models saved to {MODELS_DIR}")


if __name__ == '__main__':
    engine = PredictionEngine()
    result = engine.predict_game(
        opponent  = 'LSU Tigers',
        is_home   = 0,
        net_rank  = 78,
        opp_bpi   = 10.0,
        injuries  = ['Jayden Quaintance', 'Jaland Lowe', 'Kam Williams']
    )
    print(engine.format_prediction(result))
