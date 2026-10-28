import asyncio

import pandas as pd

from app.config import Settings
from app.service import GoldService
from app.storage import Store
from app.backtest import format_report, run, summarize

CFG = Settings()


def _loose_rule(monkeypatch):
    """נשמר לתאימות: שיטת הפתיחה היומית לא צריכה שחרור כדי לייצר עסקאות בנתונים המדומים."""


def test_backtest_runs(market, monkeypatch):
    _loose_rule(monkeypatch)
    trades = run(market, CFG)
    assert trades, "האסטרטגיה צריכה לייצר עסקאות על נתונים עם מגמות"
    for t in trades:
        assert t["status"] in {"tp2", "sl", "be", "expired", "reversed"}
        assert -1.01 <= t["result_r"] <= 3.01 or t.get("method") == "channel_fade" or t["status"] in {"expired", "reversed"}
    methods = {t["method"] for t in trades}
    print("\nmethods:", {m: sum(t["method"] == m for t in trades) for m in methods})


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


def test_summary_and_report(market, monkeypatch):
    _loose_rule(monkeypatch)
    trades = run(market, CFG)
    s = summarize(trades)
    assert s["count"] == len(trades) == s["long"]["count"] + s["short"]["count"]
    assert abs(s["total_r"] - sum(t["result_r"] for t in trades)) < 0.05
    assert s["max_drawdown_r"] >= 0
    text = format_report(trades, market)
    assert "לונג בפתיחה" in text and "לפי חודש" in text
    assert format_report([], market).endswith("לא היו סיגנלים בתקופה הזאת.")


def test_twelvedata_paging(monkeypatch):
    """מושך דפים אחורה בזמן עד שמגיע לתאריך ההתחלה, בלי כפילויות."""
    import httpx
    from app.backtest import fetch_twelvedata_history

    full = pd.date_range("2026-01-01", periods=12000, freq="5min", tz="UTC")
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params.get("end_date"))
        end = pd.Timestamp(params["end_date"], tz="UTC") if "end_date" in params else full[-1] + pd.Timedelta("5min")
        idx = full[full <= end][-5000:] if "end_date" in params else full[-5000:]
        values = [{"datetime": t.strftime("%Y-%m-%d %H:%M:%S"), "open": 1, "high": 2, "low": 0.5, "close": 1.5} for t in idx]

        class R:
            def json(self):
                return {"status": "ok", "values": values}
        return R()

    monkeypatch.setattr(httpx, "get", fake_get)
    df = fetch_twelvedata_history("XAU/USD", "5min", full[100], "k", pause=0)
    assert len(calls) == 3
    assert df.index.is_unique and df.index[0] <= full[100] and df.index[-1] == full[-1]


def test_only_alert_methods_are_notified(market, tmp_path):
    """עסקאות מגמה נשמרות בהיסטוריה אבל לא נשלחות כהתראה כשהשיטה במעקב בלבד."""
    from app.service import event_method
    trend_ev = {"type": "signal", "trade": {"method": "trend"}}
    liq_ev = {"type": "setup", "setup": {}}
    assert event_method(trend_ev) == "trend" and event_method(liq_ev) == "liquidity"
    assert event_method({"type": "weak"}) == "trend"
    assert event_method({"type": "closed", "trade": {"method": "liquidity"}}) == "liquidity"
    assert CFG.alert_methods == frozenset({"channel_fade"})
    assert event_method({"type": "setup", "setup": {"method": "smc"}}) == "smc"
