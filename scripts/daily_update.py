#!/usr/bin/env python3
from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from lexbet.data import connect, upsert_matches
from lexbet.providers import LEAGUES, pull_historical

load_dotenv()
db = Path(os.getenv("LEXBET_DB_PATH", "data/lexbet.sqlite"))
seasons = [str(y) for y in range(2023, datetime.now().year + 1)]
conn = connect(db)
for league in os.getenv("LEXBET_LEAGUES", ",".join(LEAGUES)).split(","):
    try:
        frame = pull_historical(league.strip(), seasons)
        frame = frame.rename(columns={"date": "kickoff", "home_score": "home_goals", "away_score": "away_goals"})
        frame["league"] = league.strip(); frame["id"] = frame.apply(lambda r: f"{league.strip()}|{r.get('kickoff')}|{r.get('home_team')}|{r.get('away_team')}", axis=1)
        upsert_matches(conn, frame)
        print(f"updated {league}: {len(frame)} rows")
    except Exception as exc:
        print(f"warning: {league}: {exc}")
