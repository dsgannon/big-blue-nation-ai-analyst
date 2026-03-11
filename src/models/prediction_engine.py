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
    'net_rank',
    'uk_is_home',
    'opp_pts_roll3', 'opp_pts_roll5',
    'opp_fg_pct_roll3', 'opp_three_pct_roll3', 'opp_reb_roll3',
    'uk_def_roll3', 'uk_def_roll5', 'uk_def_season',
    'uk_bpi_defense',   # V2: injury-aware via Kentucky's current BPI defense
]

WIN_PROB_FEATURES = ['pts_diff', 'uk_is_home', 'neutral_site']

# ── V3 feature lists — active after retraining with usage_rate + sos ──────────
# usage_rate_roll3: player's share of possessions used (proxy for role/load)
# sos_roll5:        rolling avg opp defensive quality (higher = weaker defenses faced)
FEATURE_COLS_V3 = [
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
    # V3: usage rate + strength of schedule
    'usage_rate_roll3', 'sos_roll5',
    # Context
    'is_home', 'game_number', 'starter',
    'is_current_season', 'season_segment',
    'days_rest', 'is_back_to_back',
    'opp_avg_points_allowed', 'opp_avg_rebounds', 'opp_avg_turnovers_forced',
    'player_encoded', 'position_encoded', 'opponent_encoded',
    # Chained minutes
    'predicted_minutes',
]

MINUTES_FEATURES_V3 = [
    'minutes_roll3', 'minutes_roll5', 'minutes_season_avg', 'minutes_trend',
    'minutes_decay3', 'minutes_decay5',
    'usage_rate_roll3', 'sos_roll5',
    'starter', 'is_home', 'game_number',
    'is_current_season', 'season_segment',
    'days_rest', 'is_back_to_back',
    'player_encoded', 'position_encoded',
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
        self.model_G          = None
        self.model_FC         = None
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
        self.game_stats_df = self._compute_game_stats()

    # ── Model loading ──────────────────────────────────────────────────────────

    def _load_models(self):
        """Load trained models and encoders from disk."""
        try:
            self.model_v3      = joblib.load(os.path.join(MODELS_DIR, 'model_v3.joblib'))
            try:
                self.model_G  = joblib.load(os.path.join(MODELS_DIR, 'model_G.joblib'))
                self.model_FC = joblib.load(os.path.join(MODELS_DIR, 'model_FC.joblib'))
                print("✅ Position-specific models loaded (G, FC)")
            except Exception:
                self.model_G  = self.model_v3
                self.model_FC = self.model_v3
                print("⚠️  Position-specific models not found, using combined model")
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

        # Load feature columns directly from model artifacts (source of truth)
        try:
            with open(os.path.join(MODELS_DIR, 'feature_meta_v2.json')) as f:
                meta = json.load(f)
            self._feature_cols  = meta['FEATURE_COLS_V2']
            self._minutes_cols  = meta['MINUTES_FEATURES_V2']
            self._feature_version = 'v6'
        except Exception:
            # Fallback: detect from model feature names
            try:
                trained_features = self.model_v3.get_booster().feature_names or []
                if 'usage_rate_roll3' in trained_features:
                    self._feature_version = 'v3'
                    self._feature_cols    = FEATURE_COLS_V3
                    self._minutes_cols    = MINUTES_FEATURES_V3
                else:
                    self._feature_version = 'v2'
                    self._feature_cols    = FEATURE_COLS
                    self._minutes_cols    = MINUTES_FEATURES
            except Exception:
                self._feature_version = 'v2'
                self._feature_cols    = FEATURE_COLS
                self._minutes_cols    = MINUTES_FEATURES

        print(f"✅ Models loaded from disk (feature version: {self._feature_version})")

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

        # V8: season trajectory — rolling win rate over last 10 games
        try:
            games_raw = pd.read_sql("""
                SELECT id as game_id, home_team, home_score, away_score, date as game_date
                FROM games WHERE home_score IS NOT NULL AND away_score IS NOT NULL
                ORDER BY date
            """, conn)
            games_raw['home_score'] = pd.to_numeric(games_raw['home_score'], errors='coerce')
            games_raw['away_score'] = pd.to_numeric(games_raw['away_score'], errors='coerce')
            games_raw['uk_won'] = (
                ((games_raw['home_team'] == 'Kentucky Wildcats') & (games_raw['home_score'] > games_raw['away_score'])) |
                ((games_raw['home_team'] != 'Kentucky Wildcats') & (games_raw['away_score'] > games_raw['home_score']))
            ).astype(int)
            win_series = games_raw['uk_won'].shift(1).rolling(10, min_periods=5).mean().fillna(0.5)
            self._uk_win_rate_roll10 = float(win_series.iloc[-1]) if len(win_series) > 0 else 0.5
        except Exception:
            self._uk_win_rate_roll10 = 0.5

        conn.close()
        print(f"✅ Data loaded: {len(self.df_model)} player records, "
              f"{len(self.opp_model_df)} opponent games")
        print(f"   UK BPI Defense: {self.uk_bpi_defense} | "
              f"Win prob model: {'V2 logistic' if self._win_prob_v2 else 'hybrid fallback'}")

    # ── V6 game-level stats ────────────────────────────────────────────────────

    def _compute_game_stats(self):
        """Compute per-game UK totals for pace and efficiency features."""
        if self.df_model is None or len(self.df_model) == 0:
            return pd.DataFrame()
        # df_model has per-player rows; we need to aggregate to game level
        # Use columns that should exist in player_model_features
        agg_cols = {}
        for col in ['fg_att', 'off_rebounds', 'turnovers', 'ft_att', 'three_made', 'three_att']:
            if col in self.df_model.columns:
                agg_cols[col] = 'sum'
        if not agg_cols:
            return pd.DataFrame()

        game_poss = self.df_model.groupby('game_id').agg(
            **{f'uk_{k}': (k, v) for k, v in agg_cols.items()},
            game_date=('game_date', 'first'),
        ).reset_index()

        # Possessions formula
        fg  = game_poss.get('uk_fg_att',      pd.Series(0, index=game_poss.index))
        orb = game_poss.get('uk_off_rebounds', pd.Series(0, index=game_poss.index))
        tov = game_poss.get('uk_turnovers',    pd.Series(0, index=game_poss.index))
        fta = game_poss.get('uk_ft_att',       pd.Series(0, index=game_poss.index))
        game_poss['uk_possessions'] = (fg - orb + tov + 0.44 * fta).clip(lower=55)

        # Team 3PT%
        three_made = game_poss.get('uk_three_made', pd.Series(0, index=game_poss.index))
        three_att  = game_poss.get('uk_three_att',  pd.Series(1, index=game_poss.index))
        game_poss['uk_team_3pt'] = three_made / three_att.clip(lower=1)

        # UK score from summed points; opp score from opp_model_df
        uk_scores = self.df_model.groupby('game_id')['points'].sum().reset_index().rename(columns={'points': 'uk_score'})
        game_poss = game_poss.merge(uk_scores, on='game_id', how='left')

        if hasattr(self, 'opp_model_df') and len(self.opp_model_df) > 0:
            opp_scores = self.opp_model_df[['game_id', 'opp_team_points']].copy()
            game_poss = game_poss.merge(opp_scores, on='game_id', how='left')
            game_poss['uk_off_eff'] = (game_poss['uk_score'] / game_poss['uk_possessions'] * 100).clip(60, 140)
            game_poss['uk_def_eff'] = (game_poss['opp_team_points'] / game_poss['uk_possessions'] * 100).clip(60, 140)
        else:
            game_poss['uk_off_eff'] = 105.0
            game_poss['uk_def_eff'] = 95.0

        return game_poss.sort_values('game_date')

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

    # ── V3 feature helpers ─────────────────────────────────────────────────────

    def _compute_usage_rate(self, player_history, n: int = 3) -> float:
        """
        Simplified usage rate proxy: possessions used per minute.
          usage = (fg_att + 0.44 * ft_att + turnovers) / minutes
        Returns rolling mean over the last n games.
        """
        rates = []
        for _, row in player_history.tail(n + 1).head(n).iterrows():  # last n (shifted)
            mins = float(row.get('minutes', 0))
            if mins < 1:
                continue
            fg_att = float(row.get('fg_att', 0))
            ft_att = float(row.get('ft_att', 0))
            tov    = float(row.get('turnovers', 0))
            rates.append((fg_att + 0.44 * ft_att + tov) / mins)
        return float(np.mean(rates)) if rates else 0.0

    def _compute_sos(self, player_history, n: int = 5) -> float:
        """
        Strength of schedule proxy: rolling mean of opp_avg_points_allowed
        for the last n games. Higher value = weaker defenses faced recently
        (player has had an easier schedule).
        """
        vals = player_history['opp_avg_points_allowed'].dropna().tolist()
        recent = vals[-n:] if len(vals) >= n else vals
        return float(np.mean(recent)) if recent else 75.6

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

        # ── Injury minutes redistribution ──────────────────────────────────────
        minutes_scale = 1.0
        if injuries:
            injured_avg_mins = 0.0
            active_avg_mins  = 0.0
            for p in roster:
                if p.get('walk_on'):
                    continue
                hist = self.df_model[self.df_model['player_name'] == p['name']]
                avg_min = float(hist['minutes'].tail(5).mean()) if len(hist) > 0 else 0.0
                if p['name'] in injuries:
                    injured_avg_mins += avg_min
                else:
                    active_avg_mins += avg_min
            if active_avg_mins > 0 and injured_avg_mins > 0:
                minutes_scale = min(1.35, (active_avg_mins + injured_avg_mins) / active_avg_mins)

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
                # Apply minutes scale to CI prediction's minutes output
                if minutes_scale != 1.0:
                    result['minutes']    = min(40.0, round(result['minutes'] * minutes_scale, 1))
                    result['minutes_lo'] = min(40.0, round(result.get('minutes_lo', result['minutes']) * minutes_scale, 1))
                    result['minutes_hi'] = min(40.0, round(result.get('minutes_hi', result['minutes']) * minutes_scale, 1))
                projections.append(result)

        uk_score = sum(p['points'] for p in projections)

        injury_bpi_penalty   = len(injuries) * 0.4
        adjusted_bpi_defense = self.uk_bpi_defense + injury_bpi_penalty
        opp_score = self.predict_opponent_score(
            opponent, is_home, net_rank,
            uk_bpi_defense=adjusted_bpi_defense,
            opp_bpi=opp_bpi,
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
                       season_segment=3, minutes_scale=1.0):
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

        # ── Compute V3 features ────────────────────────────────────────────────
        row['usage_rate_roll3'] = self._compute_usage_rate(player_data, n=3)
        row['sos_roll5']        = self._compute_sos(player_data, n=5)

        # ── Compute V4/V5 features ─────────────────────────────────────────────
        recent5 = player_data.tail(5)
        recent3 = player_data.tail(3)

        # ft_rate_roll3: free throw attempt rate (FTA/FGA) rolling 3
        ft_rate = (recent3['ft_att'] / recent3['fg_att'].clip(lower=1)).mean()
        row['ft_rate_roll3'] = ft_rate if pd.notna(ft_rate) else 0.3

        # pts_per_min_roll5: efficiency per minute rolling 5
        ppm = (recent5['points'] / recent5['minutes'].clip(lower=1)).mean()
        row['pts_per_min_roll5'] = ppm if pd.notna(ppm) else 0.5

        # role_stability: std of minutes over last 5 games
        row['role_stability'] = float(recent5['minutes'].std()) if len(recent5) >= 3 else 5.0

        # cumulative_minutes_last3: fatigue index
        row['cumulative_minutes_last3'] = float(recent3['minutes'].sum()) if len(recent3) >= 1 else 60.0

        # home_away_delta: player's career home avg minus away avg
        home_pts = player_data[player_data['home_away'] == 'home']['points'].mean()
        away_pts = player_data[player_data['home_away'] == 'away']['points'].mean()
        row['home_away_delta'] = float(home_pts - away_pts) if pd.notna(home_pts) and pd.notna(away_pts) else 0.0

        # neutral_site: passed via is_home context (0 = away or neutral)
        row['neutral_site'] = 0  # default; can be overridden externally

        # conf_game: SEC conference opponent
        SEC_TEAMS = {
            'Alabama Crimson Tide', 'Arkansas Razorbacks', 'Auburn Tigers',
            'Florida Gators', 'Georgia Bulldogs', 'LSU Tigers',
            'Mississippi State Bulldogs', 'Missouri Tigers', 'Ole Miss Rebels',
            'South Carolina Gamecocks', 'Tennessee Volunteers', 'Texas A&M Aggies',
            'Texas Longhorns', 'Vanderbilt Commodores', 'Oklahoma Sooners'
        }
        row['conf_game'] = int(opponent in SEC_TEAMS)

        # ── V6: pace, efficiency, team 3PT% ───────────────────────────────────
        if hasattr(self, 'game_stats_df') and len(self.game_stats_df) > 0:
            gs = self.game_stats_df.tail(5)
            row['uk_possessions_roll3'] = float(gs['uk_possessions'].tail(3).mean()) if len(gs) >= 1 else 70.0
            row['uk_off_eff_roll5']     = float(gs['uk_off_eff'].mean())              if len(gs) >= 1 else 105.0
            row['uk_def_eff_roll5']     = float(gs['uk_def_eff'].mean())              if len(gs) >= 1 else 95.0
            row['uk_team_3pt_roll3']    = float(gs['uk_team_3pt'].tail(3).mean())    if len(gs) >= 1 else 0.33
        else:
            row['uk_possessions_roll3'] = 70.0
            row['uk_off_eff_roll5']     = 105.0
            row['uk_def_eff_roll5']     = 95.0
            row['uk_team_3pt_roll3']    = 0.33

        # ── V7: opponent defensive matchup quality ─────────────────────────────
        opp_hist = self.df_model[self.df_model['opponent'] == opponent]
        if len(opp_hist) > 0 and 'uk_fg_pct_vs_opp_hist' in opp_hist.columns:
            row['uk_fg_pct_vs_opp_hist']    = float(opp_hist['uk_fg_pct_vs_opp_hist'].iloc[0])
            row['uk_three_pct_vs_opp_hist'] = float(opp_hist['uk_three_pct_vs_opp_hist'].iloc[0])
        else:
            row['uk_fg_pct_vs_opp_hist']    = float(self.df_model['uk_fg_pct_vs_opp_hist'].mean()) if 'uk_fg_pct_vs_opp_hist' in self.df_model.columns else 0.45
            row['uk_three_pct_vs_opp_hist'] = float(self.df_model['uk_three_pct_vs_opp_hist'].mean()) if 'uk_three_pct_vs_opp_hist' in self.df_model.columns else 0.33

        # steals_roll3: already in player_model_features if refreshed; fallback
        if 'steals_roll3' not in row or pd.isna(row.get('steals_roll3')):
            row['steals_roll3'] = float(recent3['steals'].mean()) if 'steals' in recent3.columns else 0.5

        # ── V8: Season trajectory ──────────────────────────────────────────────
        row['uk_win_rate_roll10'] = self._uk_win_rate_roll10

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
        X_min = pd.DataFrame([row[self._minutes_cols]])
        pred_minutes = max(0.0, float(self.minutes_model.predict(X_min)[0]) * minutes_scale)
        # Cap at 40 minutes (OT rarely changes predictions materially)
        pred_minutes = min(pred_minutes, 40.0)

        # ── Step 2: Update rolling minutes with predicted value ────────────────
        row['minutes_roll3'] = (row['minutes_roll3'] * 2 + pred_minutes) / 3
        row['minutes_roll5'] = (row['minutes_roll5'] * 4 + pred_minutes) / 5
        row['predicted_minutes'] = pred_minutes

        # ── Step 3: Predict points/rebounds/assists ────────────────────────────
        X_pts = pd.DataFrame([row[self._feature_cols]])
        model = self.model_G if row.get('position', 'G') == 'G' else self.model_FC
        pred_points   = max(0.0, float(model.predict(X_pts)[0]))
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
                                uk_bpi_defense=None, opp_bpi=None):
        """
        Predict opponent score. V2 adds uk_bpi_defense so the model
        reacts to Kentucky's current defensive strength (and implicitly
        to injuries — weaker defense = higher BPI defense number = more pts allowed).
        opp_bpi is the opponent's current BPI (offensive strength).
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

        # opp_off_eff_roll3: opponent's rolling offensive efficiency
        global_opp_eff = float(self.opp_model_df['opp_off_eff'].mean()) if 'opp_off_eff' in self.opp_model_df.columns else 108.3
        if len(opp_games) > 0 and 'opp_off_eff' in opp_games.columns:
            opp_off_eff_roll3 = float(opp_games['opp_off_eff'].tail(3).mean())
            if pd.isna(opp_off_eff_roll3):
                opp_off_eff_roll3 = global_opp_eff
        else:
            opp_off_eff_roll3 = global_opp_eff

        opp_input = pd.DataFrame([{
            'net_rank':            int(net_rank),
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
            'opp_bpi':             float(opp_bpi) if opp_bpi is not None else 10.0,
            'game_pace_roll3':     float(self.game_stats_df['uk_possessions'].tail(3).mean()) if hasattr(self, 'game_stats_df') and len(self.game_stats_df) >= 1 else 70.0,
            'opp_off_eff_roll3':   opp_off_eff_roll3,
        }])

        # Match features to whatever the model was trained with
        model_features = self.opp_model_v4.get_booster().feature_names
        opp_input = opp_input[[c for c in model_features if c in opp_input.columns]]
        return round(float(self.opp_model_v4.predict(opp_input)[0]), 1)

    def _win_prob_logistic(self, projections, opp_score, is_home,
                            opp_pts_roll3=None, opp_fg_pct_roll3=None, uk_def_roll3=None,
                            neutral_site=0):
        """
        V2 win probability using trained logistic regression.
        Uses simplified features: pts_diff, uk_is_home, neutral_site.
        """
        uk_pts   = sum(p['points'] for p in projections)
        pts_diff = uk_pts - opp_score

        features = pd.DataFrame(
            [[pts_diff, int(is_home), int(neutral_site)]],
            columns=['margin_bucket', 'uk_is_home', 'neutral_site']
        )
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

        # ── Injury minutes redistribution ──────────────────────────────────────
        # Compute how many minutes injured players typically play, then scale
        # up active players proportionally so total approaches ~200 min/game.
        minutes_scale = 1.0
        if injuries:
            injured_avg_mins = 0.0
            active_avg_mins  = 0.0
            for p in roster:
                if p.get('walk_on'):
                    continue
                hist = self.df_model[self.df_model['player_name'] == p['name']]
                avg_min = float(hist['minutes'].tail(5).mean()) if len(hist) > 0 else 0.0
                if p['name'] in injuries:
                    injured_avg_mins += avg_min
                else:
                    active_avg_mins += avg_min
            if active_avg_mins > 0 and injured_avg_mins > 0:
                # Cap scale at 1.35 to avoid extreme extrapolation
                minutes_scale = min(1.35, (active_avg_mins + injured_avg_mins) / active_avg_mins)

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
                minutes_scale   = minutes_scale,
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
            uk_bpi_defense=adjusted_bpi_defense,
            opp_bpi=opp_bpi,
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
