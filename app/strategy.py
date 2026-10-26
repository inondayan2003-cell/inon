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
        if not self.tp1_hit:
            return move
        tp1_r = (self.tp1 - self.entry) * self.direction / self.risk  # חצי נסגר ביעד 1
        return 0.5 * tp1_r + 0.5 * move


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
               "ASL": "השפל של סשן אסיה", "ASH": "השיא של סשן אסיה",
               "LDL": "השפל של סשן לונדון", "LDH": "השיא של סשן לונדון",
               "PWL": "השפל של השבוע שעבר", "PWH": "השיא של השבוע שעבר",
               "SWL": "שפל סווינג (6 השעות האחרונות)", "SWH": "שיא סווינג (6 השעות האחרונות)"}


def _num(v) -> float | None:
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


class LiquidityStrategy(TradeBook):
    # (שם, עמודה בטבלה, כיוון העסקה אחרי סוויפ)
    LEVELS = (("PDL", "pdl", 1), ("ASL", "asia_low", 1), ("PDH", "pdh", -1), ("ASH", "asia_high", -1))
    SWEEP_BARS = 12      # כמה נרות אחרי הסוויפ מחכים לשבירת מבנה (שעה)
    SETUP_BARS = 12      # כמה זמן הזמנת הלימיט בתוקף (שעה)
    STRUCTURE_BARS = 6   # נרות לפני הסוויפ שמגדירים את המבנה לשבירה
    BUF = 40
    # "כפתורי שחרור" (ברירת מחדל = השיטה המקורית)
    KZ_ONLY = True       # סוויפים רק בשעות לונדון/ניו יורק
    ENTRY = "fvg"        # fvg = לימיט באמצע ה-FVG; market = כניסה מיידית בשבירת המבנה
    HTF_MIN: float | None = -20  # לא נגד מגמה חזקה ב-1H/4H (None = בלי מסנן)
    DISP_ATR: float | None = None  # Displacement: גוף נר שבירת המבנה לפחות X פעמים ATR של 5M
    TP1_R = 1.0                  # יעד חלקי (חצי מהפוזיציה)
    TP2_MIN_R, TP2_MAX_R, TP2_DEFAULT_R = 2.0, 4.0, 2.0  # יעד סופי: נזילות נגדית בטווח, אחרת ברירת מחדל
    OPP = {1: ("pdh", "asia_high"), -1: ("pdl", "asia_low")}  # הנזילות הנגדית כיעד
    METHOD = "liquidity"

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
                               method=s.get("method", "liquidity"), note=s["note"])
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
        if (row.get("kz", 0) or not self.KZ_ONLY) and session:
            for name, col, d in self.LEVELS:
                level = _num(row.get(col))
                # רמות סווינג משתנות כל הזמן - כל רמה חדשה נספרת בנפרד
                key = f"{session}:{name}" + (f":{round(level, 1)}" if name.startswith("SW") and level else "")
                if level is None or key in self.used:
                    continue
                if (d == 1 and lo < level) or (d == -1 and hi > level):
                    ext = lo if d == 1 else hi
                    self.cands.append({"direction": d, "name": name, "level": level, "ext": ext,
                                       "ext_n": self.n, "born": self.n})
                    self.used = (self.used + [key])[-60:]

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
            a5 = _num(row.get("atr_5m"))
            if self.DISP_ATR and a5 and (close - float(row["open"])) * d < self.DISP_ATR * a5:
                continue  # שבירת מבנה בלי Displacement (נר חלש) - לא נחשבת
            # שבירת מבנה - הסוויפ "נוצל" (וגם סוויפים אחרים באותו כיוון, כדי לא לאותת פעמיים על אותו מהלך)
            self.cands = [x for x in self.cands if x["direction"] != d]
            if allow_entry and self.ENTRY == "market":
                plan = self._plan(c, row, float(row["close"]))
                if plan:
                    self.trade = Trade(id=plan["id"], direction=d, opened_at=row["t"].isoformat(), entry=plan["entry"],
                                       sl=plan["sl"], tp1=plan["tp1"], tp2=plan["tp2"], score=plan["score"],
                                       stop=plan["sl"], method="liquidity", note=plan["note"])
                    return [{"type": "signal", "trade": asdict(self.trade), "t": row["t"].isoformat()}]
                continue
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
        return self._plan(c, row, (fvg[0] + fvg[1]) / 2, check_price=True)

    def _plan(self, c: dict, row, entry: float, check_price: bool = False) -> dict | None:
        d, a = c["direction"], _num(row.get("atr_15m"))
        if not a:
            return None
        entry = round(entry, 2)
        sl = round(c["ext"] - d * 0.1 * a, 2)
        risk = (entry - sl) * d
        if not (0.25 * a <= risk <= 2.5 * a):
            return None
        if check_price and (float(row["close"]) - entry) * d <= 0:
            return None
        htf = (float(row["score_1h"]) + float(row["score_4h"])) / 2
        if self.HTF_MIN is not None and htf * d < self.HTF_MIN:  # לא נכנסים נגד מגמה חזקה ב-1H/4H
            return None
        tp1, tp2 = entry + d * self.TP1_R * risk, entry + d * self.TP2_DEFAULT_R * risk
        # היעד הסופי: הנזילות הנגדית הקרובה, אם היא בטווח TP2_MIN_R-TP2_MAX_R
        opp = [_num(row.get(k)) for k in self.OPP[d]]
        far = sorted(x for x in opp if x is not None
                     and self.TP2_MIN_R * risk <= (x - entry) * d <= self.TP2_MAX_R * risk)
        if far:
            tp2 = far[0] if d == 1 else far[-1]
        return {"id": self.new_id(), "method": self.METHOD, "direction": d, "entry": entry, "sl": sl, "tp1": round(tp1, 2),
                "tp2": round(tp2, 2), "score": round(htf, 1), "level": round(c["level"], 2), "name": c["name"],
                "note": LEVEL_NAMES.get(c["name"], c["name"]), "created": row["t"].isoformat(),
                "expires": (row["t"] + pd.Timedelta(minutes=5 * self.SETUP_BARS)).isoformat(),
                "expires_n": self.n + self.SETUP_BARS}


class LiquidityLooseStrategy(LiquidityStrategy):
    """נזילות משוחררת (לבקשת המשתמש - יותר עסקאות): כל היום, כניסה מיידית בשבירת המבנה,
    רמות נוספות (לונדון, שבוע שעבר, סווינג של 6 שעות), ושעתיים לשבירת המבנה.
    בבדיקה של שנתיים (10/2024-10/2026): 747 עסקאות (~1.5 ביום), +6.3R - בערך אפס לעסקה."""
    KZ_ONLY = False
    ENTRY = "market"
    SWEEP_BARS = 24
    LEVELS = LiquidityStrategy.LEVELS + (("LDL", "lon_low", 1), ("LDH", "lon_high", -1),
                                         ("PWL", "pwl", 1), ("PWH", "pwh", -1),
                                         ("SWL", "swing_low", 1), ("SWH", "swing_high", -1))


class SMCStrategy(LiquidityStrategy):
    """אסטרטגיית SMC/ICT לזהב - שני מודלים, עסקה אחת בכל פעם, עד 2 סטאפים ביום.

    מודל A (Sweep + FVG): בשעות לונדון/ניו יורק, סוויפ של השיא/שפל של אתמול, אסיה או לונדון,
      חזרה מעבר לרמה ושבירת מבנה ב-5M עם Displacement (גוף נר >= 1 ATR של 5M),
      FVG בכיוון ההפוך לסוויפ -> לימיט באמצע ה-FVG.
    מודל B (Session Liquidity): הנזילות של אסיה/לונדון נלקחה לפני ניו יורק; בסשן ניו יורק
      מחפשים Displacement + BOS נגד כיוון הסוויפ -> לימיט באמצע ה-FVG, סטופ מעבר לקצה המהלך.
    סטופ מעבר לקצה הסוויפ + 0.1 ATR. יעד 1 = 1.5R (חצי + סטופ לכניסה), יעד סופי = הנזילות הנגדית
    אם היא 3R-8R, אחרת 3R. לא נגד מגמה חזקה ב-1H/4H. לא פותחים סטאפ חדש בשישי אחרי 10:00 ניו יורק.
    """
    LEVELS = (("PDL", "pdl", 1), ("ASL", "asia_low", 1), ("LDL", "lon_low", 1),
              ("PDH", "pdh", -1), ("ASH", "asia_high", -1), ("LDH", "lon_high", -1))
    DISP_ATR = 1.0
    TP1_R = 1.5
    TP2_MIN_R, TP2_MAX_R, TP2_DEFAULT_R = 3.0, 8.0, 3.0
    OPP = {1: ("pdh", "asia_high", "lon_high"), -1: ("pdl", "asia_low", "lon_low")}
    METHOD = "smc"
    DAILY_MAX = 2

    def __init__(self, cfg: Settings, state: dict | None = None, ids: dict | None = None):
        super().__init__(cfg, state, ids)
        state = state or {}
        self.day: dict = state.get("day", {})  # session, count, swept (מודל B)

    def to_state(self) -> dict:
        return {**super().to_state(), "day": self.day}

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        session = row.get("session")
        if session and self.day.get("session") != session:
            self.day = {"session": session, "count": 0, "swept": {}, "b_done": False}
        self._track_session_sweeps(row)
        t_ny = row["t"].tz_convert("America/New_York")
        late_friday = t_ny.dayofweek == 4 and t_ny.hour >= 10
        can_open = allow_entry and not late_friday and self.day.get("count", 0) < self.DAILY_MAX
        had_setup = self.setup
        events = super().on_bar(row, can_open)
        if not self.trade and not self.setup and can_open:
            events += self._model_b(row)
        if self.setup and self.setup is not had_setup:
            self.day["count"] = self.day.get("count", 0) + 1
        return events

    def _track_session_sweeps(self, row):
        """לפני ניו יורק: האם נלקחה נזילות של אסיה/לונדון (לאיזה צד)."""
        if row.get("kz") == 2 or not self.day:
            return
        hi, lo = float(row["high"]), float(row["low"])
        for name, col, side in (("ASH", "asia_high", 1), ("LDH", "lon_high", 1),
                                ("ASL", "asia_low", -1), ("LDL", "lon_low", -1)):
            lvl = _num(row.get(col))
            if lvl is not None and ((side == 1 and hi > lvl) or (side == -1 and lo < lvl)):
                self.day["swept"][name] = side

    def _model_b(self, row) -> list[dict]:
        if row.get("kz") != 2 or self.day.get("b_done") or not self.day.get("swept"):
            return []
        sides = set(self.day["swept"].values())
        if len(sides) != 1:  # נלקחו שני הצדדים - אין הטיה ברורה
            return []
        d = -sides.pop()     # נלקח למעלה -> מחפשים שורט, ולהפך
        a5, a = _num(row.get("atr_5m")), _num(row.get("atr_15m"))
        close, opn = float(row["close"]), float(row["open"])
        prev = [b for b in self.buf[:-1]][-6:]
        if not (a5 and a) or len(prev) < 6 or (close - opn) * d < self.DISP_ATR * a5:
            return []
        ref = min(b["l"] for b in prev) if d == -1 else max(b["h"] for b in prev)
        if (close - ref) * d <= 0:   # אין BOS
            return []
        last3 = self.buf[-3:]
        x, z = last3[0], last3[2]
        fvg = (x["h"], z["l"]) if d == 1 and z["l"] > x["h"] else (z["h"], x["l"]) if d == -1 and z["h"] < x["l"] else None
        if not fvg:
            return []
        recent = self.buf[-12:]
        ext = min(b["l"] for b in recent) if d == 1 else max(b["h"] for b in recent)
        names = [k for k, v in self.day["swept"].items()]
        c = {"direction": d, "name": names[0], "level": ref, "ext": ext}
        plan = self._plan(c, row, (fvg[0] + fvg[1]) / 2, check_price=True)
        self.day["b_done"] = True
        if not plan:
            return []
        plan["note"] = f"מודל B: נזילות {'/'.join(LEVEL_NAMES[n] for n in names)} נלקחה לפני ניו יורק, BOS בניו יורק"
        self.setup = plan
        return [{"type": "setup", "setup": plan, "t": row["t"].isoformat()}]


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
        self.liquidity = LiquidityLooseStrategy(cfg, state.get("liquidity"), self.ids)
        self.range = RangeStrategy(cfg, state.get("range"), self.ids)
        self.smc = SMCStrategy(cfg, state.get("smc"), self.ids)

    def to_state(self) -> dict:
        return {"next_id": self.ids["next"], "last_t": self.last_t, "trend": self.trend.to_state(),
                "liquidity": self.liquidity.to_state(), "range": self.range.to_state(), "smc": self.smc.to_state()}

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        """מעבד נר 5 דקות סגור אחד ומחזיר רשימת אירועים להתראה."""
        self.last_t = row["t"].isoformat()
        return (self.trend.on_bar(row, allow_entry) + self.liquidity.on_bar(row, allow_entry)
                + self.range.on_bar(row, allow_entry) + self.smc.on_bar(row, allow_entry))

    @property
    def open_trades(self) -> list[dict]:
        trades = [asdict(s.trade) for s in (self.smc, self.trend, self.liquidity) if s.trade]
        return trades + [{k: v for k, v in x.items() if k != "opened_n"} for x in self.range.trades]

    @property
    def pending(self) -> dict | None:
        return self.smc.setup or self.liquidity.setup
