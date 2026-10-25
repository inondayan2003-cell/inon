"""שיטות מועמדות לבדיקה. כולן משתמשות באותו ניהול עסקה של הבוט (חצי ב-1R, סטופ לכניסה, יתרה ב-TP2)."""
from dataclasses import asdict

import pandas as pd

from app.config import Settings
from app.strategy import LiquidityStrategy, Trade, TradeBook, TrendStrategy, _num


class LiqPlus(LiquidityStrategy):
    """נזילות מורחבת: גם שיא/שפל לונדון (לסוויפ בניו יורק) ושיא/שפל השבוע הקודם."""
    LEVELS = LiquidityStrategy.LEVELS + (("LDL", "lon_low", 1), ("LDH", "lon_high", -1),
                                         ("PWL", "pwl", 1), ("PWH", "pwh", -1))


class ORB(TradeBook):
    """פריצת טווח פתיחה: נר 5M שנסגר מעבר לטווח בתוך חלון המסחר. סטופ באמצע הטווח."""

    def __init__(self, cfg: Settings, prefix: str, start: int, end: int, rr: float = 2.0):
        super().__init__(cfg, None, {"next": 1})
        self.prefix, self.start, self.end, self.rr = prefix, start, end, rr
        self.done: set[str] = set()

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        events = self._update_trade(row) if self.trade else []
        if self.trade or not (self.start <= row["ny_min"] < self.end):
            return events
        hi, lo, a = _num(row.get(f"{self.prefix}_high")), _num(row.get(f"{self.prefix}_low")), _num(row.get("atr_15m"))
        if hi is None or lo is None or not a:
            return events
        c = float(row["close"])
        d = 1 if c > hi else -1 if c < lo else 0
        key = f"{row['session']}:{d}"
        if not d or key in self.done:
            return events
        self.done.add(key)
        sl = (hi + lo) / 2
        risk = (c - sl) * d
        if not (0.3 * a <= risk <= 2.5 * a):
            return events
        self.trade = Trade(id=self.new_id(), direction=d, opened_at=row["t"].isoformat(), entry=c, sl=sl,
                           tp1=c + d * risk, tp2=c + d * self.rr * risk, score=0, stop=sl, method=f"orb_{self.prefix}")
        return events + [{"type": "signal", "trade": asdict(self.trade)}]


def candidates(cfg: Settings) -> dict:
    """שם -> יצרן אסטרטגיה (כל הרצה מקבלת מופע חדש)."""
    return {
        "trend": lambda: TrendStrategy(cfg),
        "liq": lambda: LiquidityStrategy(cfg),
        "liq_plus": lambda: LiqPlus(cfg),
        "orb_ny": lambda: ORB(cfg, "orbny", 510, 660),      # 08:30-11:00 ניו יורק
        "orb_lon": lambda: ORB(cfg, "orblon", 180, 300),    # 03:00-05:00 ניו יורק
    }
