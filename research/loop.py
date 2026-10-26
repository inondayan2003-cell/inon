"""לולאת חיפוש שיטה: משפחת FVG-retest (הכיוון היחיד שהראה סימן בבדיקה של קוד ה-FVG).

כללים נגד "רווח מדומה":
- כספת: 4 החודשים האחרונים לא משתתפים בבחירה בכלל. מדווחים עליהם רק בסוף, לטופ בלבד.
- ביקורת: כל תצורה רצה גם על 3 גרסאות של הנתונים שעורבבו בתוך כל יום (shuffle_within_day).
  המגמה הרב-יומית נשמרת, הדפוסים התוך-יומיים נמחקים. ציון = רווח מעבר לממוצע הביקורת.
- דרישה: גם הלונג וגם השורט רווחיים ב-IS (אחרת זו רכיבה על מגמת הזהב).
- סטופ נבדק לפני יעד. בנר המילוי נבדק רק סטופ. עלות לכל עסקה.
"""
import itertools

import numpy as np
import pandas as pd

from app.indicators import atr as wilder_atr

MIN_RISK = 0.1
HOLD_HOURS = 48


def run(df: pd.DataFrame, cost: float, entry_frac=0.5, stop="mid", rr=3.0, win=12, filt="none", min_gap=0.0,
        tf_min=60) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = wilder_atr(df, 14).to_numpy()
    ema = df["close"].ewm(span=50, adjust=False).mean().to_numpy()
    t = df.index
    n = len(df)
    hold = max(int(HOLD_HOURS * 60 / tf_min), 4)
    out_t, out_d, out_r = [], [], []
    i = 3
    while i < n - 1:
        f = i - 1
        if np.isnan(a[f]):
            i += 1
            continue
        d = 0
        if l[f] > h[f - 2] and c[f - 1] > o[f - 1]:
            d, g = 1, l[f] - h[f - 2]
        elif h[f] < l[f - 2] and c[f - 1] < o[f - 1]:
            d, g = -1, l[f - 2] - h[f]
        if d == 0 or g < min_gap * a[f] or (filt == "ema" and (c[f] - ema[f]) * d <= 0) \
                or (filt == "anti" and (c[f] - ema[f]) * d >= 0):
            i += 1
            continue
        edge = l[f] if d == 1 else h[f]
        entry = edge - d * entry_frac * g
        if stop == "mid":
            sl = l[f - 1] if d == 1 else h[f - 1]
        elif stop == "c1":
            sl = l[f - 2] if d == 1 else h[f - 2]
        else:
            sl = entry - d * a[f]
        risk = (entry - sl) * d
        if risk < MIN_RISK:
            i += 1
            continue
        tp = entry + d * rr * risk
        fill = -1
        for j in range(i, min(i + win, n)):
            if (h[j] >= tp) if d == 1 else (l[j] <= tp):  # היעד הושג לפני מילוי - פספסנו
                break
            if (l[j] <= entry) if d == 1 else (h[j] >= entry):
                fill = j
                break
        if fill < 0:
            i += 1
            continue
        if (l[fill] <= sl) if d == 1 else (h[fill] >= sl):
            r, k = -1.0, fill
        else:
            end = min(fill + 1 + hold, n)
            hh, ll = h[fill + 1:end], l[fill + 1:end]
            if len(hh) == 0:
                break
            st = (ll <= sl) if d == 1 else (hh >= sl)
            tg = (hh >= tp) if d == 1 else (ll <= tp)
            big = len(hh) + 1
            si = int(st.argmax()) if st.any() else big
            ti = int(tg.argmax()) if tg.any() else big
            if si <= ti and si < big:
                r, k = -1.0, fill + 1 + si
            elif ti < big:
                r, k = rr, fill + 1 + ti
            else:
                k = end - 1
                r = (c[k] - entry) * d / risk
        out_t.append(t[fill])
        out_d.append(d)
        out_r.append(r - cost / risk)
        i = k + 1
    return pd.DataFrame({"t": out_t, "dir": out_d, "r": out_r})


def _s(tr: pd.DataFrame) -> dict:
    if len(tr) < 2:
        return {"n": len(tr), "sum": float(tr["r"].sum()) if len(tr) else 0.0, "t": 0.0, "win": 0.0}
    r = tr["r"].to_numpy()
    return {"n": len(r), "sum": float(r.sum()), "t": float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))),
            "win": float(100 * (r > 0).mean()), "pf": float(r[r > 0].sum() / max(-r[r < 0].sum(), 1e-9))}


GRID = {
    "tf": [("30M", "30min", 30), ("1H", "1h", 60), ("2H", "2h", 120)],
    "entry_frac": [0.0, 0.5, 1.0],
    "stop": ["mid", "c1", "atr"],
    "rr": [2.0, 3.0],
    "win": [6, 12, 24],
    "filt": ["none", "ema", "anti"],
    "min_gap": [0.0, 0.3],
}


def report(m1: pd.DataFrame, cost: float, holdout_months: int = 4, nulls: int = 3, top: int = 15) -> str:
    from app.data import resample
    from research.null import shuffle_within_day
    vault = m1.index[-1] - pd.DateOffset(months=holdout_months)
    days_is = m1.index[m1.index < vault].normalize().nunique()
    days_v = m1.index[m1.index >= vault].normalize().nunique()
    datasets = [m1] + [shuffle_within_day(m1, s) for s in range(1, nulls + 1)]
    frames = {tf: [resample(d, rule) for d in datasets] for tf, rule, _ in GRID["tf"]}
    rows = []
    keys = [k for k in GRID if k != "tf"]
    for (tf, rule, mins), combo in itertools.product(GRID["tf"], itertools.product(*(GRID[k] for k in keys))):
        p = dict(zip(keys, combo))
        res = [run(df, cost, tf_min=mins, **p) for df in frames[tf]]
        real = res[0]
        is_ = real[real.t < vault]
        s = _s(is_)
        if s["n"] < 100:
            continue
        null_is = [_s(x[x.t < vault])["sum"] for x in res[1:]]
        lo, sh = is_[is_.dir == 1]["r"].sum(), is_[is_.dir == -1]["r"].sum()
        sd = is_["r"].std(ddof=1)
        excess = s["sum"] - float(np.mean(null_is))
        z = excess / (sd * np.sqrt(s["n"])) if sd > 0 else 0.0
        rows.append({"tf": tf, **p, "n": s["n"], "per_day": s["n"] / days_is, "wr": s["win"], "sum": s["sum"],
                     "t": s["t"], "null": float(np.mean(null_is)), "null_max": float(np.max(null_is)),
                     "excess": excess, "z": z, "long": lo, "short": sh, "both": lo > 0 and sh > 0,
                     "_res": res})
    rows.sort(key=lambda r: (r["both"] and r["sum"] > r["null_max"], r["z"]), reverse=True)
    lines = [f"### 🔁 לולאת חיפוש FVG-retest · {len(rows)} תצורות · כספת {holdout_months} חודשים אחרונים · "
             f"ביקורת = {nulls} ערבובים בתוך היום · עלות {cost}$", "",
             f"עברו את כל המסננים (לונג וגם שורט רווחיים, ומעל כל הביקורות): "
             f"{sum(r['both'] and r['sum'] > r['null_max'] for r in rows)}", "",
             "| # | טווח | כניסה | סטופ | יחס | חלון | מסנן | פער | IS: עסקאות/יום | הצלחה | R | t | ביקורת R | עודף z | "
             "לונג/שורט | **כספת: n · R · t** | כספת ביקורת R |",
             "|" + "---|" * 17]
    for k, r in enumerate(rows[:top], 1):
        v = r["_res"][0]
        v = v[v.t >= vault]
        sv = _s(v)
        vn = np.mean([_s(x[x.t >= vault])["sum"] for x in r["_res"][1:]])
        lines.append(f"| {k} | {r['tf']} | {r['entry_frac']} | {r['stop']} | 1:{r['rr']:.0f} | {r['win']} | {r['filt']} | "
                     f"{r['min_gap']} | {r['n']} / {r['per_day']:.1f} | {r["wr"]:.0f}% | {r['sum']:+.0f} | {r['t']:+.1f} | "
                     f"{r['null']:+.0f} | {r['z']:+.2f} | {r['long']:+.0f}/{r['short']:+.0f} | "
                     f"**{sv['n']} · {sv['sum']:+.1f} · {sv['t']:+.1f}** ({sv['n'] / max(days_v, 1):.1f}/יום) | {vn:+.1f} |")
    zs = np.array([r["z"] for r in rows])
    lines += ["", f"פיזור z בכל התצורות: חציון {np.median(zs):+.2f}, 90% {np.quantile(zs, .9):+.2f}, מקס {zs.max():+.2f}"]
    return "\n".join(lines)
