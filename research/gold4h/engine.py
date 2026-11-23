"""Reference implementation of the Ultimate Gold (XAUUSD 4H) system.

This file mirrors, bar for bar, the logic in tradingview/Ultimate_Gold_*.pine so that the
Pine scripts and the Python backtest use the same entry and exit rules.

Conventions (identical to the Pine code):
  * Every decision is taken on a CLOSED bar. Entry price = close of the signal bar.
  * Swing pivots use `swing_len` bars on each side and become known only `swing_len` bars
    after the pivot bar (no look-ahead).
  * Exits start on the bar AFTER entry. Stop/target in force on a bar are the ones set at the
    previous bar's close. Stop advancement (1R -> BE, 2R -> +1R) is decided at bar close.
  * If a bar (or a 1H sub-bar when the magnifier is on) touches both stop and target, the stop
    is assumed to be hit first (conservative). A gap through the stop fills at the open.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------- parameters
@dataclass(frozen=True)
class Params:
    ema_fast: int = 50
    ema_slow: int = 200
    rsi_len: int = 14
    adx_len: int = 14
    atr_len: int = 14
    swing_len: int = 5             # pivot strength (bars each side)
    eq_tol_atr: float = 0.10       # equal highs/lows tolerance, in ATR
    max_pools: int = 10            # liquidity levels kept per side
    sweep_lookback: int = 20       # a sweep counts if it happened within this many bars
    struct_window: int = 12        # entry must come within N bars of the BOS/CHOCH
    fvg_min_atr: float = 0.10      # minimum FVG size, in ATR
    fvg_max_age: int = 60
    ob_lookback: int = 10
    ob_max_age: int = 100
    rsi_long_min: float = 40.0
    rsi_long_max: float = 70.0
    rsi_short_min: float = 30.0
    rsi_short_max: float = 60.0
    adx_min: float = 20.0
    range_len: int = 50            # dealing range for premium / discount
    sl_buffer_atr: float = 0.30    # ATR multiplier for the safety buffer beyond structure
    min_stop_atr: float = 0.75
    max_stop_atr: float = 3.00
    rr: float = 3.0
    min_score: int = 70
    trend_filter: str = "none"     # none | ema | structure | both
    require_sweep: bool = False
    stop_management: bool = True
    cost: float = 0.50             # round-trip spread + commission + slippage, price units
    # weights (sum = 100)
    w_trend: int = 15
    w_sweep: int = 20
    w_struct: int = 15
    w_fvg: int = 15
    w_ob: int = 10
    w_rsi: int = 5
    w_adx: int = 10
    w_zone: int = 10


# ----------------------------------------------------------------------------- indicators (Pine-equivalent)
def rma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    vals = x[~np.isnan(x)]
    start = np.argmax(~np.isnan(x))
    if len(vals) < n:
        return out
    out[start + n - 1] = np.mean(x[start:start + n])
    a = 1.0 / n
    for i in range(start + n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = np.mean(x[:n])
    a = 2.0 / (n + 1)
    for i in range(n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def indicators(df: pd.DataFrame, p: Params) -> dict[str, np.ndarray]:
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    pc = np.r_[np.nan, c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    tr[0] = h[0] - l[0]
    chg = np.r_[np.nan, np.diff(c)]
    up = rma(np.where(np.isnan(chg), np.nan, np.maximum(chg, 0)), p.rsi_len)
    dn = rma(np.where(np.isnan(chg), np.nan, np.maximum(-chg, 0)), p.rsi_len)
    rsi = np.where(dn == 0, 100.0, np.where(up == 0, 0.0, 100 - 100 / (1 + up / np.where(dn == 0, 1, dn))))
    ph, pl = np.r_[np.nan, h[:-1]], np.r_[np.nan, l[:-1]]
    upm, dnm = h - ph, pl - l
    plus_dm = np.where((upm > dnm) & (upm > 0), upm, 0.0)
    minus_dm = np.where((dnm > upm) & (dnm > 0), dnm, 0.0)
    plus_dm[0] = minus_dm[0] = np.nan
    trur = rma(np.where(np.arange(len(tr)) == 0, np.nan, tr), p.adx_len)
    pdi = 100 * rma(plus_dm, p.adx_len) / trur
    mdi = 100 * rma(minus_dm, p.adx_len) / trur
    s = pdi + mdi
    dx = 100 * np.abs(pdi - mdi) / np.where(s == 0, 1, s)
    adx = rma(dx, p.adx_len)
    return dict(o=o, h=h, l=l, c=c, atr=rma(tr, p.atr_len), rsi=rsi, adx=adx,
                ema_f=ema(c, p.ema_fast), ema_s=ema(c, p.ema_slow))


# ----------------------------------------------------------------------------- data structures
@dataclass
class Zone:
    top: float
    bottom: float
    bar: int
    bull: bool


@dataclass
class Pool:
    price: float
    bar: int
    equal: bool = False


@dataclass
class Trade:
    direction: int
    entry_bar: int
    entry_time: pd.Timestamp
    entry: float
    stop0: float
    tp: float
    score: int
    stop: float = 0.0
    stage: int = 0
    exit_bar: int = -1
    exit_time: pd.Timestamp | None = None
    exit: float = np.nan
    status: str = "ACTIVE"
    r_gross: float = np.nan
    r_net: float = np.nan
    parts: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- engine
def run(df4: pd.DataFrame, p: Params, sub: pd.DataFrame | None = None, keep_parts: bool = False) -> list[Trade]:
    """Run the system on 4H bars. `sub` (optional 1H bars) resolves intrabar exit order."""
    d = indicators(df4, p)
    o, h, l, c, atr, rsi, adx, ef, es = (d[k] for k in ("o", "h", "l", "c", "atr", "rsi", "adx", "ema_f", "ema_s"))
    n = len(c)
    times = df4.index
    L = p.swing_len

    # 1H sub-bars grouped by their 4H bar
    sub_groups = None
    if sub is not None:
        pos = np.searchsorted(times.values, sub.index.values, side="right") - 1
        sub_groups = {}
        so, sh_, sl_ = sub["open"].to_numpy(), sub["high"].to_numpy(), sub["low"].to_numpy()
        for k in range(len(sub)):
            if pos[k] >= 0:
                sub_groups.setdefault(pos[k], []).append((so[k], sh_[k], sl_[k]))

    hh = pd.Series(h).rolling(p.range_len).max().to_numpy()
    ll = pd.Series(l).rolling(p.range_len).min().to_numpy()

    sh1 = sh2 = sl1 = sl2 = np.nan
    sh_broken = sl_broken = True
    ms_trend = 0
    bull_break_bar = bear_break_bar = -10**9
    bull_break_choch = bear_break_choch = False
    high_pools: list[Pool] = []
    low_pools: list[Pool] = []
    bull_sweep_bar = bear_sweep_bar = -10**9
    bull_sweep_eq = bear_sweep_eq = False
    bull_sweep_px = bear_sweep_px = np.nan
    fvgs: list[Zone] = []
    obs: list[Zone] = []
    trades: list[Trade] = []
    tr: Trade | None = None
    warm = max(p.ema_slow, 2 * L + 1, p.range_len, 3 * p.adx_len)

    for i in range(n):
        a = atr[i]
        # ---------- 1. pivots (confirmed L bars after the pivot bar)
        if i >= 2 * L:
            cbar = i - L
            left_h, right_h = h[i - 2 * L:cbar].max(), h[cbar + 1:i + 1].max()
            left_l, right_l = l[i - 2 * L:cbar].min(), l[cbar + 1:i + 1].min()
            if h[cbar] > left_h and h[cbar] >= right_h:
                sh2, sh1, sh_broken = sh1, h[cbar], False
                _add_pool(high_pools, h[cbar], cbar, a, p, high=True)
            if l[cbar] < left_l and l[cbar] <= right_l:
                sl2, sl1, sl_broken = sl1, l[cbar], False
                _add_pool(low_pools, l[cbar], cbar, a, p, high=False)

        # ---------- 2. structure breaks (close beyond last unbroken swing)
        if not sh_broken and not np.isnan(sh1) and c[i] > sh1:
            sh_broken = True
            bull_break_choch = ms_trend == -1
            ms_trend, bull_break_bar = 1, i
            for k in range(1, p.ob_lookback + 1):
                if i - k >= 0 and c[i - k] < o[i - k]:
                    obs.append(Zone(h[i - k], l[i - k], i, True))
                    break
        if not sl_broken and not np.isnan(sl1) and c[i] < sl1:
            sl_broken = True
            bear_break_choch = ms_trend == 1
            ms_trend, bear_break_bar = -1, i
            for k in range(1, p.ob_lookback + 1):
                if i - k >= 0 and c[i - k] > o[i - k]:
                    obs.append(Zone(h[i - k], l[i - k], i, False))
                    break

        # ---------- 3. liquidity sweeps
        for pool in list(low_pools):
            if l[i] < pool.price:
                if c[i] > pool.price:
                    if bull_sweep_bar != i:
                        bull_sweep_eq = False
                        bull_sweep_px = l[i]
                    bull_sweep_bar = i
                    bull_sweep_eq = bull_sweep_eq or pool.equal
                low_pools.remove(pool)
        for pool in list(high_pools):
            if h[i] > pool.price:
                if c[i] < pool.price:
                    if bear_sweep_bar != i:
                        bear_sweep_eq = False
                        bear_sweep_px = h[i]
                    bear_sweep_bar = i
                    bear_sweep_eq = bear_sweep_eq or pool.equal
                high_pools.remove(pool)
        # a close beyond the sweep extreme cancels the sweep
        if bull_sweep_bar > -10**9 and c[i] < bull_sweep_px:
            bull_sweep_bar = -10**9
        if bear_sweep_bar > -10**9 and c[i] > bear_sweep_px:
            bear_sweep_bar = -10**9

        # ---------- 4. trade management (bar i, using stop/target set at the previous close)
        if tr is not None and i > tr.entry_bar:
            parts = sub_groups.get(i, [(o[i], h[i], l[i])]) if sub_groups is not None else [(o[i], h[i], l[i])]
            for so_, sh_k, sl_k in parts:
                px = _exit_price(tr, so_, sh_k, sl_k)
                if px is not None:
                    _close(tr, i, times[i], px, p)
                    trades.append(tr)
                    tr = None
                    break
            if tr is not None and p.stop_management:
                risk = abs(tr.entry - tr.stop0)
                fav = (h[i] - tr.entry) if tr.direction == 1 else (tr.entry - l[i])
                if fav >= 2 * risk and tr.stage < 2:
                    tr.stage, new = 2, tr.entry + tr.direction * risk
                    tr.stop = max(tr.stop, new) if tr.direction == 1 else min(tr.stop, new)
                elif fav >= risk and tr.stage < 1:
                    tr.stage, new = 1, tr.entry
                    tr.stop = max(tr.stop, new) if tr.direction == 1 else min(tr.stop, new)

        # ---------- 5. signal (needs warm-up and no open trade)
        if i >= warm and tr is None and not np.isnan(a):
            sig = None
            for direction in (1, -1):
                s = _evaluate(direction, i, d, p, fvgs, obs, ms_trend, sh1, sh2, sl1, sl2,
                              bull_break_bar, bear_break_bar, bull_break_choch, bear_break_choch,
                              bull_sweep_bar, bear_sweep_bar, bull_sweep_eq, bear_sweep_eq, hh, ll)
                if s is not None:
                    sig = None if sig is not None else s  # both directions valid -> skip
            if sig is not None:
                direction, score, stop, used, parts_ = sig
                risk = abs(c[i] - stop)
                tr = Trade(direction, i, times[i], c[i], stop, c[i] + direction * p.rr * risk, score, stop=stop,
                           parts=parts_ if keep_parts else {})
                for z in used:  # a zone triggers at most one trade
                    lst = fvgs if any(z is x for x in fvgs) else obs
                    lst[:] = [x for x in lst if x is not z]

        # ---------- 6. FVG creation / maintenance (after the signal so the new gap is not retested on its own bar)
        for z in list(fvgs):
            if z.bull and (l[i] <= z.bottom or c[i] < z.bottom) and z.bar < i:
                fvgs.remove(z)
            elif not z.bull and (h[i] >= z.top or c[i] > z.top) and z.bar < i:
                fvgs.remove(z)
            elif i - z.bar > p.fvg_max_age:
                fvgs.remove(z)
        for z in list(obs):
            if z.bar < i and ((z.bull and c[i] < z.bottom) or (not z.bull and c[i] > z.top) or i - z.bar > p.ob_max_age):
                obs.remove(z)
        if i >= 2 and not np.isnan(a):
            if l[i] > h[i - 2] and l[i] - h[i - 2] >= p.fvg_min_atr * a:
                fvgs.append(Zone(l[i], h[i - 2], i, True))
            if h[i] < l[i - 2] and l[i - 2] - h[i] >= p.fvg_min_atr * a:
                fvgs.append(Zone(l[i - 2], h[i], i, False))

    if tr is not None:
        trades.append(tr)  # still open at the end of data (excluded from statistics)
    return trades


def _add_pool(pools: list[Pool], price: float, bar: int, a: float, p: Params, high: bool):
    tol = p.eq_tol_atr * (a if not np.isnan(a) else 0)
    for pool in pools:
        if abs(pool.price - price) <= tol:
            pool.equal = True
            pool.price = max(pool.price, price) if high else min(pool.price, price)
            pool.bar = bar
            return
    pools.append(Pool(price, bar))
    if len(pools) > p.max_pools:
        pools.pop(0)


def _evaluate(direction, i, d, p, fvgs, obs, ms_trend, sh1, sh2, sl1, sl2, bull_break_bar, bear_break_bar,
              bull_choch, bear_choch, bull_sweep_bar, bear_sweep_bar, bull_sweep_eq, bear_sweep_eq, hh, ll):
    o, h, l, c, atr, rsi, adx, ef, es = (d[k] for k in ("o", "h", "l", "c", "atr", "rsi", "adx", "ema_f", "ema_s"))
    a = atr[i]
    bull = direction == 1
    # structure: a break in this direction within struct_window bars, not reversed since
    brk = bull_break_bar if bull else bear_break_bar
    if ms_trend != direction or i - brk > p.struct_window:
        return None
    # candle confirmation
    if (bull and not c[i] > o[i]) or (not bull and not c[i] < o[i]):
        return None
    # retest of an FVG / Order Block of this direction created before this bar
    def touched(z: Zone) -> bool:
        if z.bull != bull or z.bar >= i:
            return False
        return (l[i] <= z.top and c[i] > z.bottom) if bull else (h[i] >= z.bottom and c[i] < z.top)
    fvg_hit = [z for z in fvgs if touched(z)]
    ob_hit = [z for z in obs if touched(z)]
    if not fvg_hit and not ob_hit:
        return None
    used = fvg_hit[-1:] + ob_hit[-1:]

    ema_ok = (ef[i] > es[i]) if bull else (ef[i] < es[i])
    struct_ok = (sh1 > sh2 and sl1 > sl2) if bull else (sh1 < sh2 and sl1 < sl2)
    if p.trend_filter in ("ema", "both") and not ema_ok:
        return None
    if p.trend_filter in ("structure", "both") and not struct_ok:
        return None
    sweep_bar = bull_sweep_bar if bull else bear_sweep_bar
    sweep = i - sweep_bar <= p.sweep_lookback
    if p.require_sweep and not sweep:
        return None
    sweep_eq = bull_sweep_eq if bull else bear_sweep_eq
    choch = bull_choch if bull else bear_choch

    parts = {
        "trend": (p.w_trend * 8 // 15 if ema_ok else 0) + (p.w_trend - p.w_trend * 8 // 15 if struct_ok else 0),
        "sweep": (p.w_sweep if sweep_eq else p.w_sweep * 3 // 4) if sweep else 0,
        "struct": p.w_struct if choch else p.w_struct * 4 // 5,
        "fvg": p.w_fvg if fvg_hit else 0,
        "ob": p.w_ob if ob_hit else 0,
        "rsi": p.w_rsi if ((p.rsi_long_min <= rsi[i] <= p.rsi_long_max) if bull
                           else (p.rsi_short_min <= rsi[i] <= p.rsi_short_max)) else 0,
        "adx": p.w_adx if adx[i] >= p.adx_min else (p.w_adx // 2 if adx[i] >= 0.75 * p.adx_min else 0),
    }
    zone_top = max(z.top for z in used)
    zone_bot = min(z.bottom for z in used)
    mid = (hh[i] + ll[i]) / 2
    discount = c[i] < mid if bull else c[i] > mid
    rejection = c[i] > zone_top if bull else c[i] < zone_bot
    parts["zone"] = (p.w_zone // 2 if discount else 0) + (p.w_zone - p.w_zone // 2 if rejection else 0)
    score = int(sum(parts.values()))
    if score < p.min_score:
        return None

    # stop: beyond the structural invalidation (zone / signal candle) + ATR buffer
    if bull:
        stop = min(l[i], zone_bot) - p.sl_buffer_atr * a
        stop = min(stop, c[i] - p.min_stop_atr * a)
        if c[i] - stop > p.max_stop_atr * a:
            return None
    else:
        stop = max(h[i], zone_top) + p.sl_buffer_atr * a
        stop = max(stop, c[i] + p.min_stop_atr * a)
        if stop - c[i] > p.max_stop_atr * a:
            return None
    return direction, score, stop, used, parts


def _exit_price(tr: Trade, op: float, hi: float, lo: float):
    if tr.direction == 1:
        if op <= tr.stop:
            return op                    # gap through stop
        if op >= tr.tp:
            return op                    # gap through target
        if lo <= tr.stop:
            return tr.stop               # stop first if both are inside the bar
        if hi >= tr.tp:
            return tr.tp
    else:
        if op >= tr.stop:
            return op
        if op <= tr.tp:
            return op
        if hi >= tr.stop:
            return tr.stop
        if lo <= tr.tp:
            return tr.tp
    return None


def _close(tr: Trade, i: int, t, px: float, p: Params):
    risk = abs(tr.entry - tr.stop0)
    tr.exit_bar, tr.exit_time, tr.exit = i, t, px
    tr.r_gross = tr.direction * (px - tr.entry) / risk
    tr.r_net = tr.r_gross - p.cost / risk
    hit_tp = (px >= tr.tp) if tr.direction == 1 else (px <= tr.tp)
    if hit_tp:
        tr.status = "TP HIT"
    elif tr.stage == 0:
        tr.status = "SL HIT"
    elif tr.stage == 1:
        tr.status = "BREAK EVEN"
    else:
        tr.status = "PROFIT PROTECTED"


# ----------------------------------------------------------------------------- data helpers
def to_4h(h1: pd.DataFrame) -> pd.DataFrame:
    """Resample UTC 1H bars into 4H bars aligned like TradingView forex charts
    (sessions start 17:00 New York; bars at 17,21,01,05,09,13 NY)."""
    ny = h1.tz_convert("America/New_York")
    agg = ny.resample("4h", offset="1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    agg = agg.dropna(subset=["open"])
    return agg.tz_convert("UTC")


def stats(trades: list[Trade]) -> dict:
    closed = [t for t in trades if t.exit_bar >= 0]
    r = np.array([t.r_net for t in closed])
    if len(r) == 0:
        return dict(trades=0)
    eq = np.cumsum(r)
    dd = np.max(np.maximum.accumulate(np.r_[0, eq]) - np.r_[0, eq])
    wins, losses = r[r > 0], r[r <= 0]
    gp, gl = wins.sum(), -losses.sum()
    return dict(
        trades=len(r), wins=int((r > 0).sum()), losses=int((r <= 0).sum()),
        win_rate=float((r > 0).mean() * 100), pf=float(gp / gl) if gl > 0 else float("inf"),
        net_r=float(r.sum()), avg_r=float(r.mean()), max_dd_r=float(dd),
        avg_win=float(wins.mean()) if len(wins) else 0.0, avg_loss=float(losses.mean()) if len(losses) else 0.0,
        tp=sum(t.status == "TP HIT" for t in closed), sl=sum(t.status == "SL HIT" for t in closed),
        be=sum(t.status == "BREAK EVEN" for t in closed), pp=sum(t.status == "PROFIT PROTECTED" for t in closed),
        longs=sum(t.direction == 1 for t in closed), shorts=sum(t.direction == -1 for t in closed),
        t_stat=float(r.mean() / r.std(ddof=1) * np.sqrt(len(r))) if len(r) > 1 else 0.0,
    )
