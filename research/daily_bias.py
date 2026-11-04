"""כיוון יומי לזהב: האם כלל פשוט על נרות יומיים מנבא את הכיוון של 1-5 הימים הבאים?

יום מסחר = 17:00-17:00 ניו יורק. ההחלטה בסגירת היום, הכניסה במחיר הסגירה, יציאה בסגירה אחרי N ימים
או בסטופ של 1.5 ATR(14) יומי (נבדק על נרות דקה, סטופ לפני הכל). עלות 0.35$ לעסקה.
קבוצת ביקורת: "תמיד לונג". הזהב עלה הרבה ב-2018-2026, אז כלל שקונה הרבה ייראה טוב גם בלי יתרון.
התקופות קבועות מראש: 2018-2021, 2022-2024, 2025-היום.
"""
import numpy as np
import pandas as pd

NY = "America/New_York"
PERIODS = (("2018-2021", "2018-01-01", "2022-01-01"), ("2022-2024", "2022-01-01", "2025-01-01"),
           ("2025-היום", "2025-01-01", "2100-01-01"))


def daily(m1: pd.DataFrame) -> pd.DataFrame:
    ny = m1.index.tz_convert(NY)
    day = (ny + pd.Timedelta(hours=7)).normalize().tz_localize(None)   # 17:00 ניו יורק = תחילת יום חדש
    d = m1.groupby(day).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                            n=("close", "size"), end=("close", lambda x: x.index[-1]))
    d = d[d.n >= 600]   # ימים מלאים בלבד
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(14).mean()
    for n in (20, 50, 100, 200):
        d[f"sma{n}"] = d.close.rolling(n).mean()
    for n in (1, 5, 20):
        d[f"ret{n}"] = d.close - d.close.shift(n)
    up = d.close.diff().clip(lower=0).rolling(14).mean()
    dn = (-d.close.diff()).clip(lower=0).rolling(14).mean()
    d["rsi"] = 100 - 100 / (1 + up / dn)
    return d.dropna()


RULES = {
    "תמיד לונג (ביקורת)": lambda d: pd.Series(1, d.index),
    "מעל/מתחת ממוצע 20": lambda d: np.sign(d.close - d.sma20),
    "מעל/מתחת ממוצע 50": lambda d: np.sign(d.close - d.sma50),
    "מעל/מתחת ממוצע 100": lambda d: np.sign(d.close - d.sma100),
    "מעל/מתחת ממוצע 200": lambda d: np.sign(d.close - d.sma200),
    "ממוצע 20 מול 50": lambda d: np.sign(d.sma20 - d.sma50),
    "מומנטום 20 יום": lambda d: np.sign(d.ret20),
    "המשך של אתמול": lambda d: np.sign(d.ret1),
    "היפוך של אתמול": lambda d: -np.sign(d.ret1),
    "היפוך של 5 ימים": lambda d: -np.sign(d.ret5),
    "RSI קיצון (היפוך)": lambda d: pd.Series(np.where(d.rsi < 30, 1, np.where(d.rsi > 70, -1, 0)), d.index),
    "מגמה + תיקון": lambda d: pd.Series(np.where((d.close > d.sma50) & (d.ret5 < 0), 1,
                                                 np.where((d.close < d.sma50) & (d.ret5 > 0), -1, 0)), d.index),
}


def trades(m1: pd.DataFrame, d: pd.DataFrame, sig: pd.Series, hold: int, stop_atr: float, cost: float) -> pd.DataFrame:
    c, lo, hi = m1.close.to_numpy(), m1.low.to_numpy(), m1.high.to_numpy()
    idx = m1.index
    days = d.index
    out = []
    for i in range(len(days) - hold):
        s = int(sig.iloc[i])
        if not s:
            continue
        t0, t1 = d.end.iloc[i], d.end.iloc[i + hold]
        a, b = idx.searchsorted(t0, side="right"), idx.searchsorted(t1, side="right")
        if b - a < 30:
            continue
        entry, risk = d.close.iloc[i], stop_atr * d.atr.iloc[i]
        sl = entry - s * risk
        hit = np.flatnonzero(lo[a:b] <= sl) if s == 1 else np.flatnonzero(hi[a:b] >= sl)
        exit_px = sl if len(hit) else c[b - 1]
        out.append({"t": days[i], "d": s, "r": ((exit_px - entry) * s - cost) / risk,
                    "up": d.close.iloc[i + 1] > entry, "stopped": bool(len(hit))})
    return pd.DataFrame(out)


def _t(r: pd.Series) -> float:
    return float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else 0.0


def report(m1: pd.DataFrame, cost: float = 0.35) -> str:
    d = daily(m1)
    lines = [f"### 🧭 כיוון יומי לזהב · {d.index[0]:%Y-%m} עד {d.index[-1]:%Y-%m} · {len(d)} ימים · עלות {cost}$", "",
             "R = סיכון של 1.5 ATR יומי. 'צדק מחר' = הכיוון של היום הבא בלבד.", ""]
    for hold in (1, 3, 5):
        lines += [f"#### החזקה {hold} ימים", "",
                  "| כלל | עסק' | לונג/שורט | צדק מחר | " + " | ".join(f"{p[0]} R · t" for p in PERIODS) +
                  " | סה\"כ R · t | שורטים R |", "|" + "---|" * (6 + len(PERIODS))]
        for name, f in RULES.items():
            sig = f(d).fillna(0).astype(int)
            tr = trades(m1, d, sig, hold, 1.5, cost)
            if len(tr) < 20:
                continue
            hit = ((tr.d == 1) == tr.up).mean()
            cells = []
            for _, a, b in PERIODS:
                x = tr[(tr.t >= a) & (tr.t < b)].r
                cells.append(f"{x.sum():+.0f} · {_t(x):+.1f}" if len(x) > 2 else "-")
            lines.append(f"| {name} | {len(tr)} | {(tr.d == 1).sum()}/{(tr.d == -1).sum()} | {100 * hit:.0f}% | "
                         + " | ".join(cells) + f" | **{tr.r.sum():+.0f}** · {_t(tr.r):+.1f} | "
                         f"{tr[tr.d == -1].r.sum():+.0f} |")
        lines.append("")
    lines += ["כלל נחשב שימושי רק אם הוא רווחי בכל 3 התקופות, וגם השורטים שלו רווחיים "
              "(אחרת הוא רק 'קונה זהב בשוק עולה', ו'תמיד לונג' עושה את זה בלי כלל)."]
    return "\n".join(lines)
