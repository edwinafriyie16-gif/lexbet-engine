"""External providers and normalization for the installed soccerdata release."""
from __future__ import annotations
import io
import os
import time
from datetime import datetime, timezone
import pandas as pd
import requests

LEAGUES = ["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1", "ENG-Championship"]
SOCCERDATA_LEAGUES = set(LEAGUES[:-1])
FOOTBALL_DATA_CODES = {"ENG-Premier League": "E0", "ESP-La Liga": "SP1", "GER-Bundesliga": "D1", "ITA-Serie A": "I1", "FRA-Ligue 1": "F1", "ENG-Championship": "E1"}


def _season_code(season: str) -> str:
    s = str(season)
    return s[-2:] + str(int(s[-2:]) + 1).zfill(2) if len(s) == 4 else str(int(s))[-2:] + str((int(s[-2:]) + 1) % 100).zfill(2)


def football_data_history(league: str, seasons: list[str], retries: int = 4) -> pd.DataFrame:
    rows = []
    code = FOOTBALL_DATA_CODES[league]
    session = requests.Session()
    for season in seasons:
        url = f"https://www.football-data.co.uk/mmz4281/{_season_code(season)}/{code}.csv"
        for attempt in range(retries):
            try:
                r = session.get(url, timeout=30, headers={"User-Agent": "lexbet-engine/0.1"})
                r.raise_for_status()
                rows.append(pd.read_csv(io.BytesIO(r.content)))
                break
            except Exception as exc:
                if attempt == retries - 1:
                    print(f"warning: {league} {season}: {exc}")
                else:
                    time.sleep(2 ** attempt)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def pull_historical(league: str, seasons: list[str]) -> pd.DataFrame:
    import soccerdata as sd
    if league in SOCCERDATA_LEAGUES:
        try:
            return sd.MatchHistory(league, seasons=seasons).read_games().reset_index(drop=True)
        except Exception as exc:
            print(f"warning: soccerdata {league} failed ({exc}); falling back to Football-Data.co.uk")
            return football_data_history(league, seasons)
    return football_data_history(league, seasons)


def normalize_history(raw: pd.DataFrame, league: str) -> pd.DataFrame:
    if raw.empty: return raw
    x = raw.reset_index(drop=True).copy()
    date_col = "date" if "date" in x else "Date"
    x["kickoff"] = pd.to_datetime(x[date_col], dayfirst=(date_col == "Date"), errors="coerce", utc=True)
    rename = {"HomeTeam": "home_team", "AwayTeam": "away_team", "FTHG": "home_goals", "FTAG": "away_goals", "AvgH": "odds_home", "AvgD": "odds_draw", "AvgA": "odds_away", "Avg>2.5": "over25_odds", "Avg<2.5": "under25_odds", "AvgCH": "closing_home", "AvgCD": "closing_draw", "AvgCA": "closing_away", "AvgC>2.5": "closing_over25", "AvgC<2.5": "closing_under25", "B365H": "odds_home", "B365D": "odds_draw", "B365A": "odds_away", "B365>2.5": "over25_odds", "B365<2.5": "under25_odds"}
    for old, new in rename.items():
        if old in x.columns and new not in x.columns: x[new] = x[old]
    required = ["kickoff", "home_team", "away_team"]
    for c in required:
        if c not in x: raise ValueError(f"{league}: missing normalized field {c}; columns={list(x.columns)[:15]}")
    x["league"] = league
    x["id"] = x.apply(lambda r: f"{league}|{r.kickoff.isoformat()}|{r.home_team}|{r.away_team}", axis=1)
    if "closing_over25" in x: x["over25_odds"] = x["over25_odds"].combine_first(x["closing_over25"])
    if "closing_under25" in x: x["under25_odds"] = x["under25_odds"].combine_first(x["closing_under25"])
    for c in ["home_goals", "away_goals", "odds_home", "odds_draw", "odds_away", "over25_odds", "under25_odds", "closing_home", "closing_draw", "closing_away"]:
        if c not in x: x[c] = pd.NA
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x["source"] = "soccerdata" if league in SOCCERDATA_LEAGUES else "football-data.co.uk"
    return x


def pull_xg(league: str, seasons: list[str]) -> pd.DataFrame:
    import soccerdata as sd
    return sd.Understat(league, seasons=seasons).read_schedule().reset_index(drop=True)


def pull_elo(date: str | datetime | None = None) -> pd.DataFrame:
    import soccerdata as sd
    return sd.ClubElo().read_by_date(date=date).reset_index(drop=True)


def fetch_live_odds(sport: str = "soccer_epl", regions: str = "uk,eu", markets: str = "h2h,totals") -> list[dict]:
    key = os.environ.get("ODDS_API_KEY")
    if not key: raise RuntimeError("ODDS_API_KEY is required for live odds")
    r = requests.get(f"https://api.the-odds-api.com/v4/sports/{sport}/odds", params={"apiKey": key, "regions": regions, "markets": markets, "oddsFormat": "decimal"}, timeout=30)
    r.raise_for_status(); return r.json()


def normalise_odds(payload: list[dict]) -> pd.DataFrame:
    rows = []
    observed = datetime.now(timezone.utc).isoformat()
    for event in payload:
        kickoff = pd.to_datetime(event.get("commence_time"), utc=True)
        if kickoff <= pd.Timestamp.now(tz="UTC"): continue
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                for outcome in market.get("outcomes", []):
                    rows.append({"event_id": event.get("id"), "kickoff": kickoff.isoformat(), "home_team": event.get("home_team"), "away_team": event.get("away_team"), "market": market.get("key"), "selection": outcome.get("name"), "odds": outcome.get("price"), "bookmaker": book.get("key"), "observed_at": observed, "is_closing": 0})
    return pd.DataFrame(rows)
