import pandas as pd

from app.config import Settings
from app.messages import event_message
from app.strategy import ChannelFadeStrategy, Strategy

CFG = Settings()


def bar(t, c, h=None, l=None):
    return pd.Series(dict(t=t, open=c, high=h if h is not None else c + 0.3, low=l if l is not None else c - 0.3,
                          close=c, atr_1h=10.0))


def warmed():
    """ירידה של 20$ ב-4 שעות עד 09:15 שעון ישראל (06:15 UTC), ואז נר ראשון של תיקון (עוד לא מעל המחיר של לפני 15 דקות)."""
    st = ChannelFadeStrategy(CFG)
    t = pd.Timestamp("2026-10-20 01:00", tz="UTC")
    turn = pd.Timestamp("2026-10-20 06:15", tz="UTC")
    while t <= turn:
        hrs = (turn - t) / pd.Timedelta(hours=1)
        st.on_bar(bar(t, 4170.0 if hrs > 4 else 4150.0 + hrs / 4 * 20))
        t += pd.Timedelta(minutes=5)
    for c in (4150.5,):
        st.on_bar(bar(t, c))
        t += pd.Timedelta(minutes=5)
    return st, t


def test_fade_after_bounce_in_morning_window():
    st, t = warmed()
    ev = st.on_bar(bar(t, 4152.0))
    sig = [e for e in ev if e["type"] == "cf_signal"]
    assert sig, ev
    s = sig[0]["trade"]
    k = 4152.0 / 4150
    assert s["direction"] == 1 and s["window"] == "בוקר"
    assert s["entry"] == round(4152 - 0.5 * k, 2) and s["sl"] == round(s["far"] - 10 * k, 2)
    assert [round((x - s["entry"]) / k, 1) for x in s["tps"]] == [5.0, 10.0, 15.0]
    msg = event_message(sig[0])
    assert "TP1" in msg and "SL" in msg and "לכניסה" in msg
    t += pd.Timedelta(minutes=5)
    assert not [e for e in st.on_bar(bar(t, 4152.0)) if e["type"] == "cf_signal"]   # סיגנל אחד לחלון


def test_no_signal_without_bounce_or_outside_window():
    st, t = warmed()
    assert not [e for e in st.on_bar(bar(t, 4149.0)) if e["type"] == "cf_signal"]   # עדיין יורד
    st2 = ChannelFadeStrategy(CFG)
    t = pd.Timestamp("2026-10-20 06:00", tz="UTC")   # 09:00-13:55 ישראל: יורד, התיקון רק ב-13:55
    for i in range(60):
        st2.on_bar(bar(t + pd.Timedelta(minutes=5 * i), 4200.0 - i * 0.5 + (2 if i == 59 else 0)))
    assert st2.setup is None


def test_breakeven_after_tp1():
    st, t = warmed()
    st.on_bar(bar(t, 4152.0))
    s = st.setup
    t += pd.Timedelta(minutes=5)
    assert st.on_bar(bar(t, s["entry"] - 0.5))[0]["type"] == "cf_filled"
    t += pd.Timedelta(minutes=5)
    ev = st.on_bar(bar(t, s["tps"][0], h=s["tps"][0] + 0.1))
    assert [e["n"] for e in ev if e["type"] == "cf_tp"] == [1]
    assert "לכניסה" in event_message([e for e in ev if e["type"] == "cf_tp"][0])
    t += pd.Timedelta(minutes=5)
    ev = st.on_bar(bar(t, s["entry"] - 0.2, l=s["entry"] - 0.2))   # חזר לכניסה: נסגר באפס על השאר
    closed = [e for e in ev if e["type"] == "closed"][0]["trade"]
    risk = s["entry"] - s["sl"]
    assert closed["status"] == "be" and closed["result_r"] == round((s["tps"][0] - s["entry"]) / risk / 3, 2)


def test_full_stop_without_tp():
    st, t = warmed()
    st.on_bar(bar(t, 4152.0))
    s = st.setup
    t += pd.Timedelta(minutes=5)
    st.on_bar(bar(t, s["entry"] - 0.5))
    t += pd.Timedelta(minutes=5)
    closed = [e for e in st.on_bar(bar(t, s["sl"] - 1, l=s["sl"] - 1)) if e["type"] == "closed"][0]["trade"]
    assert closed["status"] == "sl" and closed["result_r"] == -1.0


def test_cancel_and_combined_state():
    st, t = warmed()
    st.on_bar(bar(t, 4152.0))
    ev = []
    for _ in range(30):
        t += pd.Timedelta(minutes=5)
        ev += st.on_bar(bar(t, 4170.0))
    assert any(e["type"] == "cf_cancel" for e in ev) and st.setup is None
    s = Strategy(CFG)
    s2 = Strategy(CFG, s.to_state())
    assert s2.channel.to_state() == s.channel.to_state()
