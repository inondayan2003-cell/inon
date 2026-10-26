"""GoldSmartMoneyStrategy (קוד FVG שהמשתמש שלח) - מימוש נאמן במנוע שלנו.

הכללים כמו בקוד המקורי:
- FVG שורי בנר i-1: low[i-1] > high[i-3] ונר האמצע (i-2) ירוק. דובי: הפוך.
- בנר i נכנסים בסגירה. סטופ: השפל (שורט: השיא) של נר i-2. יעד: RR כפול מרחק הסטופ.
- הערה: בקוד המשתנה fvg_zone מחושב ולא בשימוש, כך שאין "חזרה לבדוק את ה-FVG" -
  הכניסה מיידית אחרי הפער. לכן נבדקת גם גרסה B עם לימיט באמצע ה-FVG (כמו שהתיאור בקוד מתכוון).
- בגרסת הלימיט היעד נבדק רק מהנר שאחרי המילוי (השיא של נר המילוי אולי היה לפני המילוי).
- לקוד אין יציאה בזמן ואין הגבלת עסקאות. כאן: סטופ נבדק לפני יעד, ויציאה בסגירה אחרי MAX_HOLD נרות.
"""
import numpy as np
import pandas as pd

from research.pullback import _stats

MAX_HOLD = 200
LIMIT_BARS = 12
MIN_RISK = 0.1  # סטופ קטן מ-10 סנט = לא עסקה אמיתית


def _exit(h, l, c, j0, d, entry, sl, tp, cost):
    """j0 = הנר הראשון שבו בודקים סטופ/יעד. מחזיר (R נטו, נר היציאה)."""
    end = min(j0 + MAX_HOLD, len(c))
    hh, ll = h[j0:end], l[j0:end]
    stop = (ll <= sl) if d == 1 else (hh >= sl)
    targ = (hh >= tp) if d == 1 else (ll <= tp)
    big = end - j0 + 1
    si = int(stop.argmax()) if stop.any() else big
    ti = int(targ.argmax()) if targ.any() else big
    risk = abs(entry - sl)
    if si <= ti and si < big:
        px, k = sl, si
    elif ti < big:
        px, k = tp, ti
    else:
        k = end - j0 - 1
        px = c[end - 1]
    return ((px - entry) * d - cost) / risk, j0 + k


def run(df: pd.DataFrame, cost: float, rr: float, mode: str) -> pd.DataFrame:
    """mode: 'all' = כל איתות (כמו בקוד), 'one' = עסקה אחת בכל פעם, 'retest' = לימיט באמצע ה-FVG."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = df.index
    n = len(df)
    trades, busy_until = [], -1
    for i in range(3, n - 1):
        f = i - 1  # נר 3 של ה-FVG
        bull = l[f] > h[f - 2] and c[f - 1] > o[f - 1]
        bear = (not bull) and h[f] < l[f - 2] and c[f - 1] < o[f - 1]
        if not (bull or bear):
            continue
        d = 1 if bull else -1
        sl = l[f - 1] if d == 1 else h[f - 1]
        if mode == "retest":
            mid = (l[f] + h[f - 2]) / 2 if d == 1 else (h[f] + l[f - 2]) / 2
            if busy_until >= i:
                continue
            fill = None
            for j in range(i, min(i + LIMIT_BARS, n)):
                if (l[j] <= mid) if d == 1 else (h[j] >= mid):
                    fill = j
                    break
            if fill is None or (mid - sl) * d <= 0:
                continue
            entry = mid
            if abs(entry - sl) < MIN_RISK:
                continue
            tp = entry + d * rr * abs(entry - sl)
            if (l[fill] <= sl) if d == 1 else (h[fill] >= sl):  # סטופ בנר המילוי = הפסד. יעד רק מהנר הבא
                r, k = (-abs(entry - sl) - cost) / abs(entry - sl), fill
            else:
                r, k = _exit(h, l, c, fill + 1, d, entry, sl, tp, cost)
            trades.append({"t": t[fill], "dir": d, "r": r})
            busy_until = k
            continue
        entry = c[i]
        if (entry - sl) * d < MIN_RISK:
            continue
        if mode == "one" and busy_until >= i:
            continue
        tp = entry + d * rr * abs(entry - sl)
        r, k = _exit(h, l, c, i + 1, d, entry, sl, tp, cost)
        trades.append({"t": t[i], "dir": d, "r": r})
        busy_until = k
    return pd.DataFrame(trades)


def report(m1: pd.DataFrame, cost: float, shuffle) -> str:
    from app.data import resample
    days = m1.index.normalize().nunique()
    null_m1 = shuffle(m1, 1)
    modes = (("all", "כמו בקוד (כל איתות)"), ("one", "עסקה אחת בכל פעם"), ("retest", "לימיט באמצע ה-FVG"))
    lines = [f"### 🧪 GoldSmartMoneyStrategy (קוד ה-FVG ששלחת) - שנתיים XAU/USD, עלות {cost}$", "",
             "| טווח | יחס | גרסה | עסקאות | ליום | הצלחה | R נטו | ממוצע | PF | ירידה מקס' | t | 4 תקופות (R) | ביקורת: R · t |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for tf, rule in (("1H", "1h"), ("15M", "15min"), ("5M", "5min")):
        df, nf = resample(m1, rule), resample(null_m1, rule)
        for rr in (2.0, 3.0):
            for mode, label in modes:
                s = _stats(run(df, cost, rr, mode), days)
                z = _stats(run(nf, cost, rr, mode), days)
                if not s["n"]:
                    lines.append(f"| {tf} | 1:{rr:.0f} | {label} | 0 |" + " |" * 9)
                    continue
                lines.append(f"| {tf} | 1:{rr:.0f} | {label} | {s['n']} | {s['per_day']:.1f} | {s['win']:.0f}% | "
                             f"{s['sum']:+.1f} | {s['avg']:+.3f} | {s['pf']:.2f} | {s['dd']:.1f} | {s['t']:+.1f} | "
                             + " / ".join(f"{x:+.0f}" for x in s["folds"])
                             + f" | {z.get('sum', 0):+.1f} · {z.get('t', 0):+.1f} |")
    lines += ["", "**בדיקת עומק ל-1H יחס 1:3 (המועמד הכי טוב):**", "",
              "| גרסה | לונג R (n) | שורט R (n) | 4 חודשים אחרונים R (n) | עלות 0.2$ / 0.5$ / 0.7$ | סגירה בזמן (%) |",
              "|---|---|---|---|---|---|"]
    df = resample(m1, "1h")
    last = df.index[-1] - pd.Timedelta(days=122)
    for mode, label in modes:
        tr = run(df, cost, 3.0, mode)
        lg, sh, rc = tr[tr.dir == 1], tr[tr.dir == -1], tr[tr.t >= last]
        cs = " / ".join(f"{run(df, c, 3.0, mode)['r'].sum():+.0f}" for c in (0.2, 0.5, 0.7))
        timed = 100 * ((tr.r > -1.0) & (tr.r < 2.5)).mean()
        lines.append(f"| {label} | {lg.r.sum():+.1f} ({len(lg)}) | {sh.r.sum():+.1f} ({len(sh)}) | "
                     f"{rc.r.sum():+.1f} ({len(rc)}) | {cs} | {timed:.0f}% |")
    bh = (df.close.iloc[-1] - df.close.iloc[0]) / df.close.iloc[0] * 100
    lines.append(f"\nלהשוואה: הזהב עצמו זז {bh:+.0f}% בתקופה.")
    return "\n".join(lines)
