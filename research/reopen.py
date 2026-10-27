"""סבב 5: "דחיפת הפתיחה" - הזהב נוטה לעלות בשעות הראשונות אחרי הפתיחה היומית (אסיה).

הממצא מסבב 4: התנועה הממוצעת בשעות 18:00-21:00 ניו יורק חיובית בכל אחת מהשנים 2018-2024
(t כולל +5.6/+5.8/+5.2), וגם בשנתיים האחרונות.
כאן: כניסה בלונג בדקה הראשונה אחרי ההפסקה היומית (מזוהה מהנתונים: פער של 30+ דקות, בלי תלות בשעון קיץ),
סטופ k*ATR(1H), יעד rr*סטופ, ויציאה בזמן אחרי H שעות. הכל על נרות דקה (סדר מדויק של סטופ/יעד).
"""
import numpy as np
import pandas as pd

from app.indicators import atr as wilder_atr


def _secs(idx: pd.DatetimeIndex) -> np.ndarray:
    return ((idx - idx[0]) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)


def reopen_points(m1: pd.DataFrame, gap_min: int = 30) -> np.ndarray:
    gaps = np.diff(_secs(m1.index)) / 60
    return np.flatnonzero(gaps >= gap_min) + 1


def run(m1: pd.DataFrame, cost: float, hours: float = 3, k: float | None = 1.0, rr: float | None = 2.0,
        direction: int = 1, skip_weekend: bool = False, min_risk: float = 0.0, offset_h: float = 0.0,
        delay_min: float = 0.0) -> pd.DataFrame:
    o, h, l, c = (m1[x].to_numpy() for x in ("open", "high", "low", "close"))
    t = m1.index
    h1 = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    a1 = wilder_atr(h1, 14)
    atr_at = a1.reindex(t, method="ffill").shift(1).to_numpy()  # ATR ידוע לפני הכניסה
    ns = _secs(t)
    out = []
    pts = reopen_points(m1)
    if offset_h or delay_min:  # בסיס להשוואה / כניסה מאוחרת כמו בבוט (אחרי סגירת נר 5 דקות)
        pts = np.searchsorted(ns, ns[pts] + offset_h * 3600 + delay_min * 60)
        pts = pts[pts < len(ns) - 10]
    for i in pts:
        if skip_weekend and (ns[i] - ns[i - 1]) / 3600 > 24:
            continue
        a = atr_at[i]
        if np.isnan(a) or a <= 0:
            continue
        e = o[i]
        end = np.searchsorted(ns, ns[i] + hours * 3600)
        if end - i < 10:
            continue
        d = direction
        risk = k * a if k else a  # בלי סטופ: R נמדד ביחידות ATR
        if risk < min_risk:
            continue
        sl = e - d * risk if k else None
        tp = e + d * rr * risk if (k and rr) else None
        hh, ll = h[i:end], l[i:end]
        exit_px, hit = c[end - 1], "time"
        if k:
            st = (ll <= sl) if d == 1 else (hh >= sl)
            tg = ((hh >= tp) if d == 1 else (ll <= tp)) if tp is not None else np.zeros(len(hh), bool)
            si = int(st.argmax()) if st.any() else 10**9
            ti = int(tg.argmax()) if tg.any() else 10**9
            if si <= ti and si < 10**9:
                exit_px, hit = sl, "sl"
            elif ti < 10**9:
                exit_px, hit = tp, "tp"
        r = ((exit_px - e) * d - cost) / risk
        out.append({"t": t[i], "dir": d, "r": r, "hit": hit, "risk": risk})
    return pd.DataFrame(out)


def _row(name, tr, years, null_tr=None):
    from research.loop import _s
    s = _s(tr)
    per = [tr[tr.t.dt.year == y]["r"].sum() for y in years]
    pos = sum(x > 0 for x in per)
    hits = tr["hit"].value_counts(normalize=True)
    nul = f"{null_tr['r'].sum():+.0f}" if null_tr is not None and len(null_tr) else ""
    days = tr.t.dt.normalize().nunique()
    return (f"| {name} | {s['n']} | {s['win']:.0f}% | {s['sum']:+.0f} | {tr['r'].mean():+.3f} | {s['t']:+.1f} | "
            + " | ".join(f"{x:+.0f}" for x in per)
            + f" | {pos}/{len(years)} | {100 * hits.get('tp', 0):.0f}/{100 * hits.get('sl', 0):.0f}/{100 * hits.get('time', 0):.0f} | {nul} |")


VARIANTS = [
    ("זמן בלבד 3ש' (R=ATR)", dict(hours=3, k=None, rr=None)),
    ("זמן בלבד 4ש'", dict(hours=4, k=None, rr=None)),
    ("סטופ 1 ATR · יעד 1:2 · עד 3ש'", dict(hours=3, k=1.0, rr=2.0)),
    ("סטופ 1 ATR · יעד 1:3 · עד 4ש'", dict(hours=4, k=1.0, rr=3.0)),
    ("סטופ 0.7 ATR · יעד 1:2 · עד 3ש'", dict(hours=3, k=0.7, rr=2.0)),
    ("סטופ 0.7 ATR · יעד 1:3 · עד 4ש'", dict(hours=4, k=0.7, rr=3.0)),
    ("סטופ 1.5 ATR · יעד 1:2 · עד 4ש'", dict(hours=4, k=1.5, rr=2.0)),
    ("סטופ 0.5 ATR · יעד 1:3 · עד 3ש'", dict(hours=3, k=0.5, rr=3.0)),
    ("ביקורת: שורט באותו זמן 1:2", dict(hours=3, k=1.0, rr=2.0, direction=-1)),
    ("1:3 4ש' רק כשסטופ ≥ 5$", dict(hours=4, k=1.0, rr=3.0, min_risk=5.0)),
    ("1:3 4ש' רק כשסטופ ≥ 8$", dict(hours=4, k=1.0, rr=3.0, min_risk=8.0)),
    ("1:2 3ש' סטופ 0.7 רק כשסטופ ≥ 5$", dict(hours=3, k=0.7, rr=2.0, min_risk=5.0)),
    ("בסיס: אותו לונג 6ש' אחרי הפתיחה", dict(hours=4, k=1.0, rr=3.0, offset_h=6)),
    ("בסיס: אותו לונג 12ש' אחרי הפתיחה", dict(hours=4, k=1.0, rr=3.0, offset_h=12)),
    ("בסיס: אותו לונג 18ש' אחרי הפתיחה", dict(hours=4, k=1.0, rr=3.0, offset_h=18)),
]


def report(m1: pd.DataFrame, cost: float, title: str) -> str:
    from research.null import shuffle_within_day
    years = sorted(set(m1.index.year))
    nm = shuffle_within_day(m1, 3)
    lines = [f"### 🌏 סבב 5: לונג בפתיחה היומית · {title} · {m1.index[0]:%Y-%m} עד {m1.index[-1]:%Y-%m} · עלות {cost}$", "",
             "| גרסה | עסקאות | הצלחה | R | ממוצע | t | " + " | ".join(str(y) for y in years)
             + " | שנים ברווח | יעד/סטופ/זמן % | ביקורת R |", "|" + "---|" * (10 + len(years))]
    for name, p in VARIANTS:
        tr = run(m1, cost, **p)
        if tr.empty:
            lines.append(f"| {name} | 0 |")
            continue
        lines.append(_row(name, tr, years, run(nm, cost, **p)))
    tr = run(m1, cost, hours=3, k=1.0, rr=2.0)
    by_dow = tr.groupby(tr.t.dt.tz_convert("America/New_York").dt.dayofweek)["r"].agg(["count", "sum", "mean"])
    lines += ["", "לפי יום (1:2, יום הפתיחה בשעון NY; 6=ראשון): " + " · ".join(
        f"{int(d)}: {int(r['count'])} עסק' {r['sum']:+.0f}R" for d, r in by_dow.iterrows())]
    return "\n".join(lines)



def delay_report(m1: pd.DataFrame, cost: float, start: str | None = None, end: str | None = None) -> str:
    """כמה מהרווח נמצא בדקות הראשונות אחרי הפתיחה? (הבוט נכנס רק בסגירת נר ה-5 דקות הראשון)."""
    if start:
        m1 = m1[(m1.index >= pd.Timestamp(start, tz="UTC")) & (m1.index < pd.Timestamp(end, tz="UTC"))]
    lines = [f"### ⏱ כניסה מאוחרת בפתיחה · {m1.index[0]:%Y-%m-%d} עד {m1.index[-1]:%Y-%m-%d} · סטופ 1 ATR · 1:3 · 4ש' · עלות {cost}$", "",
             "| עיכוב | עסקאות | הצלחה | R | ממוצע | t | לפי חודש |", "|---|---|---|---|---|---|---|"]
    from research.loop import _s
    for dm in (0, 1, 2, 5, 10, 15, 30, 60):
        tr = run(m1, cost, hours=4, k=1.0, rr=3.0, delay_min=dm)
        if tr.empty:
            continue
        s = _s(tr)
        by = tr.groupby(tr.t.dt.strftime("%Y-%m"))["r"].sum()
        lines.append(f"| {dm} דק' | {s['n']} | {s['win']:.0f}% | {s['sum']:+.1f} | {tr.r.mean():+.3f} | {s['t']:+.1f} | "
                     + " ".join(f"{k[5:]}:{v:+.0f}" for k, v in by.items()) + " |")
    # כמה המחיר זז בדקות הראשונות (מהפתיחה) - ב-ATR
    o, c = m1["open"].to_numpy(), m1["close"].to_numpy()
    pts = reopen_points(m1)
    ns = _secs(m1.index)
    h1 = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    atr = wilder_atr(h1, 14).reindex(m1.index, method="ffill").shift(1).to_numpy()
    for dm in (1, 5, 15, 60, 180):
        j = np.searchsorted(ns, ns[pts] + dm * 60)
        ok = (j < len(c)) & (atr[pts] > 0)
        mv = (c[np.minimum(j, len(c) - 1)] - o[pts])[ok] / atr[pts][ok]
        lines.append(f"- תנועה ממוצעת מהפתיחה עד {dm} דק': {np.nanmean(mv):+.3f} ATR (חציון {np.nanmedian(mv):+.3f})")
    return "\n".join(lines)


def regime_report(m1: pd.DataFrame, cost: float) -> str:
    """האם השיטות עובדות רק ב'סוג שוק' מסוים (כמו השנתיים האחרונות), וגם בעבר כשהשוק היה דומה?
    סוג שוק נמדד עם נתונים שידועים לפני העסקה: מגמה (מחיר מעל ממוצע 100 ימים) ותנודתיות (טווח יומי / מחיר
    מעל החציון של השנה האחרונה)."""
    from research.loop import _s
    d = m1.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    rng = ((d.high - d.low) / d.close).rolling(14).mean()
    trend = (d.close > d.close.rolling(100).mean()).shift(1)
    vol = (rng > rng.rolling(250, min_periods=120).median()).shift(1)
    reg = pd.DataFrame({"trend": trend, "vol": vol}).dropna()
    reg.index = reg.index.tz_convert("UTC") if reg.index.tz is not None else reg.index.tz_localize("UTC")
    tr = run(m1, cost, hours=4, k=1.0, rr=3.0, delay_min=5)
    day = tr.t.dt.tz_convert("UTC").dt.normalize()
    tr = tr.join(reg, on=day.rename("d")) if False else tr.assign(trend=reg.trend.reindex(day).to_numpy(),
                                                                    vol=reg.vol.reindex(day).to_numpy())
    tr = tr.dropna(subset=["trend", "vol"])
    names = {(True, True): "עולה + תנודתי (כמו עכשיו)", (True, False): "עולה + רגוע",
             (False, True): "יורד/צדדי + תנודתי", (False, False): "יורד/צדדי + רגוע"}
    periods = [("2018-2019", "2018-01-01", "2020-01-01"), ("2020", "2020-01-01", "2021-01-01"),
               ("2021-2023", "2021-01-01", "2024-01-01"), ("2024", "2024-01-01", "2025-01-01"),
               ("2025-2026", "2025-01-01", "2027-01-01")]
    lines = [f"### 🌦 לונג בפתיחה (כניסה ריאלית אחרי 5 דק') לפי סוג שוק · {m1.index[0]:%Y} עד {m1.index[-1]:%Y-%m} · עלות {cost}$", "",
             "| סוג שוק | " + " | ".join(p[0] for p in periods) + " | הכל |", "|" + "---|" * (len(periods) + 2)]
    for key, name in names.items():
        sub = tr[(tr.trend == key[0]) & (tr.vol == key[1])]
        cells = []
        for _, a, b in periods:
            x = sub[(sub.t >= pd.Timestamp(a, tz="UTC")) & (sub.t < pd.Timestamp(b, tz="UTC"))]
            s = _s(x)
            cells.append(f"{s['n']} · {s['sum']:+.0f}R · t {s['t']:+.1f}" if s["n"] else "-")
        s = _s(sub)
        lines.append(f"| {name} | " + " | ".join(cells) + f" | **{s['n']} · {s['sum']:+.0f}R · t {s['t']:+.1f}** |")
    share = reg.groupby([reg.trend, reg.vol]).size() / len(reg)
    lines += ["", "כמה מהזמן השוק היה בכל סוג: " + " · ".join(f"{names[(bool(k[0]), bool(k[1]))]} {100 * v:.0f}%"
                                                            for k, v in share.items())]
    last = reg.iloc[-1]
    lines.append(f"סוג השוק היום: **{names[(bool(last.trend), bool(last.vol))]}**")
    return "\n".join(lines)
