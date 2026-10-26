"""לולאת חיפוש - סבב 2: משפחות חדשות על אותו מנוע הוגן.

משפחות:
- hour:  כיוון קבוע בשעה מסוימת ביום (הטיה עונתית תוך-יומית של הזהב).
- rsi2:  היפוך מקיצון RSI(2), עם/בלי/נגד מגמת EMA200.
- mom:   תנועה חדה של L נרות (מעל z ATR) - המשך או היפוך.
- donch: פריצת שיא/שפל של N נרות - המשך או היפוך (false breakout).
כל עסקה: כניסה בסגירת נר האות, סטופ k*ATR, יעד rr*סטופ, יציאה בזמן אחרי hold נרות. עסקה אחת בכל פעם.
אותם כללי שיפוט כמו loop.py: כספת נעולה, ביקורת ערבוב-בתוך-היום, לונג וגם שורט רווחיים.
"""
import itertools

import numpy as np
import pandas as pd

from app.indicators import atr as wilder_atr
from research.loop import _s

MIN_RISK = 0.1


def simulate(df: pd.DataFrame, sig: np.ndarray, dist: np.ndarray, rr: float, hold: int, cost: float) -> pd.DataFrame:
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    t = df.index
    n = len(df)
    idx = np.flatnonzero(sig)
    out_t, out_d, out_r = [], [], []
    free = 0
    for i in idx:
        if i < free or i + 1 >= n:
            continue
        d = int(sig[i])
        risk = dist[i]
        if not risk >= MIN_RISK:
            continue
        e = c[i]
        sl, tp = e - d * risk, e + d * rr * risk
        end = min(i + 1 + hold, n)
        hh, ll = h[i + 1:end], l[i + 1:end]
        st = (ll <= sl) if d == 1 else (hh >= sl)
        tg = (hh >= tp) if d == 1 else (ll <= tp)
        big = len(hh) + 1
        si = int(st.argmax()) if st.any() else big
        ti = int(tg.argmax()) if tg.any() else big
        if si <= ti and si < big:
            r, k = -1.0, i + 1 + si
        elif ti < big:
            r, k = rr, i + 1 + ti
        else:
            k = end - 1
            r = (c[k] - e) * d / risk
        out_t.append(t[i])
        out_d.append(d)
        out_r.append(r - cost / risk)
        free = k + 1
    return pd.DataFrame({"t": out_t, "dir": out_d, "r": out_r})


def _rsi(c: pd.Series, n: int) -> np.ndarray:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


def signals(df: pd.DataFrame, fam: str, p: dict) -> np.ndarray:
    c = df["close"]
    a = wilder_atr(df, 14).to_numpy()
    cv = c.to_numpy()
    sig = np.zeros(len(df), dtype=int)
    if fam == "hour":
        nxt = (df.index + pd.Timedelta(minutes=p["tf_min"])).hour
        sig[nxt == p["H"]] = p["d"]
        return sig
    if fam == "rsi2":
        r = _rsi(c, 2)
        ema = c.ewm(span=200, adjust=False).mean().to_numpy()
        lo, hi = r < p["x"], r > 100 - p["x"]
        up, dn = cv > ema, cv < ema
        if p["filt"] == "with":
            lo, hi = lo & up, hi & dn
        elif p["filt"] == "against":
            lo, hi = lo & dn, hi & up
        sig[lo] = 1
        sig[hi] = -1
        return sig
    if fam == "mom":
        mv = (cv - np.roll(cv, p["L"])) / a
        mv[: p["L"]] = 0
        s = np.where(mv > p["z"], 1, np.where(mv < -p["z"], -1, 0))
        return s * p["mode"]
    if fam == "donch":
        hi = df["high"].rolling(p["N"]).max().shift(1).to_numpy()
        lo = df["low"].rolling(p["N"]).min().shift(1).to_numpy()
        s = np.where(cv > hi, 1, np.where(cv < lo, -1, 0))
        return s * p["mode"]
    raise ValueError(fam)


TFS = {"15M": ("15min", 15), "1H": ("1h", 60)}
EXIT = {"k": [1.0, 1.5], "rr": [2.0, 3.0], "hold_h": [4, 12]}
FAMS = {
    "hour": {"tf": ["1H"], "H": list(range(24)), "d": [1, -1]},
    "rsi2": {"tf": ["15M", "1H"], "x": [5, 10], "filt": ["none", "with", "against"]},
    "mom": {"tf": ["15M", "1H"], "L": [3, 6, 12], "z": [1.5, 2.5], "mode": [1, -1]},
    "donch": {"tf": ["15M", "1H"], "N": [20, 50], "mode": [1, -1]},
}


def configs():
    for fam, grid in FAMS.items():
        keys = list(grid) + list(EXIT)
        for combo in itertools.product(*(grid[k] for k in grid), *(EXIT[k] for k in EXIT)):
            yield fam, dict(zip(keys, combo))


def report(m1: pd.DataFrame, cost: float, holdout_months: int = 4, nulls: int = 3, top: int = 20) -> str:
    from app.data import resample
    from research.null import shuffle_within_day
    vault = m1.index[-1] - pd.DateOffset(months=holdout_months)
    days_is = m1.index[m1.index < vault].normalize().nunique()
    days_v = m1.index[m1.index >= vault].normalize().nunique()
    datasets = [m1] + [shuffle_within_day(m1, s) for s in range(1, nulls + 1)]
    frames = {tf: [resample(d, rule) for d in datasets] for tf, (rule, _) in TFS.items()}
    atrs = {tf: [wilder_atr(df, 14).to_numpy() for df in fr] for tf, fr in frames.items()}
    rows = []
    for fam, p in configs():
        tf = p["tf"]
        mins = TFS[tf][1]
        hold = max(int(p["hold_h"] * 60 / mins), 1)
        res = []
        for df, a in zip(frames[tf], atrs[tf]):
            sig = signals(df, fam, {**p, "tf_min": mins})
            res.append(simulate(df, sig, p["k"] * a, p["rr"], hold, cost))
        is_ = res[0][res[0].t < vault]
        s = _s(is_)
        if s["n"] < 150:
            continue
        null_is = [_s(x[x.t < vault])["sum"] for x in res[1:]]
        lo, sh = is_[is_.dir == 1]["r"].sum(), is_[is_.dir == -1]["r"].sum()
        sd = is_["r"].std(ddof=1)
        excess = s["sum"] - float(np.mean(null_is))
        rows.append({"fam": fam, "p": p, "n": s["n"], "per_day": s["n"] / days_is, "wr": s["win"], "sum": s["sum"],
                     "t": s["t"], "null": float(np.mean(null_is)), "null_max": float(np.max(null_is)),
                     "z": excess / (sd * np.sqrt(s["n"])) if sd > 0 else 0.0, "long": lo, "short": sh,
                     "both": (lo > 0 and sh > 0) or fam == "hour", "_res": res})
    ok = lambda r: r["both"] and r["sum"] > r["null_max"] and r["sum"] > 0
    rows.sort(key=lambda r: (ok(r), r["z"]), reverse=True)
    lines = [f"### 🔁 סבב 2: hour / rsi2 / mom / donch · {len(rows)} תצורות · כספת {holdout_months} ח' · עלות {cost}$", "",
             f"עברו את כל המסננים: {sum(ok(r) for r in rows)}", "",
             "| # | משפחה | פרמטרים | IS: עסקאות/יום | הצלחה | R | t | ביקורת R | z | לונג/שורט | **כספת: n · R · t** | כספת ביקורת R |",
             "|" + "---|" * 12]
    for k, r in enumerate(rows[:top], 1):
        v = r["_res"][0]
        sv = _s(v[v.t >= vault])
        vn = np.mean([_s(x[x.t >= vault])["sum"] for x in r["_res"][1:]])
        ps = " ".join(f"{a}={b}" for a, b in r["p"].items())
        lines.append(f"| {k} | {r['fam']} | {ps} | {r['n']} / {r['per_day']:.1f} | {r['wr']:.0f}% | {r['sum']:+.0f} | "
                     f"{r['t']:+.1f} | {r['null']:+.0f} | {r['z']:+.2f} | {r['long']:+.0f}/{r['short']:+.0f} | "
                     f"**{sv['n']} · {sv['sum']:+.1f} · {sv['t']:+.1f}** ({sv['n'] / max(days_v, 1):.1f}/יום) | {vn:+.1f} |")
    for fam in FAMS:
        zs = np.array([r["z"] for r in rows if r["fam"] == fam])
        if len(zs):
            lines.append(f"\n{fam}: {len(zs)} תצורות · z חציון {np.median(zs):+.2f} · 90% {np.quantile(zs, .9):+.2f} · מקס {zs.max():+.2f}")
    return "\n".join(lines)
