"""Estimate the XAUUSD bid/ask spread from Dukascopy hourly ASK vs BID candles for sample months.

    python -m research.gold4h.spread CACHE_DIR
Spread per hour = ASK close - BID close. Reports median and 90th percentile per sample month.
"""
import sys
from pathlib import Path

from research.gold4h.duka_hourly import month

SAMPLES = [(2015, 6), (2021, 6), (2026, 6)]

if __name__ == "__main__":
    cache = Path(sys.argv[1])
    print("| Month | Median spread $ | 90th pct $ |\n|---|---|---|")
    for y, m in SAMPLES:
        bid, ask = month(cache, y, m, "BID"), month(cache, y, m, "ASK")
        j = bid.join(ask, rsuffix="_ask", how="inner")
        s = j["close_ask"] - j["close"]
        print(f"| {y}-{m:02d} | {s.median():.3f} | {s.quantile(0.9):.3f} |", flush=True)
