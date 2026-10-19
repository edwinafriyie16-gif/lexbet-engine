from __future__ import annotations
import numpy as np
import pandas as pd
from .model import metrics


def walk_forward(frame: pd.DataFrame, predict_fn, months: int = 6) -> dict:
    df = frame.sort_values("kickoff").copy()
    cutoff = df.kickoff.max() - pd.Timedelta(days=months * 30)
    test = df[df.kickoff >= cutoff]
    if test.empty: return {"roi": 0.0, "n_bets": 0, "note": "No test rows in requested window."}
    bets, returns, probs, labels = [], [], [], []
    for _, row in test.iterrows():
        out = predict_fn(row, df[df.kickoff < row.kickoff])
        if not out: continue
        edge = out.get("edge", 0)
        if not (.02 <= edge <= .08): continue
        bets.append(out)
        won = bool(out.get("won", False))
        returns.append((out["odds"] - 1) if won else -1)
        probs.append(out["prob"]); labels.append(int(won))
    if not bets: return {"roi": 0.0, "n_bets": 0, "note": "No bets passed the 2–8 pp filter."}
    return {"roi": float(np.sum(returns) / len(returns)), "n_bets": len(bets), "hit_rate": float(np.mean(labels)), "brier_score": float(np.mean((np.array(labels) - probs) ** 2)), "log_loss": float(-np.mean(np.array(labels) * np.log(np.clip(probs, 1e-9, 1)) + (1-np.array(labels))*np.log(np.clip(1-np.array(probs), 1e-9, 1)))), "closing_line_value": float(np.mean([b.get("closing_value", 0) for b in bets]))}


def reliability_bins(y_true, probs, bins=10) -> pd.DataFrame:
    x = pd.DataFrame({"prob": probs, "outcome": y_true})
    x["bin"] = pd.cut(x.prob, np.linspace(0, 1, bins + 1), include_lowest=True)
    return x.groupby("bin", observed=True).agg(mean_pred=("prob", "mean"), fraction_positive=("outcome", "mean"), count=("outcome", "size")).reset_index()
