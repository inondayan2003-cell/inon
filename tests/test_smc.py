import pandas as pd

from app.config import Settings
from app.messages import event_message
from app.strategy import SMCStrategy
from tests.test_liquidity import SWEEP_UP

CFG = Settings()
T0 = pd.Timestamp("2026-10-21 11:00", tz="UTC")  # 07:00 ניו יורק


def bar(i, o, h, l, c, t0=T0, **kw):
    row = dict(t=t0 + pd.Timedelta(minutes=5 * i), open=o, high=h, low=l, close=c, session="2026-10-21",
               pdl=2000.0, pdh=2060.0, asia_low=1990.0, asia_high=2050.0, lon_low=1985.0, lon_high=2055.0,
               kz=2, atr_15m=4.0, atr_5m=2.0, score_1h=10.0, score_4h=0.0)
    row.update(kw)
    return pd.Series(row)


def test_model_a_sweep_fvg_with_3r_target():
    st = SMCStrategy(CFG)
    ev = []
    for i, b in enumerate(SWEEP_UP):
        ev += st.on_bar(bar(i, *b))
    s = [e for e in ev if e["type"] == "setup"][0]["setup"]
    assert s["method"] == "smc" and s["direction"] == 1 and s["name"] == "PDL"
    risk = s["entry"] - s["sl"]
    assert abs((s["tp1"] - s["entry"]) - 1.5 * risk) < 0.02           # יעד 1 = 1.5R
    assert (s["tp2"] - s["entry"]) >= 3 * risk - 0.02                  # יעד סופי לפחות 3R
    msg = event_message({"type": "setup", "setup": s})
    assert "SMC" in msg and "מודל A" in msg and "Buy Limit" in msg


def test_model_a_requires_displacement():
    st = SMCStrategy(CFG)
    ev = []
    for i, b in enumerate(SWEEP_UP):
        ev += st.on_bar(bar(i, *b, atr_5m=10.0))  # כל נר "חלש" ביחס ל-ATR - אין Displacement
    assert not [e for e in ev if e["type"] == "setup"]


def test_partial_take_profit_result():
    st = SMCStrategy(CFG)
    for i, b in enumerate(SWEEP_UP):
        st.on_bar(bar(i, *b))
    s, n = st.setup, len(SWEEP_UP)
    st.on_bar(bar(n, 2008, 2008.5, s["entry"] - 0.1, 2004))                      # מילוי
    st.on_bar(bar(n + 1, 2004, s["tp1"] + 0.1, 2003.9, s["tp1"]))                # יעד 1
    ev = st.on_bar(bar(n + 2, s["tp1"], s["tp1"] + 0.5, s["entry"] - 0.1, s["entry"]))  # חזר לכניסה
    tr = ev[-1]["trade"]
    assert tr["status"] == "be" and abs(tr["result_r"] - 0.75) < 0.02           # חצי ב-1.5R + חצי ב-0


def test_model_b_session_liquidity_short():
    st = SMCStrategy(CFG)
    early = pd.Timestamp("2026-10-21 09:00", tz="UTC")  # 05:00 ניו יורק, לפני ניו יורק
    st.on_bar(bar(0, 2049, 2051.5, 2048.5, 2049.5, t0=early, kz=0))  # נלקח השיא של אסיה
    assert st.day["swept"] == {"ASH": 1}
    path = [(2049, 2049.8, 2048.6, 2049.2)] * 6 + [
        (2049.2, 2049.4, 2047.0, 2047.2),   # נר 1 של ה-FVG
        (2047.2, 2047.3, 2043.0, 2043.2),   # displacement
        (2043.2, 2046.5, 2042.0, 2042.4),   # תיקון קטן
    ]
    ev = []
    for i, b in enumerate(path):
        ev += st.on_bar(bar(i, *b, kz=2, score_1h=-10.0))
    ev += st.on_bar(bar(len(path), 2042.4, 2042.6, 2038.0, 2038.4, kz=2, score_1h=-10.0))  # BOS + FVG
    setups = [e for e in ev if e["type"] == "setup"]
    assert setups and setups[0]["setup"]["direction"] == -1
    s = setups[0]["setup"]
    assert s["sl"] > s["entry"] > s["tp1"] > s["tp2"]
    assert "מודל B" in event_message(setups[0])


def test_daily_cap_and_late_friday():
    st = SMCStrategy(CFG)
    fri = pd.Timestamp("2026-10-23 15:00", tz="UTC")  # שישי 11:00 ניו יורק
    ev = []
    for i, b in enumerate(SWEEP_UP):
        ev += st.on_bar(bar(i, *b, t0=fri, session="2026-10-23"))
    assert not [e for e in ev if e["type"] == "setup"]
