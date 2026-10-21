import numpy as np
import pandas as pd

from app.analysis import analyze, enrich
from app.config import Settings
from app.indicators import rsi
from app.strategy import Strategy

CFG = Settings()


def test_rsi_bounds_and_trend():
    up = pd.Series(np.linspace(100, 200, 100))
    assert rsi(up).iloc[-1] == 100
    down = pd.Series(np.linspace(200, 100, 100))
    assert rsi(down).iloc[-1] < 1


def test_score_sign_follows_trend():
    idx = pd.date_range("2026-01-01", periods=400, freq="15min", tz="UTC")
    c = np.linspace(2000, 2200, 400) + np.sin(np.arange(400)) * 2
    df = pd.DataFrame({"open": c - 0.5, "high": c + 1, "low": c - 1, "close": c}, index=idx)
    assert enrich(df, "15min")["score"].iloc[-1] > 60
    df_down = df.iloc[::-1].set_axis(idx)
    assert enrich(df_down, "15min")["score"].iloc[-1] < -60


def test_analyze_snapshot(market):
    now = market.m5.index[-1] + pd.Timedelta(minutes=5)
    a = analyze(market, now, CFG)
    s = a.snapshot
    assert -100 <= s["composite"] <= 100
    assert [t["tf"] for t in s["timeframes"]] == ["4H", "1H", "15M", "5M"]
    assert {"PP", "R1", "S1", "PDH", "PDL"} <= set(s["levels"])
    assert a.timeline["t"].max() <= now
    if s["plan"]:
        p = s["plan"]
        d = s["direction"] or s["lean"]
        assert (p["entry"] - p["sl"]) * d > 0 and (p["tp2"] - p["tp1"]) * d > 0


def test_no_lookahead(market):
    """הציון בזמן t לא משתנה כשמוסיפים נתונים עתידיים."""
    now = market.m5.index[-1] + pd.Timedelta(minutes=5)
    full = analyze(market, now, CFG).timeline.set_index("t")
    cut = market.m5.index[-300]
    from app.data import MarketData, resample
    partial = MarketData(m5=market.m5[market.m5.index < cut], h1=market.h1[market.h1.index < cut.floor("1h")],
                         symbol="T", source="t")
    part = analyze(partial, cut, CFG).timeline.set_index("t")
    common = part.index[-50:]
    assert np.allclose(full.loc[common, "composite"], part.loc[common, "composite"])


def _row(t, close, composite, high=None, low=None, **kw):
    base = dict(t=pd.Timestamp(t, tz="UTC"), open=close, high=high or close + 0.5, low=low or close - 0.5,
                close=close, composite=composite, score_5m=composite, score_15m=composite,
                score_1h=composite, score_4h=composite, atr_15m=4.0, ema21_15m=close - 2,
                adx_15m=30.0, swing_low_15m=close - 5, swing_high_15m=close + 5)
    base.update(kw)
    return pd.Series(base)


def test_strategy_long_lifecycle():
    s = Strategy(CFG)
    ev = s.on_bar(_row("2026-10-21 10:00", 2400, 70))
    assert [e["type"] for e in ev] == ["signal"]
    tr = s.trade
    assert tr.direction == 1 and tr.sl < tr.entry < tr.tp1 < tr.tp2
    # אותו כיוון שוב - אין סיגנל כפול
    assert s.on_bar(_row("2026-10-21 10:05", 2401, 70)) == []
    ev = s.on_bar(_row("2026-10-21 10:10", tr.tp1, 70, high=tr.tp1 + 0.1))
    assert ev[0]["type"] == "tp1" and s.trade.stop == tr.entry
    ev = s.on_bar(_row("2026-10-21 10:15", tr.tp2, 70, high=tr.tp2 + 0.1, low=tr.entry + 1))
    assert ev[-1]["type"] == "closed" and ev[-1]["trade"]["status"] == "tp2"
    assert ev[-1]["trade"]["result_r"] == 1.5


def test_strategy_stop_and_state_roundtrip():
    s = Strategy(CFG)
    s.on_bar(_row("2026-10-21 10:00", 2400, -70, ema21_15m=2402))
    assert s.trade.direction == -1
    s = Strategy(CFG, s.to_state())  # שמירה וטעינה כמו בשרת
    ev = s.on_bar(_row("2026-10-21 10:05", 2405, -70, high=s.trade.sl + 1, ema21_15m=2402))
    assert ev[0]["trade"]["status"] == "sl" and ev[0]["trade"]["result_r"] == -1.0
    # בתוך ה-cooldown אין סיגנל חדש באותו כיוון
    assert s.on_bar(_row("2026-10-21 10:10", 2400, -70, ema21_15m=2402)) == []


def test_filters_block_entry():
    s = Strategy(CFG)
    assert s.on_bar(_row("2026-10-21 10:00", 2400, 70, adx_15m=10)) == []          # אין מגמה
    assert s.on_bar(_row("2026-10-21 10:05", 2400, 70, ema21_15m=2380)) == []      # מתוח מדי
    assert s.on_bar(_row("2026-10-21 10:10", 2400, 70, score_4h=-10)) == []        # 4H נגד
    assert s.on_bar(_row("2026-10-21 10:15", 2400, 70), allow_entry=False) == []  # נר ישן


def test_weak_and_reverse():
    s = Strategy(CFG)
    s.on_bar(_row("2026-10-21 10:00", 2400, 70))
    ev = s.on_bar(_row("2026-10-21 10:05", 2400, 10))
    assert [e["type"] for e in ev] == ["weak"]
    ev = s.on_bar(_row("2026-10-21 10:10", 2399, -70, ema21_15m=2401))
    assert [e["type"] for e in ev] == ["closed", "signal"]
    assert ev[0]["trade"]["status"] == "reversed"
