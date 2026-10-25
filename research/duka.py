"""הורדת נרות דקה של XAU/USD מ-Dukascopy (חינם, בלי מפתח) עם מטמון מקומי לפי חודש."""
import datetime as dt
import lzma
import struct
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

HOSTS = ["https://datafeed.dukascopy.com", "http://datafeed.dukascopy.com", "https://www.dukascopy.com"]
PATH = "/datafeed/{sym}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}
REC = struct.Struct(">5if")  # שניות מתחילת היום, open, close, low, high, volume


def _day(client: httpx.Client, sym: str, day: dt.date, scale: float) -> pd.DataFrame | None:
    path = PATH.format(sym=sym, y=day.year, m=day.month - 1, d=day.day)  # חודשים מתחילים מ-0
    for attempt in range(6):
        try:
            r = client.get(HOSTS[attempt % len(HOSTS)] + path, timeout=20, headers=HEADERS, follow_redirects=True)
            if r.status_code == 404 or not r.content:
                return None
            r.raise_for_status()
            raw = lzma.decompress(r.content)
            break
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 * (attempt + 1))
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
            with ThreadPoolExecutor(4) as ex:
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
