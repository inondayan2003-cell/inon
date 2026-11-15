"""קריאה יומית: ב-10:00 שעון ישראל לונג או שורט, יציאה ב-22:00. האם אפשר לנבא את הכיוון, ובאיזה ביטחון (1-10)?

מאפיינים שידועים ב-10:00 (ביחידות של ATR יומי): מגמה מול ממוצע 200/20, השינוי של אתמול ושל 5 ימים,
התנועה מהסגירה היומית עד 10:00, התנועה בשעה האחרונה, המיקום בטווח של הלילה, RSI יומי, והמהלך 10:00-22:00 של אתמול.
מודל: רגרסיה לוגיסטית פשוטה. מאמנים רק על 2018-2022, ובודקים על 2023-2024 ו-2025-היום בלי לגעת.
דירוג 1-10 = עשירון של המרחק מ-50% (לפי תקופת האימון). אם הדירוג שווה משהו, דירוג גבוה צריך לצדוק יותר במבחן.
"""
import numpy as np
import pandas as pd

from research.daily_bias import daily

IL = "Asia/Jerusalem"
FEATS = ["trend200", "trend20", "ret1", "ret5", "overnight", "hour", "pos", "rsi", "prev_win"]
NAMES = {"trend200": "מרחק מממוצע 200", "trend20": "מרחק מממוצע 20", "ret1": "השינוי של אתמול", "ret5": "השינוי ב-5 ימים",
         "overnight": "מהסגירה עד 10:00", "hour": "השעה האחרונה (09-10)", "pos": "מיקום בטווח הלילה", "rsi": "RSI יומי",
         "prev_win": "10:00-22:00 של אתמול"}
SPLITS = (("אימון 2018-2022", "2018-01-01", "2023-01-01"), ("מבחן 2023-2024", "2023-01-01", "2025-01-01"),
          ("מבחן 2025-היום", "2025-01-01", "2100-01-01"))


def dataset(m1: pd.DataFrame, t_in: int = 10, t_out: int = 22) -> pd.DataFrame:
    d = daily(m1)
    d["sma20_"] = d.close.rolling(20).mean()
    c = m1.close
    il = m1.index.tz_convert(IL)
    days = pd.Series(il.normalize().unique())
    rows = []
    for day in days:
        if day.weekday() >= 5:
            continue
        a, b = day + pd.Timedelta(hours=t_in), day + pd.Timedelta(hours=t_out)
        ia, ib = c.index.searchsorted(a, side="right") - 1, c.index.searchsorted(b, side="right") - 1
        if ia < 0 or a - c.index[ia] > pd.Timedelta(minutes=10) or b - c.index[ib] > pd.Timedelta(minutes=10):
            continue
        label = (a.tz_convert("America/New_York") + pd.Timedelta(hours=7)).normalize().tz_localize(None)
        past = d[d.index < label]
        if len(past) < 2:
            continue
        p = past.iloc[-1]
        px, out = c.iloc[ia], c.iloc[ib]
        i0 = c.index.searchsorted(p.end, side="right")          # תחילת יום המסחר הנוכחי
        seg = m1.iloc[i0:ia + 1]
        if len(seg) < 60:
            continue
        hi, lo = seg.high.max(), seg.low.min()
        rows.append({"t": a, "px": px, "out": out, "atr": p.atr, "move": out - px,
                     "trend200": (p.close - p.sma200) / p.atr, "trend20": (p.close - p.sma20_) / p.atr,
                     "ret1": p.ret1 / p.atr, "ret5": p.ret5 / p.atr, "overnight": (px - p.close) / p.atr,
                     "hour": (px - c.asof(a - pd.Timedelta(hours=1))) / p.atr,
                     "pos": (px - (hi + lo) / 2) / (hi - lo) if hi > lo else 0.0, "rsi": (p.rsi - 50) / 50})
    df = pd.DataFrame(rows).dropna()
    df["prev_win"] = (df.move / df.atr).shift(1)
    return df.dropna().reset_index(drop=True)


def fit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, steps: int = 3000, lr: float = 0.1) -> np.ndarray:
    """רגרסיה לוגיסטית עם רגולריזציה, בלי ספריות. מחזיר [הטיה, משקלים...]."""
    Xb = np.c_[np.ones(len(X)), X]
    w = np.zeros(Xb.shape[1])
    for _ in range(steps):
        p = 1 / (1 + np.exp(-Xb @ w))
        g = Xb.T @ (p - y) / len(y)
        g[1:] += l2 * w[1:] / len(y)
        w -= lr * g
    return w


def predict(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(np.c_[np.ones(len(X)), X] @ w)))


def model(train: pd.DataFrame) -> dict:
    mu, sd = train[FEATS].mean(), train[FEATS].std().replace(0, 1)
    w = fit(((train[FEATS] - mu) / sd).to_numpy(), (train.move > 0).to_numpy(float))
    conf = np.abs(predict(w, ((train[FEATS] - mu) / sd).to_numpy()) - 0.5)
    return {"mu": mu.to_dict(), "sd": sd.to_dict(), "w": w.tolist(),
            "edges": np.quantile(conf, np.arange(0.1, 1.0, 0.1)).tolist()}


def score(m: dict, df: pd.DataFrame) -> pd.DataFrame:
    X = ((df[FEATS] - pd.Series(m["mu"])) / pd.Series(m["sd"])).to_numpy()
    p = predict(np.array(m["w"]), X)
    out = df.copy()
    out["p"], out["d"] = p, np.where(p >= 0.5, 1, -1)
    out["rating"] = 1 + np.searchsorted(m["edges"], np.abs(p - 0.5))
    return out


def report(m1: pd.DataFrame, cost: float = 0.35) -> str:
    df = dataset(m1)
    cut = lambda x, a, b: x[(x.t >= pd.Timestamp(a, tz=IL)) & (x.t < pd.Timestamp(b, tz=IL))]
    m = model(cut(df, *SPLITS[0][1:]))
    s = score(m, df)
    s["pnl"] = s.d * s.move - cost
    s["hit"] = (s.d * s.move) > 0
    lines = [f"### 🎯 קריאה יומית 10:00→22:00 (שעון ישראל) · {len(df)} ימים · עלות {cost}$", "",
             f"תנועה ממוצעת 10:00→22:00: {df.move.abs().mean():.1f}$ · ימים שעלו: {100 * (df.move > 0).mean():.0f}%", "",
             "| תקופה | ימים | המודל צדק | $ ממוצע ליום | סה\"כ $ | תמיד לונג: צדק · סה\"כ $ | לונג/שורט של המודל |", "|---|---|---|---|---|---|---|"]
    for name, a, b in SPLITS:
        x = cut(s, a, b)
        base = x.move - cost
        lines.append(f"| {name} | {len(x)} | **{100 * x.hit.mean():.1f}%** | {x.pnl.mean():+.2f} | {x.pnl.sum():+.0f} | "
                     f"{100 * (x.move > 0).mean():.1f}% · {base.sum():+.0f} | {(x.d == 1).sum()}/{(x.d == -1).sum()} |")
    test = cut(s, SPLITS[1][1], SPLITS[2][2])
    lines += ["", "#### לפי דירוג (רק שנות המבחן 2023-היום)", "", "| דירוג | ימים | צדק | $ ממוצע ליום | סה\"כ $ |", "|---|---|---|---|---|"]
    for lo, hi in ((1, 3), (4, 6), (7, 8), (9, 10)):
        x = test[(test.rating >= lo) & (test.rating <= hi)]
        if len(x):
            lines.append(f"| {lo}-{hi} | {len(x)} | {100 * x.hit.mean():.1f}% | {x.pnl.mean():+.2f} | {x.pnl.sum():+.0f} |")
    sh, lg = test[test.d == -1], test[test.d == 1]
    lines += ["", f"במבחן: לונגים {len(lg)} · צדק {100 * lg.hit.mean():.1f}% · {lg.pnl.sum():+.0f}$ | "
                  f"שורטים {len(sh)} · צדק {100 * sh.hit.mean():.1f}% · {sh.pnl.sum():+.0f}$" if len(sh) and len(lg) else "",
              "", "#### מה המודל למד (משקל חיובי = דוחף ללונג)", ""]
    for f, w in sorted(zip(FEATS, m["w"][1:]), key=lambda x: -abs(x[1])):
        lines.append(f"- {NAMES[f]}: {w:+.3f}")
    lines += ["", "המודל שווה משהו רק אם בשני המבחנים הוא צדק יותר מ'תמיד לונג' והרוויח יותר, ואם דירוג גבוה צדק יותר מדירוג נמוך."]
    return "\n".join(lines)
