"""Backtest of the Ultimate Gold 4H system on Dukascopy XAUUSD data.

    python -m research.gold4h.backtest CACHE_DIR [OUT_MD]

* In-sample (IS):      2010-01 .. 2019-12   (variations are compared here only)
* Out-of-sample (OOS): 2020-01 .. end       (looked at once per configuration, never used to pick)
* Results are in R (1R = initial risk), net of a round-trip cost (spread + commission + slippage).
* Exit order inside a bar is resolved with 1H sub-bars ("magnifier"); if a 1H bar touches both
  stop and target the stop is taken first. "4H-only" = the same rule on the whole 4H bar
  (this is exactly what the TradingView indicator does).
"""
from __future__ import annotations

import itertools
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from research.gold4h.engine import Params, Trade, run, stats, to_4h

IS_END = pd.Timestamp("2020-01-01", tz="UTC")


def load(cache: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    files = sorted(cache.glob("BID_*.parquet"))
    h1 = pd.concat(pd.read_parquet(f) for f in files).sort_index()
    h1 = h1[~h1.index.duplicated()]
    return h1, to_4h(h1)


def split(trades: list[Trade]):
    closed = [t for t in trades if t.exit_bar >= 0]
    return ([t for t in closed if t.entry_time < IS_END], [t for t in closed if t.entry_time >= IS_END])


def fmt_stats(s: dict) -> str:
    if not s.get("trades"):
        return "| 0 | - | - | - | - | - | - | - |"
    return (f"| {s['trades']} | {s['win_rate']:.1f}% | {s['pf']:.2f} | {s['net_r']:+.1f}R | {s['max_dd_r']:.1f}R "
            f"| {s['avg_r']:+.3f}R | {s['t_stat']:.2f} | {s['tp']}/{s['sl']}/{s['be']}/{s['pp']} |")


HDR = "| Trades | Win rate | PF | Net | Max DD | Expectancy/trade | t | TP/SL/BE/+1R |\n|---|---|---|---|---|---|---|---|"


def yearly(trades: list[Trade]) -> str:
    rows = ["| Year | Trades | Win rate | Net R | PF |", "|---|---|---|---|---|"]
    df = pd.DataFrame([(t.entry_time.year, t.r_net) for t in trades if t.exit_bar >= 0], columns=["y", "r"])
    for y, g in df.groupby("y"):
        w, l = g.r[g.r > 0].sum(), -g.r[g.r <= 0].sum()
        rows.append(f"| {y} | {len(g)} | {(g.r > 0).mean()*100:.0f}% | {g.r.sum():+.1f} | {w/l if l else float('inf'):.2f} |")
    return "\n".join(rows)


def random_baseline(df4: pd.DataFrame, h1: pd.DataFrame, base: Params, trades: list[Trade], seeds: int = 200) -> dict:
    """Null test: same number of trades, same direction mix, same stop distance in ATR, same
    management, but entries on random bars. Tells whether the setups beat chance."""
    from research.gold4h.engine import indicators, _exit_price, _close
    d = indicators(df4, base)
    c, o, h, l, a = d["c"], d["o"], d["h"], d["l"], d["atr"]
    closed = [t for t in trades if t.exit_bar >= 0]
    stop_atr = np.array([abs(t.entry - t.stop0) / a[t.entry_bar] for t in closed])
    dirs = np.array([t.direction for t in closed])
    rng = np.random.default_rng(7)
    n = len(c)
    nets = []
    for _ in range(seeds):
        bars = np.sort(rng.choice(np.arange(250, n - 200), size=len(closed), replace=False))
        total = []
        for b, sd, dr in zip(bars, rng.permutation(stop_atr), rng.permutation(dirs)):
            risk = sd * a[b]
            t = Trade(int(dr), b, df4.index[b], c[b], c[b] - dr * risk, c[b] + dr * base.rr * risk, 0, stop=c[b] - dr * risk)
            for i in range(b + 1, min(n, b + 400)):
                px = _exit_price(t, o[i], h[i], l[i])
                if px is not None:
                    _close(t, i, df4.index[i], px, base)
                    break
                fav = (h[i] - t.entry) if dr == 1 else (t.entry - l[i])
                if fav >= 2 * risk and t.stage < 2:
                    t.stage, t.stop = 2, t.entry + dr * risk
                elif fav >= risk and t.stage < 1:
                    t.stage, t.stop = 1, t.entry
            if t.exit_bar >= 0:
                total.append(t.r_net)
        nets.append(np.sum(total))
    nets = np.array(nets)
    real = sum(t.r_net for t in closed)
    return dict(real=real, mean=nets.mean(), p95=np.percentile(nets, 95), pct_better=(nets >= real).mean() * 100)


def main():
    cache = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    h1, df4 = load(cache)
    lines = [f"Data: Dukascopy XAUUSD BID, {h1.index[0]:%Y-%m-%d} .. {h1.index[-1]:%Y-%m-%d}, "
             f"{len(h1):,} 1H bars -> {len(df4):,} 4H bars (TradingView-style 4H alignment, sessions from 17:00 New York).", ""]
    base = Params()

    def block(title, trades):
        a, b = split(trades)
        lines.extend([f"### {title}", "", "| Period " + HDR.split("\n")[0], "|---" + HDR.split("\n")[1],
                      "| In-sample 2010-2019 " + fmt_stats(stats(a)),
                      "| Out-of-sample 2020-2026 " + fmt_stats(stats(b)),
                      "| All " + fmt_stats(stats(a + b)), ""])
        return a, b

    print("baseline ...", flush=True)
    tr_mag = run(df4, base, sub=h1)
    tr_4h = run(df4, base)
    lines.append("## 1. Baseline (default inputs, the values shipped in the Pine scripts)\n")
    block("Baseline, 1H magnifier (stop first when a 1H bar hits both)", tr_mag)
    block("Baseline, 4H only (= TradingView indicator logic)", tr_4h)
    a, b = split(tr_mag)
    block("Baseline LONG only", [t for t in tr_mag if t.direction == 1])
    block("Baseline SHORT only", [t for t in tr_mag if t.direction == -1])
    for cost in (0.30, 1.00):
        block(f"Baseline with cost {cost:.2f}$ per round trip", run(df4, replace(base, cost=cost), sub=h1))
    block("Baseline WITHOUT stop management (fixed SL, TP 3R)", run(df4, replace(base, stop_management=False), sub=h1))
    lines += ["### Baseline per year (1H magnifier)", "", yearly(tr_mag), ""]

    print("random baseline ...", flush=True)
    rb = random_baseline(df4, h1, base, tr_4h)
    lines += ["### Null test: random entries with the same count, direction mix, stop size and management (4H-only exits, 200 runs)", "",
              f"Strategy net {rb['real']:+.1f}R; random mean {rb['mean']:+.1f}R; random 95th percentile {rb['p95']:+.1f}R; "
              f"share of random runs at least as good: {rb['pct_better']:.1f}%.", ""]

    # ---------------- one-at-a-time sensitivity
    print("sensitivity ...", flush=True)
    lines.append("## 2. One-at-a-time variations (each row changes one input; all others at default)\n")
    lines.append("| Variation | IS trades | IS PF | IS net R | IS exp. | OOS trades | OOS PF | OOS net R | OOS exp. |\n|---|---|---|---|---|---|---|---|---|")
    variations = [("default", {})]
    variations += [(f"RSI long {lo}-{hi} / short {100-hi}-{100-lo}", dict(rsi_long_min=lo, rsi_long_max=hi, rsi_short_min=100 - hi, rsi_short_max=100 - lo))
                   for lo, hi in ((30, 80), (45, 65), (50, 70))]
    variations += [(f"ADX min {x}", dict(adx_min=x)) for x in (15, 25, 30)]
    variations += [(f"ATR stop buffer {x}", dict(sl_buffer_atr=x)) for x in (0.0, 0.5, 1.0)]
    variations += [(f"Min stop {x} ATR", dict(min_stop_atr=x)) for x in (0.5, 1.0, 1.5)]
    variations += [(f"Min score {x}", dict(min_score=x)) for x in (60, 65, 75, 80, 85)]
    variations += [("Require sweep", dict(require_sweep=True))]
    variations += [(f"Trend filter {x}", dict(trend_filter=x)) for x in ("ema", "structure", "both")]
    variations += [(f"Swing length {x}", dict(swing_len=x)) for x in (3, 4, 7, 10)]
    variations += [(f"Struct window {x}", dict(struct_window=x)) for x in (6, 24)]
    variations += [(f"Max stop {x} ATR", dict(max_stop_atr=x)) for x in (2.0, 4.0)]
    sens = []
    for name, kw in variations:
        a, b = split(run(df4, replace(base, **kw), sub=h1))
        sa, sb = stats(a), stats(b)
        sens.append((name, sa, sb))
        g = lambda s, k, f: (f.format(s[k]) if s.get("trades") else "-")
        lines.append(f"| {name} | {sa.get('trades', 0)} | {g(sa,'pf','{:.2f}')} | {g(sa,'net_r','{:+.1f}')} | {g(sa,'avg_r','{:+.3f}')} "
                     f"| {sb.get('trades', 0)} | {g(sb,'pf','{:.2f}')} | {g(sb,'net_r','{:+.1f}')} | {g(sb,'avg_r','{:+.3f}')} |")
    lines.append("")

    # ---------------- small grid, selected on IS only
    print("grid ...", flush=True)
    grid = list(itertools.product((60, 65, 70, 75, 80), (15, 20, 25), (0.0, 0.3, 0.6), ("none", "ema"), (False, True)))
    rows = []
    for ms, adx, buf, tf, sw in grid:
        p = replace(base, min_score=ms, adx_min=adx, sl_buffer_atr=buf, trend_filter=tf, require_sweep=sw)
        a, b = split(run(df4, p, sub=h1))
        sa, sb = stats(a), stats(b)
        rows.append(dict(min_score=ms, adx=adx, buf=buf, trend=tf, sweep=sw,
                         is_n=sa.get("trades", 0), is_exp=sa.get("avg_r", np.nan), is_pf=sa.get("pf", np.nan), is_net=sa.get("net_r", 0),
                         oos_n=sb.get("trades", 0), oos_exp=sb.get("avg_r", np.nan), oos_pf=sb.get("pf", np.nan), oos_net=sb.get("net_r", 0)))
    g = pd.DataFrame(rows)
    ok = g[g.is_n >= 40].copy()
    lines.append(f"## 3. Grid of {len(g)} combinations (min score x ADX min x ATR buffer x EMA filter x sweep required)\n")
    lines.append(f"* Share of combinations with positive IS expectancy: {(g.is_exp > 0).mean()*100:.0f}%; positive OOS expectancy: {(g.oos_exp > 0).mean()*100:.0f}%.")
    lines.append(f"* Correlation of IS and OOS expectancy across combinations: {g[['is_exp','oos_exp']].corr().iloc[0,1]:.2f}.")
    if len(ok):
        best = ok.sort_values("is_exp", ascending=False).head(10)
        lines.append("\nTop 10 by IS expectancy (min 40 IS trades) and what they did out of sample:\n")
        lines.append(best.to_markdown(index=False, floatfmt=".3f"))
    lines.append("")
    if out:
        out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    g.to_csv(cache / "grid.csv", index=False)


if __name__ == "__main__":
    main()
