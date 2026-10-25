"""אסטרטגיות הסיגנלים וניהול העסקה - משותף לבוט החי ול-backtest.

שתי שיטות רצות במקביל, כל אחת עם עסקה משלה:
- מגמה (trend): יישור טווחים לפי אינדיקטורים, כניסה במחיר השוק.
- נזילות (liquidity): סוויפ של שיא/שפל אתמול או של סשן אסיה בשעות לונדון/ניו יורק,
  שבירת מבנה ב-5M, והזמנת לימיט באמצע ה-FVG שנוצר.

ניהול עסקה: חצי מהפוזיציה נסגר ב-TP1 (1R) והסטופ זז לכניסה, החצי השני ב-TP2.
"""
import math
from dataclasses import asdict, dataclass

import pandas as pd

from .analysis import entry_direction, make_plan
from .config import Settings


@dataclass
class Trade:
    id: int
    direction: int
    opened_at: str
    entry: float
    sl: float
    tp1: float
    tp2: float
    score: float
    stop: float
    tp1_hit: bool = False
    status: str = "open"          # open / tp2 / sl / be / expired / reversed
    result_r: float | None = None
    exit_price: float | None = None
    closed_at: str | None = None
    method: str = "trend"         # trend / liquidity
    note: str = ""                # למשל איזו נזילות נלקחה

    @property
    def risk(self) -> float:
        return abs(self.entry - self.sl)

    def r_at(self, price: float) -> float:
        move = (price - self.entry) * self.direction / self.risk
        return 0.5 + 0.5 * move if self.tp1_hit else move


class TradeBook:
    """עסקה פתוחה אחת וניהול שלה (יעדים, סטופ, זמן)."""

    def __init__(self, cfg: Settings, trade: dict | None, ids: dict):
        self.cfg = cfg
        self.ids = ids  # מונה מזהים משותף לכל השיטות
        self.trade: Trade | None = Trade(**trade) if trade else None

    def new_id(self) -> int:
        self.ids["next"] += 1
        return self.ids["next"] - 1

    def _update_trade(self, row) -> list[dict]:
        tr, t = self.trade, row["t"]
        hi, lo, d = float(row["high"]), float(row["low"]), self.trade.direction
        fav, adv = (hi, lo) if d == 1 else (lo, hi)

        def crossed(level, price):  # האם המחיר הגיע לרמה בכיוון הנתון
            return (price - level) * d >= 0

        if (adv - tr.stop) * d <= 0:  # נגענו בסטופ (בודקים קודם - הנחה שמרנית)
            return [self._close(tr.stop, "be" if tr.tp1_hit else "sl", t)]
        events = []
        if not tr.tp1_hit and crossed(tr.tp1, fav):
            tr.tp1_hit, tr.stop = True, tr.entry
            events.append({"type": "tp1", "trade": asdict(tr), "t": t.isoformat()})
        if tr.tp1_hit and crossed(tr.tp2, fav):
            events.append(self._close(tr.tp2, "tp2", t))
            return events
        if t - pd.Timestamp(tr.opened_at) >= pd.Timedelta(hours=self.cfg.trade_expiry_hours):
            events.append(self._close(float(row["close"]), "expired", t))
        return events

    def _close(self, price: float, status: str, t: pd.Timestamp) -> dict:
        tr = self.trade
        tr.result_r = round(tr.r_at(price), 2)
        tr.status, tr.exit_price, tr.closed_at = status, round(price, 2), t.isoformat()
        self.trade = None
        return {"type": "closed", "trade": asdict(tr), "t": t.isoformat()}


class TrendStrategy(TradeBook):
    def __init__(self, cfg: Settings, state: dict | None = None, ids: dict | None = None):
        state = state or {}
        super().__init__(cfg, state.get("trade"), ids if ids is not None else {"next": state.get("next_id", 1)})
        self.active_dir: int = state.get("active_dir", 0)
        self.last_signal: dict[str, str] = state.get("last_signal", {})

    def to_state(self) -> dict:
        return {"active_dir": self.active_dir, "last_signal": self.last_signal,
                "trade": asdict(self.trade) if self.trade else None}

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        t: pd.Timestamp = row["t"]
        events: list[dict] = []
        if self.trade:
            events += self._update_trade(row)

        if self.active_dir and row["composite"] * self.active_dir < self.cfg.exit_threshold:
            events.append({"type": "weak", "direction": self.active_dir, "price": float(row["close"]),
                           "score": float(row["composite"]), "t": t.isoformat()})
            self.active_dir = 0

        d = entry_direction(row, self.cfg)
        if not (d and allow_entry and d != self.active_dir):
            return events
        if self.trade and self.trade.direction == d:
            return events
        last = self.last_signal.get(str(d))
        if last and t - pd.Timestamp(last) < pd.Timedelta(minutes=self.cfg.cooldown_minutes):
            return events

        if self.trade:  # סיגנל הפוך: סוגרים את העסקה הקיימת במחיר השוק
            events.append(self._close(float(row["close"]), "reversed", t))
        plan = make_plan(d, row, self.cfg)
        self.trade = Trade(id=self.new_id(), direction=d, opened_at=t.isoformat(), entry=plan["entry"],
                           sl=plan["sl"], tp1=plan["tp1"], tp2=plan["tp2"],
                           score=round(float(row["composite"]), 1), stop=plan["sl"])
        self.active_dir = d
        self.last_signal[str(d)] = t.isoformat()
        events.append({"type": "signal", "trade": asdict(self.trade), "t": t.isoformat()})
        return events


LEVEL_NAMES = {"PDL": "השפל של אתמול", "PDH": "השיא של אתמול",
               "ASL": "השפל של סשן אסיה", "ASH": "השיא של סשן אסיה"}


def _num(v) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


class LiquidityStrategy(TradeBook):
    # (שם, עמודה בטבלה, כיוון העסקה אחרי סוויפ)
    LEVELS = (("PDL", "pdl", 1), ("ASL", "asia_low", 1), ("PDH", "pdh", -1), ("ASH", "asia_high", -1))
    SWEEP_BARS = 12      # כמה נרות אחרי הסוויפ מחכים לשבירת מבנה (שעה)
    SETUP_BARS = 12      # כמה זמן הזמנת הלימיט בתוקף (שעה)
    STRUCTURE_BARS = 6   # נרות לפני הסוויפ שמגדירים את המבנה לשבירה
    BUF = 40

    def __init__(self, cfg: Settings, state: dict | None = None, ids: dict | None = None):
        state = state or {}
        super().__init__(cfg, state.get("trade"), ids if ids is not None else {"next": 1})
        self.n: int = state.get("n", 0)
        self.buf: list[dict] = state.get("buf", [])
        self.cands: list[dict] = state.get("cands", [])
        self.used: list[str] = state.get("used", [])
        self.setup: dict | None = state.get("setup")

    def to_state(self) -> dict:
        return {"n": self.n, "buf": self.buf, "cands": self.cands, "used": self.used, "setup": self.setup,
                "trade": asdict(self.trade) if self.trade else None}

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        self.n += 1
        self.buf.append({"n": self.n, "h": float(row["high"]), "l": float(row["low"]), "c": float(row["close"])})
        self.buf = self.buf[-self.BUF:]
        events: list[dict] = []
        if self.trade:
            events += self._update_trade(row)
        if self.setup:
            events += self._manage_setup(row)
        if not self.trade and not self.setup:
            events += self._scan(row, allow_entry)
        return events

    # ---------- הזמנת לימיט ממתינה ----------
    def _manage_setup(self, row) -> list[dict]:
        s, t, d = self.setup, row["t"], self.setup["direction"]
        hi, lo = float(row["high"]), float(row["low"])
        fav, adv = (hi, lo) if d == 1 else (lo, hi)
        if (adv - s["entry"]) * d <= 0:  # המחיר חזר לאזור הכניסה - הלימיט התמלא
            self.trade = Trade(id=s["id"], direction=d, opened_at=t.isoformat(), entry=s["entry"], sl=s["sl"],
                               tp1=s["tp1"], tp2=s["tp2"], score=s["score"], stop=s["sl"],
                               method="liquidity", note=s["note"])
            self.setup = None
            events = [{"type": "filled", "trade": asdict(self.trade), "t": t.isoformat()}]
            if (adv - s["sl"]) * d <= 0:  # באותו נר גם הסטופ נלקח (הנחה שמרנית)
                events.append(self._close(s["sl"], "sl", t))
            return events
        reason = None
        if (fav - s["tp1"]) * d >= 0:
            reason = "המחיר הגיע ליעד בלי לחזור לאזור הכניסה"
        elif self.n > s["expires_n"]:
            reason = "לא התמלאה בזמן"
        if reason:
            self.setup = None
            return [{"type": "cancelled", "setup": s, "reason": reason, "t": t.isoformat()}]
        return []

    # ---------- חיפוש סוויפ + שבירת מבנה + FVG ----------
    def _scan(self, row, allow_entry: bool) -> list[dict]:
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        session = row.get("session")
        if row.get("kz", 0) and session:
            for name, col, d in self.LEVELS:
                level = _num(row.get(col))
                key = f"{session}:{name}"
                if level is None or key in self.used:
                    continue
                if (d == 1 and lo < level) or (d == -1 and hi > level):
                    ext = lo if d == 1 else hi
                    self.cands.append({"direction": d, "name": name, "level": level, "ext": ext,
                                       "ext_n": self.n, "born": self.n})
                    self.used = (self.used + [key])[-20:]

        for c in self.cands:  # הסוויפ ממשיך להעמיק - מעדכנים את הקצה
            if (c["direction"] == 1 and lo < c["ext"]) or (c["direction"] == -1 and hi > c["ext"]):
                c["ext"], c["ext_n"] = (lo if c["direction"] == 1 else hi), self.n
        self.cands = [c for c in self.cands if self.n - c["born"] <= self.SWEEP_BARS]

        for c in list(self.cands):
            d = c["direction"]
            pre = [b for b in self.buf if c["ext_n"] - self.STRUCTURE_BARS <= b["n"] < c["ext_n"]]
            if len(pre) < 3:
                continue
            ref = max(b["h"] for b in pre) if d == 1 else min(b["l"] for b in pre)
            if not ((close - c["level"]) * d > 0 and (close - ref) * d > 0):
                continue
            # שבירת מבנה - הסוויפ "נוצל" (וגם סוויפים אחרים באותו כיוון, כדי לא לאותת פעמיים על אותו מהלך)
            self.cands = [x for x in self.cands if x["direction"] != d]
            setup = self._make_setup(c, row) if allow_entry else None
            if setup:
                self.setup = setup
                return [{"type": "setup", "setup": setup, "t": row["t"].isoformat()}]
        return []

    def _make_setup(self, c: dict, row) -> dict | None:
        d, a = c["direction"], _num(row.get("atr_15m"))
        if not a:
            return None
        leg = [b for b in self.buf if b["n"] >= c["ext_n"] - 2]
        fvg = None
        for i in range(2, len(leg)):
            x, z = leg[i - 2], leg[i]
            if z["n"] <= c["ext_n"]:
                continue
            if d == 1 and z["l"] > x["h"]:
                fvg = (x["h"], z["l"])
            elif d == -1 and z["h"] < x["l"]:
                fvg = (z["h"], x["l"])
        if not fvg:
            return None
        entry = round((fvg[0] + fvg[1]) / 2, 2)
        sl = round(c["ext"] - d * 0.1 * a, 2)
        risk = (entry - sl) * d
        if not (0.25 * a <= risk <= 2.5 * a) or (float(row["close"]) - entry) * d <= 0:
            return None
        htf = (float(row["score_1h"]) + float(row["score_4h"])) / 2
        if htf * d < -20:  # לא נכנסים נגד מגמה חזקה ב-1H/4H
            return None
        tp1, tp2 = entry + d * risk, entry + 2 * d * risk
        # היעד השני: הנזילות שבצד השני, אם היא בטווח של 2R-4R
        opp = [_num(row.get(k)) for k in (("pdh", "asia_high") if d == 1 else ("pdl", "asia_low"))]
        far = sorted(x for x in opp if x is not None and 2 * risk <= (x - entry) * d <= 4 * risk)
        if far:
            tp2 = far[0] if d == 1 else far[-1]
        return {"id": self.new_id(), "direction": d, "entry": entry, "sl": sl, "tp1": round(tp1, 2),
                "tp2": round(tp2, 2), "score": round(htf, 1), "level": round(c["level"], 2), "name": c["name"],
                "note": LEVEL_NAMES.get(c["name"], c["name"]), "created": row["t"].isoformat(),
                "expires": (row["t"] + pd.Timedelta(minutes=5 * self.SETUP_BARS)).isoformat(),
                "expires_n": self.n + self.SETUP_BARS}


class RangeStrategy:
    """שיטת טווחים (נבדקה על שנתיים, 10/2024-10/2026, ועברה את קבוצת הביקורת):
    - פריצה ראשונה ביום של טווח לונדון (02:00-05:00 ניו יורק) -> פייד: חוזרים פנימה.
    - פריצה ראשונה ביום של השיא/שפל של אתמול -> ממשיכים עם הפריצה.
    כניסה בסגירת נר 5M, סטופ 1.5 ATR(15M), יעד 2.25 ATR (פי 1.5 מהסטופ), יציאה בזמן אחרי שעתיים.
    כמה עסקאות יכולות להיות פתוחות במקביל (כל אחת מהגדרה אחרת)."""

    SETUPS = (  # שם, עמודה, צד הפריצה (1=למעלה), כיוון העסקה
        ("LDH", "lon_high", 1, -1), ("LDL", "lon_low", -1, 1),
        ("PDH", "pdh", 1, 1), ("PDL", "pdl", -1, -1),
    )
    NOTES = {"LDH": "פריצה של השיא של לונדון - פייד (חזרה לטווח)",
             "LDL": "פריצה של השפל של לונדון - פייד (חזרה לטווח)",
             "PDH": "פריצה של השיא של אתמול - המשך",
             "PDL": "פריצה של השפל של אתמול - המשך"}
    SL_ATR, RR, HOLD_BARS = 1.5, 1.5, 24

    def __init__(self, cfg: Settings, state: dict | None = None, ids: dict | None = None):
        state = state or {}
        self.cfg = cfg
        self.ids = ids if ids is not None else {"next": 1}
        self.n: int = state.get("n", 0)
        self.done: list[str] = state.get("done", [])
        self.trades: list[dict] = state.get("trades", [])  # Trade כ-dict + opened_n

    def to_state(self) -> dict:
        return {"n": self.n, "done": self.done, "trades": self.trades}

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        self.n += 1
        t = row["t"]
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        events, still = [], []
        for x in self.trades:
            tr = Trade(**{k: v for k, v in x.items() if k != "opened_n"})
            d = tr.direction
            fav, adv = (hi, lo) if d == 1 else (lo, hi)
            exit_px, status = None, None
            if (adv - tr.sl) * d <= 0:          # סטופ קודם (הנחה שמרנית)
                exit_px, status = tr.sl, "sl"
            elif (fav - tr.tp2) * d >= 0:
                exit_px, status = tr.tp2, "tp2"
            elif self.n - x["opened_n"] >= self.HOLD_BARS:
                exit_px, status = close, "expired"
            if status:
                tr.result_r = round((exit_px - tr.entry) * d / tr.risk, 2)
                tr.status, tr.exit_price, tr.closed_at = status, round(exit_px, 2), t.isoformat()
                events.append({"type": "closed", "trade": asdict(tr), "t": t.isoformat()})
            else:
                still.append(x)
        self.trades = still

        session, a = row.get("session"), _num(row.get("atr_15m"))
        for name, col, side, d in self.SETUPS:
            level = _num(row.get(col))
            key = f"{session}:{name}"
            if level is None or not session or key in self.done:
                continue
            if (close - level) * side <= 0:
                continue
            self.done = (self.done + [key])[-40:]  # רק הפריצה הראשונה ביום נספרת
            if not allow_entry or not a:
                continue
            sl = round(close - d * self.SL_ATR * a, 2)
            tp = round(close + d * self.SL_ATR * self.RR * a, 2)
            tr = Trade(id=self.ids["next"], direction=d, opened_at=t.isoformat(), entry=round(close, 2), sl=sl,
                       tp1=tp, tp2=tp, score=round(float(row.get("composite", 0) or 0), 1), stop=sl,
                       method="range", note=self.NOTES[name])
            self.ids["next"] += 1
            self.trades.append({**asdict(tr), "opened_n": self.n})
            events.append({"type": "signal", "trade": asdict(tr), "level": round(level, 2),
                           "expires": (t + pd.Timedelta(minutes=5 * self.HOLD_BARS)).isoformat(), "t": t.isoformat()})
        return events


class Strategy:
    """מריץ את כל השיטות על כל נר ושומר את המצב של כולן."""

    def __init__(self, cfg: Settings, state: dict | None = None):
        state = state or {}
        if state and "trend" not in state:  # מצב שנשמר בגרסה הקודמת (שיטת מגמה בלבד)
            state = {"trend": state, "next_id": state.get("next_id", 1), "last_t": state.get("last_t")}
        self.ids = {"next": state.get("next_id", 1)}
        self.last_t: str | None = state.get("last_t")
        self.trend = TrendStrategy(cfg, state.get("trend"), self.ids)
        self.liquidity = LiquidityStrategy(cfg, state.get("liquidity"), self.ids)
        self.range = RangeStrategy(cfg, state.get("range"), self.ids)

    def to_state(self) -> dict:
        return {"next_id": self.ids["next"], "last_t": self.last_t, "trend": self.trend.to_state(),
                "liquidity": self.liquidity.to_state(), "range": self.range.to_state()}

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        """מעבד נר 5 דקות סגור אחד ומחזיר רשימת אירועים להתראה."""
        self.last_t = row["t"].isoformat()
        return (self.trend.on_bar(row, allow_entry) + self.liquidity.on_bar(row, allow_entry)
                + self.range.on_bar(row, allow_entry))

    @property
    def open_trades(self) -> list[dict]:
        trades = [asdict(s.trade) for s in (self.trend, self.liquidity) if s.trade]
        return trades + [{k: v for k, v in x.items() if k != "opened_n"} for x in self.range.trades]

    @property
    def pending(self) -> dict | None:
        return self.liquidity.setup
