import numpy as np
import pandas as pd

from app.config import Settings
from app.messages import event_message
from app.regime import daily_bars, daily_lookup
from app.strategy import DailyLongStrategy, Strategy

CFG = Settings()
UP = {"day": "2026-11-09", "close": 4100.0, "sma": 3900.0, "atr": 60.0}
DOWN = {**UP, "close": 3800.0}


def bar(t, c, lo=None, daily=UP):
    return pd.Series(dict(t=pd.Timestamp(t, tz="UTC"), open=c, high=c + 1, low=lo if lo is not None else c - 1,
                          close=c, daily=daily))


def test_buy_hold_and_exit_on_trend_change():
    st = DailyLongStrategy(CFG)
    assert st.on_bar(bar("2026-11-10 05:00", 4100)) == []                 # 07:00 ישראל: מוקדם מדי
    ev = st.on_bar(bar("2026-11-10 06:05", 4100))                         # 08:05 ישראל
    assert ev[0]["type"] == "dl_signal" and st.trade["sl"] == 4100 - 90
    msg = event_message(ev[0])
    assert "BUY עכשיו" in msg and "SL: 4010" in msg
    assert st.on_bar(bar("2026-11-10 12:00", 4120)) == []                 # פעם אחת ביום
    ev = st.on_bar(bar("2026-11-11 06:05", 4130))
    assert ev[0]["state"] == "hold" and "יום 1 מתוך 5" in event_message(ev[0])
    ev = st.on_bar(bar("2026-11-12 06:05", 4050, daily=DOWN))
    assert [e["type"] for e in ev] == ["dl_exit", "closed"] and "לצאת" in event_message(ev[0])
    assert ev[1]["trade"]["status"] == "reversed" and ev[1]["trade"]["result_r"] == round(-50 / 90, 2)
    ev = st.on_bar(bar("2026-11-13 06:05", 4040, daily=DOWN))
    assert ev[0]["state"] == "out" and st.trade is None and "לא לקנות" in event_message(ev[0])


def test_stop_time_exit_and_weekend():
    st = DailyLongStrategy(CFG)
    st.on_bar(bar("2026-11-09 06:05", 4100))
    ev = st.on_bar(bar("2026-11-09 15:00", 4005, lo=4005))
    assert ev[0]["trade"]["status"] == "sl" and ev[0]["trade"]["result_r"] == -1.0
    assert st.on_bar(bar("2026-11-14 06:05", 4100)) == []                 # שבת
    st.on_bar(bar("2026-11-16 06:05", 4100))
    for d in ("17", "18", "19", "20"):
        st.on_bar(bar(f"2026-11-{d} 06:05", 4110))
    ev = st.on_bar(bar("2026-11-23 06:05", 4160))                         # יום 5: נסגר ונפתח מחדש
    assert [e["type"] for e in ev] == ["closed", "dl_signal"] and ev[0]["trade"]["status"] == "expired"
    assert ev[0]["trade"]["result_r"] == round(60 / 90, 2) and st.trade["entry"] == 4160


def test_daily_bars_and_combined_state():
    idx = pd.date_range("2025-10-01", "2026-11-10 06:00", freq="1h", tz="UTC")
    idx = idx[idx.dayofweek < 5]
    c = 3000 + np.arange(len(idx)) * 0.2
    h1 = pd.DataFrame({"open": c, "high": c + 2, "low": c - 2, "close": c}, index=idx)
    d = daily_lookup(daily_bars(h1), pd.Timestamp("2026-11-10 06:05", tz="UTC"))
    assert d and d["close"] > d["sma"] and d["atr"] > 0 and d["day"] == "2026-11-09"
    assert daily_lookup(daily_bars(h1.iloc[-500:]), pd.Timestamp("2026-11-10 06:05", tz="UTC")) is None
    s = Strategy(CFG)
    s.on_bar(bar("2026-11-10 06:05", 4100))
    s2 = Strategy(CFG, s.to_state())
    assert len(s2.open_trades) == 1 and s2.daily.to_state() == s.daily.to_state()
