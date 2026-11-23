"""Download XAUUSD 1-minute BID candles from Dukascopy, one file per day, cached as parquet.

    python -m research.gold4h.duka_minutes CACHE_DIR START END [reverse]
Dates are YYYY-MM-DD. Weekends (Saturday) are skipped. The server throttles hard (HTTP 429),
so requests are retried with back-off and every finished day is cached.
"""
import datetime as dt
import lzma
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
REC = struct.Struct(">5if")


def day(cache: Path, d: dt.date) -> pd.DataFrame | None:
    f = cache / f"m1_{d:%Y%m%d}.parquet"
    empty = cache / f"m1_{d:%Y%m%d}.empty"
    if f.exists():
        return pd.read_parquet(f)
    if empty.exists():
        return None
    tmp = cache / f"tmp_{d:%Y%m%d}.bi5"
    for attempt in range(60):
        r = subprocess.run(["curl", "-s", "-A", "Mozilla/5.0", "-o", str(tmp), "-w", "%{http_code}", "--max-time", "40",
                            URL.format(y=d.year, m=d.month - 1, d=d.day)], capture_output=True, text=True)
        code = r.stdout.strip()
        if code in ("200", "404"):
            break
        time.sleep(min(5 + 5 * attempt, 60))
    else:
        raise RuntimeError(f"failed {d}")
    data = tmp.read_bytes() if code == "200" and tmp.exists() else b""
    tmp.unlink(missing_ok=True)
    if not data:
        empty.touch()
        return None
    raw = lzma.decompress(data)
    a = np.array([REC.unpack_from(raw, i) for i in range(0, len(raw), REC.size)], dtype=float)
    idx = pd.Timestamp(d, tz="UTC") + pd.to_timedelta(a[:, 0], unit="s")
    df = pd.DataFrame({"open": a[:, 1] / 1000, "high": a[:, 4] / 1000, "low": a[:, 3] / 1000,
                       "close": a[:, 2] / 1000, "volume": a[:, 5]}, index=idx)
    df = df[~((df["volume"] <= 0) & (df["high"] == df["low"]))]
    if df.empty:
        empty.touch()
        return None
    df.to_parquet(f)
    return df


def load(cache: Path) -> pd.DataFrame:
    out = pd.concat(pd.read_parquet(f) for f in sorted(cache.glob("m1_*.parquet"))).sort_index()
    return out[~out.index.duplicated()]


if __name__ == "__main__":
    cache = Path(sys.argv[1]); cache.mkdir(parents=True, exist_ok=True)
    days = [d.date() for d in pd.date_range(sys.argv[2], sys.argv[3]) if d.weekday() != 5]
    if len(sys.argv) > 4 and sys.argv[4] == "reverse":
        days = days[::-1]
    for i, d in enumerate(days):
        day(cache, d)
        if i % 20 == 0:
            print(d, len(list(cache.glob("m1_*.parquet"))), time.strftime("%H:%M:%S"), flush=True)
