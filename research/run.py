"""מעבדת מחקר: מריצה שיטות מועמדות על היסטוריה ארוכה של XAU/USD ומדווחת ביצועים אחרי עלויות.

python -m research.run --months 24 --cost 0.35 [--only liq,orb_ny]
החלוקה: 70% הראשונים = in-sample (פיתוח), 30% האחרונים = out-of-sample (מבחן עיוור).
"""
import argparse
import datetime as dt
import json
import math
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from app.analysis import build_frames, build_timeline, enrich, TIMEFRAMES
from app.config import Settings
from app.data import MarketData, resample
from research import duka, histdata
from research.features import extra_features
from research.strategies import candidates


def build(m1: pd.DataFrame) -> pd.DataFrame:
    m5 = resample(m1, "5min")
    md = MarketData(m5=m5, h1=resample(m1, "1h"), symbol="XAU/USD", source="dukascopy")
    enriched = {tf: enrich(df, TIMEFRAMES[tf]) for tf, df in build_frames(md).items()}
    tl = build_timeline(enriched)
    return tl.merge(extra_features(m5), on="t", how="left")


def simulate(rows: list[dict], make) -> list[dict]:
    strat, trades = make(), []
    for row in rows:
        for ev in strat.on_bar(row):
            if ev["type"] == "closed":
                trades.append(ev["trade"])
    return trades


def stats(trades: list[dict], cost: float, days: float) -> dict:
    if not trades:
        return {"n": 0}
    net = np.array([t["result_r"] - cost / abs(t["entry"] - t["sl"]) for t in trades])
    eq = net.cumsum()
    win, loss = net[net > 0].sum(), -net[net < 0].sum()
    sd = net.std(ddof=1) if len(net) > 1 else 0
    return {"n": len(net), "per_day": round(len(net) / days, 2), "win": round(100 * (net > 0).mean(), 1),
            "net_r": round(net.sum(), 1), "avg_r": round(net.mean(), 3),
            "pf": round(win / loss, 2) if loss else None,
            "dd": round(float((np.maximum.accumulate(np.maximum(eq, 0)) - eq).max()), 1),
            "t": round(net.mean() / sd * math.sqrt(len(net)), 2) if sd else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--cost", type=float, default=0.35, help="ספרד+עמלה+החלקה לעסקה, בדולרים לאונקיה")
    ap.add_argument("--only", default="")
    ap.add_argument("--cache", default="research/cache")
    ap.add_argument("--scan", action="store_true", help="גם סריקת דפוסים")
    ap.add_argument("--ml", action="store_true", help="גם מודל למידת מכונה בהליכה קדימה")
    ap.add_argument("--search", type=int, default=0, help="חיפוש אוטומטי של N חוקים (עם כספת וביקורת)")
    ap.add_argument("--kmax", type=int, default=3)
    ap.add_argument("--minday", type=float, default=1.0)
    ap.add_argument("--holdout", type=int, default=4, help="חודשי כספת")
    ap.add_argument("--excess", action="store_true", help="ציון מעבר לכיוון הכללי של השוק")
    ap.add_argument("--check", action="store_true", help="בדיקת חוק 4 עם יציאות שונות")
    ap.add_argument("--channel", default="", help="ערוץ טלגרם ציבורי לבדיקת הסיגנלים שלו")
    ap.add_argument("--pair", default="XAUUSD", help="נכס ב-HistData (למשל NSXUSD = נאסד\"ק 100)")
    ap.add_argument("--all", action="store_true", help="כל המבחנים (פתיחה, שעות, נזילות, כל היום) על 2018 עד היום")
    ap.add_argument("--allday", action="store_true", help="סבב 8: שיטות כל היום על 2018 עד היום")
    ap.add_argument("--liq9", action="store_true", help="סבב 7: שיטות נזילות על 2018 עד היום")
    ap.add_argument("--day", action="store_true", help="סבב 6: שיטות לשעות היום על 2018 עד היום")
    ap.add_argument("--reopen", action="store_true", help="סבב 5: לונג בפתיחה היומית (על הישן ועל החדש)")
    ap.add_argument("--old", default="", help="סבב 4: שנה התחלתית למבחן על היסטוריה ישנה (למשל 2018)")
    ap.add_argument("--loop3", action="store_true", help="סבב 3: הטיית שעה בשעון ניו יורק")
    ap.add_argument("--loop2", action="store_true", help="סבב 2: hour/rsi2/mom/donch")
    ap.add_argument("--loop", action="store_true", help="לולאת חיפוש FVG-retest עם כספת וביקורת יומית")
    ap.add_argument("--fvg", action="store_true", help="GoldSmartMoneyStrategy (קוד FVG של המשתמש)")
    ap.add_argument("--pullback", action="store_true", help="GoldPullbackStrategy (קוד backtrader של המשתמש)")
    ap.add_argument("--source", default="histdata", choices=["histdata", "duka"])
    a = ap.parse_args()

    end = dt.date.today() - dt.timedelta(days=1)
    start = (pd.Timestamp(end) - pd.DateOffset(months=a.months)).date()
    t0 = time.time()
    if a.channel:
        from research import channel
        print(channel.report(a.channel, Path(a.cache)), flush=True)
        return
    if a.pair != "XAUUSD" and a.cost == 0.35:
        a.cost = {"NSXUSD": 1.5, "SPXUSD": 0.5, "XAGUSD": 0.02}.get(a.pair, a.cost)
    if a.all:
        from research import allday, daytime, liq9, reopen
        full = histdata.fetch_minutes(dt.date(int(a.old or 2018), 1, 1), end, Path(a.cache), pair=a.pair)
        full = full[~full.index.duplicated()].sort_index()
        print(f"{a.pair}: {len(full):,} דקות, {full.index[0]:%Y-%m} - {full.index[-1]:%Y-%m}, עלות {a.cost} ({time.time() - t0:.0f}s)\n", flush=True)
        split = pd.Timestamp(start, tz="UTC")
        print(reopen.report(full[full.index < split], a.cost, f"{a.pair} · לפני השנתיים"), flush=True)
        print("\n" + reopen.report(full[full.index >= split], a.cost, f"{a.pair} · השנתיים האחרונות"), flush=True)
        for mod in (daytime, liq9, allday):
            try:
                print("\n" + mod.report(full, a.cost), flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"\n{mod.__name__} נכשל: {e!r}", flush=True)
        return
    if a.old:
        from research import oldcheck
        old_end = start - dt.timedelta(days=1)
        old = histdata.fetch_minutes(dt.date(int(a.old), 1, 1), old_end, Path(a.cache))
        old = old[old.index < pd.Timestamp(old_end, tz="UTC")]
        print(f"היסטוריה ישנה: {len(old):,} דקות ({time.time() - t0:.0f}s)", flush=True)
        if a.day or a.liq9 or a.allday:
            from research import allday, daytime, liq9
            recent = histdata.fetch_minutes(start, end, Path(a.cache))
            full = pd.concat([old, recent[recent.index >= pd.Timestamp(old_end, tz="UTC")]])
            full = full[~full.index.duplicated()].sort_index()
            print((allday if a.allday else liq9 if a.liq9 else daytime).report(full, a.cost), flush=True)
            return
        if a.reopen:
            from research import reopen
            print(reopen.report(old, a.cost, "היסטוריה שלא נראתה"), flush=True)
            recent = histdata.fetch_minutes(start, end, Path(a.cache))
            print("\n" + reopen.report(recent, a.cost, "השנתיים האחרונות"), flush=True)
            return
        print(oldcheck.report(old, a.cost), flush=True)
        return
    print(f"מוריד נתונים {start} - {end}", flush=True)
    m1 = (histdata if a.source == "histdata" else duka).fetch_minutes(start, end, Path(a.cache))
    print(f"{len(m1):,} דקות, {m1.index[0]} - {m1.index[-1]} ({time.time() - t0:.0f}s)", flush=True)
    table = build(m1)
    rows = table.to_dict("records")
    split = rows[int(len(rows) * 0.7)]["t"]
    total_days = (rows[-1]["t"] - rows[0]["t"]).days * 5 / 7
    print(f"טבלה: {len(rows):,} נרות 5M · פיצול IS/OOS: {split:%Y-%m-%d} ({time.time() - t0:.0f}s)\n", flush=True)

    cfg = Settings()
    results = {}
    for name, make in candidates(cfg).items():
        if a.only and name not in a.only.split(","):
            continue
        tr = simulate(rows, make)
        is_tr = [t for t in tr if pd.Timestamp(t["opened_at"]) < split]
        oos_tr = [t for t in tr if pd.Timestamp(t["opened_at"]) >= split]
        edges = [rows[int(len(rows) * k / 4)]["t"] for k in range(4)] + [rows[-1]["t"] + pd.Timedelta("5min")]
        folds = []
        for k in range(4):
            part = [t for t in tr if edges[k] <= pd.Timestamp(t["opened_at"]) < edges[k + 1]]
            folds.append(stats(part, a.cost, 1).get("net_r", 0.0))
        results[name] = {"folds": folds, "all": stats(tr, a.cost, total_days), "is": stats(is_tr, a.cost, total_days * 0.7),
                         "oos": stats(oos_tr, a.cost, total_days * 0.3),
                         "cost": {c: stats(tr, c, total_days).get("net_r") for c in (0.2, 0.5, 0.7)}}
        print(f"  {name}: {len(tr)} עסקאות ({time.time() - t0:.0f}s)", flush=True)

    head = "| שיטה | עסקאות | ליום | הצלחה | R נטו | ממוצע | PF | DD | t | IS R | IS PF | OOS R | OOS PF | OOS t | 4 תקופות (R) |"
    lines = [f"### תוצאות {start} - {end} · עלות {a.cost}$ לעסקה", "", head, "|" + "---|" * 15]
    for name, r in results.items():
        s, i, o = r["all"], r["is"], r["oos"]
        if not s["n"]:
            lines.append(f"| {name} | 0 |" + " |" * 12)
            continue
        lines.append(f"| {name} | {s['n']} | {s['per_day']} | {s['win']}% | {s['net_r']} | {s['avg_r']} | {s['pf']} | "
                     f"{s['dd']} | {s['t']} | {i.get('net_r')} | {i.get('pf')} | {o.get('net_r')} | {o.get('pf')} | {o.get('t')} | "
                     + " / ".join(f"{x:+.1f}" for x in r["folds"]) + " |")
    if a.pullback:
        from research import pullback
        from research.null import shuffle_within_hour
        lines += ["", pullback.report(m1, a.cost, shuffle_within_hour)]
    if a.loop3:
        from research import loop3
        lines += ["", loop3.report(m1, a.cost, a.holdout)]
    if a.loop2:
        from research import loop2
        lines += ["", loop2.report(m1, a.cost, a.holdout)]
    if a.loop:
        from research import loop
        lines += ["", loop.report(m1, a.cost, a.holdout)]
    if a.fvg:
        from research import fvg_user
        from research.null import shuffle_within_hour
        lines += ["", fvg_user.report(m1, a.cost, shuffle_within_hour)]
    if a.check:
        from research import search
        lines += ["", search.check_rule(table, a.cost, a.holdout)]
    if a.search:
        from research import search
        from research.null import shuffle_within_hour
        nulls = [build(shuffle_within_hour(m1, s)) for s in (1, 2, 3, 4)]
        lines += ["", search.run(table, nulls, a.cost, a.holdout, a.search, a.kmax, a.minday, a.excess)]
    if a.ml:
        from research import ml
        from research.null import shuffle_within_hour
        txt, _ = ml.report(table, a.cost, "🤖 מודל למידת מכונה - הליכה קדימה (אימון רק על העבר, בדיקה על החודש הבא)")
        print("  ml real done", flush=True)
        txt0, _ = ml.report(build(shuffle_within_hour(m1, 1)), a.cost, "🎲 אותו מודל על מחירים מעורבבים (ביקורת)")
        lines += ["", txt, "", txt0]
    if a.scan:
        from research.null import shuffle_within_hour
        null_rows = build(shuffle_within_hour(m1, 1)).to_dict("records")
        lines += ["", "### ביקורת לשיטות הנזילות (אותן שיטות על נתונים מעורבבים)", "",
                  "| שיטה | עסקאות | R נטו | t |", "|---|---|---|---|"]
        for name, make in candidates(cfg).items():
            if not name.startswith("liq") or (a.only and name not in a.only.split(",")):
                continue
            s0 = stats(simulate(null_rows, make), a.cost, total_days)
            lines.append(f"| {name} | {s0.get('n', 0)} | {s0.get('net_r')} | {s0.get('t')} |")
        from research import events
        res = events.search(table, split, a.cost)
        real_best = []
        lines += ["", events.report(res, total_days * 0.3), "", events.families_report(table, a.cost, out=real_best)]
        from research.null import shuffle_within_hour
        null_t, null_pass = [], []
        for seed in (1, 2, 3):
            nt = build(shuffle_within_hour(m1, seed))
            nb = []
            events.families_report(nt, a.cost, out=nb)
            null_t.append(max(t for _, t, _, _ in nb))
            nres = events.search(nt, split, a.cost)
            null_pass.append(sum(1 for x in nres if x["oos"].get("n", 0) >= 20 and x["is"]["t"] > 2.5
                                 and x["oos"]["avg"] > 0 and x["oos"]["t"] > 1.5))
            print(f"  null seed {seed}: best family t={null_t[-1]:+.1f}, events passed={null_pass[-1]}", flush=True)
        top = max(t for _, t, _, _ in real_best)
        lines += ["", f"### קבוצת ביקורת (נתונים מעורבבים, 3 הרצות)",
                  f"- t הכי גבוה של משפחה בביקורת: {', '.join(f'{x:+.1f}' for x in null_t)} · בנתונים האמיתיים: {top:+.1f}",
                  f"- אירועים שעברו בביקורת: {null_pass} (צריך להיות 0 כדי לסמוך על המבחן)"]
    lines += ["", "**רגישות לעלות (R נטו בעלות 0.20$ / 0.50$ / 0.70$ לעסקה):** " +
              "; ".join(f"{n}: " + " / ".join(f"{v}" for v in r["cost"].values()) for n, r in results.items())]
    report = "\n".join(lines)
    print("\n" + report + "\nRESULTS_JSON " + json.dumps(results, ensure_ascii=False), flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(report)


if __name__ == "__main__":
    main()
