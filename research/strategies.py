"""שיטות מועמדות לבדיקה. כולן משתמשות באותו ניהול עסקה של הבוט (חצי ב-1R, סטופ לכניסה, יתרה ב-TP2)."""
from dataclasses import asdict

import pandas as pd

from app.config import Settings
from app.strategy import LiquidityLooseStrategy, LiquidityStrategy, RangeStrategy, SMCStrategy, Trade, TradeBook, TrendStrategy, _num


def liq_variant(name: str, **knobs):
    """גרסה של שיטת הנזילות עם "כפתורים" משוחררים."""
    return type(name, (LiquidityStrategy,), knobs)


MORE_LEVELS = LiquidityStrategy.LEVELS + (("LDL", "lon_low", 1), ("LDH", "lon_high", -1),
                                          ("PWL", "pwl", 1), ("PWH", "pwh", -1))
SWINGS = (("SWL", "swing_low", 1), ("SWH", "swing_high", -1))
LiqAllDay = liq_variant("LiqAllDay", KZ_ONLY=False)
LiqMarket = liq_variant("LiqMarket", ENTRY="market")
LiqLevels = liq_variant("LiqLevels", LEVELS=MORE_LEVELS)
LiqSwings = liq_variant("LiqSwings", LEVELS=MORE_LEVELS + SWINGS)
LiqNoHTF = liq_variant("LiqNoHTF", HTF_MIN=None)
LiqLong = liq_variant("LiqLong", SWEEP_BARS=24)
LiqLoose = liq_variant("LiqLoose", KZ_ONLY=False, ENTRY="market", LEVELS=MORE_LEVELS + SWINGS, SWEEP_BARS=24)
LiqLooseKZ = liq_variant("LiqLooseKZ", ENTRY="market", LEVELS=MORE_LEVELS + SWINGS, SWEEP_BARS=24)
LiqLooseFVG = liq_variant("LiqLooseFVG", KZ_ONLY=False, LEVELS=MORE_LEVELS + SWINGS, SWEEP_BARS=24)


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
        "smc": lambda: SMCStrategy(cfg),
        "range": lambda: RangeStrategy(cfg),
        "trend": lambda: TrendStrategy(cfg),
        "liq": lambda: LiquidityStrategy(cfg),
        "liq_plus": lambda: LiqPlus(cfg),
        # שחרור שיטת הנזילות - כל כפתור לחוד, ואז ביחד
        "liq_allday": lambda: LiqAllDay(cfg),
        "liq_market": lambda: LiqMarket(cfg),
        "liq_levels": lambda: LiqLevels(cfg),
        "liq_swings": lambda: LiqSwings(cfg),
        "liq_nohtf": lambda: LiqNoHTF(cfg),
        "liq_2h": lambda: LiqLong(cfg),
        "liq_loose": lambda: LiqLoose(cfg),
        "liq_live": lambda: LiquidityLooseStrategy(cfg),  # הגרסה שרצה בבוט - צריכה להיות זהה ל-liq_loose
        "liq_loose_kz": lambda: LiqLooseKZ(cfg),
        "liq_loose_fvg": lambda: LiqLooseFVG(cfg),
        "orb_ny": lambda: ORB(cfg, "orbny", 510, 660),      # 08:30-11:00 ניו יורק
        "orb_lon": lambda: ORB(cfg, "orblon", 180, 300),    # 03:00-05:00 ניו יורק
    }
