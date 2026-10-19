# lexbet-engine

A Python 3.11 football likely-outcome research engine. It ranks the most likely result in each available market and explains the evidence, risks, and alternatives so a user can debate the recommendation. It does not place wagers or guarantee profit. Gambling involves real financial risk; use only where legal, follow age and responsible-gambling rules, and never chase losses.

## End-to-end pipeline

1. `python scripts/daily_update.py` downloads and normalizes historical results and odds from soccerdata/Football-Data.co.uk, enriches top-five-league matches with Understat xG where available, and prints row counts for every SQLite table. The installed soccerdata release does not expose the Championship, so the refresh uses the same Football-Data.co.uk source directly for `ENG-Championship`. It also attempts ClubElo season-start snapshots; the ClubElo endpoint returned HTTP 502 during the October 19, 2026 run, so no Elo values were fabricated.
2. `python scripts/train.py` creates a chronological 60/20/20 train/validation/test split, fits separate XGBoost models for 1X2 and Over/Under 2.5, and fits isotonic calibrators on validation data only. Models are saved under `artifacts/` locally.
3. `python scripts/backtest.py` evaluates the last 183 days, removes market margin, blends calibrated model and market probabilities 50/50, applies the 2–8 percentage-point filter, and saves JSON, CSV, and PNG reliability artifacts under `reports/`.
4. `python scripts/predict.py` fetches upcoming fixtures and odds from The Odds API, computes pre-match features, ranks the most likely outcome in each market, and stores debate-ready recommendations plus paper-trade rows in SQLite. The default minimum likelihood is 55%; configure it with `LEXBET_MIN_PROBABILITY`.
5. `python scripts/settle.py` settles open paper picks once final match results are present. `python scripts/telegram.py` starts the Telegram bot; `/picks` reads open SQLite picks, `/stats` reads the latest backtest and paper-trade results, and `/bankroll` shows the configured paper bankroll.

## Real refresh and backtest run

The live refresh completed on 2026-10-19 with these match counts:

- English Premier League: 1,200
- Spanish La Liga: 1,218
- German Bundesliga: 963
- Italian Serie A: 1,200
- French Ligue 1: 972
- English Championship: 1,775
- Total matches: 7,328
- Matches with Understat xG: 3,153
- Matches with historical closing 1X2 odds: 7,328

The six-month report covers April 14 to October 14, 2026 using five expanding-window monthly folds. Each fold fits on earlier matches and calibrates only on the immediately preceding validation slice. It was not tuned to force a positive result:

- ROI: **−8.77%**
- Hit rate: **34.40%**
- Bets passing the filter: **936**
- 1X2 Brier score: **0.6120**
- 1X2 log loss: **1.0531**
- Mean closing-line value: **+0.072 percentage points**

This ROI is negative. It remains available as a diagnostic, but it is not the live recommendation objective. The report files are `reports/backtest.json`, `reports/reliability_curve.csv`, and `reports/reliability_curve.png`.

## Setup

```bash
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
pytest -q
```

`ODDS_API_KEY` is required for `scripts/predict.py`. `TELEGRAM_BOT_TOKEN` is required for the bot. `LEXBET_BANKROLL` defaults to 1000. No live prediction call was made in this run because no Odds API key was present in the environment.

## Guardrails

All reported probabilities are blended probabilities, never raw model probabilities. Market probabilities are de-vigged from decimal odds. Live recommendations are ranked by likelihood, not by positive market edge. Each recommendation stores its confidence, reasons, risks, and alternative outcome. The default minimum likelihood is 55%, and no stake size is suggested by the live predictor. Picks are recorded as paper trades and settled only after a final result is available.

## Reference projects

The design reuses ideas from [soccerdata](https://github.com/probberechts/soccerdata) (Apache-2.0), especially its source adapters and consistent match identifiers, and from [ProphitBet-Soccer-Bets-Predictor](https://github.com/kochlisGit/ProphitBet-Soccer-Bets-Predictor) (MIT), especially feature engineering and evaluation concepts. No GUI code is copied.
