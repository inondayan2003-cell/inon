"""מנוע אירועים: כל דפוס נבדק כעסקה (סטופ/יעד ביחידות ATR, יציאה בזמן), עם בחירת פרמטרים
ב-IS בלבד ובדיקה עיוורת ב-OOS. סטופ נבדק לפני יעד באותו נר (הנחה שמרנית)."""
import itertools

import numpy as np
import pandas as pd

SL = (0.75, 1.0, 1.5, 2.0)          # סטופ ביחידות ATR של 15M
RR = (0.33, 0.5, 0.75, 1.0, 1.5)    # יעד כמכפלה של הסטופ (0.5 = יעד בחצי מרחק הסטופ -> אחוז הצלחה גבוה)
HOLD = (12, 24, 48)                  # יציאה בזמן: 1/2/4 שעות


def _first(s: pd.Series, session: pd.Series) -> pd.Series:
    """True רק בפעם הראשונה ביום המסחר."""
    return s & ~s.groupby(session).transform(lambda x: x.shift(fill_value=False).cummax())


def define_events(tl: pd.DataFrame) -> dict[str, tuple[pd.Series, int]]:
    ev = {}
    m, ses = tl["ny_min"], tl["session"]
    for h in range(24):
        ev[f"hour{h:02d}_long"] = (m == h * 60, 1)
        ev[f"hour{h:02d}_short"] = (m == h * 60, -1)
    for name, col in (("orblon", "orblon_low"), ("lon", "lon_low"), ("asia", "asia_low"), ("pd", "pdl"), ("orbny", "orbny_low")):
        below = _first(tl["close"] < tl[col], ses)
        ev[f"{name}_lowbreak_fade_long"] = (below, 1)
        ev[f"{name}_lowbreak_follow_short"] = (below, -1)
    for name, col in (("orblon", "orblon_high"), ("lon", "lon_high"), ("asia", "asia_high"), ("pd", "pdh"), ("orbny", "orbny_high")):
        above = _first(tl["close"] > tl[col], ses)
        ev[f"{name}_highbreak_follow_long"] = (above, 1)
        ev[f"{name}_highbreak_fade_short"] = (above, -1)
    for name, col, d in (("pdl", "pdl", 1), ("asl", "asia_low", 1), ("ldl", "lon_low", 1),
                         ("pdh", "pdh", -1), ("ash", "asia_high", -1), ("ldh", "lon_high", -1)):
        lvl = tl[col]
        crossed = (tl["low"] < lvl) if d == 1 else (tl["high"] > lvl)
        back = _first(crossed, ses) & ((tl["close"] - lvl) * d > 0)
        ev[f"{name}_sweep_reclaim"] = (back, d)
    body = (tl["close"] - tl["open"]) / tl["atr_5m"]
    ev["bigup_follow_long"] = (body > 1.5, 1)
    ev["bigup_fade_short"] = (body > 1.5, -1)
    ev["bigdown_fade_long"] = (body < -1.5, 1)
    ev["bigdown_follow_short"] = (body < -1.5, -1)
    return ev


def simulate(tl: pd.DataFrame, mask: pd.Series, d: int, cost: float):
    """מחזיר פונקציה (sl, rr, hold) -> מערך תוצאות R נטו לכל עסקה, ואת זמני הכניסה."""
    idx = np.flatnonzero(mask.to_numpy() & tl["atr_15m"].notna().to_numpy())
    n = len(tl)
    idx = idx[idx + max(HOLD) < n]
    hi, lo, cl = (tl[c].to_numpy() for c in ("high", "low", "close"))
    atr = tl["atr_15m"].to_numpy()[idx]
    entry = cl[idx]
    win = np.arange(1, max(HOLD) + 1)
    H, L, C = hi[idx[:, None] + win], lo[idx[:, None] + win], cl[idx[:, None] + win]
    fav, adv = (H, L) if d == 1 else (-L, -H)
    e = entry if d == 1 else -entry

    def run(sl, rr, hold):
        dist = sl * atr
        stop_hit = adv[:, :hold] <= (e - dist)[:, None]
        tp_hit = fav[:, :hold] >= (e + rr * dist)[:, None]
        big = hold + 1
        s_i = np.where(stop_hit.any(1), stop_hit.argmax(1), big)
        t_i = np.where(tp_hit.any(1), tp_hit.argmax(1), big)
        timed = (C[:, hold - 1] - entry) * d / dist
        r = np.where(s_i <= t_i, np.where(s_i < big, -1.0, timed), rr)
        return r - cost / dist

    return run, tl["t"].to_numpy(dtype="datetime64[ns]")[idx]


def _stats(r: np.ndarray) -> dict:
    if len(r) < 2:
        return {"n": len(r)}
    win, loss = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": len(r), "win": 100 * (r > 0).mean(), "avg": r.mean(), "sum": r.sum(),
            "pf": win / loss if loss else np.inf, "t": r.mean() / r.std(ddof=1) * np.sqrt(len(r))}


def search(tl: pd.DataFrame, split, cost: float, min_is: int = 60):
    tl = tl.reset_index(drop=True)
    results = []
    for name, (mask, d) in define_events(tl).items():
        run, times = simulate(tl, mask, d, cost)
        is_m = times < np.datetime64(pd.Timestamp(split).tz_convert(None))
        if is_m.sum() < min_is:
            continue
        best = None
        for sl, rr, hold in itertools.product(SL, RR, HOLD):
            r = run(sl, rr, hold)
            s = _stats(r[is_m])
            if best is None or s["avg"] > best[0]["avg"]:
                best = (s, (sl, rr, hold), r)
        s_is, params, r = best
        s_oos = _stats(r[~is_m])
        results.append({"event": name, "params": params, "is": s_is, "oos": s_oos, "r": r, "times": times, "is_m": is_m})
    return results


def report(results: list[dict], days_oos: float) -> str:
    rows = sorted(results, key=lambda x: -x["is"]["avg"])
    out = ["### מנוע אירועים - פרמטרים נבחרו ב-IS בלבד; OOS = מבחן עיוור", "",
           "| אירוע | סטופ/יעד/זמן | IS n | IS הצלחה | IS ממוצע R | IS t | OOS n | OOS הצלחה | OOS ממוצע R | OOS PF | OOS t | עבר? |",
           "|" + "---|" * 12]
    passed = []
    for x in rows:
        i, o = x["is"], x["oos"]
        if o.get("n", 0) < 20:
            continue
        # מחמירים: נבחרו הכי טובים מ-60 שילובים ב-IS, אז דורשים t גבוה, ו-OOS מובהק בעצמו
        ok = i["t"] > 2.5 and o["avg"] > 0 and o["t"] > 1.5
        if ok:
            passed.append(x)
        out.append(f"| {x['event']} | {x['params'][0]}/{x['params'][1]}/{x['params'][2]} | {i['n']} | {i['win']:.0f}% | "
                   f"{i['avg']:+.3f} | {i['t']:+.1f} | {o['n']} | {o['win']:.0f}% | {o['avg']:+.3f} | {o['pf']:.2f} | "
                   f"{o['t']:+.1f} | {'✅' if ok else ''} |")
    if passed:
        oos_r = np.concatenate([x["r"][~x["is_m"]] for x in passed])
        s = _stats(oos_r)
        out += ["", f"**תיק של {len(passed)} האירועים שעברו - OOS:** {s['n']} עסקאות ({s['n'] / days_oos:.1f} ליום), "
                    f"הצלחה {s['win']:.0f}%, ממוצע {s['avg']:+.3f}R, סה\"כ {s['sum']:+.1f}R, PF {s['pf']:.2f}, t {s['t']:+.1f}"]
    else:
        out += ["", "**אף אירוע לא עבר את המבחן העיוור.**"]
    return "\n".join(out)


# ---------- משפחות דפוסים עם פרמטרים קבועים, ובדיקת יציבות על 4 תקופות ----------
FAMILIES = {
    "fade_lon": ["lon_highbreak_fade_short", "lon_lowbreak_fade_long"],
    "fade_orblon": ["orblon_highbreak_fade_short", "orblon_lowbreak_fade_long"],
    "fade_asia": ["asia_highbreak_fade_short", "asia_lowbreak_fade_long"],
    "fade_pd": ["pd_highbreak_fade_short", "pd_lowbreak_fade_long"],
    "fade_orbny": ["orbny_highbreak_fade_short", "orbny_lowbreak_fade_long"],
    "sweeps": ["pdl_sweep_reclaim", "asl_sweep_reclaim", "ldl_sweep_reclaim",
               "pdh_sweep_reclaim", "ash_sweep_reclaim", "ldh_sweep_reclaim"],
    "follow_lon": ["lon_highbreak_follow_long", "lon_lowbreak_follow_short"],
    "follow_asia": ["asia_highbreak_follow_long", "asia_lowbreak_follow_short"],
}
FAMILIES["fade_lon+sweeps"] = FAMILIES["fade_lon"] + FAMILIES["sweeps"]
FAMILIES["fade_all"] = (FAMILIES["fade_lon"] + FAMILIES["fade_orblon"] + FAMILIES["fade_asia"]
                        + FAMILIES["fade_pd"] + FAMILIES["fade_orbny"])
PARAM_SETS = [(1.5, 1.5, 24), (1.5, 1.0, 24), (1.5, 0.5, 24), (2.0, 0.5, 48), (1.0, 1.0, 24), (1.0, 2.0, 48), (2.0, 0.33, 48)]


def families_report(tl: pd.DataFrame, cost: float, folds: int = 4, out: list | None = None) -> str:
    tl = tl.reset_index(drop=True)
    evs = define_events(tl)
    t_all = tl["t"].to_numpy(dtype="datetime64[ns]")
    edges = np.quantile(t_all.astype("int64"), np.linspace(0, 1, folds + 1)).astype("datetime64[ns]")
    days = (t_all[-1] - t_all[0]).astype("timedelta64[D]").astype(int) * 5 / 7
    sims = {name: simulate(tl, *evs[name], cost) for name in {e for f in FAMILIES.values() for e in f}}
    lines = ["### משפחות דפוסים - פרמטרים קבועים (בלי אופטימיזציה), יציבות על פני 4 תקופות", "",
             "| משפחה | סטופ/יעד/זמן | עסקאות | ליום | הצלחה | ממוצע R | PF | t | ת1 | ת2 | ת3 | ת4 | חיוביות |",
             "|" + "---|" * 13]
    best = []
    for fam, names in FAMILIES.items():
        for sl, rr, hold in PARAM_SETS:
            rs, ts = [], []
            for nm in names:
                run, times = sims[nm]
                rs.append(run(sl, rr, hold))
                ts.append(times)
            r, ts = np.concatenate(rs), np.concatenate(ts)
            if len(r) < 50:
                continue
            s = _stats(r)
            fold_avg = []
            for k in range(folds):
                sel = (ts >= edges[k]) & (ts <= edges[k + 1])
                fold_avg.append(r[sel].mean() if sel.any() else np.nan)
            pos = sum(x > 0 for x in fold_avg)
            best.append((pos, s["t"], fam, (sl, rr, hold)))
            lines.append(f"| {fam} | {sl}/{rr}/{hold} | {s['n']} | {s['n'] / days:.2f} | {s['win']:.0f}% | {s['avg']:+.3f} | "
                         f"{s['pf']:.2f} | {s['t']:+.1f} | " + " | ".join(f"{x:+.2f}" for x in fold_avg) + f" | {pos}/{folds} |")
    best.sort(reverse=True)
    if out is not None:
        out.extend(best)
    lines += ["", "**הכי יציבות (מס' תקופות חיוביות, ואז t):** " +
              "; ".join(f"{f} {p[0]}/{p[1]}/{p[2]} ({pos}/4, t={t:+.1f})" for pos, t, f, p in best[:5])]
    return "\n".join(lines)
