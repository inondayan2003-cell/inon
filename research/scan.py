"""סורק דפוסים: תשואה עתידית (ביחידות ATR של 15M) אחרי אירועים שונים, בנפרד ל-IS ול-OOS.

דפוס "אמיתי" = אותו סימן ב-IS וב-OOS, עם t מובהק (|t|>2) לפחות ב-IS.
"""
import numpy as np
import pandas as pd

H = {"15m": 3, "30m": 6, "1h": 12, "2h": 24}


def _fwd(tl: pd.DataFrame) -> pd.DataFrame:
    c, a = tl["close"], tl["atr_15m"]
    return pd.DataFrame({k: (c.shift(-n) - c) / a for k, n in H.items()})


def _row(name, mask, fwd, split_mask, sign=1):
    out = [name]
    for part in (~split_mask, split_mask):
        sel = fwd[mask & part].dropna()
        n = len(sel)
        if n < 20:
            out.append(f"n={n}")
            continue
        cells = []
        for k in ("30m", "1h", "2h"):
            x = sel[k] * sign
            t = x.mean() / x.std(ddof=1) * np.sqrt(n)
            cells.append(f"{x.mean() * 100:+.1f}({t:+.1f})")
        out.append(f"n={n} " + " ".join(cells))
    return "| " + " | ".join(out) + " |"


def scan(tl: pd.DataFrame, split) -> str:
    tl = tl.reset_index(drop=True)
    fwd = _fwd(tl)
    oos = tl["t"] >= split
    m = tl["ny_min"]
    lines = ["### סריקת דפוסים - תשואה עתידית ב-%ATR (t) ל-30m/1h/2h", "",
             "| אירוע | IS | OOS |", "|---|---|---|"]

    # עונתיות: לפי שעה בשעון ניו יורק, בתחילת השעה
    for h in range(24):
        lines.append(_row(f"שעה {h:02d}:00 NY (לונג)", (m == h * 60), fwd, oos))

    # נר 5M חזק: המשך או היפוך?
    body = (tl["close"] - tl["open"]) / tl["atr_5m"]
    for th in (1.5, 2.5):
        lines.append(_row(f"נר עולה >{th} ATR5 (לונג=המשך)", body > th, fwd, oos))
        lines.append(_row(f"נר יורד >{th} ATR5 (לונג=היפוך)", body < -th, fwd, oos))

    # מגמה גבוהה: ציון 1H/4H
    for col in ("score_1h", "score_4h"):
        lines.append(_row(f"{col}>50 (לונג)", tl[col] > 50, fwd, oos))
        lines.append(_row(f"{col}<-50 (לונג)", tl[col] < -50, fwd, oos))

    # סוויפ רמות: נר שעובר את הרמה (לראשונה באותו יום) - לונג = היפוך אחרי סוויפ שפל
    for name, col, d in (("PDL", "pdl", 1), ("PDH", "pdh", -1), ("ASL", "asia_low", 1), ("ASH", "asia_high", -1),
                         ("LDL", "lon_low", 1), ("LDH", "lon_high", -1)):
        lvl = tl[col]
        crossed = (tl["low"] < lvl) if d == 1 else (tl["high"] > lvl)
        first = crossed & ~crossed.groupby(tl["session"]).transform(lambda s: s.shift(fill_value=False).cummax())
        closed_back = first & (((tl["close"] - lvl) * d) > 0)
        closed_beyond = first & (((tl["close"] - lvl) * d) <= 0)
        lines.append(_row(f"סוויפ {name} וסגירה חזרה (היפוך)", closed_back, fwd, oos, sign=d))
        lines.append(_row(f"פריצת {name} וסגירה מעבר (היפוך)", closed_beyond, fwd, oos, sign=d))

    # פריצת טווח פתיחה - ראשונה ביום
    for pre in ("orbny", "orblon"):
        up = tl["close"] > tl[f"{pre}_high"]
        dn = tl["close"] < tl[f"{pre}_low"]
        for nm, ev, sgn in (("מעלה", up, 1), ("מטה", dn, -1)):
            first = ev & ~ev.groupby(tl["session"]).transform(lambda s: s.shift(fill_value=False).cummax())
            lines.append(_row(f"{pre} פריצה ל{nm} (המשך)", first, fwd, oos, sign=sgn))

    # ימי השבוע (לונג מ-08:00 NY)
    dow = tl["t"].dt.tz_convert("America/New_York").dt.dayofweek
    for i, dname in enumerate(["ב'", "ג'", "ד'", "ה'", "ו'"]):
        lines.append(_row(f"יום {dname} 08:00 NY (לונג)", (dow == i) & (m == 480), fwd, oos))
    return "\n".join(lines)
