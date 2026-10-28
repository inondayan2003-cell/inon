"""Cryptonew84: הנדסה הפוכה של 105 סיגנלי זהב (03/08/2026-07/10/2026) ושכפול של "הקוד" של הערוץ.

מה רואים בטקסט עצמו (python -m research.cryptonew84):
- תבנית קבועה: אזור ברוחב 5$ (49) או 10$ (47), TP1 = 5$ מעבר לקצה האזור (99/105), ועוד 5$ לכל יעד (104/105).
- הסטופ מוסתר ("SL⛔️#VIP") ב-92 מתוך 105. ב-13 שבהם הוא מופיע: 10$ מעבר לקצה הרחוק של האזור (בערך 20$ מהכניסה).
  כלומר יעד ראשון 5$ מול סיכון 15$-20$: צריך הצלחה של 75%-80% ב-TP1 רק כדי לא להפסיד.
- שעות (שעון ישראל): 09:00-12:00 (46), 13:30-17:00 (35), 17:00-20:00 (24). 1-4 סיגנלים ביום, 3-6 שעות ביניהם,
  רק ימי חול. הדקות מפוזרות באופן אחיד (00-59), כלומר לא נשלח בסגירת נר: מישהו לוחץ "שלח".
- טעויות הקלדה (44320, 42665, SELL עם יעדים למעלה, SELL🟢 / BUY🔴): הודעה שמועתקת ונערכת ביד, לא בוט.
- כיוון: מול האזור של הסיגנל הקודם (כשהמחיר זז 10$ ומעלה) הוא נגד התנועה ב-56 מקרים ועם התנועה ב-29.

הכלל המשוכפל (Clone):
  בכל אחד משלושת החלונות, פעם אחת, בדקה אקראית: אם המחיר זז מאז הסיגנל הקודם (או ב-4 השעות האחרונות)
  ביותר מ-FADE דולר, הולכים נגד; אחרת נגד התנועה של השעה האחרונה. אזור לימיט 5$/10$ צמוד למחיר,
  יעדים +5/+10/+15 ו-OPEN, סטופ 10$ מעבר לאזור (מוסתר ב-#VIP).

בדיקה מול נתוני דקה: python -m research.run --clone   (ב-GitHub Actions, עם HistData)
"""
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

IL = "Asia/Jerusalem"
SIGNALS = Path(__file__).with_name("cryptonew84_signals.txt")
WINDOWS = ((9.25, 10.5), (14.0, 16.25), (17.25, 19.75))   # שעות עשרוניות בשעון ישראל


def load(path: Path = SIGNALS, year: int = 2026) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        n, d, t, side, a, b, t1, t2, t3, op, sl = line.split()
        a, b = float(a), float(b)
        ts = pd.Timestamp(f"{year}-{d[3:5]}-{d[:2]} {t}", tz=IL)
        out.append({"n": int(n), "t": ts.tz_convert("UTC"), "il": ts, "direction": 1 if side == "B" else -1,
                    "first": a, "zone_lo": min(a, b), "zone_hi": max(a, b),
                    "tps": [float(t1), float(t2), float(t3)], "open": op == "1", "sl": None if sl == "-" else float(sl)})
    return out


def profile(sigs: list[dict]) -> str:
    def near(s):
        return s["zone_hi"] if s["direction"] == 1 else s["zone_lo"]

    def far(s):
        return s["zone_lo"] if s["direction"] == 1 else s["zone_hi"]

    width = pd.Series([s["zone_hi"] - s["zone_lo"] for s in sigs]).value_counts()
    tp1 = pd.Series([abs(s["tps"][0] - near(s)) for s in sigs]).value_counts()
    sl = [abs(s["sl"] - far(s)) for s in sigs if s["sl"]]
    hrs = pd.Series([s["il"].hour for s in sigs]).value_counts().sort_index()
    per_day = pd.Series([s["il"].date() for s in sigs]).value_counts().value_counts().sort_index()
    fade = cont = 0
    for p, s in zip(sigs, sigs[1:]):
        mv = (s["zone_lo"] + s["zone_hi"]) / 2 - (p["zone_lo"] + p["zone_hi"]) / 2
        if abs(mv) >= 10:
            fade, cont = fade + (mv * s["direction"] < 0), cont + (mv * s["direction"] > 0)
    buys = sum(s["direction"] == 1 for s in sigs)
    return "\n".join([
        f"### 🧬 Cryptonew84: {len(sigs)} סיגנלים, {sigs[0]['il']:%d/%m} עד {sigs[-1]['il']:%d/%m/%Y}",
        f"- קניות {buys} · מכירות {len(sigs) - buys}",
        "- רוחב אזור: " + " · ".join(f"{k:g}$×{v}" for k, v in width.items()),
        "- TP1 מקצה האזור: " + " · ".join(f"{k:g}$×{v}" for k, v in tp1.items()),
        f"- סטופ גלוי ב-{len(sl)} סיגנלים, מעבר לקצה הרחוק: {np.mean(sl):.1f}$ בממוצע (השאר: #VIP)",
        "- שעה (ישראל): " + " · ".join(f"{h:02d}:{v}" for h, v in hrs.items()),
        "- סיגנלים ביום: " + " · ".join(f"{k}→{v} ימים" for k, v in per_day.items()),
        f"- מול הסיגנל הקודם (תזוזה ≥10$): נגד התנועה {fade} · עם התנועה {cont}",
    ])


TEMPLATES = {
    "aug": "Gold（XAUUSD）📊\n{SIDE}{dot}{a}-{b}\n\n{tps}\n\nSL⛔️    #VIP       \n\n"
           "⚠️ Manage your risk properly, strictly follow SL and TP",
    "sep": "Gold（XAUUSD）📊\n{SIDE}{dot}{a}-{b}\n{tps}\n\nSL⛔️{sl}",
    "product": "🪙 Product: Gold (XAUUSD)\n\n{dot}{SIDE}：{a}-{b}\n\n{tps}\n\n{sl_line}",
}


def render(sig: dict, style: str = "product", show_sl: bool = False) -> str:
    d = sig["direction"]
    dot = "🟢" if d == 1 else "🔴"
    a, b = (sig["zone_hi"], sig["zone_lo"]) if d == 1 else (sig["zone_lo"], sig["zone_hi"])
    tps = [f"{x:.0f}" for x in sig["tps"]] + (["OPEN"] if sig.get("open", True) else [])
    if style == "product":
        lines = [f"🎯 TP{i}: {x}" for i, x in enumerate(tps, 1)]
        sl_line = f"⛔️ SL: {sig['sl']:.0f}" if show_sl else "SL⛔️#VIP"
    else:
        lines = [f"TP{i} 🎯{x}" for i, x in enumerate(tps, 1)]
        sl_line = ""
    return TEMPLATES[style].format(SIDE="BUY" if d == 1 else "SELL", dot=dot, a=f"{a:.0f}", b=f"{b:.0f}",
                                   tps="\n".join(lines), sl=f"{sig['sl']:.0f}" if show_sl else "#VIP", sl_line=sl_line)


def build(price: float, d: int, width: float = 10, near_gap: float = 1, tp_step: float = 5, sl_gap: float = 10) -> dict:
    """האזור לפי התבנית: הקצה הקרוב 1$ מהמחיר (לימיט), עוד width$ לעומק, יעדים כל 5$ מהקצה הקרוב."""
    near = round(price - d * near_gap)
    far = near - d * width
    return {"direction": d, "zone_lo": min(near, far), "zone_hi": max(near, far),
            "tps": [near + d * tp_step * i for i in (1, 2, 3)], "sl": far - d * sl_gap, "open": True}


@dataclass
class Clone:
    """"הקוד של הערוץ" כפי שאפשר לשחזר אותו: מקבל נר דקה (UTC) בכל פעם ומחזיר סיגנל או None."""
    fade: float = 10.0          # תזוזה מינימלית בדולרים כדי ללכת נגדה
    wide: float = 15.0          # מעל תזוזה כזו ב-4 שעות האזור 10$, אחרת 5$
    min_gap_h: float = 2.5
    seed: int = 84
    _hist: deque = field(default_factory=deque)
    _last: tuple | None = None   # (זמן, מחיר) של הסיגנל הקודם
    _plan: dict = field(default_factory=dict)

    def _minute(self, day, w) -> float:
        a, b = WINDOWS[w]
        r = random.Random(f"{self.seed}-{day}-{w}")
        return a + r.random() * (b - a)

    def on_bar(self, t: pd.Timestamp, close: float) -> dict | None:
        self._hist.append((t, close))
        while t - self._hist[0][0] > pd.Timedelta(hours=24):
            self._hist.popleft()
        il = t.tz_convert(IL)
        if il.weekday() >= 5:
            return None
        h = il.hour + il.minute / 60
        for w, (a, b) in enumerate(WINDOWS):
            key = (il.date(), w)
            if not a <= h < b or key in self._plan:
                continue
            if h < self._minute(il.date(), w):
                return None
            if self._last and t - self._last[0] < pd.Timedelta(hours=self.min_gap_h):
                self._plan[key] = None
                return None
            past4 = [c for x, c in self._hist if x <= t - pd.Timedelta(hours=4)]
            past1 = [c for x, c in self._hist if x <= t - pd.Timedelta(hours=1)]
            ref = self._last[1] if self._last and t - self._last[0] <= pd.Timedelta(hours=24) else (past4 or [close])[-1]
            mv = close - ref
            if abs(mv) < self.fade:
                mv = close - (past1 or [close])[-1]
            d = -1 if mv > 0 else 1
            m4 = abs(close - (past4 or [close])[-1])
            sig = build(close, d, width=10 if m4 >= self.wide else 5)
            sig.update(t=t, price=close, move=mv)
            self._plan[key] = sig
            self._last = (t, close)
            return sig
        return None


def compare(m1: pd.DataFrame, sigs: list[dict] | None = None) -> str:
    """בודק את הכלל מול הסיגנלים האמיתיים: איפה המחיר היה ברגע הסיגנל, ואיזה מאפיין מנבא את הכיוון."""
    sigs = sigs or load()
    c = m1["close"]
    rows = []
    for s in sigs:
        i = c.index.searchsorted(s["t"])
        if i >= len(c) or i < 24 * 60:
            continue
        px = c.iloc[i]
        at = lambda hours: c.asof(s["t"] - pd.Timedelta(hours=hours))
        near = s["zone_hi"] if s["direction"] == 1 else s["zone_lo"]
        rows.append({"n": s["n"], "d": s["direction"], "px": px, "near_gap": (px - near) * s["direction"],
                     "in_zone": s["zone_lo"] <= px <= s["zone_hi"],
                     **{f"m{h}": px - at(h) for h in (0.25, 1, 4, 24)}})
    if not rows:
        return "אין נתוני דקה שחופפים לסיגנלים."
    df = pd.DataFrame(rows)
    lines = [f"### 🧬 Cryptonew84 מול נתוני דקה: {len(df)} סיגנלים", "",
             f"- המחיר בתוך האזור ברגע השליחה: {100 * df.in_zone.mean():.0f}%",
             f"- מרחק המחיר מהקצה הקרוב (חיובי = המחיר כבר מעבר לקצה, לכיוון היעד): חציון {df.near_gap.median():+.1f}$",
             "", "| תנועה לפני הסיגנל | נגד התנועה | עם התנועה | ממוצע התנועה בכיוון העסקה |", "|---|---|---|---|"]
    for h in (0.25, 1, 4, 24):
        x = df[f"m{h}"] * df.d
        lines.append(f"| {h:g} שעות | {100 * (x < 0).mean():.0f}% | {100 * (x > 0).mean():.0f}% | {x.mean():+.1f}$ |")
    clone, agree, n = Clone(), 0, 0
    times = {s["t"].floor("min"): s for s in sigs}
    got = []
    for t, px in c[c.index >= sigs[0]["t"] - pd.Timedelta(days=2)].items():
        g = clone.on_bar(t, px)
        if g:
            got.append(g)
    for s in sigs:   # לכל סיגנל אמיתי: מה הקלון אמר באותו חלון
        same = [g for g in got if abs((g["t"] - s["t"]).total_seconds()) <= 3 * 3600 and
                g["t"].tz_convert(IL).date() == s["il"].date()]
        if same:
            n += 1
            agree += same[0]["direction"] == s["direction"]
    lines += ["", f"- הקלון שלח {len(got)} סיגנלים בתקופה (הערוץ: {len(times)}). "
                  f"באותו חלון: {n} התאמות זמן, מתוכן אותו כיוון ב-{agree} ({100 * agree / max(n, 1):.0f}%)"]
    return "\n".join(lines)


if __name__ == "__main__":
    s = load()
    print(profile(s))
    print("\n--- דוגמה מהקלון (מחיר 4150, קנייה) ---\n" + render(build(4150, 1)))
