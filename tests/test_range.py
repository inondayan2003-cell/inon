import pandas as pd

from app.config import Settings
from app.messages import event_message
from app.strategy import RangeStrategy, Strategy

CFG = Settings()
T0 = pd.Timestamp("2026-10-21 10:00", tz="UTC")  # 06:00 ניו יורק - אחרי שטווח לונדון ידוע


def bar(i, c, h=None, l=None, **kw):
    row = dict(t=T0 + pd.Timedelta(minutes=5 * i), open=c, high=h if h is not None else c + 0.3,
               low=l if l is not None else c - 0.3, close=c, session="2026-10-21", lon_high=2010.0,
               lon_low=1990.0, pdh=2030.0, pdl=1970.0, atr_15m=4.0, composite=0.0)
    row.update(kw)
    return pd.Series(row)


def test_fade_london_high_hits_target():
    rs = RangeStrategy(CFG)
    ev = rs.on_bar(bar(0, 2011.0))  # סגירה מעל השיא של לונדון -> שורט
    tr = ev[0]["trade"]
    assert ev[0]["type"] == "signal" and tr["direction"] == -1 and tr["method"] == "range"
    assert tr["sl"] == 2017.0 and tr["tp2"] == 2002.0  # סטופ 1.5 ATR, יעד 2.25 ATR
    assert "פייד" in event_message(ev[0])
    assert rs.on_bar(bar(1, 2012.0)) == []           # אותה פריצה שוב - לא נספרת
    ev = rs.on_bar(bar(2, 2003.0, l=2001.9))
    assert ev[0]["trade"]["status"] == "tp2" and ev[0]["trade"]["result_r"] == 1.5


def test_follow_pdl_stop_and_time_exit():
    rs = RangeStrategy(CFG)
    ev = rs.on_bar(bar(0, 1969.0, lon_low=None, lon_high=None))  # שבירת השפל של אתמול -> שורט
    assert ev[0]["trade"]["direction"] == -1
    ev = rs.on_bar(bar(1, 1974.0, h=1975.1, lon_low=None, lon_high=None))
    assert ev[0]["trade"]["status"] == "sl" and ev[0]["trade"]["result_r"] == -1.0
    rs2 = RangeStrategy(CFG)
    rs2.on_bar(bar(0, 1989.0, pdl=None, pdh=None))  # שבירת השפל של לונדון -> לונג (פייד)
    evs = []
    for i in range(1, 25):
        evs += rs2.on_bar(bar(i, 1990.0, pdl=None, pdh=None))
    assert evs[-1]["trade"]["status"] == "expired" and len(evs) == 1  # אחרי שעתיים בדיוק


def test_parallel_trades_and_state_roundtrip():
    rs = RangeStrategy(CFG)
    rs.on_bar(bar(0, 2031.0))
    assert len(rs.trades) == 2  # גם פייד לשיא לונדון (שורט) וגם המשך לשיא אתמול (לונג)
    rs2 = RangeStrategy(CFG, rs.to_state(), {"next": 3})
    assert len(rs2.trades) == 2 and rs2.done == rs.done
