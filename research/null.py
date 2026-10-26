"""קבוצת ביקורת: מערבבים את סדר הדקות בתוך כל שעה ביום. נשמרת התנודתיות לפי שעה,
אבל נמחק כל דפוס של המשך/היפוך. כל "רווח" על הנתונים האלה = מזל של בחירה."""
import numpy as np
import pandas as pd


def shuffle_within_hour(m1: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    c = m1["close"].to_numpy()
    ret = np.diff(c, prepend=c[0])
    offs = (m1[["open", "high", "low"]].to_numpy() - c[:, None])
    key = (m1.index.floor("1h").asi8 // 3_600_000_000_000)
    order = np.arange(len(m1))
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(m1)]
    for s, e in zip(starts, ends):
        order[s:e] = s + rng.permutation(e - s)
    new_c = c[0] + np.cumsum(ret[order])
    o = new_c[:, None] + offs[order]
    return pd.DataFrame({"open": o[:, 0], "high": np.maximum(o[:, 1], new_c), "low": np.minimum(o[:, 2], new_c),
                         "close": new_c, "volume": 0.0}, index=m1.index)


def shuffle_within_day(m1: pd.DataFrame, seed: int) -> pd.DataFrame:
    """כמו shuffle_within_hour אבל בתוך כל יום: נשמר כיוון היום (וכך כל המגמה הרב-יומית),
    נמחק כל דפוס תוך-יומי. ביקורת הוגנת לשיטות של 30M-2H."""
    rng = np.random.default_rng(seed)
    c = m1["close"].to_numpy()
    ret = np.diff(c, prepend=c[0])
    offs = (m1[["open", "high", "low"]].to_numpy() - c[:, None])
    key = m1.index.normalize().asi8
    order = np.arange(len(m1))
    starts = np.flatnonzero(np.r_[True, key[1:] != key[:-1]])
    ends = np.r_[starts[1:], len(m1)]
    for s, e in zip(starts, ends):
        order[s:e] = s + rng.permutation(e - s)
    new_c = c[0] + np.cumsum(ret[order])
    o = new_c[:, None] + offs[order]
    return pd.DataFrame({"open": o[:, 0], "high": np.maximum(o[:, 1], new_c), "low": np.minimum(o[:, 2], new_c),
                         "close": new_c, "volume": 0.0}, index=m1.index)
