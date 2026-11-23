"""Intraday multi-timeframe version of the Ultimate Gold system (XAUUSD).

  4H  -> trend / bias (EMA 50/200)          1H -> structure, liquidity sweeps, POI zones
  15M -> setup / direction                  5M -> entry confirmation (variants B and C)

Variants (same score, same risk rules, same costs, same data):
  A  "15m":       entries on 15M bars (15M BOS/CHOCH + retest of a 15M FVG/OB + confirmation candle)
  B  "5m_15m":    entries on 5M bars; 15M structure must point the same way (hard filter)
  C  "5m_htf":    as B, plus hard filters: 4H EMA50>EMA200 (short: <) and 1H structure in the same direction

No look-ahead: a higher-timeframe value is used only once that higher-timeframe bar has CLOSED
(its close time <= the OPEN time of the entry bar, like request.security(expr[1], lookahead_on)). Entries at the close of the confirmed entry bar.
Exits are resolved on 1-minute bars (or on the entry bar itself with magnifier=False); if a bar touches
both stop and target the stop is taken.
Stop management (1R -> BE, 2R -> +1R) is decided at entry-bar closes. Open trades are closed at the
last bar before the 17:00 New York daily break (intraday = flat every day).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from research.gold4h.engine import indicators
from research.gold_intraday.smc import NOBAR, Tracker

TF_MIN = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}


@dataclass(frozen=True)
class IParams:
    variant: str = "5m_htf"          # 15m | 5m_15m | 5m_htf
    ema_fast: int = 50
    ema_slow: int = 200
    rsi_len: int = 14
    adx_len: int = 14
    atr_len: int = 14
    swing_len: int = 3               # pivot strength on the entry / setup timeframes
    htf_swing_len: int = 3           # pivot strength on 1H / 4H
    struct_window: int = 12          # entry within N entry bars of the BOS/CHOCH
    sweep_lookback: int = 20         # entry-TF sweep valid for N entry bars
    htf_sweep_bars: int = 8          # 1H sweep valid for N 1H bars
    fvg_min_atr: float = 0.10
    fvg_max_age: int = 60
    ob_max_age: int = 100
    rsi_long_min: float = 40
    rsi_long_max: float = 70
    rsi_short_min: float = 30
    rsi_short_max: float = 60
    adx_min: float = 20
    sl_buffer_atr: float = 0.30
    min_stop_atr: float = 0.75
    max_stop_atr: float = 3.0
    rr: float = 3.0
    min_score: int = 70
    max_trades_day: int = 5
    no_entry_ny_hours: tuple = (15, 16, 17)   # no new entries in the last hours before the daily break
    cost_pct: float = 0.0002         # round-trip spread, fraction of price (measured 0.015-0.02%)
    slippage: float = 0.10           # $ per round trip
    max_cost_r: float = 0.20         # skip trades whose cost exceeds this fraction of the risk
    stop_management: bool = True


@dataclass
class ITrade:
    direction: int
    entry_time: pd.Timestamp
    entry: float
    stop0: float
    tp: float
    score: int
    entry_bar: int
    cost: float
    stop: float = 0.0
    stage: int = 0
    exit_time: pd.Timestamp | None = None
    exit: float = np.nan
    status: str = "ACTIVE"
    r_net: float = np.nan
    parts: dict = field(default_factory=dict)


# ----------------------------------------------------------------------------- data
def resample(m1: pd.DataFrame, tf: str) -> pd.DataFrame:
    ny = m1.tz_convert("America/New_York")
    rule = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}[tf]
    kw = {"offset": "1h"} if tf == "4h" else {}
    out = ny.resample(rule, **kw).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna(subset=["open"]).tz_convert("UTC")


class Frames:
    """All timeframes built once from 1-minute data (shared by every variant / parameter set)."""

    def __init__(self, m1: pd.DataFrame):
        self.m1 = m1
        self.tf = {k: resample(m1, k) for k in ("5m", "15m", "1h", "4h")}
        self.close_time = {k: (v.index + pd.Timedelta(minutes=TF_MIN[k])).values for k, v in self.tf.items()}


def _snapshots(df: pd.DataFrame, p: IParams, swing_len: int, keep_zones: bool):
    """Run a tracker over a whole timeframe and record its state after every closed bar."""
    d = indicators(df, p)
    t = Tracker(d["o"], d["h"], d["l"], d["c"], d["atr"], swing_len=swing_len, fvg_min_atr=p.fvg_min_atr,
                fvg_max_age=p.fvg_max_age, ob_max_age=p.ob_max_age)
    n = len(df)
    ms = np.zeros(n, int)
    bsw = np.full(n, NOBAR)
    ssw = np.full(n, NOBAR)
    zones = [None] * n
    for i in range(n):
        t.pre(i)
        t.post(i)
        ms[i], bsw[i], ssw[i] = t.ms_trend, t.bull_sweep_bar, t.bear_sweep_bar
        if keep_zones:   # most recent still-active zone of each direction: (top, bottom) or None
            zb = next(((z.top, z.bottom) for z in reversed(t.zones) if z.bull), None)
            zs = next(((z.top, z.bottom) for z in reversed(t.zones) if not z.bull), None)
            zones[i] = (zb, zs)
    return dict(ms=ms, bull_sweep=bsw, bear_sweep=ssw, zones=zones,
                ema_bias=np.where(d["ema_f"] > d["ema_s"], 1, np.where(d["ema_f"] < d["ema_s"], -1, 0)))


def _asof(htf_close: np.ndarray, t_close: np.ndarray) -> np.ndarray:
    """Index of the last higher-timeframe bar that is closed at each entry-bar close (-1 = none)."""
    return np.searchsorted(htf_close, t_close, side="right") - 1


# ----------------------------------------------------------------------------- engine
def run(fr: Frames, p: IParams, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
        cache: dict | None = None, keep_parts: bool = False, magnifier: bool = True) -> list[ITrade]:
    """magnifier=True resolves exits on 1-minute bars; False uses the entry bar only (= TradingView indicator)."""
    etf = "15m" if p.variant == "15m" else "5m"
    df = fr.tf[etf]
    d = indicators(df, p)
    o, h, l, c, atr, rsi, adx = (d[k] for k in ("o", "h", "l", "c", "atr", "rsi", "adx"))
    n = len(df)
    times = df.index
    tclose = fr.close_time[etf]

    key = (p.htf_swing_len, p.swing_len, p.fvg_min_atr, p.fvg_max_age, p.ob_max_age, p.ema_fast, p.ema_slow)
    if cache is not None and key in cache:
        s4, s1, s15 = cache[key]
    else:
        s4 = _snapshots(fr.tf["4h"], p, p.htf_swing_len, False)
        s1 = _snapshots(fr.tf["1h"], p, p.htf_swing_len, True)
        s15 = _snapshots(fr.tf["15m"], p, p.swing_len, False)
        if cache is not None:
            cache[key] = (s4, s1, s15)
    # higher-TF bar must have closed by the OPEN of the entry bar (= Pine request.security(expr[1], lookahead_on))
    topen = times.values
    j4 = _asof(fr.close_time["4h"], topen)
    j1 = _asof(fr.close_time["1h"], topen)
    j15 = _asof(fr.close_time["15m"], topen)

    ny = times.tz_convert("America/New_York")
    ny_close = (times + pd.Timedelta(minutes=TF_MIN[etf])).tz_convert("America/New_York")
    trade_day = (ny_close - pd.Timedelta(hours=17)).normalize()          # NY trading day (starts 17:00)
    td = trade_day.values
    last_of_day = np.asarray((ny_close.hour == 17) & (ny_close.minute == 0))   # bar that ends at the 17:00 NY break
    entry_hour_ok = ~np.isin(ny.hour, p.no_entry_ny_hours)

    m1 = fr.m1
    m1_pos = np.searchsorted(times.values, m1.index.values, side="right") - 1
    m1o, m1h, m1l = m1["open"].to_numpy(), m1["high"].to_numpy(), m1["low"].to_numpy()
    starts = np.searchsorted(m1_pos, np.arange(n), side="left")
    ends = np.searchsorted(m1_pos, np.arange(n), side="right")

    hh = pd.Series(h).rolling(48).max().to_numpy()   # dealing range for premium/discount on the entry TF
    ll = pd.Series(l).rolling(48).min().to_numpy()

    tr_e = Tracker(o, h, l, c, atr, swing_len=p.swing_len, fvg_min_atr=p.fvg_min_atr,
                   fvg_max_age=p.fvg_max_age, ob_max_age=p.ob_max_age)
    trades: list[ITrade] = []
    tr: ITrade | None = None
    day_count: dict = {}
    warm = max(p.ema_slow, 50)
    i0 = 0 if start is None else int(np.searchsorted(times.values, np.datetime64(start.tz_convert("UTC").tz_localize(None)), "left"))
    i1 = n if end is None else int(np.searchsorted(times.values, np.datetime64(end.tz_convert("UTC").tz_localize(None)), "left"))

    for i in range(n):
        tr_e.pre(i)
        if tr is not None and i > tr.entry_bar:
            subs = ((m1o[k], m1h[k], m1l[k], m1.index[k]) for k in range(starts[i], ends[i])) if magnifier \
                else [(o[i], h[i], l[i], times[i] + pd.Timedelta(minutes=TF_MIN[etf]))]
            for so, sh, sl, st in subs:
                px = _exit_price(tr, so, sh, sl)
                if px is not None:
                    _close(tr, st, px)
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
                    tr.stage = 1
                    tr.stop = max(tr.stop, tr.entry) if tr.direction == 1 else min(tr.stop, tr.entry)
            if tr is not None and last_of_day[i]:
                _close(tr, times[i] + pd.Timedelta(minutes=TF_MIN[etf]), c[i], session=True)
                trades.append(tr)
                tr = None

        if (tr is None and i >= warm and i0 <= i < i1 and not np.isnan(atr[i]) and entry_hour_ok[i]
                and not last_of_day[i] and day_count.get(td[i], 0) < p.max_trades_day
                and min(j4[i], j1[i], j15[i]) >= 0):
            sig = None
            for direction in (1, -1):
                s = _evaluate(direction, i, p, tr_e, o, h, l, c, atr, rsi, adx, hh, ll,
                              s4, j4[i], s1, j1[i], s15, j15[i])
                if s is not None:
                    sig = None if sig is not None else s
            if sig is not None:
                direction, score, stop, used, parts = sig
                risk = abs(c[i] - stop)
                cost = p.cost_pct * c[i] + p.slippage
                if cost / risk <= p.max_cost_r:
                    tr = ITrade(direction, times[i] + pd.Timedelta(minutes=TF_MIN[etf]), c[i], stop,
                                c[i] + direction * p.rr * risk, score, i, cost, stop=stop,
                                parts=parts if keep_parts else {})
                    day_count[td[i]] = day_count.get(td[i], 0) + 1
                    tr_e.remove(used)
        tr_e.post(i)
    return trades  # a trade still open at the end of data is dropped (never counted)


def _evaluate(direction, i, p, t, o, h, l, c, atr, rsi, adx, hh, ll, s4, j4, s1, j1, s15, j15):
    bull = direction == 1
    a = atr[i]
    brk = t.bull_break_bar if bull else t.bear_break_bar
    if t.ms_trend != direction or i - brk > p.struct_window:
        return None
    if (bull and not c[i] > o[i]) or (not bull and not c[i] < o[i]):
        return None
    hit = t.touched(i, bull)
    if not hit:
        return None
    fvg = [z for z in hit if z.kind == "FVG"][-1:]
    ob = [z for z in hit if z.kind == "OB"][-1:]
    used = fvg + ob

    ema4_ok = s4["ema_bias"][j4] == direction
    ms1_ok = s1["ms"][j1] == direction
    ms15_ok = s15["ms"][j15] == direction
    if p.variant in ("5m_15m", "5m_htf") and not ms15_ok:
        return None
    if p.variant == "5m_htf" and not (ema4_ok and ms1_ok):
        return None

    sw1 = s1["bull_sweep"][j1] if bull else s1["bear_sweep"][j1]
    htf_sweep = j1 - sw1 <= p.htf_sweep_bars
    swe = t.bull_sweep_bar if bull else t.bear_sweep_bar
    ltf_sweep = i - swe <= p.sweep_lookback
    choch = t.bull_choch if bull else t.bear_choch
    zone_top = max(z.top for z in used)
    zone_bot = min(z.bottom for z in used)
    poi = s1["zones"][j1][0 if bull else 1]
    in_poi = poi is not None and l[i] <= poi[0] and h[i] >= poi[1]
    mid = (hh[i] + ll[i]) / 2
    rejection = c[i] > zone_top if bull else c[i] < zone_bot
    parts = {
        "trend": (8 if ema4_ok else 0) + (7 if ms1_ok else 0),
        "sweep": 20 if htf_sweep else (15 if ltf_sweep else 0),
        "struct": 15 if choch else 12,
        "fvg": 15 if fvg else 0,
        "ob": 10 if ob else 0,
        "rsi": 5 if ((p.rsi_long_min <= rsi[i] <= p.rsi_long_max) if bull else (p.rsi_short_min <= rsi[i] <= p.rsi_short_max)) else 0,
        "adx": 10 if adx[i] >= p.adx_min else (5 if adx[i] >= 0.75 * p.adx_min else 0),
        "zone": (5 if (in_poi or ((c[i] < mid) if bull else (c[i] > mid))) else 0) + (5 if rejection else 0),
    }
    score = int(sum(parts.values()))
    if score < p.min_score:
        return None
    if bull:
        stop = min(min(l[i], zone_bot) - p.sl_buffer_atr * a, c[i] - p.min_stop_atr * a)
        if c[i] - stop > p.max_stop_atr * a:
            return None
    else:
        stop = max(max(h[i], zone_top) + p.sl_buffer_atr * a, c[i] + p.min_stop_atr * a)
        if stop - c[i] > p.max_stop_atr * a:
            return None
    return direction, score, stop, used, parts


def _exit_price(tr: ITrade, op, hi, lo):
    if tr.direction == 1:
        if op <= tr.stop or op >= tr.tp:
            return op
        if lo <= tr.stop:
            return tr.stop
        if hi >= tr.tp:
            return tr.tp
    else:
        if op >= tr.stop or op <= tr.tp:
            return op
        if hi >= tr.stop:
            return tr.stop
        if lo <= tr.tp:
            return tr.tp
    return None


def _close(tr: ITrade, t, px, session=False):
    risk = abs(tr.entry - tr.stop0)
    tr.exit_time, tr.exit = t, px
    tr.r_net = tr.direction * (px - tr.entry) / risk - tr.cost / risk
    hit_tp = (px >= tr.tp) if tr.direction == 1 else (px <= tr.tp)
    if hit_tp:
        tr.status = "TP HIT"
    elif session:
        tr.status = "SESSION CLOSE"
    else:
        tr.status = ["SL HIT", "BREAK EVEN", "PROFIT PROTECTED"][tr.stage]
