import pandas as pd

from app.config import Settings
from app.messages import event_message
from app.strategy import ReopenLongStrategy, Strategy

CFG = Settings()
# 21/10/2026: 17:00 ניו יורק = 21:00 UTC (שעון קיץ). הפתיחה ב-18:00 ניו יורק = 22:00 UTC.
CLOSE = pd.Timestamp("2026-10-21 20:55", tz="UTC")   # נר אחרון לפני ההפסקה (נסגר ב-16:55+5)
REOPEN = pd.Timestamp("2026-10-21 22:05", tz="UTC")  # סגירת הנר הראשון אחרי הפתיחה


def bar(t, c, h=None, l=None, atr=10.0):
    return pd.Series(dict(t=t, open=c, high=h if h is not None else c + 0.5, low=l if l is not None else c - 0.5,
                          close=c, atr_1h=atr))


def test_signal_on_first_bar_after_daily_break():
    st = ReopenLongStrategy(CFG)
    assert st.on_bar(bar(CLOSE, 4000.0)) == []
    ev = st.on_bar(bar(REOPEN, 4002.0))
    tr = ev[0]["trade"]
    assert ev[0]["type"] == "signal" and tr["direction"] == 1 and tr["method"] == "reopen_long"
    assert tr["sl"] == 3992.0 and tr["tp2"] == 4032.0          # סטופ 1 ATR, יעד 1:3
    assert ev[0]["expires"] == pd.Timestamp("2026-10-22 02:00", tz="UTC").isoformat()
    msg = event_message(ev[0])
    assert "לונג" in msg and "1:3" in msg


def test_once_per_day_and_clock_fallback():
    st = ReopenLongStrategy(CFG)
    # בלי פער בנתונים (ספק שממלא את ההפסקה): הנר הראשון מ-18:00 ניו יורק
    t = pd.Timestamp("2026-10-21 22:00", tz="UTC")   # נר 17:55-18:00 ניו יורק
    assert st.on_bar(bar(t, 4000.0)) == []
    assert st.on_bar(bar(t + pd.Timedelta(minutes=5), 4000.0))[0]["type"] == "signal"
    assert st.on_bar(bar(t + pd.Timedelta(minutes=10), 4000.0)) == []   # פעם אחת ביום


def test_exits_target_stop_time():
    st = ReopenLongStrategy(CFG)
    st.on_bar(bar(CLOSE, 4000.0))
    st.on_bar(bar(REOPEN, 4000.0))
    ev = st.on_bar(bar(REOPEN + pd.Timedelta(minutes=5), 4020.0, h=4030.5))
    assert ev[0]["trade"]["status"] == "tp2" and ev[0]["trade"]["result_r"] == 3.0

    st = ReopenLongStrategy(CFG)
    st.on_bar(bar(CLOSE, 4000.0))
    st.on_bar(bar(REOPEN, 4000.0))
    ev = st.on_bar(bar(REOPEN + pd.Timedelta(minutes=5), 4000.0, h=4031.0, l=3989.0))  # שניהם באותו נר -> סטופ
    assert ev[0]["trade"]["status"] == "sl" and ev[0]["trade"]["result_r"] == -1.0

    st = ReopenLongStrategy(CFG)
    st.on_bar(bar(CLOSE, 4000.0))
    st.on_bar(bar(REOPEN, 4000.0))
    evs = []
    t = REOPEN
    while not evs:
        t += pd.Timedelta(minutes=5)
        evs = st.on_bar(bar(t, 4004.0))
    assert evs[0]["trade"]["status"] == "expired" and evs[0]["trade"]["result_r"] == 0.4
    assert t == pd.Timestamp("2026-10-22 02:00", tz="UTC")


def test_combined_strategy_state_roundtrip():
    s = Strategy(CFG)
    s.on_bar(bar(CLOSE, 4000.0))
    s.on_bar(bar(REOPEN, 4000.0))
    s2 = Strategy(CFG, s.to_state())
    assert len(s2.open_trades) == 1 and s2.reopen.last_day == s.reopen.last_day
