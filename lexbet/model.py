from __future__ import annotations
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss

FEATURES = ["home_form_points","away_form_points","home_goals_for_avg","away_goals_for_avg","home_goals_against_avg","away_goals_against_avg","home_xg_for_avg","away_xg_for_avg","home_xg_against_avg","away_xg_against_avg","home_rest_days","away_rest_days","elo_diff","xg_diff"]


def remove_margin(odds: list[float]) -> np.ndarray:
    inv = np.array([1 / float(x) for x in odds], dtype=float)
    return inv / inv.sum()


def fractional_kelly(prob: float, odds: float, bankroll: float, fraction: float = .25, cap: float = .02) -> float:
    b, q = odds - 1, 1 - prob
    raw = max(0.0, (b * prob - q) / b) if b > 0 else 0.0
    return bankroll * min(cap, fraction * raw)


def poisson_1x2(home_lambda: float, away_lambda: float, max_goals: int = 10) -> np.ndarray:
    from scipy.stats import poisson
    probs = np.zeros(3)
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson.pmf(h, home_lambda) * poisson.pmf(a, away_lambda)
            probs[0 if h > a else 1 if h == a else 2] += p
    return probs / probs.sum()


def fit_xgb(X: pd.DataFrame, y: pd.Series):
    from xgboost import XGBClassifier
    model = XGBClassifier(n_estimators=250, max_depth=3, learning_rate=.04, subsample=.8, colsample_bytree=.8, objective="multi:softprob", eval_metric="mlogloss", random_state=42)
    model.fit(X[FEATURES], y)
    return model


def calibrate_multiclass(model, X_cal: pd.DataFrame, y_cal: pd.Series):
    raw = model.predict_proba(X_cal[FEATURES])
    calibrators = []
    for i in range(raw.shape[1]):
        cal = IsotonicRegression(out_of_bounds="clip").fit(raw[:, i], (y_cal.to_numpy() == i).astype(int))
        calibrators.append(cal)
    return calibrators


def calibrated_predict(model, calibrators, X: pd.DataFrame) -> np.ndarray:
    raw = model.predict_proba(X[FEATURES])
    out = np.column_stack([cal.predict(raw[:, i]) for i, cal in enumerate(calibrators)])
    return out / out.sum(axis=1, keepdims=True)


def blend(model_prob: np.ndarray, market_prob: np.ndarray, weight: float = .5) -> np.ndarray:
    """Always blend; callers should not expose model_prob as a bet probability."""
    result = weight * model_prob + (1 - weight) * market_prob
    return result / result.sum(axis=1, keepdims=True)


def confidence_label(prob: float, model_prob: float, market_prob: float) -> str:
    """Describe confidence from probability and model/market agreement."""
    agreement = abs(model_prob - market_prob)
    if prob >= .85 and agreement <= .08:
        return "High"
    if prob >= .70 and agreement <= .15:
        return "Medium-high"
    if prob >= .55:
        return "Medium"
    return "Low"


def rank_outcomes(names, model_probs, market_probs, blended_probs, odds=None) -> list[dict]:
    """Return all outcomes ranked by likelihood, not by betting edge."""
    odds = odds or [None] * len(names)
    rows = []
    for name, model_prob, market_prob, blended_prob, price in zip(names, model_probs, market_probs, blended_probs, odds):
        rows.append({
            "selection": name,
            "model_prob": float(model_prob),
            "market_prob": float(market_prob),
            "blended_prob": float(blended_prob),
            "odds": None if price is None else float(price),
            "confidence": confidence_label(float(blended_prob), float(model_prob), float(market_prob)),
            "agreement": float(1 - abs(float(model_prob) - float(market_prob))),
        })
    return sorted(rows, key=lambda x: x["blended_prob"], reverse=True)


def value_filter(prob: float, odds: float, kickoff, now=None, min_edge=.02, max_edge=.08) -> dict | None:
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    kick = pd.Timestamp(kickoff)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    kick = kick.tz_localize("UTC") if kick.tzinfo is None else kick.tz_convert("UTC")
    edge = prob - 1 / odds
    if kick <= now or not (min_edge <= edge <= max_edge): return None
    return {"edge": float(edge), "stake": fractional_kelly(prob, odds, bankroll=1.0), "odds": float(odds)}


def metrics(y_true, probs) -> dict:
    pred = np.argmax(probs, axis=1)
    return {"brier_score": float(np.mean(np.sum((probs - np.eye(probs.shape[1])[y_true]) ** 2, axis=1))), "log_loss": float(log_loss(y_true, probs)), "hit_rate": float(np.mean(pred == y_true))}
