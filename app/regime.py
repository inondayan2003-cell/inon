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
