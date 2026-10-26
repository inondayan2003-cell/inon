"""GoldPullbackStrategy (קוד backtrader שהמשתמש שלח) - מימוש נאמן במנוע שלנו.

הכללים כמו בקוד המקורי:
- מגמה שורית: EMA20 > EMA50 והסגירה מעל EMA20 (דובית: הפוך). כל נר כזה "טוען" חלון של 5 נרות.
- נר שאינו במגמה מוריד את החלון ב-1. בתוך החלון: לונג כשהסגירה חוזרת אל/מתחת ל-EMA20 (שורט: הפוך).
- סטופ 2 ATR(14), יעד 1.5x מרחק הסטופ (3 ATR), מחושבים מסגירת נר האות.
- עסקה אחת בכל פעם. פקודת שוק -> ביצוע בפתיחת הנר הבא (כמו ב-backtrader).

תיקון אחד הכרחי: בקוד המקורי הסטופ והיעד מחושבים אבל לא נשלחים לברוקר (self.buy() בלי bracket),
ולכן העסקה הראשונה לעולם לא נסגרת. כאן הם מבוצעים בפועל (כמו buy_bracket). סטופ נבדק לפני יעד.
"""
import numpy as np
import pandas as pd

from app.indicators import atr as wilder_atr


def ema_bt(s: pd.Series, n: int) -> pd.Series:
    """EMA כמו ב-backtrader: מתחיל מ-SMA של n הנרות הראשונים."""
    out = s.ewm(alpha=2 / (n + 1), adjust=False).mean()
    seed = s.rolling(n).mean()
    first = seed.first_valid_index()
    if first is None:
        return out * np.nan
    vals = s.to_numpy(dtype=float)
    res = np.full(len(s), np.nan)
    i0 = s.index.get_loc(first)
    res[i0] = seed.iloc[i0]
    a = 2 / (n + 1)
    for i in range(i0 + 1, len(s)):
        res[i] = a * vals[i] + (1 - a) * res[i - 1]
    return pd.Series(res, index=s.index)


def run(df: pd.DataFrame, cost: float, ema_fast=20, ema_slow=50, atr_period=14, atr_mult=2.0, window=5, rr=1.5):
    ef, es = ema_bt(df["close"], ema_fast).to_numpy(), ema_bt(df["close"], ema_slow).to_numpy()
    a = wilder_atr(df, atr_period).to_numpy()
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    times = df.index
    trades = []
    win_left, trend = 0, 0
    pos = None  # (direction, entry, sl, tp, entry_time)
    pending = None
    for i in range(len(df)):
        if pending is not None:  # פקודת שוק מהנר הקודם מתבצעת בפתיחה
            d, sl, tp = pending
            pos = (d, o[i], sl, tp, times[i])
            pending = None
        if pos is not None:
            d, entry, sl, tp, t0 = pos
            hit_sl = (l[i] <= sl) if d == 1 else (h[i] >= sl)
            hit_tp = (h[i] >= tp) if d == 1 else (l[i] <= tp)
            if hit_sl or hit_tp:
                exit_px = sl if hit_sl else tp
                risk = abs(entry - sl)
                if risk > 0:
                    r = ((exit_px - entry) * d - cost) / risk
                    trades.append({"t": t0, "dir": d, "r": r, "win": not hit_sl})
                pos = None
            else:
                continue  # "if self.position: return" - בזמן עסקה לא מעדכנים כלום
        if pending is not None:
            continue
        if np.isnan(es[i]) or np.isnan(a[i]):
            continue
        bull = ef[i] > es[i] and c[i] > ef[i]
        bear = ef[i] < es[i] and c[i] < ef[i]
        if bull:
            trend, win_left = 1, window
        elif bear:
            trend, win_left = -1, window
        elif win_left > 0:
            win_left -= 1
        if win_left > 0 and i + 1 < len(df):
            if trend == 1 and c[i] <= ef[i]:
                pending = (1, c[i] - a[i] * atr_mult, c[i] + a[i] * atr_mult * rr)
                win_left = 0
            elif trend == -1 and c[i] >= ef[i]:
                pending = (-1, c[i] + a[i] * atr_mult, c[i] - a[i] * atr_mult * rr)
                win_left = 0
    return pd.DataFrame(trades)


def _stats(tr: pd.DataFrame, days: float) -> dict:
    if tr.empty:
        return {"n": 0}
    r = tr["r"].to_numpy()
    eq = r.cumsum()
    q = np.quantile(tr["t"].astype("int64"), [0, .25, .5, .75, 1])
    ti = tr["t"].astype("int64").to_numpy()
    folds = [r[(ti >= q[k]) & (ti <= q[k + 1])].sum() for k in range(4)]
    return {"n": len(r), "per_day": len(r) / days, "win": 100 * (r > 0).mean(), "sum": r.sum(), "avg": r.mean(),
            "pf": r[r > 0].sum() / max(-r[r < 0].sum(), 1e-9),
            "dd": float((np.maximum.accumulate(np.maximum(eq, 0)) - eq).max()),
            "t": r.mean() / r.std(ddof=1) * np.sqrt(len(r)) if len(r) > 1 else 0, "folds": folds,
            "long": (tr["dir"] == 1).sum(), "short": (tr["dir"] == -1).sum()}


def report(m1: pd.DataFrame, cost: float, shuffle) -> str:
    from app.data import resample
    days = m1.index.normalize().nunique()
    lines = ["### 🧪 GoldPullbackStrategy (הקוד ששלחת) - שנתיים של XAU/USD, עלות 0.35$ לעסקה", "",
             "| טווח | עסקאות | ליום | הצלחה | R נטו | ממוצע | PF | ירידה מקס' | t | 4 תקופות (R) | לונג/שורט | ביקורת (מעורבב): R · t |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    null_m1 = shuffle(m1, 1)
    for tf, rule in (("1H (כמו בקוד)", "1h"), ("15M", "15min"), ("5M", "5min")):
        df = resample(m1, rule)
        s = _stats(run(df, cost), days)
        z = _stats(run(resample(null_m1, rule), cost), days)
        if not s["n"]:
            lines.append(f"| {tf} | 0 | | | | | | | | | | |")
            continue
        lines.append(f"| {tf} | {s['n']} | {s['per_day']:.1f} | {s['win']:.0f}% | {s['sum']:+.1f} | {s['avg']:+.3f} | "
                     f"{s['pf']:.2f} | {s['dd']:.1f} | {s['t']:+.1f} | " + " / ".join(f"{x:+.0f}" for x in s["folds"])
                     + f" | {s['long']}/{s['short']} | {z.get('sum', 0):+.1f} · {z.get('t', 0):+.1f} |")
    lines += ["", "**עלות שונה (1H):** " + " · ".join(
        f"{c}$: {_stats(run(resample(m1, '1h'), c), days).get('sum', 0):+.1f}R" for c in (0.0, 0.2, 0.5, 0.7))]
    return "\n".join(lines)
