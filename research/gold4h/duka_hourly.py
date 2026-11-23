"""Download XAUUSD hourly BID candles from Dukascopy (one file per month) with a local cache.

Usage: python -m research.gold4h.duka_hourly CACHE_DIR [START_YEAR] [END_YEAR]
The monthly file holds one record per hour: seconds-from-month-start, open, close, low, high, volume.
Prices are integers scaled by 1000 for XAUUSD. Timestamps are UTC.
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

URL = "https://datafeed.dukascopy.com/datafeed/XAUUSD/{y}/{m:02d}/{side}_candles_hour_1.bi5"
REC = struct.Struct(">5if")
SCALE = 1000.0


def _get(url: str, out: Path) -> bool:
    for attempt in range(40):
        r = subprocess.run(["curl", "-s", "-A", "Mozilla/5.0", "-o", str(out), "-w", "%{http_code}", "--max-time", "40", url],
                           capture_output=True, text=True)
        code = r.stdout.strip()
        if code == "200":
            return True
        if code == "404":
            return False
        time.sleep(min(10 + 5 * attempt, 60))
    raise RuntimeError(f"failed {url}")


def month(cache: Path, y: int, m: int, side: str = "BID") -> pd.DataFrame | None:
    f = cache / f"{side}_{y}_{m:02d}.parquet"
    if f.exists():
        return pd.read_parquet(f)
    raw_f = cache / f"tmp_{y}_{m}.bi5"
    if not _get(URL.format(y=y, m=m - 1, side=side), raw_f):
        return None
    data = raw_f.read_bytes()
    if not data:
        return None
    raw = lzma.decompress(data)
    a = np.array([REC.unpack_from(raw, i) for i in range(0, len(raw), REC.size)], dtype=float)
    base = pd.Timestamp(dt.datetime(y, m, 1), tz="UTC")
    df = pd.DataFrame({"open": a[:, 1] / SCALE, "high": a[:, 4] / SCALE, "low": a[:, 3] / SCALE,
                       "close": a[:, 2] / SCALE, "volume": a[:, 5]},
                      index=base + pd.to_timedelta(a[:, 0], unit="s"))
    df = df[df["volume"] > 0]  # Dukascopy fills closed hours with flat zero-volume candles
    df.to_parquet(f)
    return df


def main():
    cache = Path(sys.argv[1]); cache.mkdir(parents=True, exist_ok=True)
    y0 = int(sys.argv[2]) if len(sys.argv) > 2 else 2010
    y1 = int(sys.argv[3]) if len(sys.argv) > 3 else dt.date.today().year
    today = dt.date.today()
    frames = []
    for y in range(y0, y1 + 1):
        for m in range(1, 13):
            if dt.date(y, m, 1) > today.replace(day=1):
                break
            if (y, m) == (today.year, today.month):
                continue  # current month file is incomplete on the server
            df = month(cache, y, m)
            print(y, m, 0 if df is None else len(df), flush=True)
            if df is not None:
                frames.append(df)
            time.sleep(2)
    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated()]
    out.to_parquet(cache / "XAUUSD_H1.parquet")
    print("done", len(out), out.index[0], out.index[-1])


if __name__ == "__main__":
    main()
