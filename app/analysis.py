"""מנוע הניתוח: ציון לכל טווח זמן, ציון משוקלל, רמות ותוכנית מסחר.

כל הטווחים מאונדקסים לפי זמן *סגירת* הנר, כך שבכל רגע משתמשים רק בנרות סגורים.
אותו קוד משמש גם לניתוח החי וגם ל-backtest.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Settings
from .data import MarketData, gold_closed, resample
from .indicators import adx, atr, ema, macd, rsi, supertrend

TIMEFRAMES = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}
# סוחר יומי: 1H ו-4H קובעים את הכיוון, 15M את המבנה, 5M את התזמון
WEIGHTS = {"4h": 0.30, "1h": 0.30, "15m": 0.25, "5m": 0.15}
COMPONENT_WEIGHTS = {"c_ema": 0.25, "c_200": 0.15, "c_macd": 0.20, "c_rsi": 0.15, "c_st": 0.15, "c_dmi": 0.10}
TF_LABELS = {"5m": "5M", "15m": "15M", "1h": "1H", "4h": "4H"}


def build_frames(md: MarketData) -> dict[str, pd.DataFrame]:
    return {
        "5m": md.m5,
        "15m": resample(md.m5, "15min"),
        "1h": md.h1,
        "4h": resample(md.h1, "4h"),
    }


def enrich(df: pd.DataFrame, period: str) -> pd.DataFrame:
    out = df.copy()
    c = out["close"]
    for n in (9, 21, 50, 200):
        out[f"ema{n}"] = ema(c, n)
    out["rsi"] = rsi(c)
    _, _, out["hist"] = macd(c)
    out["atr"] = atr(out)
    out["adx"], out["pdi"], out["mdi"] = adx(out)
    out["st"] = supertrend(out)
    out["swing_low"] = out["low"].rolling(8).min()
    out["swing_high"] = out["high"].rolling(8).max()

    e21, e50, e200 = out["ema21"], out["ema50"], out["ema200"]
    bull = (c > e21) & (e21 > e50)
    bear = (c < e21) & (e21 < e50)
    out["c_ema"] = np.where(bull, 1.0, np.where(bear, -1.0, 0.5 * np.sign(c - e50)))
    out["c_200"] = np.sign(c - e200)
    hist, prev = out["hist"], out["hist"].shift()
    out["c_macd"] = np.where(hist > 0, np.where(hist >= prev, 1.0, 0.5),
                             np.where(hist < 0, np.where(hist <= prev, -1.0, -0.5), 0.0))
    r = out["rsi"]
    c_rsi = ((r - 50) / 20).clip(-1, 1)
    # RSI קיצוני = המהלך מתוח, מורידים את המשקל שלו
    out["c_rsi"] = np.where(r > 75, 0.3, np.where(r < 25, -0.3, c_rsi))
    out["c_st"] = out["st"]
    out["c_dmi"] = np.sign(out["pdi"] - out["mdi"]) * np.where(out["adx"] >= 20, 1.0, 0.5)

    comps = out[list(COMPONENT_WEIGHTS)].fillna(0.0)
    out["score"] = 100 * sum(comps[k] * w for k, w in COMPONENT_WEIGHTS.items())
    out.loc[out["ema50"].isna(), "score"] = np.nan  # לא מספיק היסטוריה
    out["close_time"] = out.index + pd.Timedelta(period)
    return out


def build_timeline(enriched: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """שורה לכל נר 5 דקות (לפי זמן סגירה) עם הציון העדכני של כל טווח."""
    base = enriched["5m"][["open", "high", "low", "close", "close_time", "score"]]
    base = base.rename(columns={"score": "score_5m"}).reset_index(drop=True)
    for tf in ("15m", "1h", "4h"):
        cols = ["close_time", "score"]
        if tf == "15m":
            cols += ["atr", "ema21", "adx", "swing_low", "swing_high"]
        part = enriched[tf][cols].rename(columns={c: f"{c}_{tf}" for c in cols if c != "close_time"})
        base = pd.merge_asof(base.sort_values("close_time"), part.sort_values("close_time"),
                             on="close_time", direction="backward")
    scores = base[[f"score_{tf}" for tf in WEIGHTS]]
    base["composite"] = sum(scores[f"score_{tf}"] * w for tf, w in WEIGHTS.items())
    base.loc[scores.isna().any(axis=1), "composite"] = np.nan
    return base.rename(columns={"close_time": "t"}).dropna(subset=["composite", "atr_15m"])


def classify(row, cfg: Settings) -> tuple[int, int, str]:
    """(כיוון מאושר, נטייה, תווית). כיוון מאושר דורש יישור של הטווחים הגבוהים."""
    s = row["composite"]
    if s >= cfg.entry_threshold and row["score_1h"] >= 0 and row["score_4h"] >= 0 and row["score_15m"] >= 20:
        return 1, 1, "לונג"
    if s <= -cfg.entry_threshold and row["score_1h"] <= 0 and row["score_4h"] <= 0 and row["score_15m"] <= -20:
        return -1, -1, "שורט"
    if s >= 25:
        return 0, 1, "נטייה ללונג"
    if s <= -25:
        return 0, -1, "נטייה לשורט"
    return 0, 0, "ניטרלי - לא להיכנס"


def entry_direction(row, cfg: Settings) -> int:
    """כיוון לכניסה בפועל: יישור טווחים + מגמה חזקה + לא רודפים + תזמון 5M."""
    d, _, _ = classify(row, cfg)
    if d == 0 or row["adx_15m"] < cfg.min_adx:
        return 0
    if abs(row["close"] - row["ema21_15m"]) > cfg.max_stretch_atr * row["atr_15m"]:
        return 0
    if row["score_5m"] * d <= 0:
        return 0
    return d


def make_plan(direction: int, row, cfg: Settings) -> dict:
    entry, a = float(row["close"]), float(row["atr_15m"])
    if direction == 1:
        sl = min(entry - cfg.sl_atr_mult * a, row["swing_low_15m"] - 0.25 * a)
        sl = max(sl, entry - 3 * a)
    else:
        sl = max(entry + cfg.sl_atr_mult * a, row["swing_high_15m"] + 0.25 * a)
        sl = min(sl, entry + 3 * a)
    risk = abs(entry - sl)
    return {"entry": round(entry, 2), "sl": round(float(sl), 2),
            "tp1": round(entry + direction * risk, 2), "tp2": round(entry + 2 * direction * risk, 2),
            "risk": round(risk, 2)}


def reasons(enriched: dict[str, pd.DataFrame], direction: int, t: pd.Timestamp) -> list[str]:
    """הסברים קצרים בעברית למה המערכת חושבת כך."""
    if direction == 0:
        return []
    word = "עולה" if direction == 1 else "יורדת"
    out = []
    rows = {tf: _last_closed(enriched[tf], t) for tf in TIMEFRAMES}
    trend_tfs = [TF_LABELS[tf] for tf in ("4h", "1h", "15m") if rows[tf] is not None and rows[tf]["c_ema"] * direction > 0]
    if trend_tfs:
        out.append(f"מגמה {word} (סדר ממוצעים נעים) ב-{', '.join(trend_tfs)}")
    r15 = rows["15m"]
    if r15 is not None:
        if r15["c_macd"] * direction > 0:
            out.append(f"MACD ב-15M {'חיובי' if direction == 1 else 'שלילי'} ומתחזק")
        out.append(f"RSI 15M: {r15['rsi']:.0f} · ADX 15M: {r15['adx']:.0f}")
    r4 = rows["4h"]
    if r4 is not None and r4["c_200"] * direction > 0:
        out.append(f"המחיר {'מעל' if direction == 1 else 'מתחת'} ל-EMA200 ב-4H")
    return out


def _last_closed(df: pd.DataFrame, t: pd.Timestamp):
    closed = df[df["close_time"] <= t]
    return None if closed.empty else closed.iloc[-1]


def key_levels(h1: pd.DataFrame, m5: pd.DataFrame, now: pd.Timestamp) -> dict:
    daily = resample(h1, "1D")
    today = now.normalize()
    prev = daily[daily.index < today]
    if prev.empty:
        return {}
    p = prev.iloc[-1]
    pp = (p["high"] + p["low"] + p["close"]) / 3
    td = m5[m5.index >= today]
    lv = {
        "R2": pp + (p["high"] - p["low"]), "R1": 2 * pp - p["low"], "PP": pp,
        "S1": 2 * pp - p["high"], "S2": pp - (p["high"] - p["low"]),
        "PDH": p["high"], "PDL": p["low"],
    }
    if not td.empty:
        lv["HOD"], lv["LOD"] = td["high"].max(), td["low"].min()
    return {k: round(float(v), 2) for k, v in lv.items()}


@dataclass
class Analysis:
    snapshot: dict
    timeline: pd.DataFrame
    enriched: dict[str, pd.DataFrame]


def analyze(md: MarketData, now: pd.Timestamp, cfg: Settings) -> Analysis:
    enriched = {tf: enrich(df, TIMEFRAMES[tf]) for tf, df in build_frames(md).items()}
    timeline = build_timeline(enriched)
    timeline = timeline[timeline["t"] <= now]
    if timeline.empty:
        raise RuntimeError("אין מספיק נתונים לניתוח")
    row = timeline.iloc[-1]
    t = row["t"]
    direction, lean, label = classify(row, cfg)
    price = float(md.m5["close"].iloc[-1])
    last_bar_time = md.m5.index[-1]
    market_open = (now - last_bar_time) <= pd.Timedelta(minutes=20) and not gold_closed(pd.DatetimeIndex([now]))[0]

    tfs = []
    for tf in ("4h", "1h", "15m", "5m"):
        r = _last_closed(enriched[tf], t)
        tfs.append({
            "tf": TF_LABELS[tf], "weight": WEIGHTS[tf],
            "score": round(float(r["score"]), 1),
            "trend": _trend_label(r["score"]),
            "rsi": round(float(r["rsi"]), 1), "adx": round(float(r["adx"]), 1),
            "macd_hist": round(float(r["hist"]), 3), "atr": round(float(r["atr"]), 2),
            "above_ema200": None if pd.isna(r["ema200"]) else bool(r["close"] > r["ema200"]),
            "supertrend": int(r["st"]),
        })

    plan_dir = direction or lean
    day_open = md.m5[md.m5.index >= now.normalize()]
    snapshot = {
        "symbol": md.symbol, "source": md.source,
        "price": round(price, 2),
        "day_change": round(price - float(day_open["open"].iloc[0]), 2) if not day_open.empty else None,
        "updated_at": now.isoformat(), "bar_time": t.isoformat(),
        "price_time": (last_bar_time + pd.Timedelta(minutes=5)).isoformat(),
        "market_open": bool(market_open),
        "composite": round(float(row["composite"]), 1),
        "direction": direction, "lean": lean, "verdict": label,
        "entry_ready": entry_direction(row, cfg) != 0,
        "confidence": _confidence(row["composite"]),
        "timeframes": tfs,
        "plan": make_plan(plan_dir, row, cfg) if plan_dir else None,
        "reasons": reasons(enriched, plan_dir, t),
        "levels": key_levels(md.h1, md.m5, now),
    }
    return Analysis(snapshot=snapshot, timeline=timeline, enriched=enriched)


def _trend_label(score: float) -> str:
    if pd.isna(score):
        return "—"
    if score >= 50:
        return "עולה חזק"
    if score >= 20:
        return "עולה"
    if score <= -50:
        return "יורד חזק"
    if score <= -20:
        return "יורד"
    return "דשדוש"


def _confidence(score: float) -> str:
    a = abs(score)
    return "גבוה" if a >= 65 else "בינוני" if a >= 45 else "נמוך"
