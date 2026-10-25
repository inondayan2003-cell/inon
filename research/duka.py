"""הורדת נרות דקה של XAU/USD מ-Dukascopy (חינם, בלי מפתח) עם מטמון מקומי לפי חודש."""
import datetime as dt
import lzma
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
REC = struct.Struct(">5if")  # שניות מתחילת היום, open, close, low, high, volume


def _day(client: httpx.Client, sym: str, day: dt.date, scale: float) -> pd.DataFrame | None:
    url = URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day)  # חודשים מתחילים מ-0
    for attempt in range(4):
        try:
            r = client.get(url, timeout=30)
            if r.status_code == 404 or not r.content:
                return None
            r.raise_for_status()
            raw = lzma.decompress(r.content)
            break
        except Exception:
            if attempt == 3:
                raise
    rows = [REC.unpack_from(raw, i) for i in range(0, len(raw), REC.size)]
    if not rows:
        return None
    a = np.array(rows, dtype=float)
    base = pd.Timestamp(day, tz="UTC")
    idx = base + pd.to_timedelta(a[:, 0], unit="s")
    df = pd.DataFrame({"open": a[:, 1] / scale, "high": a[:, 4] / scale, "low": a[:, 3] / scale,
                       "close": a[:, 2] / scale, "volume": a[:, 5]}, index=idx)
    flat = (df["volume"] <= 0) & (df["high"] == df["low"])  # דקות "מתות" בלי מסחר
    return df[~flat]


def fetch_minutes(start: dt.date, end: dt.date, cache: Path, sym: str = "XAUUSD", scale: float = 1000.0) -> pd.DataFrame:
    cache.mkdir(parents=True, exist_ok=True)
    months = pd.period_range(start, end, freq="M")
    frames = []
    with httpx.Client(http2=False) as client:
        for p in months:
            f = cache / f"{sym}_{p}.parquet"
            complete = p < pd.Period(dt.date.today(), "M")
            if f.exists() and complete:
                frames.append(pd.read_parquet(f))
                continue
            days = [d.date() for d in pd.date_range(p.start_time, p.end_time, freq="D") if d.date() <= end]
            with ThreadPoolExecutor(16) as ex:
                parts = [x for x in ex.map(lambda d: _day(client, sym, d, scale), days) if x is not None]
            if not parts:
                continue
            df = pd.concat(parts).sort_index()
            df.to_parquet(f)
            frames.append(df)
            print(f"  {p}: {len(df):,} דקות", flush=True)
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    med = out["close"].median()
    if not 300 < med < 20000:
        raise RuntimeError(f"קנה מידה לא סביר למחיר (חציון {med}) - צריך לבדוק את ה-scale")
    return out[(out.index.date >= start) & (out.index.date <= end)]
