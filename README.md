# lexbet-engine

A Python 3.11 research engine for football value-betting analysis. It is designed for paper trading and auditability, not guaranteed profit. Gambling involves real financial risk; use legal, age-appropriate, responsible-gambling practices and never chase losses.

## What is included

- SQLite storage for match results, xG, Elo, historical odds, live odds snapshots, and closing prices.
- Adapters for `soccerdata` sources: Football-Data.co.uk match history and odds, Understat xG, and ClubElo ratings. The six configured competitions are the top five European leagues plus the English Championship.
- Leakage-safe pre-match features: shifted rolling form, venue splits, goals and xG averages, Elo difference, and rest days.
- XGBoost hooks for 1X2 and totals plus an Elo/Poisson baseline. The intended evaluation protocol is chronological: train on earlier matches, calibrate on a later validation slice, then walk forward over the last six months. No random split is permitted.
- Isotonic calibration and reliability-bin helpers.
- De-vigged market probabilities and a mandatory model/market blend. The engine is not allowed to expose raw model probabilities as bet probabilities.
- Value filter: only pre-kickoff events with 2–8 percentage-point edge. Edges above 8 pp are rejected; any edge above 10 pp is explicitly treated as a bug. Fractional Kelly is 0.25 and stake is capped at 2% of bankroll.
- Telegram commands `/picks`, `/stats`, and `/bankroll` with clear no-guarantee wording.

## Setup

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest -q
```

The live data path requires `ODDS_API_KEY`. Telegram requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Never commit `.env` or a database containing credentials.

## Historical refresh

```bash
python scripts/daily_update.py
```

Schedule that command once per day with cron or a managed scheduler. Scrapers are network-dependent and may break when upstream websites change. Respect each provider's terms and rate limits.

## Modeling and backtesting

The package exposes primitives in `lexbet.model` and `lexbet.backtest`. A production runner should persist each feature snapshot and odds timestamp, use a chronological train/validation/test split, fit calibration only on validation data, and record the odds available at decision time. The six-month walk-forward report must include ROI, hit rate, Brier score, log loss, and closing line value. A positive backtest ROI is not evidence of future profit; if the measured ROI is not positive, the README and report must say so rather than tuning until it is.

This starter repository intentionally does not fabricate historical results or claim a backtest number without a downloaded, timestamped dataset. Run the data refresh and a documented walk-forward before treating any output as evidence.

## Reference projects

The design takes inspiration from the public data-source adapters and analytics concepts in [soccerdata](https://github.com/probberechts/soccerdata) (Apache-2.0) and the feature/evaluation ideas in [ProphitBet-Soccer-Bets-Predictor](https://github.com/kochlisGit/ProphitBet-Soccer-Bets-Predictor) (MIT). No GUI code is copied. See their repositories for their full license texts and provider-specific limitations.

## Status

This is an initial research scaffold. It is not a betting service, does not place wagers, and makes no guarantee of profit. Provider schemas, league identifiers, calibration quality, and odds timestamps must be validated before live use.
