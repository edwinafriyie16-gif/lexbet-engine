import numpy as np
import pandas as pd
from lexbet.data import build_features, leakage_check
from lexbet.model import remove_margin, value_filter, fractional_kelly, blend


def sample():
    return pd.DataFrame([
        {"id":"1","kickoff":"2024-01-01T12:00:00Z","home_team":"A","away_team":"B","home_goals":1,"away_goals":0,"home_xg":1.2,"away_xg":.5,"home_elo":1500,"away_elo":1450},
        {"id":"2","kickoff":"2024-01-08T12:00:00Z","home_team":"B","away_team":"A","home_goals":0,"away_goals":2,"home_xg":.4,"away_xg":1.6,"home_elo":1450,"away_elo":1500},
    ])


def test_features_use_prior_matches_only():
    out = build_features(sample(), window=5)
    assert out.loc[0, "home_form_points"] == 0
    assert out.loc[1, "away_form_points"] == 3
    assert leakage_check(out) == []


def test_margin_removed():
    p = remove_margin([2.0, 3.5, 4.0])
    assert np.isclose(p.sum(), 1)
    assert p[0] > 0


def test_blend_is_not_raw_model():
    out = blend(np.array([[.8,.1,.1]]), np.array([[.4,.3,.3]]))
    assert np.allclose(out, [[.6,.2,.2]])
    assert not np.allclose(out, [[.8,.1,.1]])


def test_value_filter_time_and_edge_guards():
    now = pd.Timestamp("2024-01-01", tz="UTC")
    assert value_filter(.60, 2.0, "2023-12-31", now=now) is None
    assert value_filter(.80, 2.0, "2024-01-02", now=now) is None  # 30 pp bug guard
    pick = value_filter(.54, 2.0, "2024-01-02", now=now)
    assert pick and .02 <= pick["edge"] <= .08


def test_kelly_is_capped():
    assert fractional_kelly(.9, 2.0, 1000) <= 20
