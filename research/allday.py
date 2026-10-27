"""סבב 8: שיטות "כל היום" - החלטה אחת ליום מסחר, מחזיקים עד סטופ/יעד/סוף היום (17:00 ניו יורק).

משפחות:
  tsmom:  מגמה רב-יומית - כיוון = סימן התשואה של L ימי המסחר האחרונים. כניסה בפתיחה / 02:00 / 08:00.
  fade:   היפוך אחרי יום קיצוני (תנועה של יום אתמול > z ממוצע הטווח היומי).
  vbo:    פריצת תנודתיות (לארי וויליאמס): פקודת קנייה/מכירה במרחק k * טווח אתמול מהפתיחה. הראשונה שנוגעת.
  dow:    יום בשבוע - לונג/שורט קבוע ביום מסוים.
  combo:  מגמה רב-יומית + לונג בפתיחה (רק כשהמגמה למעלה).
סטופ k * ATR(1H), יעד 1:2/1:3, יציאה בסוף יום המסחר. עלות לכל עסקה.
בחירה רק על 2018-2022 (t>=3 ו-4/5 שנים ברווח), מבחנים: 2023-10/2024 ו-10/2024 עד היום.
"""
import itertools

import numpy as np
import pandas as pd

from research.daytime import Data, _st


def session_stats(dt: Data):
    s = dt.session
    df = pd.DataFrame({"s": s, "h": dt.h, "l": dt.l})
    g = df.groupby("s")
    hi, lo = g["h"].max().to_numpy(), g["l"].min().to_numpy()
    rng = hi - lo
    avg = pd.Series(rng).rolling(14, min_periods=5).mean().shift(1).to_numpy()   # ידוע לפני היום
    ret = dt.sess_close - dt.sess_open
    ny = dt.m1.index[dt.reopen].tz_convert("America/New_York")
    dow = ((ny + pd.Timedelta(hours=6)).dayofweek).to_numpy()   # יום המסחר (פתיחה בערב = היום הבא)
    return rng, avg, ret, dow


def vbo_entries(dt: Data, k: float, rng: np.ndarray):
    """כניסה בדקה הראשונה שחוצה פתיחה ± k*טווח אתמול. מחזיר (E, D)."""
    E, D = [], []
    starts = dt.reopen
    ends = np.r_[starts[1:], len(dt.o)]
    for s in range(1, len(starts)):
        a, b = starts[s], ends[s]
        if b - a < 60 or np.isnan(rng[s - 1]):
            continue
        op = dt.o[a]
        up, dn = op + k * rng[s - 1], op - k * rng[s - 1]
        hu = np.flatnonzero(dt.h[a:b] >= up)
        hd = np.flatnonzero(dt.l[a:b] <= dn)
        iu = hu[0] if len(hu) else 10**9
        idn = hd[0] if len(hd) else 10**9
        if iu == idn == 10**9:
            continue
        i, d = (iu, 1) if iu < idn else (idn, -1)
        if a + i + 1 < b - 30:
            E.append(a + i + 1)
            D.append(d)
    return np.array(E, dtype=int), np.array(D, dtype=int)


def configs():
    ex = list(itertools.product((1.0, 2.0, 3.0), (2.0, 3.0)))   # (k ATR לסטופ, יחס)
    for L, t, (k, rr) in itertools.product((5, 10, 20, 60), (None, 120, 480), ex):
        yield "tsmom", dict(L=L, t=t, k=k, rr=rr)
    for z, t, (k, rr) in itertools.product((1.0, 1.5, 2.0), (None, 120), ex):
        yield "fade", dict(z=z, t=t, k=k, rr=rr)
    for kk, (k, rr) in itertools.product((0.3, 0.5, 0.7), ex):
        yield "vbo", dict(kk=kk, k=k, rr=rr)
    for dow, d, (k, rr) in itertools.product(range(5), (1, -1), ex):
        yield "dow", dict(dow=dow, d=d, k=k, rr=rr)
    for L, (k, rr), hold in itertools.product((5, 10, 20, 60), ((1.0, 3.0), (1.0, 2.0)), (4, 23)):
        yield "combo", dict(L=L, k=k, rr=rr, hold=hold)


DOW = ["שני", "שלישי", "רביעי", "חמישי", "שישי"]


def label(fam, p):
    ex = f"סטופ {p['k']:g} ATR · 1:{p['rr']:.0f}"
    when = lambda t: "בפתיחה (01:00)" if t is None else f"ב-{t // 60:02d}:00 NY ({(t // 60 + 7) % 24:02d}:00)"
    if fam == "tsmom":
        return f"מגמה {p['L']} ימים, כניסה {when(p['t'])} · {ex}"
    if fam == "fade":
        return f"היפוך אחרי יום של >{p['z']} טווחים, כניסה {when(p['t'])} · {ex}"
    if fam == "vbo":
        return f"פריצת תנודתיות {p['kk']}×טווח אתמול · {ex}"
    if fam == "dow":
        return f"{'לונג' if p['d'] == 1 else 'שורט'} ביום {DOW[p['dow']]} · {ex}"
    return f"לונג בפתיחה רק במגמת {p['L']} ימים עולה · {ex} · עד {p['hold']}ש'"


def signal(dt: Data, st, fam, p):
    rng, avg, ret, dow = st
    nS = len(dt.reopen)
    entry_at = lambda t: dt.reopen if t is None else dt.entries(t)
    if fam in ("tsmom", "combo"):
        E = entry_at(p.get("t"))
        s = dt.session[E]
        cl = dt.sess_close
        past = np.full(len(s), np.nan)
        ok = s - p["L"] >= 0
        past[ok] = cl[s[ok] - 1] - dt.sess_open[s[ok] - p["L"]]
        keep = ~np.isnan(past) & (past != 0)
        E, D = E[keep], np.sign(past[keep]).astype(int)
        if fam == "combo":
            E, D = E[D == 1], D[D == 1]
        return E, D
    if fam == "fade":
        E = entry_at(p["t"])
        s = dt.session[E]
        ok = s >= 1
        E, s = E[ok], s[ok]
        mv = ret[s - 1] / avg[s - 1]
        keep = np.abs(np.nan_to_num(mv)) > p["z"]
        return E[keep], (-np.sign(mv[keep])).astype(int)
    if fam == "vbo":
        return vbo_entries(dt, p["kk"], rng)
    if fam == "dow":
        E = dt.reopen
        keep = dow[dt.session[E]] == p["dow"]
        return E[keep], np.full(keep.sum(), p["d"])
    raise ValueError(fam)


def report(m1: pd.DataFrame, cost: float) -> str:
    from research.null import shuffle_within_day
    dt = Data(m1)
    nd = Data(shuffle_within_day(m1, 17))
    st, nst = session_stats(dt), session_stats(nd)
    years = sorted(set(dt.year))
    dev_years = [y for y in years if y <= 2022]
    sec = lambda ts: (ts - m1.index[0]) / pd.Timedelta(seconds=1)
    s1, s2 = sec(pd.Timestamp("2023-01-01", tz="UTC")), sec(m1.index[-1] - pd.DateOffset(months=24))
    rows, null_pass = [], 0
    for fam, p in configs():
        hold = p.get("hold", 23)
        E, D = signal(dt, st, fam, p)
        if len(E) < 30:
            continue
        r, E = dt.trade(E, D, hold, p["rr"], cost, k=p["k"])
        t = dt.secs[E]
        dev, te1, te2 = r[t < s1], r[(t >= s1) & (t < s2)], r[t >= s2]
        yrs = [r[dt.year[E] == y].sum() for y in years]
        dpos = sum(r[dt.year[E] == y].sum() > 0 for y in dev_years)
        rows.append({"fam": fam, "p": p, "dev": (len(dev), *_st(dev)), "dpos": dpos, "t1": (len(te1), *_st(te1)),
                     "t2": (len(te2), *_st(te2)), "years": yrs, "per_day": len(r) / len(dt.reopen)})
        nE, nD = signal(nd, nst, fam, p)
        if len(nE) >= 30:
            nr, nE = nd.trade(nE, nD, hold, p["rr"], cost, k=p["k"])
            nde = nr[nd.secs[nE] < s1]
            if _st(nde)[1] >= 3 and sum(nr[nd.year[nE] == y].sum() > 0 for y in dev_years) >= 4:
                null_pass += 1
    passed = sorted([x for x in rows if x["dev"][2] >= 3 and x["dpos"] >= 4], key=lambda x: x["dev"][2], reverse=True)
    f = lambda v: f"{v[0]} · {v[1]:+.0f} · {v[2]:+.1f}"
    lines = [f"### 🌞 סבב 8: שיטות 'כל היום' · {m1.index[0]:%Y-%m} עד {m1.index[-1]:%Y-%m} · עלות {cost}$", "",
             f"נבדקו {len(rows)} תצורות. עברו גילוי (t≥3 ב-2018-22, 4/5 שנים): **{len(passed)}** · על נתונים מעורבבים: **{null_pass}**", "",
             "| # | שיטה | עסקאות/יום | גילוי n · R · t | שנים+ | **מבחן 1** | **מבחן 2** | " + " | ".join(str(y) for y in years) + " |",
             "|" + "---|" * (7 + len(years))]
    for k, x in enumerate(passed[:25], 1):
        lines.append(f"| {k} | {label(x['fam'], x['p'])} | {x['per_day']:.2f} | {f(x['dev'])} | {x['dpos']}/5 | **{f(x['t1'])}** | "
                     f"**{f(x['t2'])}** | " + " | ".join(f"{v:+.0f}" for v in x["years"]) + " |")
    both = [x for x in passed if x["t1"][1] > 0 and x["t2"][1] > 0]
    lines += ["", f"עברו גילוי ורווחיים בשני המבחנים: **{len(both)}**", "", "**הכי קרובים (t הגבוה בגילוי):**", ""]
    for x in sorted(rows, key=lambda x: x["dev"][2], reverse=True)[:15]:
        lines.append(f"- {label(x['fam'], x['p'])} · {x['per_day']:.2f}/יום · גילוי {f(x['dev'])} ({x['dpos']}/5) · "
                     f"מבחן 1 {f(x['t1'])} · מבחן 2 {f(x['t2'])}")
    for fam in ("tsmom", "fade", "vbo", "dow", "combo"):
        ts = np.array([x["dev"][2] for x in rows if x["fam"] == fam])
        if len(ts):
            lines.append(f"\n{fam}: {len(ts)} תצורות · t בגילוי: חציון {np.median(ts):+.2f}, מקס {ts.max():+.2f}")
    return "\n".join(lines)
