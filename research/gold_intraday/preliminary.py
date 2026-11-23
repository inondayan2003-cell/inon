"""Preliminary intraday comparison on whatever minute data is available (possibly non-contiguous).

    python -m research.gold_intraday.preliminary M1_CACHE_DIR [OUT_MD]

Each contiguous chunk of data is run on its own (indicators never span a data gap). The first
WARMUP_DAYS of each chunk are warm-up (4H EMA 200 needs ~33 trading days) and are not evaluated.
No parameter is fitted here: every variant runs with the same fixed inputs; the score threshold is
shown at several levels side by side. This is NOT the walk-forward test (that needs >= 15 months).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from research.gold4h.duka_minutes import load
from research.gold_intraday.backtest import HEAD, VARIANTS, frame, metrics, row, trading_days
from research.gold_intraday.engine import Frames, IParams, run

WARMUP_DAYS = 40
SCORES = (60, 65, 70, 75, 80)


def chunks(m1: pd.DataFrame, gap_days: int = 10):
    cut = np.where(np.diff(m1.index.values).astype("timedelta64[D]").astype(int) > gap_days)[0]
    edges = [0] + list(cut + 1) + [len(m1)]
    return [m1.iloc[a:b] for a, b in zip(edges, edges[1:]) if b - a > 0]


def main():
    m1 = load(Path(sys.argv[1]))
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    parts = chunks(m1)
    L = ["# Preliminary intraday comparison (NOT walk-forward)", ""]
    windows = []
    for c in parts:
        a = c.index[0] + pd.Timedelta(days=WARMUP_DAYS)
        b = c.index[-1] + pd.Timedelta(minutes=1)
        if a < b:
            windows.append((c, a, b))
            L.append(f"* chunk {c.index[0]:%Y-%m-%d} .. {c.index[-1]:%Y-%m-%d}: evaluated from {a:%Y-%m-%d}, "
                     f"{trading_days(m1, a, b)} trading days")
    days = sum(trading_days(m1, a, b) for _, a, b in windows)
    L += ["", f"Evaluated trading days in total: {days}. Costs: spread 0.02% of price + 0.10$ slippage per round trip; "
          "exits resolved on 1-minute bars (stop first if a minute bar touches both).", ""]

    res = {}
    for v in VARIANTS:
        for s in SCORES + (0,):
            frames = []
            for c, a, b in windows:
                d = frame(run(Frames(c), IParams(variant=v, min_score=s)))
                frames.append(d[(d.time >= a) & (d.time < b)])
            res[(v, s)] = pd.concat(frames)
            print(v, s, len(res[(v, s)]), flush=True)

    L.append("## 1. The three variants at the required minimum score 70\n")
    L.append(HEAD)
    for v, name in VARIANTS.items():
        L.append(row(name, metrics(res[(v, 70)], days)))
    L.append("")
    L.append("## 2. Every score threshold (how many trades per day exist at each quality level)\n")
    L.append(HEAD)
    for v in VARIANTS:
        for s in SCORES:
            L.append(row(f"{v} score>={s}", metrics(res[(v, s)], days)))
    L.append("")
    L.append("## 3. Is the score predictive? Expectancy by score bucket (min score 0, one trade at a time)\n")
    L.append("| Variant | <50 | 50-59 | 60-69 | 70-79 | 80+ |\n|---|---|---|---|---|---|")
    for v in VARIANTS:
        d = res[(v, 0)]
        cells = []
        for lo, hi in ((0, 50), (50, 60), (60, 70), (70, 80), (80, 101)):
            g = d[(d.score >= lo) & (d.score < hi)]
            cells.append(f"{g.r.mean():+.3f} (n={len(g)})" if len(g) else "-")
        L.append(f"| {v} | " + " | ".join(cells) + " |")
    L.append("")
    for v, name in VARIANTS.items():
        d = res[(v, 70)]
        if d.empty:
            continue
        L.append(f"## Breakdown at score 70: {name}\n")
        L.append(HEAD)
        L.append(row("LONG", metrics(d[d.dir == 1], days)))
        L.append(row("SHORT", metrics(d[d.dir == -1], days)))
        L.append("")
        for label, key in (("New York hour of entry", d.ny.dt.hour), ("Weekday (New York)", d.ny.dt.day_name()),
                           ("Month", d.ny.dt.strftime("%Y-%m"))):
            g = d.groupby(key)["r"].agg(["count", "mean", "sum", lambda x: (x > 0).mean() * 100])
            g.columns = ["trades", "expectancy R", "net R", "win %"]
            if label.startswith("Weekday"):
                g = g.reindex([x for x in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"] if x in g.index])
            L.append(f"**{label}**\n")
            L.append(g.to_markdown(floatfmt=".2f"))
            L.append("")
    text = "\n".join(L) + "\n"
    if out:
        out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
