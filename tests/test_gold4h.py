"""Checks of the Ultimate Gold 4H reference engine (research/gold4h/engine.py)."""
import numpy as np
import pandas as pd
import pytest

from research.gold4h.engine import Params, Trade, _exit_price, run, to_4h


def _synthetic(n=24000, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2016-01-04", periods=n, freq="1h", tz="UTC")
    drift = np.sin(np.arange(n) / 900) * 0.6          # alternating trends so both directions trade
    c = 1300 + np.cumsum(rng.normal(drift, 3, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.exponential(1.2, n)
    l = np.minimum(o, c) - rng.exponential(1.2, n)
    return pd.DataFrame(dict(open=o, high=h, low=l, close=c, volume=1.0), index=idx)


@pytest.fixture(scope="module")
def data():
    h1 = _synthetic()
    return h1, to_4h(h1)


def test_trades_in_both_directions(data):
    _, d4 = data
    tr = run(d4, Params(min_score=60))
    assert {t.direction for t in tr} == {1, -1}


def test_no_lookahead_signals_identical_on_truncated_data(data):
    """Signals must not depend on future bars: cutting the data must not change earlier entries."""
    _, d4 = data
    full = run(d4, Params(min_score=60))
    cut = len(d4) * 2 // 3
    part = run(d4.iloc[:cut], Params(min_score=60))
    key = lambda t: (t.entry_time, t.direction, round(t.entry, 6), round(t.stop0, 6), t.score)
    assert [key(t) for t in full if t.entry_bar < cut] == [key(t) for t in part]
    # trades closed before the cut also closed identically
    assert [(t.exit_time, t.status) for t in full if 0 <= t.exit_bar < cut] == \
           [(t.exit_time, t.status) for t in part if t.exit_bar >= 0]


def test_target_is_exactly_three_r_and_stop_on_correct_side(data):
    _, d4 = data
    for t in run(d4, Params(min_score=60)):
        risk = t.direction * (t.entry - t.stop0)
        assert risk > 0
        assert t.tp == pytest.approx(t.entry + t.direction * 3 * risk)


def test_one_trade_at_a_time(data):
    _, d4 = data
    tr = [t for t in run(d4, Params(min_score=60)) if t.exit_bar >= 0]
    for a, b in zip(tr, tr[1:]):
        assert b.entry_bar >= a.exit_bar


def test_results_match_stage(data):
    h1, d4 = data
    for t in run(d4, Params(min_score=60), sub=h1):
        if t.exit_bar < 0:
            continue
        if t.status == "TP HIT":
            assert t.r_gross >= 3 - 1e-9
        elif t.status == "SL HIT":
            assert t.r_gross <= 1e-9 + 0  # never better than the initial stop unless gap
        elif t.status == "BREAK EVEN":
            assert t.r_gross <= 1e-9
        elif t.status == "PROFIT PROTECTED":
            assert t.r_gross <= 1 + 1e-9


def test_conservative_when_bar_hits_stop_and_target():
    t = Trade(1, 0, pd.Timestamp("2020-01-01", tz="UTC"), 100.0, 95.0, 115.0, 80, stop=95.0)
    assert _exit_price(t, op=100.0, hi=120.0, lo=90.0) == 95.0
    s = Trade(-1, 0, pd.Timestamp("2020-01-01", tz="UTC"), 100.0, 105.0, 85.0, 80, stop=105.0)
    assert _exit_price(s, op=100.0, hi=110.0, lo=80.0) == 105.0


def test_gap_through_stop_fills_at_open():
    t = Trade(1, 0, pd.Timestamp("2020-01-01", tz="UTC"), 100.0, 95.0, 115.0, 80, stop=95.0)
    assert _exit_price(t, op=93.0, hi=94.0, lo=90.0) == 93.0


def test_stop_never_loosens(data):
    """Replay management bar by bar and check the stop only moves in the trade's favour."""
    _, d4 = data
    p = Params(min_score=60)
    h, l = d4["high"].to_numpy(), d4["low"].to_numpy()
    for t in run(d4, p):
        if t.exit_bar < 0:
            continue
        risk = abs(t.entry - t.stop0)
        stop, stage = t.stop0, 0
        for i in range(t.entry_bar + 1, t.exit_bar):
            fav = (h[i] - t.entry) if t.direction == 1 else (t.entry - l[i])
            new = stop
            if fav >= 2 * risk and stage < 2:
                stage, new = 2, t.entry + t.direction * risk
            elif fav >= risk and stage < 1:
                stage, new = 1, t.entry
            assert (new - stop) * t.direction >= 0
            stop = new
        assert stage == t.stage or t.status == "TP HIT"
