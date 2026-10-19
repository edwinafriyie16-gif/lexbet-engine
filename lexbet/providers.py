"""External provider adapters. Network calls are intentionally explicit."""
from __future__ import annotations
import os
from datetime import datetime, timezone
import pandas as pd
import requests

LEAGUES = ["ENG-Premier League", "ESP-La Liga", "GER-Bundesliga", "ITA-Serie A", "FRA-Ligue 1", "ENG-Championship"]


def pull_historical(league: str, seasons: list[str]) -> pd.DataFrame:
    import soccerdata as sd
    history = sd.MatchHistory(league, seasons=seasons)
    return history.read_games()


def pull_xg(league: str, seasons: list[str]) -> pd.DataFrame:
    import soccerdata as sd
    return sd.Understat(league, seasons=seasons).read_results()


def pull_elo(dates: list[str] | None = None) -> pd.DataFrame:
    import soccerdata as sd
    return sd.ClubElo().read_by_date(dates=dates)


def fetch_live_odds(sport: str = "soccer_epl", regions: str = "uk,eu", markets: str = "h2h,totals") -> list[dict]:
    key = os.environ.get("ODDS_API_KEY")
    if not key: raise RuntimeError("ODDS_API_KEY is required for live odds")
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    response = requests.get(url, params={"apiKey": key, "regions": regions, "markets": markets, "oddsFormat": "decimal"}, timeout=30)
    response.raise_for_status()
    return response.json()


def normalise_odds(payload: list[dict]) -> pd.DataFrame:
    rows = []
    for event in payload:
        kickoff = pd.to_datetime(event.get("commence_time"), utc=True)
        if kickoff <= pd.Timestamp.now(tz="UTC"): continue
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                rows.append({"event_id": event.get("id"), "kickoff": kickoff, "home_team": event.get("home_team"), "away_team": event.get("away_team"), "bookmaker": book.get("key"), "market": market.get("key"), "outcomes": market.get("outcomes", []), "source_time": datetime.now(timezone.utc)})
    return pd.DataFrame(rows)
