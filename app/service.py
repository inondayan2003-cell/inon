"""הלולאה הראשית: מביאה נתונים, מנתחת, מריצה את האסטרטגיה ושולחת התראות."""
import asyncio
import logging

import pandas as pd

from .analysis import Analysis, analyze
from .config import Settings
from .data import DataFeed
from .messages import event_message
from .storage import Store
from .strategy import Strategy

log = logging.getLogger(__name__)
FRESH = pd.Timedelta(minutes=15)  # לא שולחים סיגנל כניסה על נר ישן (למשל אחרי הפעלה מחדש)


def event_method(ev: dict) -> str:
    if "trade" in ev:
        return ev["trade"].get("method", "trend")
    if "setup" in ev:
        return ev["setup"].get("method", "liquidity")
    return "trend"  # weak = מגמה


class GoldService:
    def __init__(self, cfg: Settings, store: Store, feed: DataFeed | None = None):
        self.cfg = cfg
        self.store = store
        self.feed = feed or DataFeed(cfg)
        self.analysis: Analysis | None = None
        self.last_error: str | None = None
        self.notify = None  # async callable(text) - מוגדר ע"י הבוט

    @property
    def snapshot(self) -> dict | None:
        return self.analysis.snapshot if self.analysis else None

    def strategy_state(self) -> dict:
        return self.store.get("strategy", {})

    def positions(self) -> dict:
        strat = Strategy(self.cfg, self.strategy_state())
        return {"open_trades": strat.open_trades, "pending": strat.pending,
                "alert_methods": sorted(self.cfg.alert_methods)}

    async def tick(self, now: pd.Timestamp | None = None) -> list[dict]:
        now = now or pd.Timestamp.now(tz="UTC")
        md = await asyncio.to_thread(self.feed.get)
        analysis = await asyncio.to_thread(analyze, md, now, self.cfg)
        self.analysis = analysis

        strat = Strategy(self.cfg, self.strategy_state())
        tl = analysis.timeline
        # בהפעלה ראשונה מזינים 4 שעות אחורה (בלי כניסות) כדי ששיטת הנזילות תכיר את המבנה האחרון
        rows = tl.tail(48) if strat.last_t is None else tl[tl["t"] > pd.Timestamp(strat.last_t)].tail(300)
        events = []
        for _, row in rows.iterrows():
            events += strat.on_bar(row, allow_entry=now - row["t"] <= FRESH)
        self.store.put("strategy", strat.to_state())

        for ev in events:
            if "trade" in ev:
                self.store.save_trade(ev["trade"])
            if event_method(ev) not in self.cfg.alert_methods:
                continue  # שיטה במעקב בלבד: נשמרת בהיסטוריה, בלי התראה
            text = event_message(ev, self.snapshot)
            if text and self.notify:
                await self.notify(text)
        return events

    async def run(self):
        while True:
            try:
                events = await self.tick()
                self.last_error = None
                log.info("ניתוח עודכן: %s (%s), %d אירועים",
                         self.snapshot["verdict"], self.snapshot["composite"], len(events))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.last_error = str(e)
                log.exception("שגיאה בניתוח")
            await asyncio.sleep(self.cfg.check_interval)
