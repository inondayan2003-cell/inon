import asyncio

import pandas as pd

from app.config import Settings
from app.service import GoldService
from app.storage import Store
from backtest import run

CFG = Settings()


def test_backtest_runs(market):
    trades = run(market, CFG)
    assert trades, "האסטרטגיה צריכה לייצר עסקאות על נתונים עם מגמות"
    for t in trades:
        assert t["status"] in {"tp2", "sl", "be", "expired", "reversed"}
        assert -1.01 <= t["result_r"] <= 1.51 or t["status"] in {"expired", "reversed"}


class FakeFeed:
    def __init__(self, md):
        self.md = md

    def get(self):
        return self.md


def test_service_tick_sends_and_persists(market, tmp_path):
    store = Store(str(tmp_path / "t.db"))
    sent = []
    svc = GoldService(CFG, store, FakeFeed(market))

    async def notify(text):
        sent.append(text)

    svc.notify = notify
    cut = market.m5.index[-120]
    from app.data import MarketData
    # מריצים את השירות "בזמן אמת" נר אחר נר על פני 10 שעות
    async def go():
        for i in range(120, 0, -1):
            end = market.m5.index[-i]
            svc.feed = FakeFeed(MarketData(m5=market.m5[market.m5.index <= end], h1=market.h1[market.h1.index < end.floor("1h")],
                                           symbol="T", source="t"))
            await svc.tick(now=end + pd.Timedelta(minutes=5))
    asyncio.run(go())
    assert svc.snapshot is not None
    assert store.get("strategy")["last_t"] is not None
    assert cut < pd.Timestamp(store.get("strategy")["last_t"])
    print(f"\n{len(sent)} הודעות, {len(store.trades())} עסקאות")
    if sent:
        print(sent[0])
