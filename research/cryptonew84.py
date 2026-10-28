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


def outcomes(m1: pd.DataFrame, sigs: list[dict] | None = None, hours: float = 24) -> str:
    """מה קרה לכל סיגנל מרגע השליחה: נכנס או לא, אילו יעדים, סטופ. רווח בדולרים לאונקיה, חלוקה שווה בין 3 היעדים."""
    from app.signals import evaluate
    sigs = sigs or load()
    lines = ["### 📊 Cryptonew84: מה קרה לכל סיגנל (24 שעות מהשליחה, סטופ מוסתר = 10$ מעבר לאזור)", "",
             "| # | זמן (ישראל) | צד | אזור | תוצאה | דקות עד כניסה | הכי נגד עד TP1 | $ (שליש לכל יעד) | $ רק TP1 |",
             "|---|---|---|---|---|---|---|---|---|"]
    rows = []
    for s in sigs:
        bars = m1[(m1.index >= s["t"]) & (m1.index < s["t"] + pd.Timedelta(hours=hours))]
        if len(bars) < 30:
            continue
        r = evaluate(s, bars, hours)
        side = "BUY" if s["direction"] == 1 else "SELL"
        zone = f"{s['zone_lo']:.0f}-{s['zone_hi']:.0f}"
        if not r.get("filled"):
            lines.append(f"| {s['n']} | {s['il']:%d/%m %H:%M} | {side} | {zone} | ⚪ לא נכנס | - | - | 0 | 0 |")
            rows.append({"filled": False})
            continue
        n = r["tp_hits"]
        usd, usd1 = r["r_split"] * r["risk"], r["r_tp1_only"] * r["risk"]
        res = (f"✅ TP{n} ואז סטופ" if n and r["stopped"] else "❌ סטופ" if r["stopped"] else
               "✅ כל היעדים" if n == 3 else f"✅ TP{n}, השאר נסגר בזמן" if n else "⏳ לא הגיע לכלום, נסגר בזמן")
        lines.append(f"| {s['n']} | {s['il']:%d/%m %H:%M} | {side} | {zone} | {res} | {r['fill_minutes']} | "
                     f"{r['mae']:.1f}$ | {usd:+.1f} | {usd1:+.1f} |")
        rows.append({"filled": True, "n": n, "sl": r["stopped"], "usd": usd, "usd1": usd1, "tp1ns": r["tp1_no_stop"],
                     "be": r["r_be"] * r["risk"], "d": s["direction"], "h": s["il"].hour})
    df = pd.DataFrame(rows)
    f = df[df.filled]
    p = lambda x: f"{100 * x.mean():.0f}%"
    lines += ["", "| מדד | ערך |", "|---|---|",
              f"| סיגנלים שנבדקו | {len(df)} |",
              f"| נכנסו (המחיר נגע באזור) | {len(f)} ({p(df.filled)}) |",
              f"| TP1 לפני סטופ | **{p(f.n >= 1)}** |",
              f"| TP2 | {p(f.n >= 2)} |", f"| TP3 | {p(f.n >= 3)} |",
              f"| סטופ לפני TP1 | **{p((f.n == 0) & f.sl)}** |",
              f"| TP1 ואז חזר לסטופ | {p((f.n >= 1) & f.sl)} |",
              f"| TP1 הגיע אי פעם, גם בלי סטופ בכלל | {p(f.tp1ns)} |",
              f"| סה\"כ $ לאונקיה, שליש לכל יעד | **{f.usd.sum():+.0f}$** (ממוצע {f.usd.mean():+.2f}$) |",
              f"| סה\"כ $, סוגרים הכל ב-TP1 | **{f.usd1.sum():+.0f}$** |",
              f"| סה\"כ $, שליש לכל יעד וסטופ לכניסה אחרי TP1 | {f.be.sum():+.0f}$ |",
              f"| קניות / מכירות ($ שליש לכל יעד) | {f[f.d == 1].usd.sum():+.0f}$ / {f[f.d == -1].usd.sum():+.0f}$ |",
              "| לפי חלון | " + " · ".join(f"{a}: {len(g)} עסק' {g.usd.sum():+.0f}$" for a, g in
                                    f.groupby(pd.cut(f.h, [0, 12, 17, 24], right=False,
                                                     labels=["בוקר", "צהריים", "ערב"]), observed=True)) + " |",
              "", "‏1$ לאונקיה = 1$ על 0.01 לוט (1 אונקיה), 100$ על לוט שלם."]
    return "\n".join(lines)


def bot_report(m1: pd.DataFrame, cost: float = 0.35) -> str:
    """הבוט שלנו (ChannelFadeStrategy, גרסה 2) על נרות 5 דקות: התקופה של הערוץ ואחריה. דולרים לאונקיה, אחרי עלות."""
    import itertools

    from app.config import Settings
    from app.strategy import ChannelFadeStrategy
    m5 = m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    rows = [dict(t=t + pd.Timedelta(minutes=5), open=o, high=h, low=l, close=c)
            for t, o, h, l, c in m5[m5.index >= "2026-07-25"].itertuples()]
    split, start = pd.Timestamp("2026-10-08", tz="UTC"), pd.Timestamp("2026-08-03", tz="UTC")
    cfg = Settings()

    def run(p):
        st, out = ChannelFadeStrategy(cfg, **p), []
        for r in rows:
            for ev in st.on_bar(pd.Series(r)):
                if ev["type"] == "closed":
                    tr = ev["trade"]
                    risk = abs(tr["entry"] - tr["sl"])
                    out.append({"t": pd.Timestamp(tr["opened_at"]), "d": tr["direction"], "status": tr["status"],
                                "usd": tr["result_r"] * risk - cost, "entry": tr["entry"]})
        df = pd.DataFrame(out)
        return df[df.t >= start] if len(df) else df

    def cell(x):
        if not len(x):
            return "-"
        eq = x.usd.cumsum()
        dd = float((eq.cummax().clip(lower=0) - eq).max())
        return f"{len(x)} · {x.usd.sum():+.0f}$ · DD {dd:.0f}$"

    lines = [f"### 🤖 הבוט שלנו (שיטת הערוץ גרסה 2) · עלות {cost}$ · דולרים לאונקיה (0.01 לוט)", "",
             "| ירידה/עלייה 4ש' | תיקון (דק') | רוחב | BE אחרי TP1 | 03/08-07/10 (הערוץ) עסק' · $ · DD | "
             "08/10-היום (אחרי) | TP1% | סטופ מלא% | $ לעסקה |", "|---|---|---|---|---|---|---|---|---|"]
    default = None
    for fade, bmin, width, be in itertools.product((5.0, 10.0, 15.0), (5, 15, 30), (5.0, 10.0), (True, False)):
        df = run({"fade": fade, "bounce_min": bmin, "width": width, "be": be})
        if not len(df):
            continue
        a, b = df[df.t < split], df[df.t >= split]
        tp1 = (df.status != "sl").mean() if len(df) else 0
        lines.append(f"| {fade:g}$ | {bmin} | {width:g}$ | {'כן' if be else 'לא'} | {cell(a)} | {cell(b)} | "
                     f"{100 * tp1:.0f}% | {100 * (df.status == 'sl').mean():.0f}% | {df.usd.mean():+.2f} |")
        if (fade, bmin, width, be) == (ChannelFadeStrategy.FADE, ChannelFadeStrategy.BOUNCE_MIN,
                                       ChannelFadeStrategy.WIDTH, ChannelFadeStrategy.BE):
            default = df
    if default is not None:
        lines += ["", f"**ברירת המחדל בבוט** (4ש' ≥{ChannelFadeStrategy.FADE:g}$, תיקון {ChannelFadeStrategy.BOUNCE_MIN} דק', "
                      f"רוחב {ChannelFadeStrategy.WIDTH:g}$, BE): כל העסקאות", "",
                  "| זמן (ישראל) | צד | כניסה | תוצאה | $ |", "|---|---|---|---|---|"]
        names = {"tp2": "✅ כל היעדים", "be": "⚖️ TP ואז כניסה", "sl": "❌ סטופ", "expired": "⏰ נסגר בזמן"}
        for r in default.itertuples():
            lines.append(f"| {r.t.tz_convert(IL):%d/%m %H:%M} | {'BUY' if r.d == 1 else 'SELL'} | {r.entry:.2f} | "
                         f"{names.get(r.status, r.status)} | {r.usd:+.1f} |")
    lines += ["", "‏סטטוס \"סטופ מלא\" = נעצר לפני TP1. TP1% = כל מה שלא נעצר בסטופ מלא."]
    return "\n".join(lines)


def rr_report(m1: pd.DataFrame, cost: float = 0.35) -> str:
    """המבנה ההפוך: סטופ קטן ויעד אחד גדול (1:2 / 1:3), באותם חלונות ובאותו טריגר. גם נגד וגם עם תנועת 4 השעות."""
    import itertools

    from app.config import Settings
    from app.strategy import ChannelFadeStrategy
    m5 = m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    rows = [pd.Series(dict(t=t + pd.Timedelta(minutes=5), open=o, high=h, low=l, close=c))
            for t, o, h, l, c in m5[m5.index >= "2026-07-25"].itertuples()]
    split, start = pd.Timestamp("2026-10-08", tz="UTC"), pd.Timestamp("2026-08-03", tz="UTC")
    cfg = Settings()

    def run(p):
        st, out = ChannelFadeStrategy(cfg, **p), []
        for r in rows:
            for ev in st.on_bar(r):
                if ev["type"] == "closed":
                    tr = ev["trade"]
                    risk = abs(tr["entry"] - tr["sl"])
                    out.append({"t": pd.Timestamp(tr["opened_at"]), "status": tr["status"],
                                "r": tr["result_r"] - cost / risk, "usd": tr["result_r"] * risk - cost})
        df = pd.DataFrame(out)
        return df[df.t >= start] if len(df) else df

    def cell(x):
        if not len(x):
            return "-"
        eq = x.usd.cumsum()
        dd = float((eq.cummax().clip(lower=0) - eq).max())
        return f"{len(x)} · {x.usd.sum():+.0f}$ · {x.r.sum():+.1f}R · DD {dd:.0f}$"

    lines = [f"### 🔄 מבנה הפוך: סטופ קטן, יעד גדול · עלות {cost}$ · דולרים לאונקיה (0.01 לוט)", "",
             "| כיוון | תנועה 4ש' | תיקון (דק') | סטופ | יעד | 03/08-07/10 עסק' · $ · R · DD | 08/10-היום | "
             "הצלחה | צריך להצלחה | $ לעסקה |", "|---|---|---|---|---|---|---|---|---|---|"]
    res = []
    for dr, fade, bmin, stop, rr in itertools.product((1, -1), (5.0, 10.0), (5, 15), (5.0, 8.0, 12.0), (2, 3)):
        df = run({"dir": dr, "fade": fade, "bounce_min": bmin, "width": 0.0, "sl_gap": stop,
                  "tps": (rr * stop,), "be": False})
        if not len(df):
            continue
        a, b = df[df.t < split], df[df.t >= split]
        win = (df.status == "tp2").mean()
        need = (1 + cost / stop) / (1 + rr)
        res.append((a.usd.sum() > 0 and b.usd.sum() > 0, a.usd.sum()))
        lines.append(f"| {'נגד (כמו הערוץ)' if dr == 1 else 'עם (המשך)'} | {fade:g}$ | {bmin} | {stop:g}$ | {rr * stop:g}$ (1:{rr}) | "
                     f"{cell(a)} | {cell(b)} | {100 * win:.0f}% | {100 * need:.0f}% | {df.usd.mean():+.2f} |")
    both = sum(x[0] for x in res)
    lines += ["", f"**רווחיות בשתי התקופות: {both} מתוך {len(res)} גרסאות.** "
                  "(במקרה, בערך רבע מהגרסאות אמורות לצאת רווחיות בשתיהן.)",
              "‏\"הצלחה\" = הגיע ליעד. \"צריך להצלחה\" = אחוז ההצלחה שבו הגרסה מתאזנת אחרי עלות."]
    return "\n".join(lines)
