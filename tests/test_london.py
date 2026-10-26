import pandas as pd

from app.config import Settings
from app.messages import event_message
from app.strategy import LondonShortStrategy

CFG = Settings()
T0 = pd.Timestamp("2026-10-21 08:00", tz="UTC")  # 04:00 ניו יורק - סשן לונדון


def bar(i, c, h=None, l=None, ny=240, **kw):
    row = dict(t=T0 + pd.Timedelta(minutes=5 * i), open=c, high=h if h is not None else c + 0.3,
               low=l if l is not None else c - 0.3, close=c, atr_15m=4.0, wick_up=0.1, vol_regime=0.6,
               ret12=0.0, ny_open_min=ny)
    row.update(kw)
    return pd.Series(row)


def test_short_signal_levels_and_message():
    st = LondonShortStrategy(CFG)
    ev = st.on_bar(bar(0, 4000.0))
    tr = ev[0]["trade"]
    assert ev[0]["type"] == "signal" and tr["direction"] == -1 and tr["method"] == "london_short"
    assert tr["sl"] == 4006.0 and tr["tp2"] == 3988.0   # סטופ 1.5 ATR, יעד פי 2
    msg = event_message(ev[0])
    assert "שורט" in msg and "1:2" in msg and "דמו" in msg


def test_fires_only_when_condition_turns_on():
    st = LondonShortStrategy(CFG)
    assert len(st.on_bar(bar(0, 4000.0))) == 1
    assert st.on_bar(bar(1, 4000.0)) == []                       # התנאי עדיין נכון - לא נכנסים שוב
    assert st.on_bar(bar(2, 4000.0, vol_regime=0.9)) == []       # התנאי כבה
    assert st.on_bar(bar(3, 4000.0))[0]["type"] == "signal"      # נדלק שוב - סיגנל חדש
    assert len(st.trades) == 2


def test_filters_and_session():
    st = LondonShortStrategy(CFG)
    assert st.on_bar(bar(0, 4000.0, ny=600)) == []          # 10:00 ניו יורק - מחוץ לחלון
    assert st.on_bar(bar(1, 4000.0, wick_up=0.5)) == []
    assert st.on_bar(bar(2, 4000.0, ret12=1.0)) == []


def test_exits_target_stop_and_time():
    st = LondonShortStrategy(CFG)
    st.on_bar(bar(0, 4000.0))
    ev = st.on_bar(bar(1, 3990.0, l=3987.9, vol_regime=0.9))
    assert ev[0]["trade"]["status"] == "tp2" and ev[0]["trade"]["result_r"] == 2.0
    st.on_bar(bar(2, 4000.0))
    ev = st.on_bar(bar(3, 4005.0, h=4006.1, l=3987.0, vol_regime=0.9))  # סטופ ויעד באותו נר -> סטופ
    assert ev[0]["trade"]["status"] == "sl" and ev[0]["trade"]["result_r"] == -1.0
    st.on_bar(bar(4, 4000.0))
    evs = []
    for i in range(5, 5 + 48):
        evs += st.on_bar(bar(i, 3998.0, vol_regime=0.9))
    assert evs[-1]["trade"]["status"] == "expired" and evs[-1]["trade"]["result_r"] == round(2 / 6, 2)
