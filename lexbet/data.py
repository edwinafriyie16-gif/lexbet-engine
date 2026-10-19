"""SQLite storage and leakage-safe pre-match feature construction."""
from __future__ import annotations
import json
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
CREATE TABLE IF NOT EXISTS odds_snapshots (
 event_id TEXT, kickoff TEXT NOT NULL, home_team TEXT, away_team TEXT,
 market TEXT NOT NULL, selection TEXT NOT NULL, odds REAL NOT NULL,
 bookmaker TEXT, observed_at TEXT NOT NULL, is_closing INTEGER DEFAULT 0,
 PRIMARY KEY(event_id, market, selection, bookmaker, observed_at)
);
CREATE TABLE IF NOT EXISTS picks (
 id TEXT PRIMARY KEY, event_id TEXT, kickoff TEXT NOT NULL, home_team TEXT, away_team TEXT,
 market TEXT NOT NULL, selection TEXT NOT NULL, odds REAL NOT NULL,
 model_prob REAL NOT NULL, market_prob REAL NOT NULL, blended_prob REAL NOT NULL,
 edge REAL NOT NULL, stake REAL NOT NULL, bankroll REAL NOT NULL,
 status TEXT DEFAULT 'open', outcome INTEGER, settled_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS paper_trades (
 pick_id TEXT PRIMARY KEY, placed_at TEXT NOT NULL, settled_at TEXT, result TEXT,
 profit REAL, closing_odds REAL, closing_line_value REAL
);
CREATE TABLE IF NOT EXISTS backtest_runs (
 id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP, market TEXT,
 train_end TEXT, validation_end TEXT, test_start TEXT, test_end TEXT,
 metrics_json TEXT NOT NULL, report_path TEXT
);
"""

MATCH_COLS = {"id", "league", "kickoff", "home_team", "away_team", "home_goals", "away_goals", "home_xg", "away_xg", "home_elo", "away_elo", "odds_home", "odds_draw", "odds_away", "over25_odds", "under25_odds", "closing_home", "closing_draw", "closing_away", "source"}


def connect(db_path: str | Path) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_matches(conn: sqlite3.Connection, frame: pd.DataFrame) -> int:
    cols = [c for c in frame.columns if c in MATCH_COLS]
    required = {"id", "league", "kickoff", "home_team", "away_team"}
    if not required.issubset(cols):
        raise ValueError(f"missing required columns: {required - set(cols)}")
    clean = frame[cols].copy().replace({np.nan: None})
    if "kickoff" in clean:
        clean["kickoff"] = pd.to_datetime(clean["kickoff"], utc=True, errors="coerce").map(lambda x: x.isoformat() if pd.notna(x) else None)
    placeholders = ",".join("?" for _ in cols)
    sql = f"INSERT OR REPLACE INTO matches ({','.join(cols)}) VALUES ({placeholders})"
    conn.executemany(sql, clean.itertuples(index=False, name=None))
    conn.commit()
    return len(clean)


def insert_odds(conn: sqlite3.Connection, frame: pd.DataFrame) -> int:
    if frame.empty: return 0
    cols = ["event_id", "kickoff", "home_team", "away_team", "market", "selection", "odds", "bookmaker", "observed_at", "is_closing"]
    clean = frame.reindex(columns=cols).replace({np.nan: None})
    conn.executemany(f"INSERT OR REPLACE INTO odds_snapshots ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", clean.itertuples(index=False, name=None))
    conn.commit()
    return len(clean)


def insert_picks(conn: sqlite3.Connection, picks: list[dict]) -> int:
    if not picks: return 0
    cols = ["id", "event_id", "kickoff", "home_team", "away_team", "market", "selection", "odds", "model_prob", "market_prob", "blended_prob", "edge", "stake", "bankroll"]
    conn.executemany(f"INSERT OR REPLACE INTO picks ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})", [[p.get(c) for c in cols] for p in picks])
    conn.executemany("INSERT OR IGNORE INTO paper_trades (pick_id, placed_at) VALUES (?, COALESCE(?, CURRENT_TIMESTAMP))", [(p["id"], p.get("created_at")) for p in picks])
    conn.commit()
    return len(picks)


def settle_open_picks(conn: sqlite3.Connection, matches: pd.DataFrame) -> int:
    """Settle paper picks only after a final result is available."""
    settled = 0
    for pick in conn.execute("SELECT * FROM picks WHERE status='open'").fetchall():
        rows = matches[(matches.home_team == pick["home_team"]) & (matches.away_team == pick["away_team"]) & (pd.to_datetime(matches.kickoff, utc=True) >= pd.Timestamp(pick["kickoff"], tz="UTC") - pd.Timedelta(hours=18)) & (pd.to_datetime(matches.kickoff, utc=True) <= pd.Timestamp(pick["kickoff"], tz="UTC") + pd.Timedelta(hours=18))]
        if rows.empty or pd.isna(rows.iloc[0].home_goals): continue
        r = rows.iloc[0]
        if pick["market"] == "1X2": outcome = "H" if r.home_goals > r.away_goals else "D" if r.home_goals == r.away_goals else "A"
        else: outcome = "O" if r.home_goals + r.away_goals > 2.5 else "U"
        won = int(outcome == pick["selection"])
        profit = pick["stake"] * ((pick["odds"] - 1) if won else -1)
        conn.execute("UPDATE picks SET status='settled', outcome=?, settled_at=CURRENT_TIMESTAMP WHERE id=?", (won, pick["id"]))
        conn.execute("UPDATE paper_trades SET settled_at=CURRENT_TIMESTAMP, result=?, profit=?, closing_odds=? WHERE pick_id=?", ("win" if won else "loss", profit, None, pick["id"]))
        settled += 1
    conn.commit()
    return settled


def build_features(matches: pd.DataFrame, window: int = 5) -> pd.DataFrame:
    df = matches.copy()
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
    df = df.sort_values("kickoff").reset_index(drop=True)
    df["result"] = np.select([df.home_goals > df.away_goals, df.home_goals == df.away_goals], ["H", "D"], default="A")
    rows, history = [], {}
    for _, r in df.iterrows():
        pre = {}
        for side, team, venue in [("home", r.home_team, "home"), ("away", r.away_team, "away")]:
            h = history.get(team, []); recent = h[-window:]
            def avg(key): return float(np.mean([x[key] for x in recent])) if recent else 0.0
            pre[f"{side}_form_points"] = avg("points"); pre[f"{side}_goals_for_avg"] = avg("gf"); pre[f"{side}_goals_against_avg"] = avg("ga")
            pre[f"{side}_xg_for_avg"] = avg("xgf"); pre[f"{side}_xg_against_avg"] = avg("xga")
            vr = [x for x in recent if x["venue"] == venue]
            pre[f"{side}_venue_goals_for_avg"] = float(np.mean([x["gf"] for x in vr])) if vr else 0.0
            pre[f"{side}_venue_goals_against_avg"] = float(np.mean([x["ga"] for x in vr])) if vr else 0.0
            pre[f"{side}_rest_days"] = float((r.kickoff - h[-1]["date"]).total_seconds() / 86400) if h else 30.0
        pre["elo_diff"] = float(r.home_elo or 0) - float(r.away_elo or 0)
        pre["xg_diff"] = float(r.home_xg or 0) - float(r.away_xg or 0)
        rows.append(pre)
        if pd.notna(r.home_goals) and pd.notna(r.away_goals):
            for team, venue, gf, ga, xgf, xga, pts in [(r.home_team, "home", r.home_goals, r.away_goals, r.home_xg or 0, r.away_xg or 0, 3 if r.home_goals > r.away_goals else 1 if r.home_goals == r.away_goals else 0), (r.away_team, "away", r.away_goals, r.home_goals, r.away_xg or 0, r.home_xg or 0, 3 if r.away_goals > r.home_goals else 1 if r.home_goals == r.away_goals else 0)]:
                history.setdefault(team, []).append({"date": r.kickoff, "venue": venue, "gf": gf, "ga": ga, "xgf": xgf, "xga": xga, "points": pts})
    return pd.concat([df, pd.DataFrame(rows)], axis=1)


def leakage_check(frame: pd.DataFrame) -> list[str]:
    forbidden = {"home_goals", "away_goals", "result"}
    feature_cols = [c for c in frame.columns if c.endswith("_avg") or c in {"elo_diff", "xg_diff", "home_rest_days", "away_rest_days", "home_form_points", "away_form_points"}]
    return sorted(forbidden.intersection(feature_cols))
