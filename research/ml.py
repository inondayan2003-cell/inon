"""מודל למידת מכונה שסורק כל נר 5M ומחליט: לונג / שורט / לא להיכנס.

- מאפיינים: רק מידע שידוע בסגירת הנר (מגמה בכל טווח, מרחק מרמות נזילות, שעה, תנודתיות, מומנטום).
- תווית: מה הייתה התוצאה (R נטו) של לונג ושל שורט עם סטופ/יעד/זמן קבועים.
- הליכה קדימה: לכל חודש, אימון רק על מה שהיה לפניו (עם רווח ביטחון), חיזוי על החודש עצמו.
- מסחר: נכנסים רק כשהתחזית עוברת סף, ועסקה אחת בכל פעם.
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

SL_ATR, RR, HOLD = 1.5, 1.5, 24


def labels(tl: pd.DataFrame, cost: float):
    """R נטו ומספר הנרות עד היציאה, ללונג ולשורט, לכל נר."""
    n = len(tl)
    hi, lo, cl = (tl[c].to_numpy() for c in ("high", "low", "close"))
    atr = tl["atr_15m"].to_numpy()
    idx = np.arange(n - HOLD)
    w = np.arange(1, HOLD + 1)
    H, L, C = hi[idx[:, None] + w], lo[idx[:, None] + w], cl[idx[:, None] + w]
    out = {}
    for d in (1, -1):
        dist = SL_ATR * atr[idx]
        e = cl[idx] * d
        fav, adv = (H, L) if d == 1 else (-L, -H)
        stop = adv <= (e - dist)[:, None]
        tp = fav >= (e + RR * dist)[:, None]
        big = HOLD + 1
        s_i = np.where(stop.any(1), stop.argmax(1), big)
        t_i = np.where(tp.any(1), tp.argmax(1), big)
        timed = (C[:, -1] - cl[idx]) * d / dist
        r = np.where(s_i <= t_i, np.where(s_i < big, -1.0, timed), RR) - cost / dist
        exit_off = np.minimum(np.minimum(s_i, t_i), HOLD - 1) + 1
        out[d] = (np.r_[r, np.full(HOLD, np.nan)], np.r_[exit_off, np.full(HOLD, HOLD)])
    return out


def features(tl: pd.DataFrame) -> pd.DataFrame:
    c, a = tl["close"], tl["atr_15m"]
    f = pd.DataFrame(index=tl.index)
    for k in (1, 3, 6, 12, 24, 48, 96):
        f[f"ret{k}"] = (c - c.shift(k)) / a
    for col in ("score_5m", "score_15m", "score_1h", "score_4h", "composite", "adx_15m"):
        f[col] = tl[col]
    f["dist_ema21_15m"] = (c - tl["ema21_15m"]) / a
    for col in ("pdh", "pdl", "asia_high", "asia_low", "lon_high", "lon_low", "pwh", "pwl",
                "orbny_high", "orbny_low", "swing_high", "swing_low"):
        if col in tl:
            f[f"d_{col}"] = ((c - tl[col]) / a).clip(-20, 20)
    f["atr_ratio"] = tl["atr_5m"] / a
    f["vol_regime"] = a / a.rolling(288 * 5, min_periods=288).mean()
    f["body"] = (tl["close"] - tl["open"]) / tl["atr_5m"]
    f["wick_up"] = (tl["high"] - np.maximum(tl["open"], tl["close"])) / tl["atr_5m"]
    f["wick_dn"] = (np.minimum(tl["open"], tl["close"]) - tl["low"]) / tl["atr_5m"]
    day_hi = tl.groupby("session")["high"].cummax()
    day_lo = tl.groupby("session")["low"].cummin()
    f["day_pos"] = (c - day_lo) / (day_hi - day_lo).replace(0, np.nan)
    f["day_range"] = (day_hi - day_lo) / a
    m = tl["ny_min"]
    f["tod_sin"], f["tod_cos"] = np.sin(2 * np.pi * m / 1440), np.cos(2 * np.pi * m / 1440)
    f["dow"] = tl["t"].dt.tz_convert("America/New_York").dt.dayofweek
    f["kz"] = tl["kz"]
    return f.replace([np.inf, -np.inf], np.nan)


def walk_forward(tl: pd.DataFrame, cost: float, min_train_months: int = 6, step: int = 3):
    """מחזיר תחזיות OOS (לונג/שורט) לכל נר, ואת התוויות."""
    tl = tl.reset_index(drop=True)
    X = features(tl)
    lab = labels(tl, cost)
    yl, ys = lab[1][0], lab[-1][0]
    month = tl["t"].dt.tz_convert(None).dt.to_period("M")
    months = sorted(month.unique())
    pred_l = np.full(len(tl), np.nan)
    pred_s = np.full(len(tl), np.nan)
    params = dict(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=200,
                  l2_regularization=1.0, random_state=0)
    for mo in months[min_train_months:]:
        test = (month == mo).to_numpy()
        first = np.flatnonzero(test)[0]
        train = np.zeros(len(tl), bool)
        train[: max(first - HOLD, 0)] = True  # רווח ביטחון: התווית של אימון לא "מציצה" לחודש הבדיקה
        sub = np.arange(len(tl)) % step == 0   # מדלגים כדי להקטין חפיפה בין תוויות סמוכות
        for y, pred in ((yl, pred_l), (ys, pred_s)):
            ok = train & sub & ~np.isnan(y)
            model = HistGradientBoostingRegressor(**params).fit(X[ok], y[ok])
            pred[test] = model.predict(X[test])
    return pred_l, pred_s, lab


def trade(tl: pd.DataFrame, pred_l, pred_s, lab, thr: float, hours: tuple | None = None):
    """עסקה אחת בכל פעם: נכנסים כשהתחזית הטובה מבין לונג/שורט מעל הסף."""
    tl = tl.reset_index(drop=True)
    (rl, el), (rs, es) = lab[1], lab[-1]
    m = tl["ny_min"].to_numpy()
    res, times, dirs = [], [], []
    i, n = 0, len(tl)
    while i < n:
        pl, ps = pred_l[i], pred_s[i]
        if np.isnan(pl) or (hours and not (hours[0] <= m[i] < hours[1])):
            i += 1
            continue
        best, d = (pl, 1) if pl >= ps else (ps, -1)
        r = rl[i] if d == 1 else rs[i]
        if best > thr and not np.isnan(r):
            res.append(r)
            times.append(tl["t"].iloc[i])
            dirs.append(d)
            i += int(el[i] if d == 1 else es[i])
        else:
            i += 1
    return np.array(res), pd.DatetimeIndex(times), np.array(dirs)


def report(tl: pd.DataFrame, cost: float, title: str) -> tuple[str, list]:
    tl = tl.reset_index(drop=True)
    pl, ps, lab = walk_forward(tl, cost)
    days = tl.loc[~np.isnan(pl), "session"].nunique()
    lines = [f"### {title}", "",
             "| סף | עסקאות | ליום | הצלחה | ממוצע R | R נטו | PF | t | לונג/שורט | 4 תקופות (R) |",
             "|" + "---|" * 10]
    rows = []
    for thr in (0.0, 0.05, 0.1, 0.15, 0.2, 0.3):
        r, ts, ds = trade(tl, pl, ps, lab, thr)
        if len(r) < 30:
            lines.append(f"| {thr} | {len(r)} | | | | | | | | |")
            continue
        q = np.quantile(ts.asi8, [0, .25, .5, .75, 1])
        folds = [r[(ts.asi8 >= q[k]) & (ts.asi8 <= q[k + 1])].sum() for k in range(4)]
        win, loss = r[r > 0].sum(), -r[r < 0].sum()
        t = r.mean() / r.std(ddof=1) * np.sqrt(len(r))
        rows.append((thr, len(r), r.mean(), t, sum(f > 0 for f in folds)))
        lines.append(f"| {thr} | {len(r)} | {len(r) / max(days, 1):.1f} | {100 * (r > 0).mean():.0f}% | {r.mean():+.3f} | "
                     f"{r.sum():+.1f} | {win / loss:.2f} | {t:+.1f} | {(ds == 1).sum()}/{(ds == -1).sum()} | "
                     + " / ".join(f"{x:+.1f}" for x in folds) + " |")
    return "\n".join(lines), rows
