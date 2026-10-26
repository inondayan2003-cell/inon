"""סבב 3: הטיית שעה-ביום של הזהב, בשעון ניו יורק (שעון קיץ/חורף נכון), עם בדיקת יציבות.

1. פרופיל: תשואה ממוצעת לכל שעה בשעון ניו יורק (ביחידות ATR), בנפרד ל-3 תקופות:
   P1 = 10 החודשים הראשונים, P2 = 10 החודשים הבאים, V = כספת (4 אחרונים).
2. אסטרטגיה לכל (שעה, כיוון): כניסה בתחילת השעה, סטופ 1 ATR(1H), יעד 1:2/1:3, יציאה בזמן אחרי 4 שעות.
3. הליכה קדימה: בוחרים שעות רק לפי P1 (z>2), בודקים אותן כמקשה אחת על P2 ועל הכספת.
   ואז בוחרים לפי P1+P2 ובודקים רק על הכספת.
"""
import numpy as np
import pandas as pd

from app.indicators import atr as wilder_atr
from research.loop import _s
from research.loop2 import simulate

NY = "America/New_York"


def _periods(idx: pd.DatetimeIndex, holdout_months: int):
    vault = idx[-1] - pd.DateOffset(months=holdout_months)
    mid = idx[0] + (vault - idx[0]) / 2
    return mid, vault


def run_hours(df: pd.DataFrame, a: np.ndarray, plan: dict, rr: float, hold: int, cost: float, k: float = 1.0):
    """plan = {שעת ניו יורק: כיוון}. סיגנל בנר שלפני השעה (כניסה בסגירתו = פתיחת השעה)."""
    nxt = (df.index + pd.Timedelta(hours=1)).tz_convert(NY).hour
    sig = np.zeros(len(df), dtype=int)
    for hr, d in plan.items():
        sig[nxt == hr] = d
    return simulate(df, sig, k * a, rr, hold, cost)


def report(m1: pd.DataFrame, cost: float, holdout_months: int = 4) -> str:
    from app.data import resample
    from research.null import shuffle_within_day
    df = resample(m1, "1h")
    a = wilder_atr(df, 14).to_numpy()
    mid, vault = _periods(df.index, holdout_months)
    per = np.where(df.index < mid, 0, np.where(df.index < vault, 1, 2))
    ret = (df["close"] - df["open"]).to_numpy() / a
    hr = df.index.tz_convert(NY).hour
    lines = [f"### 🕐 סבב 3: הטיית שעה בשעון ניו יורק · P1 עד {mid:%Y-%m-%d} · P2 עד {vault:%Y-%m-%d} · כספת אחרי · עלות {cost}$", "",
             "**פרופיל: תנועה ממוצעת בשעה (ב-ATR) · t**", "",
             "| שעה NY | שעון ישראל | P1 | P2 | כספת |", "|---|---|---|---|---|"]
    for h in range(24):
        cells = []
        for p in range(3):
            x = ret[(hr == h) & (per == p) & ~np.isnan(ret)]
            t = x.mean() / x.std(ddof=1) * np.sqrt(len(x)) if len(x) > 2 else 0
            cells.append(f"{x.mean():+.3f} · {t:+.1f}")
        lines.append(f"| {h:02d}:00 | {(h + 7) % 24:02d}:00 | " + " | ".join(cells) + " |")

    null_df = resample(shuffle_within_day(m1, 1), "1h")
    null_a = wilder_atr(null_df, 14).to_numpy()
    rows = []
    for h in range(24):
        for d in (1, -1):
            for rr in (2.0, 3.0):
                tr = run_hours(df, a, {h: d}, rr, 4, cost)
                nt = run_hours(null_df, null_a, {h: d}, rr, 4, cost)
                part = [_s(tr[(tr.t >= lo) & (tr.t < hi)]) for lo, hi in
                        ((df.index[0], mid), (mid, vault), (vault, df.index[-1] + pd.Timedelta(hours=1)))]
                nv = _s(nt[nt.t >= vault])["sum"]
                rows.append({"h": h, "d": d, "rr": rr, "p": part, "null_v": nv, "null_all": _s(nt)["sum"]})
    rows.sort(key=lambda r: min(r["p"][0]["t"], r["p"][1]["t"]), reverse=True)
    lines += ["", "**אסטרטגיית שעה (סטופ 1 ATR, יציאה בזמן 4 שעות) - מסודר לפי ה-t הנמוך מבין P1/P2:**", "",
              "| שעה NY | כיוון | יחס | P1: n · R · t | P2: n · R · t | **כספת: n · R · t** | ביקורת כספת R | ביקורת הכל R |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows[:16]:
        c = [f"{x['n']} · {x['sum']:+.1f} · {x['t']:+.1f}" for x in r["p"]]
        lines.append(f"| {r['h']:02d}:00 | {'לונג' if r['d'] == 1 else 'שורט'} | 1:{r['rr']:.0f} | {c[0]} | {c[1]} | **{c[2]}** | "
                     f"{r['null_v']:+.1f} | {r['null_all']:+.1f} |")

    def combo(sel_end, label, test_from):
        best = {}
        for r in rows:
            if r["rr"] != 3.0:
                continue
            ps = r["p"][:1] if sel_end == "P1" else r["p"][:2]
            n = sum(x["n"] for x in ps)
            s = sum(x["sum"] for x in ps)
            if n < 50:
                continue
            z = min(x["t"] for x in ps)
            if z > 2.0 and (r["h"] not in best or z > best[r["h"]][1]):
                best[r["h"]] = (r["d"], z)
        plan = {h: d for h, (d, _) in best.items()}
        if not plan:
            return [f"{label}: אף שעה לא עברה את הסף."]
        out = []
        for rr in (2.0, 3.0):
            tr = run_hours(df, a, plan, rr, 4, cost)
            tst = tr[tr.t >= test_from]
            v = tr[tr.t >= vault]
            s, sv = _s(tst), _s(v)
            days = df.index[df.index >= test_from].normalize().nunique()
            out.append(f"{label} · 1:{rr:.0f} · שעות {sorted(plan.items())} → מבחן: {s['n']} עסקאות ({s['n'] / max(days, 1):.1f}/יום), "
                       f"{s['sum']:+.1f}R, t {s['t']:+.1f}, הצלחה {s.get('win', 0):.0f}% · מתוכו כספת: {sv['n']} · {sv['sum']:+.1f}R · t {sv['t']:+.1f}")
        return out

    lines += ["", "**הליכה קדימה (בחירה על העבר בלבד, בדיקה על מה שאחריו):**", ""]
    lines += combo("P1", "בחירה לפי P1", mid)
    lines += combo("P2", "בחירה לפי P1+P2", vault)
    return "\n".join(lines)
