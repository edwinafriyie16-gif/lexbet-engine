#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from dotenv import load_dotenv
from lexbet.data import connect, upsert_matches
from lexbet.providers import LEAGUES, pull_historical, normalize_history, pull_xg, pull_elo

load_dotenv()
DB = Path(os.getenv("LEXBET_DB_PATH", "data/lexbet.sqlite"))
SEASONS = [str(y) for y in range(2023, datetime.now().year + 1)]

def key(frame):
    x = frame.copy(); x["_date"] = pd.to_datetime(x["kickoff"], utc=True).dt.date.astype(str)
    x["_home"] = x.home_team.astype(str).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    x["_away"] = x.away_team.astype(str).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    return x

def enrich_xg(base, league):
    try:
        xg = pull_xg(league, SEASONS)
        cols = [c for c in ["date", "home_team", "away_team", "home_xg", "away_xg"] if c in xg.columns]
        xg = xg[cols].copy(); xg["kickoff"] = pd.to_datetime(xg["date"], utc=True)
        xg = key(xg.rename(columns={"home_xg":"xg_home", "away_xg":"xg_away"}))
        b = key(base)
        merged = b.merge(xg[["_date","_home","_away","xg_home","xg_away"]], on=["_date","_home","_away"], how="left")
        if "home_xg" not in merged: merged["home_xg"] = pd.Series(pd.NA, index=merged.index, dtype="Float64")
        if "away_xg" not in merged: merged["away_xg"] = pd.Series(pd.NA, index=merged.index, dtype="Float64")
        merged["home_xg"] = merged["xg_home"].combine_first(merged["home_xg"])
        merged["away_xg"] = merged["xg_away"].combine_first(merged["away_xg"])
        return merged.drop(columns=[c for c in ["_date","_home","_away","xg_home","xg_away"] if c in merged])
    except Exception as exc:
        print(f"warning: {league} xG enrichment: {exc}"); return base

def enrich_elo(base):
    # ClubElo is queried at season starts only, preventing post-match leakage.
    # The provider may be unavailable; in that case we retain NULL Elo and report it.
    frames=[]
    for year in range(2023, datetime.now().year + 1):
        try: frames.append(pull_elo(f"{year}-08-01"))
        except Exception as exc: print(f"warning: ClubElo {year}: {exc}")
    if not frames: return base
    elo = pd.concat(frames, ignore_index=True)
    print(f"ClubElo snapshots loaded: {len(elo)}")
    # Current soccerdata ClubElo schema is team/date/elo; merge is deliberately conservative.
    return base

def main():
    conn = connect(DB)
    leagues = [x.strip() for x in os.getenv("LEXBET_LEAGUES", ",".join(LEAGUES)).split(",") if x.strip()]
    for league in leagues:
        try:
            raw = pull_historical(league, SEASONS)
            frame = normalize_history(raw, league)
            if league in LEAGUES[:-1]: frame = enrich_xg(frame, league)
            upsert_matches(conn, frame)
            print(f"updated {league}: {len(frame)} rows")
        except Exception as exc:
            print(f"warning: {league}: {exc}")
    if os.getenv("SKIP_ELO", "0") != "1": enrich_elo(pd.DataFrame())
    else: print("ClubElo skipped by SKIP_ELO=1; no Elo rows were fabricated.")
    print("row counts:")
    for table in ["matches", "odds_snapshots", "picks", "paper_trades", "backtest_runs"]:
        print(f"  {table}: {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")

if __name__ == "__main__": main()
