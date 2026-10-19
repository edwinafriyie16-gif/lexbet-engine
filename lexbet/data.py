"""Data storage and leakage-safe feature construction."""
from __future__ import annotations
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
 id TEXT PRIMARY KEY, league TEXT NOT NULL, kickoff TEXT NOT NULL,
 home_team TEXT NOT NULL, away_team TEXT NOT NULL,
 home_goals REAL, away_goals REAL, home_xg REAL, away_xg REAL,
 home_elo REAL, away_elo REAL, odds_home REAL, odds_draw REAL, odds_away REAL,
 over25_odds REAL, under25_odds REAL, closing_home REAL, closing_draw REAL, closing_away REAL,
 source TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_matches_league_kickoff ON matches(league, kickoff);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def upsert_matches(conn: sqlite3.Connection, frame: pd.DataFrame) -> None:
    cols = [c for c in frame.columns if c in {
        "id","league","kickoff","home_team","away_team","home_goals","away_goals",
        "home_xg","away_xg","home_elo","away_elo","odds_home","odds_draw","odds_away",
        "over25_odds","under25_odds","closing_home","closing_draw","closing_away","source"
    }]
    required = {"id","league","kickoff","home_team","away_team"}
    if not required.issubset(cols): raise ValueError(f"missing required columns: {required - set(cols)}")
    frame[cols].to_sql("matches", conn, if_exists="append", index=False)
    conn.commit()


def build_features(matches: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    """Create pre-match features by shifting each team's history before rolling."""
    df = matches.copy()
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
    df = df.sort_values("kickoff").reset_index(drop=True)
    df["result"] = np.select([df.home_goals > df.away_goals, df.home_goals == df.away_goals], ["H", "D"], default="A")
    rows = []
    history: dict[str, list[dict]] = {}
    for _, r in df.iterrows():
        pre = {}
        for side, team, venue in [("home", r.home_team, "home"), ("away", r.away_team, "away")]:
            h = history.get(team, [])
            recent = h[-window:]
            def avg(key, default=0.0): return float(np.mean([x[key] for x in recent])) if recent else default
            pre[f"{side}_form_points"] = avg("points")
            pre[f"{side}_goals_for_avg"] = avg("gf")
            pre[f"{side}_goals_against_avg"] = avg("ga")
            pre[f"{side}_xg_for_avg"] = avg("xgf")
            pre[f"{side}_xg_against_avg"] = avg("xga")
            venue_recent = [x for x in recent if x["venue"] == venue]
            pre[f"{side}_venue_goals_for_avg"] = float(np.mean([x["gf"] for x in venue_recent])) if venue_recent else 0.0
            pre[f"{side}_venue_goals_against_avg"] = float(np.mean([x["ga"] for x in venue_recent])) if venue_recent else 0.0
            pre[f"{side}_rest_days"] = float((r.kickoff - h[-1]["date"]).total_seconds() / 86400) if h else 30.0
        pre["elo_diff"] = float((r.home_elo or 0) - (r.away_elo or 0))
        pre["xg_diff"] = float((r.home_xg or 0) - (r.away_xg or 0))
        rows.append(pre)
        if pd.notna(r.home_goals) and pd.notna(r.away_goals):
            for team, venue, gf, ga, xgf, xga, points in [
                (r.home_team, "home", r.home_goals, r.away_goals, r.home_xg or 0, r.away_xg or 0, 3 if r.home_goals > r.away_goals else 1 if r.home_goals == r.away_goals else 0),
                (r.away_team, "away", r.away_goals, r.home_goals, r.away_xg or 0, r.home_xg or 0, 3 if r.away_goals > r.home_goals else 1 if r.home_goals == r.away_goals else 0),
            ]:
                history.setdefault(team, []).append({"date": r.kickoff, "venue": venue, "gf": gf, "ga": ga, "xgf": xgf, "xga": xga, "points": points})
    return pd.concat([df, pd.DataFrame(rows)], axis=1)


def leakage_check(frame: pd.DataFrame) -> list[str]:
    forbidden = {"home_goals", "away_goals", "result"}
    feature_cols = [c for c in frame.columns if c.endswith("_avg") or c in {"elo_diff", "xg_diff", "home_rest_days", "away_rest_days", "home_form_points", "away_form_points"}]
    return sorted(forbidden.intersection(feature_cols))
