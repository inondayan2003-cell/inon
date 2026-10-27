"""הכלל של Cryptonew84 (מההנדסה ההפוכה של 11 סיגנלי זהב), מורץ על 2018 עד היום.

מה נמצא בסיגנלים שלהם:
- ב-24 השעות שלפני: תנועה של כ-37$ נגד כיוון העסקה, ב-4 השעות שלפני: כ-15$ נגד, בשעה האחרונה: כ-1.5$ בעד (תיקון ראשון).
- רק 18% בכיוון המגמה היומית: קונים אחרי ירידה חדה (ומוכרים אחרי עלייה חדה).
- אזור ברוחב 10$, ראש האזור 1$ מהמחיר, סטופ 10$ מעבר לאזור (על מספר עגול), יעדים 5/10/15$ מראש האזור.
- שעות: בעיקר 09:00 ו-12:00-14:00 שעון ישראל.

המספרים בדולרים נכונים לזהב של ~4,150$. לשנים קודמות הם מוקטנים לפי המחיר (k = מחיר / 4150),
והתנועות נמדדות ביחידות של הטווח היומי הממוצע (37$ ≈ 0.5 טווח יומי היום).
"""
import itertools

import numpy as np
import pandas as pd

from app.signals import evaluate
from research.daytime import Data, _st

REF = 4150.0
IL = "Asia/Jerusalem"


def candidates(dt: Data, rng_avg: np.ndarray, a24: float, a4: float, bounce: bool, hours: set | None, both: bool,
               tz: str = IL):
    """נקודות החלטה: כל שעה עגולה (+5 דקות). מחזיר [(i, d)] עם הפרדה של 4 שעות לפחות בין סיגנלים."""
    m1 = dt.m1
    idx = m1.index
    il = idx.tz_convert(tz)
    ok = (il.minute == 5)
    if hours is not None:
        ok &= np.isin(il.hour, list(hours))
    cand = np.flatnonzero(ok)
    secs, c = dt.secs, dt.c
    out, last = [], -1e18
    for i in cand:
        if secs[i] - last < 4 * 3600:
            continue
        s = dt.session[i]
        R = rng_avg[s] if s < len(rng_avg) else np.nan
        if not R > 0:
            continue
        j24 = np.searchsorted(secs, secs[i] - 24 * 3600)
        j4 = np.searchsorted(secs, secs[i] - 4 * 3600)
        j1 = np.searchsorted(secs, secs[i] - 3600)
        if secs[i] - secs[j24] < 20 * 3600:
            continue
        m24, m4, m1_ = c[i] - c[j24], c[i] - c[j4], c[i] - c[j1]
        for d in ((1, -1) if both else (1,)):
            if (a24 <= 0 or m24 * d <= -a24 * R) and m4 * d <= -a4 * R and (not bounce or m1_ * d > 0):
                out.append((i, d))
                last = secs[i]
                break
    return out


def run(dt: Data, rng_avg, p, cost):
    res = []
    for i, d in candidates(dt, rng_avg, p["a24"], p["a4"], p["bounce"], p["hours"], p["both"], p.get("tz", IL)):
        price = dt.c[i]
        k = price / REF
        near = price - d * 0.5 * k
        zone = (near, near - d * p.get("width", 10) * k)
        sl = zone[1] - d * 10 * k
        if p["exit"] == "theirs":
            tps = [near + d * x * k for x in (5, 10, 15)]
        else:
            tps = [near + d * p["exit"] * abs(near - sl)]
        sig = {"direction": d, "zone_hi": max(zone), "zone_lo": min(zone), "sl": sl, "tps": tps}
        bars = dt.m1.iloc[i + 1: i + 1 + 24 * 60]
        bars = bars[dt.session[i + 1: i + 1 + len(bars)] == dt.session[i]] if len(bars) else bars
        if len(bars) < 30:
            continue
        r = evaluate(sig, bars, 24)
        if r.get("filled"):
            res.append((dt.m1.index[i], d, r["r_split"] - cost / r["risk"], r["tp_hits"] > 0, r["stopped"]))
    return pd.DataFrame(res, columns=["t", "d", "r", "tp1", "sl"])


KZ = {"לונדון 02": {2}, "קילזונים 02+07-08": {2, 7, 8}, "כל הקילזונים": {2, 3, 4, 7, 8, 9, 10}}


def report2(m1: pd.DataFrame, cost: float) -> str:
    """גרסה 2 לפי 100 הסיגנלים: שעות פתיחת הקילזונים בשעון ניו יורק, נגד תנועת 4 השעות אחרי תיקון ראשון,
    בלי דרישת ירידה של 24 שעות, אזור 5$ או 10$, יעדים 5/10/15 וסטופ 10$ מעבר לאזור."""
    from research.allday import session_stats
    dt = Data(m1)
    _, rng_avg, _, _ = session_stats(dt)
    t1, t2 = pd.Timestamp("2023-01-01", tz="UTC"), m1.index[-1] - pd.DateOffset(months=24)
    years = sorted(set(m1.index.year))
    weeks = (m1.index[-1] - m1.index[0]).days / 7
    lines = [f"### 🧬 גרסה 2: הכלל של Cryptonew84 לפי 100 סיגנלים · {m1.index[0]:%Y-%m} עד {m1.index[-1]:%Y-%m} · עלות {cost}$", "",
             "| שעות (NY) | נגד תנועת 4ש' (טווחים) | תיקון | רוחב | יציאה | עסק'/שבוע | TP1% | סטופ% | ממוצע R | "
             "גילוי 2018-22 R · t | 2023-24 R · t | שנתיים אחרונות R · t | " + " | ".join(str(y) for y in years) + " |",
             "|" + "---|" * (12 + len(years))]
    rows = []
    for (kz, hrs), a4, bounce, width, ex in itertools.product(KZ.items(), (0.05, 0.1, 0.2, 0.3), (True, False), (5, 10),
                                                             ("theirs", 2.0, 3.0)):
        p = dict(a24=0, a4=a4, bounce=bounce, hours=hrs, both=True, exit=ex, width=width, tz="America/New_York")
        tr = run(dt, rng_avg, p, cost)
        if len(tr) < 30:
            continue
        r = tr.r.to_numpy()
        parts = [r[tr.t < t1], r[(tr.t >= t1) & (tr.t < t2)], r[tr.t >= t2]]
        rows.append((kz, p, tr, parts))
    rows.sort(key=lambda x: _st(x[3][0])[1], reverse=True)
    f = lambda x: f"{x.sum():+.0f} · {_st(x)[1]:+.1f}" if len(x) > 2 else "-"
    for kz, p, tr, parts in rows:
        ex = "שלהם 5/10/15" if p["exit"] == "theirs" else f"1:{p['exit']:.0f}"
        lines.append(f"| {kz} | {p['a4']} | {'כן' if p['bounce'] else 'לא'} | {p['width']}$ | {ex} | {len(tr) / weeks:.1f} | "
                     f"{100 * tr.tp1.mean():.0f}% | {100 * tr.sl.mean():.0f}% | {tr.r.mean():+.3f} | {f(parts[0])} | {f(parts[1])} | "
                     f"{f(parts[2])} | " + " | ".join(f"{tr[tr.t.dt.year == y].r.sum():+.0f}" for y in years) + " |")
    passed = [x for x in rows if _st(x[3][0])[1] >= 3 and x[3][1].sum() > 0 and x[3][2].sum() > 0]
    lines += ["", f"עברו (t≥3 בגילוי ורווחי בשני המבחנים): **{len(passed)}** מתוך {len(rows)}"]
    return "\n".join(lines)


def report(m1: pd.DataFrame, cost: float) -> str:
    from research.allday import session_stats
    dt = Data(m1)
    _, rng_avg, _, _ = session_stats(dt)
    their_hours = {9, 12, 13, 14}
    grid = itertools.product((0.3, 0.5, 0.8), (0.0, 0.2), (True, False), (their_hours, None), (False, True),
                             ("theirs", 2.0, 3.0))
    t1, t2 = pd.Timestamp("2023-01-01", tz="UTC"), m1.index[-1] - pd.DateOffset(months=24)
    years = sorted(set(m1.index.year))
    lines = [f"### 🧬 הכלל של Cryptonew84 על {m1.index[0]:%Y-%m} עד {m1.index[-1]:%Y-%m} · עלות {cost}$", "",
             "| ירידה 24ש' (טווחים) | ירידה 4ש' | תיקון בשעה האחרונה | שעות | גם מכירות | יציאה | עסק'/שבוע | TP1% | סטופ% | "
             "גילוי 2018-22 R · t | מבחן 2023-24 R · t | שנתיים אחרונות R · t | " + " | ".join(str(y) for y in years) + " |",
             "|" + "---|" * (12 + len(years))]
    rows = []
    for a24, a4, bounce, hrs, both, ex in grid:
        p = dict(a24=a24, a4=a4, bounce=bounce, hours=hrs, both=both, exit=ex)
        tr = run(dt, rng_avg, p, cost)
        if len(tr) < 20:
            continue
        r = tr.r.to_numpy()
        parts = [r[tr.t < t1], r[(tr.t >= t1) & (tr.t < t2)], r[tr.t >= t2]]
        weeks = (m1.index[-1] - m1.index[0]).days / 7
        rows.append((p, tr, parts, weeks))
    rows.sort(key=lambda x: _st(x[2][0])[1], reverse=True)
    for p, tr, parts, weeks in rows:
        f = lambda x: f"{x.sum():+.0f} · {_st(x)[1]:+.1f}" if len(x) > 2 else "-"
        ex = "שלהם 5/10/15" if p["exit"] == "theirs" else f"1:{p['exit']:.0f}"
        lines.append(f"| {p['a24']} | {p['a4']} | {'כן' if p['bounce'] else 'לא'} | {'שלהם' if p['hours'] else 'כל שעה'} | "
                     f"{'כן' if p['both'] else 'לא'} | {ex} | {len(tr) / weeks:.1f} | {100 * tr.tp1.mean():.0f}% | "
                     f"{100 * tr.sl.mean():.0f}% | {f(parts[0])} | {f(parts[1])} | {f(parts[2])} | "
                     + " | ".join(f"{tr[tr.t.dt.year == y].r.sum():+.0f}" for y in years) + " |")
    exact = [x for x in rows if x[0]["a24"] == 0.5 and x[0]["a4"] == 0.2 and x[0]["bounce"] and x[0]["hours"]
             and x[0]["exit"] == "theirs" and not x[0]["both"]]
    if exact:
        p, tr, parts, _ = exact[0]
        lines += ["", f"**הכלל הכי קרוב לשלהם** (ירידה 0.5 טווח ב-24ש', 0.2 ב-4ש', תיקון, השעות שלהם, יעדים 5/10/15): "
                      f"{len(tr)} עסקאות, TP1 ב-{100 * tr.tp1.mean():.0f}%, סטופ ב-{100 * tr.sl.mean():.0f}%, "
                      f"סך הכל {tr.r.sum():+.1f}R (ממוצע {tr.r.mean():+.3f}R לעסקה)"]
    return "\n".join(lines)
