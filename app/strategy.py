"""אסטרטגיות הסיגנלים וניהול העסקה - משותף לבוט החי ול-backtest.
בבוט רצה רק שיטת הערוץ (Strategy בסוף הקובץ). שאר המחלקות נשארו למחקר.

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


class LondonShortStrategy:
    """שורט לונדון (נמצא בחיפוש האוטומטי, סבב 2, חוק 4; נבדק עם יחס 1:2).

    כניסה (שורט, בסגירת נר 5M), כשבשעות 02:00-07:00 ניו יורק מתקיימים לראשונה יחד:
      - פתיל עליון קטן: wick_up < 0.306 (ביחידות ATR של 5M)
      - תנודתיות נמוכה: vol_regime < 0.763 (ATR 15M ביחס לממוצע 5 הימים)
      - בלי עלייה חזקה בשעה האחרונה: ret12 < 0.655 (ביחידות ATR של 15M)
    סטופ 1.5 ATR(15M), יעד 2R (3 ATR), יציאה בזמן אחרי 4 שעות. כמה עסקאות יכולות לרוץ במקביל.
    בדיקה: 10/2024-6/2026 בערך אפס; 6/2026-10/2026 (כספת) 141 עסקאות, 50% הצלחה, +49R.
    """
    WICK_UP, VOL_REGIME, RET12 = 0.306, 0.763, 0.655
    SESSION = (120, 420)          # דקות מחצות ניו יורק, לפי פתיחת הנר
    SL_ATR, RR, HOLD_BARS = 1.5, 2.0, 48

    def __init__(self, cfg: Settings, state: dict | None = None, ids: dict | None = None):
        state = state or {}
        self.cfg = cfg
        self.ids = ids if ids is not None else {"next": 1}
        self.n: int = state.get("n", 0)
        self.prev: bool = state.get("prev", False)
        self.trades: list[dict] = state.get("trades", [])

    def to_state(self) -> dict:
        return {"n": self.n, "prev": self.prev, "trades": self.trades}

    def condition(self, row) -> bool:
        m = row.get("ny_open_min")
        vals = [_num(row.get(k)) for k in ("wick_up", "vol_regime", "ret12")]
        if m is None or any(v is None for v in vals):
            return False
        wick, vol, ret = vals
        return (self.SESSION[0] <= m < self.SESSION[1] and wick < self.WICK_UP
                and vol < self.VOL_REGIME and ret < self.RET12)

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        self.n += 1
        t = row["t"]
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        events, still = [], []
        for x in self.trades:
            tr = Trade(**{k: v for k, v in x.items() if k != "opened_n"})
            exit_px = status = None
            if hi >= tr.sl:                      # סטופ קודם (הנחה שמרנית)
                exit_px, status = tr.sl, "sl"
            elif lo <= tr.tp2:
                exit_px, status = tr.tp2, "tp2"
            elif self.n - x["opened_n"] >= self.HOLD_BARS:
                exit_px, status = close, "expired"
            if status:
                tr.result_r = round((tr.entry - exit_px) / tr.risk, 2)
                tr.status, tr.exit_price, tr.closed_at = status, round(exit_px, 2), t.isoformat()
                events.append({"type": "closed", "trade": asdict(tr), "t": t.isoformat()})
            else:
                still.append(x)
        self.trades = still

        cond = self.condition(row)
        fire = cond and not self.prev   # רק כשהתנאי "נדלק"
        self.prev = cond
        a = _num(row.get("atr_15m"))
        if fire and allow_entry and a:
            sl = round(close + self.SL_ATR * a, 2)
            tp = round(close - self.SL_ATR * self.RR * a, 2)
            tr = Trade(id=self.ids["next"], direction=-1, opened_at=t.isoformat(), entry=round(close, 2), sl=sl,
                       tp1=tp, tp2=tp, score=0.0, stop=sl, method="london_short",
                       note="שורט לונדון: פתיל עליון קטן, תנודתיות נמוכה, בלי עלייה חזקה בשעה האחרונה")
            self.ids["next"] += 1
            self.trades.append({**asdict(tr), "opened_n": self.n})
            events.append({"type": "signal", "trade": asdict(tr), "t": t.isoformat(),
                           "expires": (t + pd.Timedelta(minutes=5 * self.HOLD_BARS)).isoformat()})
        return events


class ReopenLongStrategy:
    """לונג בפתיחה היומית של הזהב (research/reopen.py, סבבים 4-5).

    הזהב נוטה לעלות ב-3 השעות הראשונות אחרי ההפסקה היומית (18:00 ניו יורק, ~01:00 שעון ישראל).
    התנועה הממוצעת בשעות האלה חיובית בכל אחת מהשנים 2018-2026; אותה עסקה בשעות אחרות לא מרוויחה.
    כניסה: לונג בסגירת נר ה-5M הראשון אחרי ההפסקה (פער של 30+ דקות בנתונים, או הנר הראשון מ-18:00 ניו יורק).
    סטופ 1 ATR(1H), יעד 3R, יציאה בזמן 4 שעות אחרי הפתיחה. עסקה אחת ביום.
    בדיקה (עלות 0.35$): 10/2024-10/2026 517 עסקאות, +99R, t=3.5, כל שנה ברווח; 2018-2024 +64R, 5/7 שנים.
    תיקון (research/reopen.py delay_report): כמעט כל הרווח של 2018-2024 נמצא בדקה הראשונה אחרי הפתיחה
    (ספרד רחב בפתיחה - לא ניתן לתפוס). בכניסה אחרי 5 דקות: 2018-2024 ‎-115R, שנתיים אחרונות +63R,
    4-10/2026 ‎-4.5R. כלומר: ניסיונית בלבד.
    """
    SL_ATR, RR, HOLD = 1.0, 3.0, pd.Timedelta(hours=4)
    GAP = pd.Timedelta(minutes=30)
    OPEN_MIN = 18 * 60

    def __init__(self, cfg: Settings, state: dict | None = None, ids: dict | None = None):
        state = state or {}
        self.cfg = cfg
        self.ids = ids if ids is not None else {"next": 1}
        self.prev_t: str | None = state.get("prev_t")
        self.last_day: str | None = state.get("last_day")
        self.trades: list[dict] = state.get("trades", [])

    def to_state(self) -> dict:
        return {"prev_t": self.prev_t, "last_day": self.last_day, "trades": self.trades}

    def _reopen(self, row) -> str | None:
        """מחזיר את יום המסחר אם הנר הזה הוא הראשון אחרי הפתיחה היומית, אחרת None."""
        t = row["t"]
        bar_open = (t - pd.Timedelta(minutes=5)).tz_convert("America/New_York")
        day = (bar_open + pd.Timedelta(hours=6)).date().isoformat()   # יום מסחר מתחיל ב-18:00 ניו יורק
        gap = self.prev_t is not None and t - pd.Timestamp(self.prev_t) >= self.GAP + pd.Timedelta(minutes=5)
        m = bar_open.hour * 60 + bar_open.minute
        at_open = self.OPEN_MIN <= m < self.OPEN_MIN + 30
        return day if (gap or at_open) and day != self.last_day else None

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        t = row["t"]
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        events, still = [], []
        for x in self.trades:
            tr = Trade(**x)
            exit_px = status = None
            if lo <= tr.sl:                      # סטופ קודם (הנחה שמרנית)
                exit_px, status = tr.sl, "sl"
            elif hi >= tr.tp2:
                exit_px, status = tr.tp2, "tp2"
            elif t >= pd.Timestamp(tr.opened_at) + self.HOLD:
                exit_px, status = close, "expired"
            if status:
                tr.result_r = round((exit_px - tr.entry) / tr.risk, 2)
                tr.status, tr.exit_price, tr.closed_at = status, round(exit_px, 2), t.isoformat()
                events.append({"type": "closed", "trade": asdict(tr), "t": t.isoformat()})
            else:
                still.append(x)
        self.trades = still

        day = self._reopen(row)
        self.prev_t = t.isoformat()
        a = _num(row.get("atr_1h"))
        ok = row.get("regime_ok", True)   # מסנן סוג שוק (app/regime.py); בלי תיוג = בלי מסנן
        if day and allow_entry and a and not self.trades and ok is not True:
            self.last_day = day
            events.append({"type": "reopen_skip", "method": "reopen_long", "label": row.get("regime_label", "לא ידוע"),
                           "t": t.isoformat()})
        elif day and allow_entry and a and not self.trades:
            self.last_day = day
            sl = round(close - self.SL_ATR * a, 2)
            tp = round(close + self.SL_ATR * self.RR * a, 2)
            opened = t - pd.Timedelta(minutes=5)          # שעת הפתיחה (תחילת הנר)
            tr = Trade(id=self.ids["next"], direction=1, opened_at=opened.isoformat(), entry=round(close, 2), sl=sl,
                       tp1=tp, tp2=tp, score=0.0, stop=sl, method="reopen_long",
                       note="לונג בפתיחה היומית של הזהב")
            self.ids["next"] += 1
            self.trades.append(asdict(tr))
            events.append({"type": "signal", "trade": asdict(tr), "t": t.isoformat(),
                           "expires": (opened + self.HOLD).isoformat()})
        elif day:
            self.last_day = day
        return events


class ChannelFadeStrategy:
    """שיטת הערוץ, גרסה 2: לפי 105 הסיגנלים של Cryptonew84 מול נתוני דקה (docs/CRYPTONEW84.md).

    מה נמצא: הם נכנסים נגד התנועה של 4 השעות (62%), אחרי ש-15 הדקות האחרונות כבר זזות לכיוון העסקה (65%),
    באזור שצמוד למחיר, יעדים 5/10/15$ וסטופ 10$ מעבר לאזור. אחרי TP1 הזזת סטופ לכניסה שיפרה את התוצאה.
    כללים:
    - שלושה חלונות בשעון ישראל: 09:15-10:30, 14:00-16:15, 17:15-19:45. לכל היותר סיגנל אחד בכל חלון,
      ולפחות 2.5 שעות בין סיגנלים. רק כשאין עסקה פתוחה או לימיט ממתין.
    - קנייה: ב-4 השעות האחרונות ירידה של FADE$ לפחות, וב-15 הדקות האחרונות המחיר עולה. מכירה: הפוך.
    - כניסה (לימיט) 0.5$ מהמחיר, אזור ברוחב WIDTH$, סטופ 10$ מעבר לאזור, יעדים +5/+10/+15 מהכניסה,
      שליש בכל יעד. אחרי TP1 הסטופ זז לכניסה (BE). המספרים מותאמים למחיר: k = מחיר / 4150.
    - הלימיט בתוקף LIMIT_H שעות, עסקה פתוחה נסגרת אחרי 24 שעות.
    """
    WINDOWS = ((9.25, 10.5, "בוקר"), (14.0, 16.25, "צהריים"), (17.25, 19.75, "ערב"))
    TZ = "Asia/Jerusalem"
    REF = 4150.0
    FADE, BOUNCE_MIN = 10.0, 15
    WIDTH, NEAR, SL_GAP, TPS = 5.0, 0.5, 10.0, (5.0, 10.0, 15.0)
    BE = True
    DIR = 1                       # 1 = נגד תנועת 4 השעות (כמו הערוץ), -1 = עם התנועה (המשך אחרי תיקון)
    LIMIT_H, HOLD_H, GAP_H = 2, 24, 2.5

    def __init__(self, cfg: Settings, state: dict | None = None, ids: dict | None = None, **params):
        st = state or {}
        self.cfg = cfg
        self.ids = ids if ids is not None else {"next": 1}
        for k, v in params.items():   # למחקר: FADE / WIDTH / BE / BOUNCE_MIN וכו'
            setattr(self, k.upper(), v)
        self.closes: list = st.get("closes", [])
        self.done: list = st.get("done", [])
        self.setup: dict | None = st.get("setup")
        self.trade: dict | None = st.get("trade")
        self.last_fire: str | None = st.get("last_fire")

    def to_state(self) -> dict:
        return {"closes": self.closes, "done": self.done, "setup": self.setup, "trade": self.trade,
                "last_fire": self.last_fire}

    def _close_trade(self, t, exit_px, status, r) -> dict:
        x = {k: v for k, v in self.trade.items() if k in Trade.__dataclass_fields__}
        tr = Trade(**x)
        tr.result_r, tr.status, tr.exit_price, tr.closed_at = round(r, 2), status, round(exit_px, 2), t.isoformat()
        self.trade = None
        return {"type": "closed", "trade": asdict(tr), "t": t.isoformat()}

    def _manage(self, t, hi, lo, close) -> list[dict]:
        tr = self.trade
        d, tps, n0 = tr["direction"], tr["tps"], len(tr["tps"])
        risk = abs(tr["entry"] - tr["sl"])
        gains = [abs(x - tr["entry"]) / risk for x in tps]
        stop = tr["entry"] if self.BE and tr["hits"] else tr["sl"]
        if (lo <= stop) if d == 1 else (hi >= stop):
            n = tr["hits"]
            lost = 0.0 if stop == tr["entry"] else 1.0
            return [self._close_trade(t, stop, "be" if lost == 0 else "sl", (sum(gains[:n]) - (n0 - n) * lost) / n0)]
        events = []
        while tr["hits"] < n0 and ((hi >= tps[tr["hits"]]) if d == 1 else (lo <= tps[tr["hits"]])):
            tr["hits"] += 1
            events.append({"type": "cf_tp", "n": tr["hits"], "be": self.BE, "trade": dict(tr), "t": t.isoformat()})
        if tr["hits"] == n0:
            events.append(self._close_trade(t, tps[-1], "tp2", sum(gains) / n0))
        elif t >= pd.Timestamp(tr["filled_at"]) + pd.Timedelta(hours=self.HOLD_H):
            n = tr["hits"]
            open_r = (close - tr["entry"]) * d / risk
            events.append(self._close_trade(t, close, "expired", (sum(gains[:n]) + (n0 - n) * open_r) / n0))
        return events

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        """row = נר 5 דקות סגור, t = זמן הסגירה (UTC)."""
        t = row["t"]
        hi, lo, close = float(row["high"]), float(row["low"]), float(row["close"])
        events = self._manage(t, hi, lo, close) if self.trade else []

        if self.setup:   # לימיט ממתין
            s = self.setup
            if (lo <= s["entry"]) if s["direction"] == 1 else (hi >= s["entry"]):
                self.trade = {**s, "hits": 0, "filled_at": t.isoformat()}
                self.setup = None
                events.append({"type": "cf_filled", "trade": dict(self.trade), "t": t.isoformat()})
            elif t >= pd.Timestamp(s["expires"]):
                self.setup = None
                events.append({"type": "cf_cancel", "trade": dict(s), "t": t.isoformat()})

        now = t.timestamp()   # closes = [שניות UTC, מחיר] של 5 השעות האחרונות
        past4 = [c for ts, c in self.closes if ts <= now - 4 * 3600]
        pastb = [c for ts, c in self.closes if ts <= now - self.BOUNCE_MIN * 60]
        self.closes = (self.closes + [[now, close]])[-60:]
        il = t.tz_convert(self.TZ)
        h = il.hour + il.minute / 60
        win = next((w for w in self.WINDOWS if w[0] <= h < w[1]), None) if il.weekday() < 5 else None
        key = f"{il.date()}-{win[2]}" if win else None
        fresh = self.last_fire is None or t - pd.Timestamp(self.last_fire) >= pd.Timedelta(hours=self.GAP_H)
        if (allow_entry and win and key not in self.done and fresh and not self.setup and not self.trade
                and past4 and pastb):
            k = close / self.REF
            m4, mb = close - past4[-1], close - pastb[-1]
            d = 1 if m4 <= -self.FADE * k and mb > 0 else -1 if m4 >= self.FADE * k and mb < 0 else 0
            d *= self.DIR
            if d:
                entry = float(round(close - d * self.NEAR * k))   # מספרים שלמים, כמו בערוץ
                far = float(round(entry - d * self.WIDTH * k))
                sl = float(round(far - d * self.SL_GAP * k))
                tps = [float(round(entry + d * x * k)) for x in self.TPS]
                self.setup = {"id": self.ids["next"], "direction": d, "opened_at": t.isoformat(), "entry": entry,
                              "far": far, "sl": sl, "tp1": tps[0], "tp2": tps[-1], "tps": tps, "score": 0.0, "stop": sl,
                              "method": "channel_fade", "window": win[2],
                              "note": f"{'ירידה' if d == 1 else 'עלייה'} של {abs(m4):.1f}$ ב-4 שעות ותיקון של "
                                      f"{abs(mb):.1f}$ ב-{self.BOUNCE_MIN} דקות",
                              "expires": (t + pd.Timedelta(hours=self.LIMIT_H)).isoformat()}
                self.ids["next"] += 1
                self.last_fire = t.isoformat()
                self.done = (self.done + [key])[-10:]
                events.append({"type": "cf_signal", "trade": dict(self.setup), "t": t.isoformat()})
        return events


class Strategy:
    """השיטה שרצה בבוט: שיטת הערוץ Cryptonew84 בלבד (ChannelFadeStrategy).
    השיטות הקודמות (לונג בפתיחה, שורט לונדון וכו') נשארו בקוד למחקר בלבד ולא רצות בבוט."""

    def __init__(self, cfg: Settings, state: dict | None = None):
        state = state or {}
        self.ids = {"next": state.get("next_id", 1)}
        self.last_t: str | None = state.get("last_t")
        self.channel = ChannelFadeStrategy(cfg, state.get("channel"), self.ids)

    def to_state(self) -> dict:
        return {"next_id": self.ids["next"], "last_t": self.last_t, "channel": self.channel.to_state()}

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        """מעבד נר 5 דקות סגור אחד ומחזיר רשימת אירועים להתראה."""
        self.last_t = row["t"].isoformat()
        return self.channel.on_bar(row, allow_entry)

    @property
    def open_trades(self) -> list[dict]:
        return [self.channel.trade] if self.channel.trade else []

    @property
    def pending(self) -> dict | None:
        return self.channel.setup
