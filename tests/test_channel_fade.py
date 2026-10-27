import pandas as pd

from app.config import Settings
from app.messages import event_message
from app.strategy import ChannelFadeStrategy, Strategy

CFG = Settings()


def bar(t, c, h=None, l=None):
    return pd.Series(dict(t=t, open=c, high=h if h is not None else c + 0.3, low=l if l is not None else c - 0.3,
                          close=c, atr_1h=10.0))


def warmed(price_path_end=4150.0):
    """6 ימים עם טווח יומי של 20$, ואז ירידה של 15$ ב-4 השעות שלפני 02:00 ניו יורק (06:00 UTC בקיץ)."""
    st = ChannelFadeStrategy(CFG)
    t = pd.Timestamp("2026-10-12 00:05", tz="UTC")
    end = pd.Timestamp("2026-10-20 06:00", tz="UTC")
    while t < end:
        hrs = (end - t) / pd.Timedelta(hours=1)
        c = 4165.0 if hrs > 4 else 4165.0 - (4 - hrs) / 4 * 15
        st.on_bar(bar(t, c, h=c + 10 if t.hour == 12 else None, l=c - 10 if t.hour == 13 else None))
        t += pd.Timedelta(minutes=5)
    return st, t + pd.Timedelta(minutes=5)   # הנר הבא נפתח ב-06:00 UTC = 02:00 ניו יורק


def test_fade_signal_at_london_killzone():
    st, t = warmed()
    assert len(st.ranges) >= 5
    ev = st.on_bar(bar(t, 4150.0))           # נר שנפתח ב-02:00 ניו יורק
    sig = [e for e in ev if e["type"] == "cf_signal"]
    assert sig, ev
    s = sig[0]["trade"]
    assert s["direction"] == 1 and s["method"] == "channel_fade"
    k = 4150.0 / 4150
    assert s["entry"] == round(4150 - 0.5 * k, 2) and s["sl"] == round(s["far"] - 10 * k, 2)
    assert [round(x - s["entry"], 1) for x in s["tps"]] == [5.0, 10.0, 15.0]
    msg = event_message(sig[0])
    assert "TP1" in msg and "SL" in msg and "ניסיונית" in msg


def test_fill_tps_and_close():
    st, t = warmed()
    st.on_bar(bar(t, 4150.0))
    s = st.setup
    t += pd.Timedelta(minutes=5)
    ev = st.on_bar(bar(t, s["entry"] - 1))
    assert ev[0]["type"] == "cf_filled" and st.trade
    t += pd.Timedelta(minutes=5)
    ev = st.on_bar(bar(t, s["tps"][1], h=s["tps"][1] + 0.2))
    assert [e["n"] for e in ev if e["type"] == "cf_tp"] == [1, 2]
    t += pd.Timedelta(minutes=5)
    ev = st.on_bar(bar(t, s["sl"] - 1, l=s["sl"] - 1))       # שני יעדים ואז סטופ
    closed = [e for e in ev if e["type"] == "closed"][0]["trade"]
    risk = s["entry"] - s["sl"]
    assert closed["status"] == "sl" and closed["result_r"] == round((5 / risk + 10 / risk - 1) / 3, 2)
    assert "TP2 הושג" in event_message({"type": "cf_tp", "n": 2, "trade": {**s, "hits": 2}})


def test_cancel_and_combined_state():
    st, t = warmed()
    st.on_bar(bar(t, 4150.0))
    for _ in range(49):
        t += pd.Timedelta(minutes=5)
        ev = st.on_bar(bar(t, 4170.0))
    assert any(e["type"] == "cf_cancel" for e in ev) or st.setup is None
    s = Strategy(CFG)
    s2 = Strategy(CFG, s.to_state())
    assert s2.channel.to_state() == s.channel.to_state()
