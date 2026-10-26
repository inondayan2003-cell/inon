"""חיפוש אוטומטי של שיטות, עם הגנות מפני "מציאת" מזל.

1. כספת: X החודשים האחרונים לא משתתפים בחיפוש בכלל. רק הזוכות נבדקות עליהם, פעם אחת.
2. חיפוש אקראי של חוקים: 2-3 תנאים על מאפייני שוק (לפי אחוזונים) + כיוון + סשן + סטופ/יעד/זמן.
3. ביקורת: אותו חיפוש בדיוק על מחירים מעורבבים. הציון הכי טוב שם = כמה "הצלחה" יוצאת ממזל.
4. עוברת רק שיטה: >= עסקה ביום, חיובית בכל 4 תקופות החיפוש, מעל הביקורת, ורווחית בכספת.
"""
import numpy as np
import pandas as pd

from research.ml import features

EXITS = [(1.5, 1.5, 24), (1.0, 2.0, 24), (2.0, 0.5, 48), (1.0, 1.0, 12), (1.5, 1.0, 48)]
# דקות משעת חצות ניו יורק; התחלה שלילית = חלון שעובר חצות (אסיה: 18:00-02:00)
SESSIONS = {"הכל": (0, 1440), "אסיה": (1080 - 1440, 120), "לונדון": (120, 420), "ניו יורק": (420, 720),
            "אחה\"צ": (720, 1020)}
QS = (0.1, 0.2, 0.3, 0.7, 0.8, 0.9)


def outcomes(tl: pd.DataFrame, cost: float, sl: float, rr: float, hold: int):
    """R נטו של לונג ושל שורט מכל נר, עבור סטופ/יעד/זמן נתונים."""
    n = len(tl)
    hi, lo, cl = (tl[c].to_numpy() for c in ("high", "low", "close"))
    atr = tl["atr_15m"].to_numpy()
    idx = np.arange(n - hold)
    w = np.arange(1, hold + 1)
    H, L, C = hi[idx[:, None] + w], lo[idx[:, None] + w], cl[idx[:, None] + w]
    out = {}
    for d in (1, -1):
        dist = sl * atr[idx]
        e = cl[idx] * d
        fav, adv = (H, L) if d == 1 else (-L, -H)
        s_i = np.where((adv <= (e - dist)[:, None]).any(1), (adv <= (e - dist)[:, None]).argmax(1), hold + 1)
        t_i = np.where((fav >= (e + rr * dist)[:, None]).any(1), (fav >= (e + rr * dist)[:, None]).argmax(1), hold + 1)
        timed = (C[:, -1] - cl[idx]) * d / dist
        r = np.where(s_i <= t_i, np.where(s_i <= hold, -1.0, timed), rr) - cost / dist
        out[d] = np.r_[r, np.full(hold, np.nan)].astype(np.float32)
    return out


class Searcher:
    def __init__(self, tl: pd.DataFrame, cost: float, dev_end: pd.Timestamp):
        tl = tl.reset_index(drop=True)
        self.t = tl["t"]
        self.dev = (self.t < dev_end).to_numpy()
        F = features(tl)
        self.names = list(F.columns)
        X = F.to_numpy(dtype=np.float32)
        # ספים לפי אחוזונים - מחושבים רק על נתוני החיפוש (לא על הכספת)
        self.thr = np.nanquantile(X[self.dev], QS, axis=0)
        self.X = X
        self.ny_min = tl["ny_min"].to_numpy()
        self.R = [outcomes(tl, cost, *e) for e in EXITS]
        dev_t = self.t[self.dev].astype("int64").to_numpy()
        self.fold_edges = np.quantile(dev_t, np.linspace(0, 1, 5))
        self.t_int = self.t.astype("int64").to_numpy()
        self.dev_days = tl.loc[self.dev, "session"].nunique()
        self.excess = False
        self._base = {}
        self.hold_days = tl.loc[~self.dev, "session"].nunique()

    def _mask(self, rule) -> np.ndarray:
        m = np.ones(len(self.X), bool)
        for f, qi, above in rule["conds"]:
            col = self.X[:, f]
            m &= (col > self.thr[qi, f]) if above else (col < self.thr[qi, f])
        a, b = SESSIONS[rule["session"]]
        mins = self.ny_min
        m &= ((mins >= a + 1440) | (mins < b)) if a < 0 else ((mins >= a) & (mins < b))
        trig = m & ~np.r_[False, m[:-1]]  # רק כשהתנאי "נדלק" - לא כל נר שבו הוא נכון
        return trig

    def baseline(self, rule, part: str) -> float:
        """התוצאה הממוצעת של כניסה באותו כיוון, באותו סשן ובאותה יציאה - בזמן אקראי."""
        key = (rule["exit"], rule["dir"], rule["session"], part)
        if key not in self._base:
            a, b = SESSIONS[rule["session"]]
            mins = self.ny_min
            sess = ((mins >= a + 1440) | (mins < b)) if a < 0 else ((mins >= a) & (mins < b))
            r_all = self.R[rule["exit"]][rule["dir"]]
            sel = sess & (self.dev if part == "dev" else ~self.dev) & ~np.isnan(r_all)
            self._base[key] = float(np.mean(r_all[sel]))
        return self._base[key]

    def evaluate(self, rule, part: str = "dev"):
        trig = self._mask(rule)
        r_all = self.R[rule["exit"]][rule["dir"]]
        sel = trig & (self.dev if part == "dev" else ~self.dev) & ~np.isnan(r_all)
        r = r_all[sel]
        if self.excess and part == "dev" and len(r):
            r = r - self.baseline(rule, part)  # מעבר לכיוון הכללי של השוק בתקופה
        if len(r) < 30:
            return None
        days = self.dev_days if part == "dev" else self.hold_days
        sd = r.std(ddof=1)
        res = {"n": len(r), "per_day": len(r) / days, "win": float((r > 0).mean() * 100), "avg": float(r.mean()),
               "sum": float(r.sum()), "t": float(r.mean() / sd * np.sqrt(len(r))) if sd > 0 else 0.0,
               "pf": float(r[r > 0].sum() / max(-r[r < 0].sum(), 1e-9))}
        if part == "dev":
            ti = self.t_int[sel]
            res["folds"] = [float(r[(ti >= self.fold_edges[k]) & (ti <= self.fold_edges[k + 1])].sum()) for k in range(4)]
        return res

    def random_rule(self, rng, k_max: int = 3):
        k = rng.integers(2, k_max + 1)
        feats = rng.choice(len(self.names), size=k, replace=False)
        conds = [(int(f), int(rng.integers(len(QS))), bool(rng.integers(2))) for f in feats]
        return {"conds": conds, "dir": int(rng.choice([1, -1])), "session": str(rng.choice(list(SESSIONS))),
                "exit": int(rng.integers(len(EXITS)))}

    def describe(self, rule) -> str:
        parts = [f"{self.names[f]} {'>' if a else '<'} {self.thr[q, f]:.2f} (אחוזון {int(QS[q] * 100)})"
                 for f, q, a in rule["conds"]]
        sl, rr, hold = EXITS[rule["exit"]]
        return (f"{'לונג' if rule['dir'] == 1 else 'שורט'} · {rule['session']} · " + " ו-".join(parts)
                + f" · סטופ {sl}ATR יעד {rr}R זמן {hold * 5} דק'")

    def search(self, n: int, seed: int, min_per_day: float = 1.0, k_max: int = 3):
        """מחזיר את החוקים הכי טובים (לפי t ב-dev) שעומדים בתנאי הסף."""
        rng = np.random.default_rng(seed)
        best = []
        for _ in range(n):
            rule = self.random_rule(rng, k_max)
            s = self.evaluate(rule)
            if not s or s["per_day"] < min_per_day or min(s["folds"]) <= 0:
                continue
            best.append((s["t"], rule, s))
        best.sort(key=lambda x: -x[0])
        return best[:20]


def run(tl_real: pd.DataFrame, tl_null: list[pd.DataFrame], cost: float, holdout_months: int,
        n: int, k_max: int, min_per_day: float, excess: bool = False) -> str:
    dev_end = tl_real["t"].max() - pd.DateOffset(months=holdout_months)
    lines = [f"### 🔎 חיפוש אוטומטי: {n:,} חוקים · עד {k_max} תנאים · לפחות {min_per_day} עסקאות ביום"
             + (" · ציון מעבר לכיוון השוק" if excess else ""),
             f"כספת (לא נבדקה בחיפוש): {dev_end:%d/%m/%Y} - {tl_real['t'].max():%d/%m/%Y}", ""]
    null_best = []
    for i, tn in enumerate(tl_null):
        sn = Searcher(tn, cost, dev_end)
        sn.excess = excess
        b = sn.search(n, seed=100 + i, min_per_day=min_per_day, k_max=k_max)
        null_best.append(b[0][0] if b else 0.0)
        print(f"  null {i}: best t={null_best[-1]:+.2f}", flush=True)
    bar = (max(null_best) if null_best else 0.0) + 0.5  # מרווח ביטחון מעל המזל הכי גדול
    S = Searcher(tl_real, cost, dev_end)
    S.excess = excess
    top = S.search(n, seed=1, min_per_day=min_per_day, k_max=k_max)
    lines += [f"**ביקורת (מחירים מעורבבים):** ה-t הכי טוב שיצא במזל: " + ", ".join(f"{x:+.2f}" for x in null_best)
              + f" · הרף: {bar:+.2f}",
              f"**בנתונים האמיתיים:** ה-t הכי טוב: {top[0][0]:+.2f}" if top else "**בנתונים האמיתיים:** אין חוק שעבר את תנאי הסף",
              "", "| # | חוק | חיפוש: עסקאות/יום · הצלחה · ממוצע R · t · 4 תקופות | מעל הביקורת? | כספת: עסקאות · הצלחה · ממוצע R · סה\"כ · t | עבר? |",
              "|---|---|---|---|---|---|"]
    winners = []
    for i, (t, rule, s) in enumerate(top[:10], 1):
        h = S.evaluate(rule, "hold")
        above = t > bar
        ok = above and h is not None and h["avg"] > 0 and h["t"] > 1.0 and h["per_day"] >= min_per_day * 0.7
        if ok:
            winners.append((rule, s, h))
        hs = (f"{h['n']} · {h['win']:.0f}% · {h['avg']:+.3f} · {h['sum']:+.1f}R · {h['t']:+.1f}" if h else "מעט מדי")
        lines.append(f"| {i} | {S.describe(rule)} | {s['per_day']:.1f} · {s['win']:.0f}% · {s['avg']:+.3f} · {t:+.1f} · "
                     + "/".join(f"{x:+.0f}" for x in s["folds"]) + f" | {'✅' if above else '❌'} | {hs} | {'✅' if ok else ''} |")
    lines += ["", f"**שיטות שעברו הכל: {len(winners)}**"]
    print("WINNERS_JSON " + str([{"rule": w[0], "dev": w[1], "hold": w[2]} for w in winners]), flush=True)
    return "\n".join(lines)


# ---------- בדיקה של חוק ספציפי עם יציאות שונות (למשל יחס 1:2 / 1:3) ----------
RULE4 = {"conds": [("wick_up", 0.7, False), ("vol_regime", 0.2, False), ("ret12", 0.7, False)],
         "dir": -1, "session": "לונדון"}
CHECK_EXITS = [(2.0, 0.5, 48), (1.0, 2.0, 24), (1.0, 2.0, 48), (1.0, 3.0, 48), (0.75, 2.0, 24),
               (0.75, 3.0, 48), (1.5, 2.0, 48), (0.5, 3.0, 48)]


def check_rule(tl: pd.DataFrame, cost: float, holdout_months: int, spec: dict = RULE4) -> str:
    dev_end = tl["t"].max() - pd.DateOffset(months=holdout_months)
    S = Searcher.__new__(Searcher)
    tl = tl.reset_index(drop=True)
    S.t = tl["t"]
    S.dev = (S.t < dev_end).to_numpy()
    F = features(tl)
    S.names = list(F.columns)
    S.X = F.to_numpy(dtype=np.float32)
    S.thr = np.nanquantile(S.X[S.dev], QS, axis=0)
    S.ny_min = tl["ny_min"].to_numpy()
    dev_t = S.t[S.dev].astype("int64").to_numpy()
    S.fold_edges = np.quantile(dev_t, np.linspace(0, 1, 5))
    S.t_int = S.t.astype("int64").to_numpy()
    S.dev_days = tl.loc[S.dev, "session"].nunique()
    S.hold_days = tl.loc[~S.dev, "session"].nunique()
    S.excess, S._base = False, {}
    conds = [(S.names.index(f), QS.index(q), above) for f, q, above in spec["conds"]]
    thr_txt = ", ".join(f"{f} {'>' if a else '<'} {S.thr[QS.index(q), S.names.index(f)]:.3f}" for f, q, a in spec["conds"])
    lines = [f"### 🔬 בדיקת חוק 4 עם יחסי סיכון/סיכוי שונים", f"תנאים: {thr_txt} · "
             f"{'שורט' if spec['dir'] == -1 else 'לונג'} · {spec['session']}", "",
             "| סטופ (ATR) | יעד (R) | זמן | חיפוש: עסקאות/יום · הצלחה · ממוצע R · t · 4 תקופות | כספת: עסקאות · הצלחה · ממוצע R · סה\"כ · t |",
             "|---|---|---|---|---|"]
    for sl, rr, hold in CHECK_EXITS:
        S.R = [outcomes(tl, cost, sl, rr, hold)]
        rule = {"conds": conds, "dir": spec["dir"], "session": spec["session"], "exit": 0}
        d, h = S.evaluate(rule), S.evaluate(rule, "hold")
        ds = (f"{d['per_day']:.1f} · {d['win']:.0f}% · {d['avg']:+.3f} · {d['t']:+.1f} · "
              + "/".join(f"{x:+.0f}" for x in d["folds"])) if d else "מעט מדי"
        hs = f"{h['n']} · {h['win']:.0f}% · {h['avg']:+.3f} · {h['sum']:+.1f}R · {h['t']:+.1f}" if h else "מעט מדי"
        lines.append(f"| {sl} | {rr} | {hold * 5} דק' | {ds} | {hs} |")
    return "\n".join(lines)
