"""Timeframe-agnostic SMC tracker: swings, BOS/CHOCH, liquidity pools + sweeps, FVG and Order Blocks.

Same rules as the 4H engine (research/gold4h/engine.py), packaged so the intraday engine can run one
tracker per timeframe. Call `pre(i)` and `post(i)` once per CLOSED bar, in order:
  pre(i)  -> pivots confirmed on this bar, structure breaks (+ new OB), liquidity sweeps
  ... caller evaluates entries here (zones created on this bar are not yet visible) ...
  post(i) -> zone invalidation / ageing, then new FVGs from this bar
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

NOBAR = -10**9


@dataclass
class Zone:
    top: float
    bottom: float
    bar: int
    bull: bool
    kind: str  # "FVG" | "OB"


@dataclass
class Pool:
    price: float
    bar: int
    equal: bool = False


class Tracker:
    def __init__(self, o, h, l, c, atr, swing_len=5, eq_tol_atr=0.10, max_pools=10, ob_lookback=10,
                 ob_max_age=100, fvg_min_atr=0.10, fvg_max_age=60):
        self.o, self.h, self.l, self.c, self.atr = o, h, l, c, atr
        self.L, self.eq_tol, self.max_pools = swing_len, eq_tol_atr, max_pools
        self.ob_lookback, self.ob_max_age = ob_lookback, ob_max_age
        self.fvg_min_atr, self.fvg_max_age = fvg_min_atr, fvg_max_age
        self.sh1 = self.sh2 = self.sl1 = self.sl2 = np.nan
        self.sh_broken = self.sl_broken = True
        self.ms_trend = 0
        self.bull_break_bar = self.bear_break_bar = NOBAR
        self.bull_choch = self.bear_choch = False
        self.high_pools: list[Pool] = []
        self.low_pools: list[Pool] = []
        self.bull_sweep_bar = self.bear_sweep_bar = NOBAR
        self.bull_sweep_eq = self.bear_sweep_eq = False
        self.bull_sweep_px = self.bear_sweep_px = np.nan
        self.zones: list[Zone] = []

    # ------------------------------------------------------------------ per bar, before entries
    def pre(self, i: int):
        o, h, l, c, L = self.o, self.h, self.l, self.c, self.L
        a = self.atr[i]
        if i >= 2 * L:
            cb = i - L
            if h[cb] > h[i - 2 * L:cb].max() and h[cb] >= h[cb + 1:i + 1].max():
                self.sh2, self.sh1, self.sh_broken = self.sh1, h[cb], False
                self._add_pool(self.high_pools, h[cb], cb, a, True)
            if l[cb] < l[i - 2 * L:cb].min() and l[cb] <= l[cb + 1:i + 1].min():
                self.sl2, self.sl1, self.sl_broken = self.sl1, l[cb], False
                self._add_pool(self.low_pools, l[cb], cb, a, False)
        if not self.sh_broken and not np.isnan(self.sh1) and c[i] > self.sh1:
            self.sh_broken = True
            self.bull_choch = self.ms_trend == -1
            self.ms_trend, self.bull_break_bar = 1, i
            for k in range(1, self.ob_lookback + 1):
                if i - k >= 0 and c[i - k] < o[i - k]:
                    self.zones.append(Zone(h[i - k], l[i - k], i, True, "OB"))
                    break
        if not self.sl_broken and not np.isnan(self.sl1) and c[i] < self.sl1:
            self.sl_broken = True
            self.bear_choch = self.ms_trend == 1
            self.ms_trend, self.bear_break_bar = -1, i
            for k in range(1, self.ob_lookback + 1):
                if i - k >= 0 and c[i - k] > o[i - k]:
                    self.zones.append(Zone(h[i - k], l[i - k], i, False, "OB"))
                    break
        keep = []
        for p in self.low_pools:
            if l[i] < p.price:
                if c[i] > p.price:
                    if self.bull_sweep_bar != i:
                        self.bull_sweep_eq, self.bull_sweep_px = False, l[i]
                    self.bull_sweep_bar = i
                    self.bull_sweep_eq = self.bull_sweep_eq or p.equal
            else:
                keep.append(p)
        self.low_pools = keep
        keep = []
        for p in self.high_pools:
            if h[i] > p.price:
                if c[i] < p.price:
                    if self.bear_sweep_bar != i:
                        self.bear_sweep_eq, self.bear_sweep_px = False, h[i]
                    self.bear_sweep_bar = i
                    self.bear_sweep_eq = self.bear_sweep_eq or p.equal
            else:
                keep.append(p)
        self.high_pools = keep
        if self.bull_sweep_bar != NOBAR and c[i] < self.bull_sweep_px:
            self.bull_sweep_bar = NOBAR
        if self.bear_sweep_bar != NOBAR and c[i] > self.bear_sweep_px:
            self.bear_sweep_bar = NOBAR

    # ------------------------------------------------------------------ per bar, after entries
    def post(self, i: int):
        h, l, c = self.h, self.l, self.c
        keep = []
        for z in self.zones:
            if z.kind == "FVG":
                dead = z.bar < i and ((z.bull and (l[i] <= z.bottom or c[i] < z.bottom)) or
                                      (not z.bull and (h[i] >= z.top or c[i] > z.top)))
                dead = dead or i - z.bar > self.fvg_max_age
            else:
                dead = z.bar < i and ((z.bull and c[i] < z.bottom) or (not z.bull and c[i] > z.top) or
                                      i - z.bar > self.ob_max_age)
            if not dead:
                keep.append(z)
        self.zones = keep
        a = self.atr[i]
        if i >= 2 and not np.isnan(a):
            if l[i] > h[i - 2] and l[i] - h[i - 2] >= self.fvg_min_atr * a:
                self.zones.append(Zone(l[i], h[i - 2], i, True, "FVG"))
            if h[i] < l[i - 2] and l[i - 2] - h[i] >= self.fvg_min_atr * a:
                self.zones.append(Zone(l[i - 2], h[i], i, False, "FVG"))

    # ------------------------------------------------------------------ helpers
    def touched(self, i: int, bull: bool) -> list[Zone]:
        l, h, c = self.l, self.h, self.c
        return [z for z in self.zones if z.bull == bull and z.bar < i and
                ((l[i] <= z.top and c[i] > z.bottom) if bull else (h[i] >= z.bottom and c[i] < z.top))]

    def remove(self, used: list[Zone]):
        self.zones = [z for z in self.zones if not any(z is u for u in used)]

    def _add_pool(self, pools, price, bar, a, high):
        tol = self.eq_tol * (0 if np.isnan(a) else a)
        for p in pools:
            if abs(p.price - price) <= tol:
                p.equal = True
                p.price = max(p.price, price) if high else min(p.price, price)
                p.bar = bar
                return
        pools.append(Pool(price, bar))
        if len(pools) > self.max_pools:
            pools.pop(0)
