"""Intraday backtest: three entry variants, walk-forward score calibration, breakdowns.

    python -m research.gold_intraday.backtest M1_CACHE_DIR [OUT_MD]

Everything is in R (1R = initial risk), net of costs: spread 0.02% of price round trip (measured on
Dukascopy: ~0.35$ in 2021, ~0.63$ in 2026) + 0.10$ slippage. Exits resolved on 1-minute bars.

Walk-forward: train 12 months -> test the next 3 months, rolled every 3 months. In each fold the
minimum score is chosen on the TRAIN window only (highest expectancy with >= MIN_TRAIN_TRADES trades),
then applied unchanged to the TEST window. The concatenated test windows are the walk-forward result.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from research.gold4h.duka_minutes import load
from research.gold_intraday.engine import Frames, IParams, run

VARIANTS = {"15m": "A: entry on 15M", "5m_15m": "B: entry on 5M, direction from 15M",
            "5m_htf": "C: entry on 5M, 4H + 1H trend filter"}
SCORES = (60, 65, 70, 75, 80)
MIN_TRAIN_TRADES = 30


def frame(trades) -> pd.DataFrame:
    rows = [(t.entry_time, t.direction, t.r_net, t.status, t.score) for t in trades if t.exit_time is not None]
    df = pd.DataFrame(rows, columns=["time", "dir", "r", "status", "score"])
    df["ny"] = df["time"].dt.tz_convert("America/New_York")
    return df


def metrics(df: pd.DataFrame, days: int) -> dict:
    if df.empty:
        return dict(n=0)
    r = df["r"].to_numpy()
    eq = np.cumsum(r)
    gl = -r[r <= 0].sum()
    months = max(days / 21.0, 1e-9)
    return dict(n=len(r), per_day=len(r) / max(days, 1), per_month=len(r) / months, win=(r > 0).mean() * 100,
                pf=r[r > 0].sum() / gl if gl > 0 else np.inf, exp=r.mean(), net=r.sum(),
                dd=np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq]),
                t=r.mean() / r.std(ddof=1) * np.sqrt(len(r)) if len(r) > 1 else 0.0,
                tp=(df.status == "TP HIT").sum(), sl=(df.status == "SL HIT").sum(), be=(df.status == "BREAK EVEN").sum(),
                pp=(df.status == "PROFIT PROTECTED").sum(), sess=(df.status == "SESSION CLOSE").sum())


HEAD = ("| | Trades | per day | per month | Win % | PF | Expectancy | Net R | Max DD R | t | TP/SL/BE/+1R/EOD |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|")


def row(name, m):
    if not m.get("n"):
        return f"| {name} | 0 | 0 | 0 | - | - | - | - | - | - | - |"
    return (f"| {name} | {m['n']} | {m['per_day']:.2f} | {m['per_month']:.1f} | {m['win']:.1f} | {m['pf']:.2f} | "
            f"{m['exp']:+.3f} | {m['net']:+.1f} | {m['dd']:.1f} | {m['t']:.2f} | "
            f"{m['tp']}/{m['sl']}/{m['be']}/{m['pp']}/{m['sess']} |")


def trading_days(m1: pd.DataFrame, a, b) -> int:
    ny = m1.index[(m1.index >= a) & (m1.index < b)].tz_convert("America/New_York")
    return int(pd.Index((ny - pd.Timedelta(hours=17)).normalize()).nunique())


def main():
    cache_dir = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    m1 = load(cache_dir)
    fr = Frames(m1)
    t0, t1 = m1.index[0], m1.index[-1]
    L = [f"Data: Dukascopy XAUUSD BID 1-minute, {t0:%Y-%m-%d} .. {t1:%Y-%m-%d}, {len(m1):,} bars, "
         f"{trading_days(m1, t0, t1 + pd.Timedelta(minutes=1))} trading days.", ""]
    cache = {}
    runs = {}
    for v in VARIANTS:
        for s in SCORES + (0,):
            print("run", v, s, flush=True)
            runs[(v, s)] = frame(run(fr, IParams(variant=v, min_score=s), cache=cache))

    # ---------------- walk-forward
    first_test = (t0 + pd.DateOffset(months=12)).to_period("Q").start_time.tz_localize("UTC")
    if first_test < t0 + pd.DateOffset(months=12):
        first_test += pd.DateOffset(months=3)
    folds = []
    ts = first_test
    while ts < t1:
        folds.append((ts - pd.DateOffset(months=12), ts, min(ts + pd.DateOffset(months=3), t1 + pd.Timedelta(minutes=1))))
        ts += pd.DateOffset(months=3)
    wf_days = trading_days(m1, folds[0][1], folds[-1][2])
    L.append(f"## 1. Walk-forward (train 12 months -> test 3 months, {len(folds)} folds, test period "
             f"{folds[0][1]:%Y-%m-%d} .. {folds[-1][2]:%Y-%m-%d}, {wf_days} trading days)\n")
    L.append("Minimum score chosen per fold on the training window only, from " + ", ".join(map(str, SCORES)) +
             f" (highest training expectancy with at least {MIN_TRAIN_TRADES} trades; otherwise 70).\n")
    L.append(HEAD)
    wf = {}
    chosen = {}
    for v, name in VARIANTS.items():
        parts, picks = [], []
        for a, b, e in folds:
            best, best_exp = 70, -np.inf
            for s in SCORES:
                d = runs[(v, s)]
                tr = d[(d.time >= a) & (d.time < b)]
                if len(tr) >= MIN_TRAIN_TRADES and tr.r.mean() > best_exp:
                    best, best_exp = s, tr.r.mean()
            d = runs[(v, best)]
            parts.append(d[(d.time >= b) & (d.time < e)])
            picks.append(best)
        wf[v] = pd.concat(parts)
        chosen[v] = picks
        L.append(row(name + " (walk-forward)", metrics(wf[v], wf_days)))
    L.append("")
    for v, name in VARIANTS.items():
        L.append(f"* {name}: chosen min score per fold: {', '.join(map(str, chosen[v]))}")
    L.append("")

    # ---------------- fixed score 70 over the same test period
    L.append(f"## 2. Fixed minimum score 70 (no calibration), same period as the walk-forward tests\n")
    L.append(HEAD)
    a, e = folds[0][1], folds[-1][2]
    for v, name in VARIANTS.items():
        d = runs[(v, 70)]
        L.append(row(name, metrics(d[(d.time >= a) & (d.time < e)], wf_days)))
    L.append("")
    L.append("### Every fixed score over the same period (for transparency, NOT used for selection)\n")
    L.append(HEAD)
    for v, name in VARIANTS.items():
        for s in SCORES:
            d = runs[(v, s)]
            L.append(row(f"{v} score>={s}", metrics(d[(d.time >= a) & (d.time < e)], wf_days)))
    L.append("")

    # ---------------- does the score predict anything? (all candidates, score >= 0)
    L.append("## 3. Is the score predictive? Expectancy by score bucket (min score 0, whole data, one trade at a time)\n")
    L.append("| Variant | <50 | 50-59 | 60-69 | 70-79 | 80+ |\n|---|---|---|---|---|---|")
    for v in VARIANTS:
        d = runs[(v, 0)]
        cells = []
        for lo, hi in ((0, 50), (50, 60), (60, 70), (70, 80), (80, 101)):
            g = d[(d.score >= lo) & (d.score < hi)]
            cells.append(f"{g.r.mean():+.3f} (n={len(g)})" if len(g) else "-")
        L.append(f"| {v} | " + " | ".join(cells) + " |")
    L.append("")

    # ---------------- breakdowns for each walk-forward variant
    for v, name in VARIANTS.items():
        d = wf[v]
        if d.empty:
            continue
        L.append(f"## Breakdown: {name} (walk-forward test trades)\n")
        L.append(HEAD)
        L.append(row("LONG", metrics(d[d.dir == 1], wf_days)))
        L.append(row("SHORT", metrics(d[d.dir == -1], wf_days)))
        L.append("")
        for label, key in (("New York hour of entry", d.ny.dt.hour), ("Weekday (New York)", d.ny.dt.day_name()),
                           ("Year", d.ny.dt.year)):
            g = d.groupby(key)["r"].agg(["count", "mean", "sum", lambda x: (x > 0).mean() * 100])
            g.columns = ["trades", "expectancy R", "net R", "win %"]
            if label.startswith("Weekday"):
                g = g.reindex([x for x in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] if x in g.index])
            L.append(f"**{label}**\n")
            L.append(g.to_markdown(floatfmt=".2f"))
            L.append("")
        dd = d.copy()
        dd["day"] = (dd.ny - pd.Timedelta(hours=17)).dt.normalize()
        per_day = dd.groupby("day").size().reindex(pd.Index(pd.date_range(dd.day.min(), dd.day.max())), fill_value=0)
        L.append(f"Trades per trading day: days with 0 trades {(per_day == 0).mean()*100:.0f}% (calendar days incl. weekends), "
                 f"max in one day {per_day.max()}.\n")

    # ---------------- cost sensitivity for the variant with the best walk-forward expectancy
    best_v = max(wf, key=lambda v: wf[v].r.mean() if len(wf[v]) else -9)
    L.append(f"## Cost sensitivity ({VARIANTS[best_v]}, score 70, walk-forward test period)\n")
    L.append(HEAD)
    for cp, sl in ((0.0001, 0.05), (0.0002, 0.10), (0.0003, 0.20)):
        d = frame(run(fr, IParams(variant=best_v, cost_pct=cp, slippage=sl), cache=cache))
        L.append(row(f"spread {cp*100:.2f}% + slippage {sl:.2f}$", metrics(d[(d.time >= a) & (d.time < e)], wf_days)))
    d = frame(run(fr, IParams(variant=best_v, stop_management=False), cache=cache))
    L.append(row("no stop management (fixed SL / 3R)", metrics(d[(d.time >= a) & (d.time < e)], wf_days)))
    L.append("")

    text = "\n".join(L) + "\n"
    if out:
        out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
