"""עמודות נוספות לטבלת הזמן (לפי זמן סגירת נר 5 דקות) לשיטות הנבדקות."""
import numpy as np
import pandas as pd

from app.data import NY


def _range_after(m5: pd.DataFrame, session: pd.Series, mask: pd.Series, valid: pd.Series, name: str) -> pd.DataFrame:
    """שיא/שפל של חלון זמן בתוך יום המסחר, ידוע רק אחרי שהחלון נסגר."""
    rng = m5[mask.values].groupby(session[mask].values).agg(high=("high", "max"), low=("low", "min"))
    out = pd.DataFrame(index=m5.index)
    out[f"{name}_high"] = session.map(rng["high"]).where(valid).values
    out[f"{name}_low"] = session.map(rng["low"]).where(valid).values
    return out


def extra_features(m5: pd.DataFrame) -> pd.DataFrame:
    ny = m5.index.tz_convert(NY)
    shifted = (ny + pd.Timedelta(hours=7)).tz_localize(None)
    session = pd.Series(shifted.normalize(), index=m5.index)
    mins = pd.Series(ny.hour * 60 + ny.minute, index=m5.index)  # דקות מחצות ניו יורק (לפי פתיחת הנר)
    same_day = shifted.hour >= 7  # אחרי חצות ניו יורק באותו יום מסחר

    parts = [
        # טווח פתיחה ניו יורק 08:00-08:30 - ידוע מ-08:30
        _range_after(m5, session, (mins >= 480) & (mins < 510), pd.Series(same_day & (mins >= 510).values, index=m5.index), "orbny"),
        # טווח פתיחה לונדון 02:00-03:00 - ידוע מ-03:00
        _range_after(m5, session, (mins >= 120) & (mins < 180), pd.Series(same_day & (mins >= 180).values, index=m5.index), "orblon"),
    ]
    out = pd.concat(parts, axis=1)

    # שיא/שפל של השבוע הקודם (שבוע לפי תאריך יום המסחר)
    week = session.dt.to_period("W-FRI")
    wk = m5.groupby(week.values).agg(high=("high", "max"), low=("low", "min")).shift(1)
    out["pwh"] = week.map(wk["high"]).values
    out["pwl"] = week.map(wk["low"]).values

    out["ny_min"] = mins.values
    out["t"] = m5.index + pd.Timedelta(minutes=5)
    return out.reset_index(drop=True)
