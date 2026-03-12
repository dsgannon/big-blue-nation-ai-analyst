"""
scripts/calibration_report.py

Retrospective win-probability calibration.

For each completed game in the Pope era, compute what win probability the
current model WOULD have predicted (using actual game scores as a proxy for
projected scores), then compare to actual outcomes.

Run:  python scripts/calibration_report.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from scipy.stats import norm

DB_PATH = "data/processed/kentucky_basketball.db"
OUT_PATH = "notebooks/win_prob_calibration.png"

# Pomeroy formula constants (mirrors prediction_engine.py)
CBB_GAME_SIGMA = 11.0
HOME_ADV_PTS   = 3.5


def pomeroy_win_prob(margin, is_home, neutral_site):
    if neutral_site:
        adj = 0.0
    elif is_home:
        adj = HOME_ADV_PTS
    else:
        adj = -HOME_ADV_PTS
    return float(norm.cdf((margin + adj) / CBB_GAME_SIGMA))


def main():
    conn = sqlite3.connect(DB_PATH)

    games = pd.read_sql("""
        SELECT id, season, date,
               home_team, away_team,
               home_score, away_score,
               neutral_site
        FROM games
        WHERE home_score IS NOT NULL AND away_score IS NOT NULL
          AND season IN ('2024-25', '2025-26')
        ORDER BY date
    """, conn)
    conn.close()

    games["home_score"]  = pd.to_numeric(games["home_score"],  errors="coerce")
    games["away_score"]  = pd.to_numeric(games["away_score"],  errors="coerce")
    games = games.dropna(subset=["home_score", "away_score"])
    games["neutral_site"] = games["neutral_site"].fillna(0).astype(int)

    games["uk_is_home"] = (games["home_team"] == "Kentucky Wildcats").astype(int)
    games["uk_score"]   = np.where(games["uk_is_home"] == 1, games["home_score"], games["away_score"])
    games["opp_score"]  = np.where(games["uk_is_home"] == 1, games["away_score"], games["home_score"])
    games["margin"]     = games["uk_score"] - games["opp_score"]
    games["uk_won"]     = (games["margin"] > 0).astype(int)

    # Win prob using actual margin as "projected margin"
    # This is an upper bound on model accuracy — shows if the formula itself is calibrated
    games["win_prob"] = games.apply(
        lambda r: pomeroy_win_prob(r["margin"], r["uk_is_home"], r["neutral_site"]),
        axis=1
    )

    # ── Calibration buckets ────────────────────────────────────────────────────
    bins   = [0, 0.30, 0.45, 0.55, 0.65, 0.75, 0.85, 1.01]
    labels = ["<30%", "30-45%", "45-55%", "55-65%", "65-75%", "75-85%", ">85%"]
    games["bucket"] = pd.cut(games["win_prob"], bins=bins, labels=labels, right=False)

    cal = (
        games.groupby("bucket", observed=True)
        .agg(predicted=("win_prob", "mean"), actual=("uk_won", "mean"), n=("uk_won", "count"))
        .reset_index()
    )
    print("\nWin Probability Calibration (Pomeroy formula, Pope era)")
    print("=" * 55)
    print(f"{'Bucket':<12} {'Predicted':>10} {'Actual':>10} {'N':>5}")
    print("-" * 55)
    for _, row in cal.iterrows():
        flag = "⚠️" if abs(row["predicted"] - row["actual"]) > 0.12 else ""
        print(f"{row['bucket']:<12} {row['predicted']:>9.1%} {row['actual']:>9.1%} {row['n']:>5}  {flag}")

    overall_acc = (games["win_prob"].round() == games["uk_won"]).mean()
    brier = ((games["win_prob"] - games["uk_won"]) ** 2).mean()
    print("-" * 55)
    print(f"Overall accuracy (>50% = win): {overall_acc:.1%}")
    print(f"Brier score (lower = better):  {brier:.4f}  (perfect=0, random=0.25)")

    # ── Plot ───────────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle("Win Probability Calibration — UK Basketball (Pope Era)", fontsize=14, fontweight="bold")

    # Left: calibration curve
    ax = axes[0]
    valid = cal.dropna(subset=["predicted", "actual"])
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="Perfect calibration")
    sc = ax.scatter(valid["predicted"], valid["actual"], s=valid["n"] * 30,
                    c=valid["n"], cmap="Blues", zorder=5, edgecolors="steelblue", linewidths=1.2)
    for _, row in valid.iterrows():
        ax.annotate(f'n={int(row["n"])}', (row["predicted"], row["actual"]),
                    textcoords="offset points", xytext=(6, 4), fontsize=8, color="#444")
    ax.set_xlabel("Predicted Win Probability")
    ax.set_ylabel("Actual Win Rate")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=1))
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1))
    ax.set_title("Calibration Curve")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    # Right: margin distribution by outcome
    ax2 = axes[1]
    wins  = games[games["uk_won"] == 1]["margin"]
    losses = games[games["uk_won"] == 0]["margin"]
    bins_hist = range(-35, 50, 5)
    ax2.hist(wins,   bins=bins_hist, alpha=0.65, color="royalblue", label=f"Wins (n={len(wins)})")
    ax2.hist(losses, bins=bins_hist, alpha=0.65, color="tomato",    label=f"Losses (n={len(losses)})")
    ax2.axvline(0, color="black", lw=1.2, linestyle="--")
    ax2.set_xlabel("Point Margin (UK - Opponent)")
    ax2.set_ylabel("Games")
    ax2.set_title("Margin Distribution by Outcome")
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    # Brier score annotation
    fig.text(0.5, 0.01,
             f"Brier Score: {brier:.4f}  |  Directional Accuracy: {overall_acc:.1%}  |  Games: {len(games)}",
             ha="center", fontsize=9, color="#555")

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    plt.savefig(OUT_PATH, dpi=150, bbox_inches="tight")
    print(f"\nCalibration plot saved → {OUT_PATH}")


if __name__ == "__main__":
    main()
