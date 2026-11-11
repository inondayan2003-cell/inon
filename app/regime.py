"""סוג השוק (research/reopen.py regime_report): מגמה x תנודתיות, מנתונים שידועים לפני היום.

מגמה: סגירה יומית מעל ממוצע 100 ימים. תנודתיות: ממוצע 14 ימים של (טווח יומי / מחיר) מעל החציון של השנה האחרונה.
הלונג בפתיחה נשלח רק ב"עולה + רגוע" - סוג השוק היחיד שבו הוא לא הפסיד באף תקופה ב-2018-2026.
"""
import pandas as pd

LABELS = {(True, True): "עולה + תנודתי", (True, False): "עולה + רגוע",
          (False, True): "יורד/צדדי + תנודתי", (False, False): "יורד/צדדי + רגוע"}


def daily_regime(h1: pd.DataFrame) -> pd.DataFrame:
    d = h1.resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    rng = ((d.high - d.low) / d.close).rolling(14).mean()
    trend = d.close > d.close.rolling(100).mean()
    vol = rng > rng.rolling(250, min_periods=120).median()
    ok = trend.notna() & d.close.rolling(100).mean().notna() & rng.rolling(250, min_periods=120).median().notna()
    reg = pd.DataFrame({"trend": trend, "vol": vol, "known": ok}).shift(1)   # רק מה שידוע לפני היום
    reg.index = reg.index.tz_convert("UTC").normalize() if reg.index.tz is not None else reg.index.normalize()
    return reg.dropna()


def lookup(reg: pd.DataFrame | None, t: pd.Timestamp) -> tuple[bool | None, str]:
    """(האם מותר לונג בפתיחה, תווית). None = לא ידוע."""
    if reg is None or reg.empty:
        return None, "לא ידוע"
    day = t.tz_convert("UTC").normalize() if t.tzinfo else t.normalize()
    if reg.index.tz is None:
        day = day.tz_localize(None)
    past = reg[reg.index <= day]
    if past.empty or not bool(past.known.iloc[-1]):
        return None, "לא ידוע (אין מספיק היסטוריה)"
    tr, vo = bool(past.trend.iloc[-1]), bool(past.vol.iloc[-1])
    return (tr and not vo), LABELS[(tr, vo)]


def tag_rows(rows: list[dict], reg: pd.DataFrame | None) -> list[dict]:
    cache = {}
    for r in rows:
        key = pd.Timestamp(r["t"]).normalize()
        if key not in cache:
            cache[key] = lookup(reg, pd.Timestamp(r["t"]))
        r["regime_ok"], r["regime_label"] = cache[key]
    return rows


def daily_bars(h1: pd.DataFrame) -> pd.DataFrame:
    """נרות יומיים (יום מסחר = 17:00-17:00 ניו יורק) עם ממוצע 200 יום ו-ATR(14). לשיטת הלונג היומי."""
    idx = h1.index if h1.index.tz is not None else h1.index.tz_localize("UTC")
    day = (idx.tz_convert("America/New_York") + pd.Timedelta(hours=7)).normalize().tz_localize(None)
    d = h1.groupby(day).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"), n=("close", "size"))
    d = d[d.n >= 12]
    tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(), (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(14).mean()
    d["sma"] = d.close.rolling(200, min_periods=150).mean()   # הבוט מחזיק ~215 ימים של נרות שעה
    return d


def daily_lookup(d: pd.DataFrame | None, t: pd.Timestamp) -> dict | None:
    """היום המלא האחרון לפני t: {day, close, sma, atr}. None אם אין מספיק היסטוריה."""
    if d is None or d.empty:
        return None
    today = (t.tz_convert("America/New_York") + pd.Timedelta(hours=7)).normalize().tz_localize(None)
    past = d[d.index < today]
    if past.empty or pd.isna(past.sma.iloc[-1]) or pd.isna(past.atr.iloc[-1]):
        return None
    r = past.iloc[-1]
    return {"day": past.index[-1].date().isoformat(), "close": float(r.close), "sma": float(r.sma), "atr": float(r.atr)}
