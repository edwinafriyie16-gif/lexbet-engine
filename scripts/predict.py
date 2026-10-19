#!/usr/bin/env python3
from __future__ import annotations
import hashlib, os, pickle, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from dotenv import load_dotenv
from lexbet.data import connect, build_features, insert_odds, insert_picks
from lexbet.model import remove_margin, rank_outcomes
from lexbet.providers import fetch_live_odds, normalise_odds
from train import calibrated

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data/lexbet.sqlite"
ART = ROOT / "artifacts"


def _fmt_pct(value: float) -> str:
    return f"{value:.1%}"


def _explain(event, selection, market, model_prob, market_prob, blended_prob, prior) -> tuple[str, str, str]:
    """Build a concise evidence trail that can be challenged in Telegram/chat."""
    home, away = event.home_team, event.away_team
    home_form = float(prior.iloc[0].get("home_form_points", 0) or 0)
    away_form = float(prior.iloc[0].get("away_form_points", 0) or 0)
    home_xg = float(prior.iloc[0].get("home_xg_for_avg", 0) or 0)
    away_xg = float(prior.iloc[0].get("away_xg_for_avg", 0) or 0)
    form_text = f"recent form: {home} {home_form:.1f}/15, {away} {away_form:.1f}/15"
    xg_text = f"recent xG averages: {home} {home_xg:.2f}, {away} {away_xg:.2f}"
    agreement = abs(model_prob - market_prob)
    agreement_text = "the model and market agree closely" if agreement <= .08 else "the model and market differ materially, so this needs debate"

    if market == "1X2" and selection == "Home":
        reasons = f"{home} is the selected winner; {form_text}; {xg_text}; {agreement_text}."
        risks = f"A draw or {away} win remains possible; check {home}'s lineup, rotation, injuries, and schedule congestion."
        alternatives = f"Draw is the main alternative; {away} win is the least likely of the three under this model."
    elif market == "1X2" and selection == "Away":
        reasons = f"{away} is the selected winner; {form_text}; {xg_text}; {agreement_text}."
        risks = f"A draw or {home} win remains possible; check {away}'s lineup, rotation, injuries, and schedule congestion."
        alternatives = f"Draw is the main alternative; {home} win is the least likely of the three under this model."
    elif market == "1X2":
        reasons = f"The draw is selected; {form_text}; {xg_text}; {agreement_text}."
        risks = f"Either team can break the stalemate with an early goal; verify lineups and motivation."
        alternatives = f"{home} win and {away} win are the alternatives; compare their attacking availability before staking."
    elif selection == "O":
        reasons = f"Over 2.5 goals is selected; {xg_text}; {agreement_text}."
        risks = f"An early tactical or finishing mismatch can produce a low-scoring game; inspect attacking lineups."
        alternatives = "Under 2.5 is the direct alternative and should be preferred if the model and market disagree."
    else:
        reasons = f"Under 2.5 goals is selected; {xg_text}; {agreement_text}."
        risks = f"An early goal, red card, or defensive error can turn this into an open game."
        alternatives = "Over 2.5 is the direct alternative and should be preferred if the model and market disagree."
    return reasons, risks, alternatives


def _pick(event_id, event, market, outcome, prior, bankroll) -> dict:
    rationale, risks, alternatives = _explain(
        event, outcome["selection"], market, outcome["model_prob"], outcome["market_prob"], outcome["blended_prob"], prior
    )
    return {
        "id": hashlib.sha256(f"{event_id}|{market}|{outcome['selection']}".encode()).hexdigest()[:24],
        "event_id": event_id,
        "kickoff": event.kickoff,
        "home_team": event.home_team,
        "away_team": event.away_team,
        "market": market,
        "selection": "O" if outcome["selection"] == "Over 2.5" else "U" if outcome["selection"] == "Under 2.5" else outcome["selection"],
        "odds": outcome["odds"],
        "model_prob": outcome["model_prob"],
        "market_prob": outcome["market_prob"],
        "blended_prob": outcome["blended_prob"],
        # Kept for backwards-compatible reporting; selection is no longer based on edge.
        "edge": outcome["blended_prob"] - outcome["market_prob"],
        "stake": 0.0,
        "bankroll": bankroll,
        "confidence": outcome["confidence"],
        "rationale": rationale,
        "risks": risks,
        "alternatives": alternatives,
    }


def main():
    load_dotenv()
    with open(ART / "models.pkl", "rb") as f:
        bundle = pickle.load(f)
    try:
        payload = fetch_live_odds()
    except RuntimeError as exc:
        print(f"live prediction unavailable: {exc}")
        return
    odds = normalise_odds(payload)
    conn = connect(DB)
    insert_odds(conn, odds)
    if odds.empty:
        print("No upcoming odds returned.")
        return

    hist = pd.read_sql_query(
        "select * from matches where home_goals is not null and away_goals is not null order by kickoff", conn
    )
    bankroll = float(os.getenv("LEXBET_BANKROLL", "1000"))
    min_probability = float(os.getenv("LEXBET_MIN_PROBABILITY", "0.55"))
    picks, near_misses = [], []
    for event_id, group in odds.groupby("event_id"):
        event = group.iloc[0]
        synthetic = hist.iloc[[0]].copy()
        synthetic.loc[:, :] = pd.NA
        synthetic["home_team"] = event.home_team
        synthetic["away_team"] = event.away_team
        synthetic["kickoff"] = event.kickoff
        prior = build_features(pd.concat([hist, synthetic], ignore_index=True)).tail(1)

        h2h = group[group.market == "h2h"]
        if all(not h2h[h2h.selection == name].empty for name in ["Home", "Draw", "Away"]):
            names = ["Home", "Draw", "Away"]
            prices = [float(h2h[h2h.selection == name].odds.mean()) for name in names]
            raw = calibrated(bundle["model_1x2"], bundle["cal_1x2"], prior)[0]
            market = remove_margin(prices)
            blended = (raw + market) / 2
            outcome = rank_outcomes(names, raw, market, blended, prices)[0]
            if outcome["blended_prob"] >= min_probability:
                picks.append(_pick(event_id, event, "1X2", outcome, prior, bankroll))
            else:
                near_misses.append((event.home_team, event.away_team, "1X2", outcome["selection"], outcome["blended_prob"]))

        totals = group[group.market == "totals"]
        if all(not totals[totals.selection == name].empty for name in ["Over 2.5", "Under 2.5"]):
            names = ["Over 2.5", "Under 2.5"]
            prices = [float(totals[totals.selection == name].odds.mean()) for name in names]
            raw = calibrated(bundle["model_ou25"], bundle["cal_ou25"], prior)[0]
            market = remove_margin(prices)
            blended = (raw + market) / 2
            outcome = rank_outcomes(names, raw, market, blended, prices)[0]
            if outcome["blended_prob"] >= min_probability:
                picks.append(_pick(event_id, event, "OU25", outcome, prior, bankroll))
            else:
                near_misses.append((event.home_team, event.away_team, "OU25", outcome["selection"], outcome["blended_prob"]))

    insert_picks(conn, picks)
    if picks:
        for pick in sorted(picks, key=lambda p: p["blended_prob"], reverse=True):
            print(f"{pick['home_team']} v {pick['away_team']} — {pick['selection']} | likelihood {_fmt_pct(pick['blended_prob'])} | confidence {pick['confidence']}")
            print(f"  Why: {pick['rationale']}")
            print(f"  Risks: {pick['risks']}")
            print(f"  Debate: {pick['alternatives']}")
    else:
        print(f"No recommendation met the {_fmt_pct(min_probability)} minimum likelihood threshold.")
        if near_misses:
            best = sorted(near_misses, key=lambda x: x[-1], reverse=True)[:5]
            print("Closest candidates: " + "; ".join(f"{h} v {a} {s} {_fmt_pct(p)}" for h, a, m, s, p in best))


if __name__ == "__main__":
    main()
