"""סבב 7: שיטות נזילות על 9 שנים (2018 עד היום), עם אותה חלוקה קשיחה כמו סבב 6.

רמות נזילות לכל יום מסחר (יום = מהפתיחה ב-18:00 ניו יורק):
  pd   = שיא/שפל יום המסחר הקודם (PDH/PDL)            - זמין מתחילת היום
  asia = שיא/שפל אסיה (18:00-02:00 ניו יורק)          - זמין מ-02:00
  lon  = שיא/שפל לונדון (02:00-05:00 ניו יורק)        - זמין מ-05:00
רמה נספרת רק אם לא נלקחה כבר לפני תחילת החלון.

משפחות:
  rev (Sweep + Reclaim, "ציד סטופים"): המחיר עובר את הרמה ואז נר 5M נסגר בחזרה בצד השני תוך N נרות
       -> עסקה נגד כיוון הסוויפ. סטופ: מעבר לקצה הסוויפ (+0.1 ATR) או 1 ATR.
  run (פריצה אמיתית): נר 5M נסגר מעבר לרמה ביותר מ-z ATR -> עסקה בכיוון הפריצה, סטופ 1 ATR.
חלונות: לונדון 02:00-05:00, ניו יורק 07:00-11:00, כל היום 02:00-15:00 (שעון ניו יורק).
יציאה: יעד 1:2/1:3, יציאה בזמן אחרי 2/4 שעות, לא חוצים את ההפסקה היומית. הכל על נרות דקה.
בחירה רק על 2018-2022 (t>=3 ו-4/5 שנים ברווח), ואז מבחן 1 = 2023-10/2024, מבחן 2 = 10/2024 עד היום.
"""
import itertools

import numpy as np
import pandas as pd

from research.daytime import Data, _st

WINDOWS = {"לונדון": (120, 300), "ניו יורק": (420, 660), "כל היום": (120, 900)}
AVAIL = {"pd": 0, "asia": 120, "lon": 300}
NS = (3, 6, 12)


def levels(dt: Data):
    """לכל סשן: (שיא, שפל) לכל סוג רמה."""
    ns = dt.session.max() + 1
    out = {k: (np.full(ns, np.nan), np.full(ns, np.nan)) for k in AVAIL}
    s, m = dt.session, dt.ny_min
    eve = m >= 18 * 60
    df = pd.DataFrame({"s": s, "h": dt.h, "l": dt.l})
    g = df.groupby("s")
    hi, lo = g["h"].max(), g["l"].min()
    out["pd"][0][hi.index[1:]] = hi.values[:-1]
    out["pd"][1][lo.index[1:]] = lo.values[:-1]
    for key, mask in (("asia", eve | (m < 120)), ("lon", ~eve & (m >= 120) & (m < 300))):
        gg = df[mask].groupby("s")
        out[key][0][gg["h"].max().index] = gg["h"].max().values
        out[key][1][gg["l"].min().index] = gg["l"].min().values
    return out


def events(dt: Data):
    """מוצא פעם אחת את כל האירועים הגולמיים; התצורות רק בוחרות מתוכם."""
    lv = levels(dt)
    s, m = dt.session, dt.ny_min
    day_min = np.where(m >= 18 * 60, m - 24 * 60, m)          # דקות מחצות, הערב שלילי
    bar_close = (m % 5) == 4
    starts = np.r_[0, np.flatnonzero(np.diff(s)) + 1]
    ends = np.r_[starts[1:], len(s)]
    rev, run = [], []
    for si, (a, b) in enumerate(zip(starts, ends)):
        dm = day_min[a:b]
        for key, avail in AVAIL.items():
            for side, L in ((1, lv[key][0][si]), (-1, lv[key][1][si])):   # side=1: רמה עליונה
                if np.isnan(L):
                    continue
                for wname, (w0, w1) in WINDOWS.items():
                    ws = max(w0, avail)
                    if ws >= w1:
                        continue
                    pre = (dm >= avail) & (dm < ws)
                    hh, ll = dt.h[a:b], dt.l[a:b]
                    if pre.any() and ((hh[pre].max() > L) if side == 1 else (ll[pre].min() < L)):
                        continue                                    # הרמה כבר נלקחה לפני החלון
                    inw = np.flatnonzero((dm >= ws) & (dm < w1))
                    if not len(inw):
                        continue
                    beyond = (hh[inw] > L) if side == 1 else (ll[inw] < L)
                    if beyond.any():
                        s0 = inw[beyond.argmax()]
                        for N in NS:
                            seg = np.arange(s0, min(s0 + 5 * N + 5, b - a))
                            cl = dt.c[a + seg]
                            back = bar_close[a + seg] & ((cl < L) if side == 1 else (cl > L))
                            if back.any():
                                r_i = seg[back.argmax()]
                                ext = hh[s0:r_i + 1].max() if side == 1 else ll[s0:r_i + 1].min()
                                rev.append((key, wname, N, side, a + r_i + 1, L, ext))
                    cl = dt.c[a + inw]
                    bc = bar_close[a + inw]
                    atr = dt.atr[a + inw]
                    for z in (0.1, 0.3):
                        ok = bc & (((cl - L) if side == 1 else (L - cl)) > z * atr)
                        if ok.any():
                            run.append((key, wname, z, side, a + inw[ok.argmax()] + 1))
    rev = pd.DataFrame(rev, columns=["key", "win", "N", "side", "E", "L", "ext"])
    run = pd.DataFrame(run, columns=["key", "win", "z", "side", "E"])
    n = len(dt.o)
    return rev[rev.E < n - 300], run[run.E < n - 300]


def trade(dt: Data, E, D, risk, hold_h, rr, cost):
    n = len(dt.o)
    H = int(hold_h * 60)
    win = np.minimum(E[:, None] + np.arange(H)[None, :], n - 1)
    valid = dt.session[win] == dt.session[E][:, None]
    e = dt.o[E]
    sl, tp = e - D * risk, e + D * rr * risk
    hh, ll = dt.h[win], dt.l[win]
    st = np.where(D[:, None] == 1, ll <= sl[:, None], hh >= sl[:, None]) & valid
    tg = np.where(D[:, None] == 1, hh >= tp[:, None], ll <= tp[:, None]) & valid
    big = H + 1
    si = np.where(st.any(1), st.argmax(1), big)
    ti = np.where(tg.any(1), tg.argmax(1), big)
    last = np.maximum(valid.sum(1) - 1, 0)
    timed = (dt.c[win[np.arange(len(E)), last]] - e) * D / risk
    return np.where((si <= ti) & (si < big), -1.0, np.where(ti < big, rr, timed)) - cost / risk


def configs():
    pairs = [(k, w) for k in AVAIL for w in WINDOWS if not (k == "lon" and w == "לונדון")]
    for (k, w), N, depth, stop, rr, hold in itertools.product(pairs, NS, (0.0, 0.2), ("ext", "atr"), (2.0, 3.0), (2, 4)):
        yield "rev", dict(key=k, win=w, N=N, depth=depth, stop=stop, rr=rr, hold=hold)
    for (k, w), z, rr, hold in itertools.product(pairs, (0.1, 0.3), (2.0, 3.0), (2, 4)):
        yield "run", dict(key=k, win=w, z=z, rr=rr, hold=hold)


NAMES = {"pd": "שיא/שפל אתמול", "asia": "שיא/שפל אסיה", "lon": "שיא/שפל לונדון"}


def label(fam, p):
    ex = f"{p['hold']}ש' 1:{p['rr']:.0f}"
    if fam == "rev":
        st = "סטופ מעבר לסוויפ" if p["stop"] == "ext" else "סטופ 1 ATR"
        dep = f", עומק ≥{p['depth']} ATR" if p["depth"] else ""
        return f"סוויפ+חזרה · {NAMES[p['key']]} · {p['win']} · תוך {p['N']} נרות{dep} · {st} · {ex}"
    return f"פריצה ({p['z']} ATR) · {NAMES[p['key']]} · {p['win']} · {ex}"


def run_config(dt, ev, fam, p, cost):
    rev, run = ev
    if fam == "rev":
        x = rev[(rev.key == p["key"]) & (rev.win == p["win"]) & (rev.N == p["N"])]
        E, side, L, ext = x.E.to_numpy(), x.side.to_numpy(), x.L.to_numpy(), x.ext.to_numpy()
        a = dt.atr[E]
        keep = ~np.isnan(a) & (np.abs(ext - L) >= p["depth"] * a)
        E, side, ext, a = E[keep], side[keep], ext[keep], a[keep]
        D = -side
        if p["stop"] == "ext":
            risk = (ext + side * 0.1 * a - dt.o[E]) * side
            ok = (risk >= 0.25 * a) & (risk <= 3 * a)
        else:
            risk = a.copy()
            ok = np.ones(len(E), bool)
        E, D, risk = E[ok], D[ok], risk[ok]
    else:
        x = run[(run.key == p["key"]) & (run.win == p["win"]) & (run.z == p["z"])]
        E, D = x.E.to_numpy(), x.side.to_numpy()
        risk = dt.atr[E]
        ok = ~np.isnan(risk)
        E, D, risk = E[ok], D[ok], risk[ok]
    if not len(E):
        return np.array([]), E, D
    return trade(dt, E, D, risk, p["hold"], p["rr"], cost), E, D


def report(m1: pd.DataFrame, cost: float) -> str:
    from research.null import shuffle_within_day
    dt = Data(m1)
    ev = events(dt)
    nd = Data(shuffle_within_day(m1, 13))
    nev = events(nd)
    years = sorted(set(dt.year))
    dev_years = [y for y in years if y <= 2022]
    sec = lambda ts: (ts - m1.index[0]) / pd.Timedelta(seconds=1)
    s1, s2 = sec(pd.Timestamp("2023-01-01", tz="UTC")), sec(m1.index[-1] - pd.DateOffset(months=24))
    rows, null_pass = [], 0
    for fam, p in configs():
        r, E, D = run_config(dt, ev, fam, p, cost)
        if len(r) < 30:
            continue
        t = dt.secs[E]
        dev, te1, te2 = r[t < s1], r[(t >= s1) & (t < s2)], r[t >= s2]
        yrs = [r[dt.year[E] == y].sum() for y in years]
        dpos = sum(r[dt.year[E] == y].sum() > 0 for y in dev_years)
        rows.append({"fam": fam, "p": p, "dev": (len(dev), *_st(dev)), "dpos": dpos, "t1": (len(te1), *_st(te1)),
                     "t2": (len(te2), *_st(te2)), "years": yrs, "ls": (r[D == 1].sum(), r[D == -1].sum()),
                     "per_day": len(r) / len(dt.reopen)})
        nr, nE, _ = run_config(nd, nev, fam, p, cost)
        if len(nr) >= 30:
            nyrs = [nr[nd.year[nE] == y].sum() for y in dev_years]
            nde = nr[nd.secs[nE] < s1]
            if _st(nde)[1] >= 3 and sum(v > 0 for v in nyrs) >= 4:
                null_pass += 1
    passed = sorted([x for x in rows if x["dev"][2] >= 3 and x["dpos"] >= 4], key=lambda x: x["dev"][2], reverse=True)
    f = lambda v: f"{v[0]} · {v[1]:+.0f} · {v[2]:+.1f}"
    lines = [f"### 💧 סבב 7: שיטות נזילות · {m1.index[0]:%Y-%m} עד {m1.index[-1]:%Y-%m} · עלות {cost}$", "",
             f"אירועים: {len(ev[0])} סוויפ+חזרה, {len(ev[1])} פריצות. נבדקו {len(rows)} תצורות.",
             f"עברו את סף הגילוי (t≥3 ב-2018-22 ו-4/5 שנים ברווח): **{len(passed)}** · אותו חיפוש על נתונים מעורבבים: **{null_pass}**", "",
             "| # | שיטה | עסקאות/יום | גילוי n · R · t | שנים+ | **מבחן 1** | **מבחן 2** | לונג/שורט R | "
             + " | ".join(str(y) for y in years) + " |", "|" + "---|" * (8 + len(years))]
    for k, x in enumerate(passed[:25], 1):
        lines.append(f"| {k} | {label(x['fam'], x['p'])} | {x['per_day']:.2f} | {f(x['dev'])} | {x['dpos']}/5 | **{f(x['t1'])}** | "
                     f"**{f(x['t2'])}** | {x['ls'][0]:+.0f}/{x['ls'][1]:+.0f} | " + " | ".join(f"{v:+.0f}" for v in x["years"]) + " |")
    both = [x for x in passed if x["t1"][1] > 0 and x["t2"][1] > 0]
    lines += ["", f"עברו גילוי ורווחיים בשני המבחנים: **{len(both)}**", "", "**הכי קרובים (t הגבוה בגילוי, בלי סף):**", ""]
    for x in sorted(rows, key=lambda x: x["dev"][2], reverse=True)[:12]:
        lines.append(f"- {label(x['fam'], x['p'])} · גילוי {f(x['dev'])} ({x['dpos']}/5) · מבחן 1 {f(x['t1'])} · מבחן 2 {f(x['t2'])}")
    for fam in ("rev", "run"):
        ts = np.array([x["dev"][2] for x in rows if x["fam"] == fam])
        if len(ts):
            lines.append(f"\n{fam}: {len(ts)} תצורות · t בגילוי: חציון {np.median(ts):+.2f}, מקס {ts.max():+.2f}")
    return "\n".join(lines)
