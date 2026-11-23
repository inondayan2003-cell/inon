"""Checks of the intraday multi-timeframe engine (research/gold_intraday/engine.py)."""
import numpy as np
import pandas as pd
import pytest

from research.gold_intraday.engine import Frames, IParams, run


def _m1(days=150, seed=5):
    rng = np.random.default_rng(seed)
    n = days * 1440
    idx = pd.date_range("2025-03-03", periods=n, freq="1min", tz="UTC")
    c = 2800 + np.cumsum(rng.normal(np.sin(np.arange(n) / 4000) * 0.03, 0.4, n))
    o = np.r_[c[0], c[:-1]]
    df = pd.DataFrame(dict(open=o, high=np.maximum(o, c) + rng.exponential(.15, n),
                           low=np.minimum(o, c) - rng.exponential(.15, n), close=c, volume=1.0), index=idx)
    ny = df.index.tz_convert("America/New_York")
    closed = (ny.hour == 17) | (ny.weekday == 5) | ((ny.weekday == 4) & (ny.hour >= 17)) | ((ny.weekday == 6) & (ny.hour < 18))
    return df[~closed]   # real gold hours: Sunday 18:00 .. Friday 17:00 NY, daily break 17:00-18:00


@pytest.fixture(scope="module")
def m1():
    return _m1()


@pytest.mark.parametrize("variant", ["15m", "5m_15m", "5m_htf"])
def test_no_lookahead(m1, variant):
    """Cutting the data must not change any entry made before the cut."""
    p = IParams(variant=variant, min_score=0)
    full = run(Frames(m1), p)
    cut = m1.index[len(m1) * 2 // 3]
    part = run(Frames(m1[m1.index < cut]), p)
    key = lambda t: (t.entry_time, t.direction, round(t.entry, 6), round(t.stop0, 6), t.score)
    before = [key(t) for t in full if t.entry_time < cut - pd.Timedelta(hours=4)]
    assert before and before == [key(t) for t in part if t.entry_time < cut - pd.Timedelta(hours=4)]


@pytest.mark.parametrize("variant", ["15m", "5m_15m", "5m_htf"])
def test_rules(m1, variant):
    p = IParams(variant=variant, min_score=50)
    trades = run(Frames(m1), p)
    per_day = {}
    for a, b in zip(trades, trades[1:]):
        assert b.entry_time >= a.exit_time                        # one trade at a time
    for t in trades:
        risk = t.direction * (t.entry - t.stop0)
        assert risk > 0 and t.tp == pytest.approx(t.entry + t.direction * 3 * risk)
        day = (t.entry_time.tz_convert("America/New_York") - pd.Timedelta(hours=17)).normalize()
        per_day[day] = per_day.get(day, 0) + 1
        exit_day = (t.exit_time.tz_convert("America/New_York") - pd.Timedelta(hours=17, minutes=1)).normalize()
        assert exit_day == day                                     # flat before the daily break
    assert max(per_day.values()) <= p.max_trades_day
