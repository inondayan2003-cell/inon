import pandas as pd

from app.config import Settings
from app.messages import event_message
from app.strategy import LiquidityStrategy, Strategy

CFG = Settings()
T0 = pd.Timestamp("2026-10-21 11:00", tz="UTC")  # 07:00 ניו יורק - Killzone של ניו יורק


def bar(i, o, h, l, c, **kw):
    row = dict(t=T0 + pd.Timedelta(minutes=5 * i), open=o, high=h, low=l, close=c, session="2026-10-21",
               pdl=2000.0, pdh=2040.0, asia_low=1990.0, asia_high=2030.0, kz=2, atr_15m=4.0, atr_5m=2.0,
               score_1h=10.0, score_4h=0.0, composite=0.0, score_5m=0.0, score_15m=0.0,
               adx_15m=10.0, ema21_15m=c, swing_low_15m=l, swing_high_15m=h)
    row.update(kw)
    return pd.Series(row)


# ירידה לכיוון השפל של אתמול (2000), סוויפ ל-1997, היפוך חד למעלה עם פער (FVG) ושבירת מבנה
SWEEP_UP = [
    (2006, 2007, 2004, 2005), (2005, 2006, 2003, 2004), (2004, 2005, 2002, 2003),
    (2003, 2004, 2001, 2002), (2002, 2003, 2000.5, 2001),
    (2001, 2001.5, 1997, 1998),        # סוויפ: מתחת ל-2000
    (1998, 2003, 1997.5, 2002.5),      # נר היפוך חזק
    (2002.5, 2009, 2002, 2008.5),      # displacement: השפל (2002) מעל השיא של לפני שני נרות (2001.5) = FVG
]


def run(ls, bars, start=0):
    events = []
    for i, b in enumerate(bars):
        events += ls.on_bar(bar(start + i, *b))
    return events


def test_full_long_setup_lifecycle():
    ls = LiquidityStrategy(CFG)
    ev = run(ls, SWEEP_UP)
    setups = [e for e in ev if e["type"] == "setup"]
    assert len(setups) == 1, ev
    s = setups[0]["setup"]
    assert s["direction"] == 1 and s["name"] == "PDL" and s["level"] == 2000.0
    assert s["sl"] < 1997 < s["entry"] < s["tp1"] < s["tp2"]
    assert 2001.5 <= s["entry"] <= 2003  # אמצע ה-FVG
    assert "השפל של אתמול" in event_message(setups[0])

    n = len(SWEEP_UP)
    ev = run(ls, [(2008, 2008.5, s["entry"] - 0.2, 2004)], n)           # חזרה לאזור הכניסה
    assert [e["type"] for e in ev] == ["filled"] and ls.trade.method == "liquidity"
    ev = run(ls, [(2004, s["tp1"] + 0.1, 2003.5, s["tp1"])], n + 1)     # יעד 1
    assert ev[0]["type"] == "tp1" and ls.trade.stop == s["entry"]
    ev = run(ls, [(s["tp1"], s["tp2"] + 0.1, s["tp1"] - 0.5, s["tp2"])], n + 2)  # יעד 2
    tr = ev[-1]["trade"]
    assert tr["status"] == "tp2" and tr["result_r"] > 1.4
    assert "💧 נזילות" in event_message(ev[-1])


def test_level_swept_only_once_per_session():
    ls = LiquidityStrategy(CFG)
    run(ls, SWEEP_UP)
    ls.setup = None
    again = run(ls, SWEEP_UP, len(SWEEP_UP))
    assert not [e for e in again if e["type"] == "setup"]


def test_one_setup_when_two_levels_swept_together():
    ls = LiquidityStrategy(CFG)
    evs = []
    for i, b in enumerate(SWEEP_UP):
        evs += ls.on_bar(bar(i, *b, asia_low=2005.0))  # גם שפל אסיה וגם שפל אתמול נלקחו
    assert len([e for e in evs if e["type"] == "setup"]) == 1 and not ls.cands


def test_no_setup_outside_killzone_or_against_strong_trend():
    quiet = LiquidityStrategy(CFG)
    evs = []
    for i, b in enumerate(SWEEP_UP):
        evs += quiet.on_bar(bar(i, *b, kz=0))
    assert not [e for e in evs if e["type"] == "setup"]
    bear = LiquidityStrategy(CFG)
    evs = []
    for i, b in enumerate(SWEEP_UP):
        evs += bear.on_bar(bar(i, *b, score_1h=-60.0, score_4h=-50.0))
    assert not [e for e in evs if e["type"] == "setup"]


def test_setup_cancelled_when_not_filled():
    ls = LiquidityStrategy(CFG)
    run(ls, SWEEP_UP)
    s = ls.setup
    hold = [(2008.5, 2009, s["entry"] + 1, 2008.6)] * (ls.SETUP_BARS + 1)
    ev = run(ls, hold, len(SWEEP_UP))
    assert ev[-1]["type"] == "cancelled" and ls.setup is None
    assert "בוטלה" in event_message(ev[-1])


def test_combined_state_roundtrip_and_legacy_state():
    st = Strategy(CFG)
    for i, b in enumerate(SWEEP_UP):
        st.on_bar(bar(i, *b))
    assert st.pending is not None
    st2 = Strategy(CFG, st.to_state())
    assert st2.pending == st.pending and st2.ids["next"] == st.ids["next"]
    legacy = {"active_dir": 1, "last_signal": {}, "next_id": 7, "last_t": "2026-10-20T10:00:00+00:00",
              "trade": None}
    st3 = Strategy(CFG, legacy)
    assert st3.trend.active_dir == 1 and st3.ids["next"] == 7 and st3.last_t == legacy["last_t"]


def test_short_setup_is_mirror_of_long():
    """אותו תרחיש בהיפוך מחירים סביב 2020: סוויפ של השיא של אתמול (2040) וסיגנל שורט."""
    m = lambda x: 4040 - x
    ls = LiquidityStrategy(CFG)
    evs = []
    for i, (o, h, l, c) in enumerate(SWEEP_UP):
        evs += ls.on_bar(bar(i, m(o), m(l), m(h), m(c), score_1h=-10.0, score_4h=0.0))
    s = [e for e in evs if e["type"] == "setup"][0]["setup"]
    assert s["direction"] == -1 and s["name"] == "PDH"
    assert s["tp2"] < s["tp1"] < s["entry"] < 2043 < s["sl"]
    assert "Sell Limit" in event_message({"type": "setup", "setup": s})


def test_loose_liquidity_enters_at_market_outside_killzone():
    from app.strategy import LiquidityLooseStrategy
    ls = LiquidityLooseStrategy(CFG)
    evs = []
    for i, b in enumerate(SWEEP_UP):
        evs += ls.on_bar(bar(i, *b, kz=0, atr_15m=5.0))  # מחוץ לשעות לונדון/ניו יורק
    sig = [e for e in evs if e["type"] == "signal"]
    assert sig and sig[0]["trade"]["method"] == "liquidity" and sig[0]["trade"]["direction"] == 1
    assert sig[0]["trade"]["entry"] == SWEEP_UP[-1][3]  # כניסה במחיר הסגירה של נר השבירה
    msg = event_message(sig[0])
    assert "כניסה עכשיו" in msg and "דמו" in msg
