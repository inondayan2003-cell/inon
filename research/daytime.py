"""סבב 6: חיפוש שיטה לשעות היום (01:00-15:00 ניו יורק = 08:00-22:00 שעון ישראל).

נתונים: 2018 עד היום (כ-9 שנים). חלוקה קשיחה:
  גילוי = 2018-2022 (רק כאן בוחרים), מבחן 1 = 2023-10/2024, מבחן 2 = 10/2024 עד היום.
בחירה: t בגילוי >= 3 וגם רווח ב-4 מתוך 5 שנות הגילוי. את המבחנים לא רואים לפני הבחירה.

משפחות (כניסה בשעה קבועה בשעון ניו יורק, נכון לשעון קיץ/חורף):
  fixed:  כיוון קבוע בשעה מסוימת.
  night:  לפי התנועה מאז הפתיחה היומית (ב-ATR) - המשך או היפוך, אם היא גדולה מ-z.
  prev:   לפי כיוון יום המסחר הקודם - המשך או היפוך.
יציאה: סטופ 1 ATR(1H), יעד 1:2 או 1:3, יציאה בזמן אחרי H שעות. הכל על נרות דקה.
"""
import itertools

import numpy as np
import pandas as pd

from app.indicators import atr as wilder_atr

NY = "America/New_York"


class Data:
    def __init__(self, m1: pd.DataFrame):
        self.m1 = m1
        self.o, self.h, self.l, self.c = (m1[x].to_numpy() for x in ("open", "high", "low", "close"))
        idx = m1.index
        self.secs = ((idx - idx[0]) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)
        ny = idx.tz_convert(NY)
        self.ny_min = (ny.hour * 60 + ny.minute).to_numpy()
        self.year = idx.year.to_numpy()
        gaps = np.diff(self.secs) / 60
        reopen = np.r_[0, np.flatnonzero(gaps >= 30) + 1]
        self.session = np.cumsum(np.isin(np.arange(len(m1)), reopen)) - 1
        self.sess_open = self.o[reopen]
        self.sess_close = np.r_[self.c[reopen[1:] - 1], self.c[-1]]
        h1 = m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
        self.atr = wilder_atr(h1, 14).reindex(idx, method="ffill").shift(1).to_numpy()
        self.reopen = reopen
        self._entries = {}

    def entries(self, minute: int) -> np.ndarray:
        """אינדקס הדקה הראשונה בכל סשן שבה השעון בניו יורק >= minute (עד 20 דקות אחרי)."""
        if minute not in self._entries:
            ok = (self.ny_min >= minute) & (self.ny_min < minute + 20)
            idx = np.flatnonzero(ok)
            first = idx[np.r_[True, self.session[idx[1:]] != self.session[idx[:-1]]]] if len(idx) else idx
            self._entries[minute] = first
        return self._entries[minute]

    def trade(self, E: np.ndarray, D: np.ndarray, hold_h: float, rr: float, cost: float, k: float = 1.0):
        """E = אינדקסי כניסה (בפתיחת הדקה), D = כיוונים. מחזיר (R, אינדקסי כניסה) לאלה שנכנסו."""
        ok = ~np.isnan(self.atr[E]) & (self.atr[E] > 0)
        E, D = E[ok], D[ok]
        n = len(self.o)
        H = int(hold_h * 60)
        win = E[:, None] + np.arange(H)[None, :]
        valid = win < n
        win = np.minimum(win, n - 1)
        # לא חוצים את ההפסקה היומית: סוגרים בסוף הסשן
        same = self.session[win] == self.session[E][:, None]
        valid &= same
        risk = k * self.atr[E]
        e = self.o[E]
        sl, tp = e - D * risk, e + D * rr * risk
        hh, ll = self.h[win], self.l[win]
        st = np.where(D[:, None] == 1, ll <= sl[:, None], hh >= sl[:, None]) & valid
        tg = np.where(D[:, None] == 1, hh >= tp[:, None], ll <= tp[:, None]) & valid
        big = H + 1
        si = np.where(st.any(1), st.argmax(1), big)
        ti = np.where(tg.any(1), tg.argmax(1), big)
        last = valid.sum(1) - 1
        last = np.maximum(last, 0)
        timed = (self.c[win[np.arange(len(E)), last]] - e) * D / risk
        r = np.where((si <= ti) & (si < big), -1.0, np.where(ti < big, rr, timed)) - cost / risk
        return r, E


def _st(r):
    if len(r) < 3:
        return 0.0, 0.0
    return float(r.sum()), float(r.mean() / r.std(ddof=1) * np.sqrt(len(r)))


TIMES = [m for m in range(60, 15 * 60 + 1, 30)]          # 01:00-15:00 ניו יורק, כל חצי שעה
EXITS = list(itertools.product([1, 2, 4], [2.0, 3.0]))   # (שעות, יחס)


def configs():
    for t in TIMES:
        for d in (1, -1):
            for hold, rr in EXITS:
                yield "fixed", dict(t=t, d=d, hold=hold, rr=rr)
    for t in (120, 180, 420, 480, 510, 570, 600, 690, 780, 840, 900, 930):
        for z, mode in itertools.product((0.5, 1.0, 2.0), (1, -1)):
            for hold, rr in EXITS:
                yield "night", dict(t=t, z=z, mode=mode, hold=hold, rr=rr)
    for t in (120, 180, 480, 510, 570):
        for mode in (1, -1):
            for hold, rr in EXITS:
                yield "prev", dict(t=t, mode=mode, hold=hold, rr=rr)
    for t in (600, 660, 720, 840):          # מומנטום תוך-יומי: התנועה מפתיחת קומקס (08:20) עד t
        for z, mode in itertools.product((0.5, 1.0, 2.0), (1, -1)):
            for hold, rr in EXITS:
                yield "comex", dict(t=t, z=z, mode=mode, hold=hold, rr=rr)


def signal(dt: Data, fam: str, p: dict):
    E = dt.entries(p["t"])
    if fam == "fixed":
        return E, np.full(len(E), p["d"])
    if fam == "night":
        mv = (dt.o[E] - dt.sess_open[dt.session[E]]) / dt.atr[E]
        keep = np.abs(mv) > p["z"]
        return E[keep], (np.sign(mv[keep]) * p["mode"]).astype(int)
    if fam == "comex":
        S = dt.entries(500)
        start = np.full(dt.session.max() + 1, np.nan)
        start[dt.session[S]] = dt.o[S]
        mv = (dt.o[E] - start[dt.session[E]]) / dt.atr[E]
        keep = np.abs(np.nan_to_num(mv)) > p["z"]
        return E[keep], (np.sign(mv[keep]) * p["mode"]).astype(int)
    if fam == "prev":
        s = dt.session[E]
        keep = s > 0
        E, s = E[keep], s[keep]
        prev = dt.sess_close[s - 1] - dt.sess_open[s - 1]
        keep = prev != 0
        return E[keep], (np.sign(prev[keep]) * p["mode"]).astype(int)
    raise ValueError(fam)


def label(fam, p):
    hhmm = f"{p['t'] // 60:02d}:{p['t'] % 60:02d}"
    il = f"{(p['t'] // 60 + 7) % 24:02d}:{p['t'] % 60:02d}"
    ex = f"{p['hold']}ש' 1:{p['rr']:.0f}"
    if fam == "fixed":
        return f"{'לונג' if p['d'] == 1 else 'שורט'} ב-{hhmm} NY ({il} ישראל) · {ex}"
    if fam == "night":
        return f"{'המשך' if p['mode'] == 1 else 'היפוך'} תנועת הלילה >{p['z']} ATR ב-{hhmm} NY ({il}) · {ex}"
    if fam == "comex":
        return f"{'המשך' if p['mode'] == 1 else 'היפוך'} התנועה מ-08:20 >{p['z']} ATR ב-{hhmm} NY ({il}) · {ex}"
    return f"{'המשך' if p['mode'] == 1 else 'היפוך'} יום אתמול ב-{hhmm} NY ({il}) · {ex}"


def report(m1: pd.DataFrame, cost: float) -> str:
    from research.null import shuffle_within_day
    dt = Data(m1)
    nd = Data(shuffle_within_day(m1, 11))
    years = sorted(set(dt.year))
    dev_years = [y for y in years if y <= 2022]
    t1 = pd.Timestamp("2023-01-01", tz="UTC")
    t2 = m1.index[-1] - pd.DateOffset(months=24)
    tsec = lambda ts: (ts - m1.index[0]) / pd.Timedelta(seconds=1)
    s1, s2 = tsec(t1), tsec(t2)
    rows = []
    for fam, p in configs():
        E, D = signal(dt, fam, p)
        r, E = dt.trade(E, D, p["hold"], p["rr"], cost)
        sec = dt.secs[E]
        dev, te1, te2 = r[sec < s1], r[(sec >= s1) & (sec < s2)], r[sec >= s2]
        dsum, dt_ = _st(dev)
        yrs = [r[dt.year[E] == y].sum() for y in dev_years]
        rows.append({"fam": fam, "p": p, "n": len(r), "dev": (len(dev), dsum, dt_), "dev_pos": sum(x > 0 for x in yrs),
                     "t1": (len(te1), *_st(te1)), "t2": (len(te2), *_st(te2)), "years": [r[dt.year[E] == y].sum() for y in years]})
    passed = [x for x in rows if x["dev"][2] >= 3.0 and x["dev_pos"] >= 4]
    passed.sort(key=lambda x: x["dev"][2], reverse=True)
    # ביקורת: כמה "עוברים" היינו מקבלים על נתונים מעורבבים (אותו חיפוש בדיוק)
    null_pass = 0
    for fam, p in configs():
        E, D = signal(nd, fam, p)
        r, E = nd.trade(E, D, p["hold"], p["rr"], cost)
        dev = r[nd.secs[E] < s1]
        yrs = [r[(nd.year[E] == y)].sum() for y in dev_years]
        if _st(dev)[1] >= 3.0 and sum(x > 0 for x in yrs) >= 4:
            null_pass += 1

    jan = dt.ny_min[dt.reopen[(m1.index[dt.reopen].month == 1)]]
    jul = dt.ny_min[dt.reopen[(m1.index[dt.reopen].month == 7)]]
    med = lambda a: f"{int(np.median(a)) // 60:02d}:{int(np.median(a)) % 60:02d}" if len(a) else "-"
    lines = [f"### ☀️ סבב 6: שיטות לשעות היום · {m1.index[0]:%Y-%m} עד {m1.index[-1]:%Y-%m} · עלות {cost}$", "",
             f"בדיקת שעון: הפתיחה היומית בנתונים = {med(jan)} NY בינואר, {med(jul)} NY ביולי (צריך 18:00 בשניהם).", "",
             f"נבדקו {len(rows)} תצורות. עברו את סף הגילוי (t≥3 ב-2018-2022 ו-4/5 שנים ברווח): **{len(passed)}**. "
             f"על נתונים מעורבבים, אותו חיפוש: **{null_pass}**.", "",
             "| # | שיטה | גילוי 2018-22: n · R · t | שנים+ | **מבחן 1 2023-24: n · R · t** | **מבחן 2 שנתיים: n · R · t** | "
             + " | ".join(str(y) for y in years) + " |",
             "|" + "---|" * (6 + len(years))]
    for k, x in enumerate(passed[:30], 1):
        f = lambda v: f"{v[0]} · {v[1]:+.0f} · {v[2]:+.1f}"
        lines.append(f"| {k} | {label(x['fam'], x['p'])} | {f(x['dev'])} | {x['dev_pos']}/5 | **{f(x['t1'])}** | **{f(x['t2'])}** | "
                     + " | ".join(f"{v:+.0f}" for v in x["years"]) + " |")
    both = [x for x in passed if x["t1"][1] > 0 and x["t2"][1] > 0]
    lines += ["", f"מתוך העוברים, רווחיים בשני המבחנים: **{len(both)}** · "
              + "; ".join(label(x["fam"], x["p"]) for x in both[:10])]
    # פרופיל מהיר של כל חצי שעה ביום לפי תקופה (לונג שעה אחת, R ב-ATR)
    lines += ["", "**פרופיל: לונג שעה אחת (זמן בלבד, ב-ATR) - t לפי תקופה**", "",
              "| שעה NY | ישראל | גילוי | מבחן 1 | מבחן 2 |", "|---|---|---|---|---|"]
    for t in TIMES:
        E = dt.entries(t)
        r, E = dt.trade(E, np.ones(len(E), int), 1, 99.0, 0.0, k=99.0)
        r = r * 99.0  # בלי סטופ אפקטיבי: R ביחידות ATR
        sec = dt.secs[E]
        parts = [r[sec < s1], r[(sec >= s1) & (sec < s2)], r[sec >= s2]]
        lines.append(f"| {t // 60:02d}:{t % 60:02d} | {(t // 60 + 7) % 24:02d}:{t % 60:02d} | "
                     + " | ".join(f"{_st(x)[1]:+.1f}" for x in parts) + " |")
    return "\n".join(lines)
