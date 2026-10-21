"""אסטרטגיית הסיגנלים וניהול העסקה - משותף לבוט החי ול-backtest.

ניהול עסקה: חצי מהפוזיציה נסגר ב-TP1 (1R) והסטופ זז לכניסה, החצי השני ב-TP2 (2R).
"""
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

    @property
    def risk(self) -> float:
        return abs(self.entry - self.sl)

    def r_at(self, price: float) -> float:
        move = (price - self.entry) * self.direction / self.risk
        return 0.5 + 0.5 * move if self.tp1_hit else move


class Strategy:
    def __init__(self, cfg: Settings, state: dict | None = None):
        state = state or {}
        self.cfg = cfg
        self.active_dir: int = state.get("active_dir", 0)
        self.last_signal: dict[str, str] = state.get("last_signal", {})
        self.next_id: int = state.get("next_id", 1)
        self.last_t: str | None = state.get("last_t")
        self.trade: Trade | None = Trade(**state["trade"]) if state.get("trade") else None

    def to_state(self) -> dict:
        return {"active_dir": self.active_dir, "last_signal": self.last_signal, "next_id": self.next_id,
                "last_t": self.last_t, "trade": asdict(self.trade) if self.trade else None}

    def on_bar(self, row, allow_entry: bool = True) -> list[dict]:
        """מעבד נר 5 דקות סגור אחד ומחזיר רשימת אירועים להתראה."""
        t: pd.Timestamp = row["t"]
        self.last_t = t.isoformat()
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
        self.trade = Trade(id=self.next_id, direction=d, opened_at=t.isoformat(), entry=plan["entry"],
                           sl=plan["sl"], tp1=plan["tp1"], tp2=plan["tp2"],
                           score=round(float(row["composite"]), 1), stop=plan["sl"])
        self.next_id += 1
        self.active_dir = d
        self.last_signal[str(d)] = t.isoformat()
        events.append({"type": "signal", "trade": asdict(self.trade), "t": t.isoformat()})
        return events

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
