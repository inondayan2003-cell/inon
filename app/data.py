"""הבאת נתוני זהב: Twelve Data (XAU/USD ספוט) או Yahoo Finance (GC=F)."""
import logging
import time
from dataclasses import dataclass

import httpx
import pandas as pd

from .config import Settings

log = logging.getLogger(__name__)
OHLC = ["open", "high", "low", "close"]


@dataclass
class MarketData:
    m5: pd.DataFrame   # נרות 5 דקות (כולל הנר שעוד נבנה)
    h1: pd.DataFrame   # נרות שעה, היסטוריה ארוכה
    symbol: str
    source: str


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)[OHLC].astype(float).dropna()
    idx = pd.DatetimeIndex(df.index)
    df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return df[~df.index.duplicated(keep="last")].sort_index()


def fetch_yfinance(symbol: str, interval: str, period: str) -> pd.DataFrame:
    import yfinance as yf

    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"Yahoo החזיר תוצאה ריקה עבור {symbol} {interval}")
    return _clean(df)


def fetch_twelvedata(symbol: str, interval: str, outputsize: int, key: str) -> pd.DataFrame:
    r = httpx.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": symbol, "interval": interval, "outputsize": outputsize,
                "timezone": "UTC", "order": "ASC", "apikey": key},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "ok":
        raise RuntimeError(f"Twelve Data: {body.get('message', body)}")
    df = pd.DataFrame(body["values"])
    df.index = pd.to_datetime(df.pop("datetime"))
    return _clean(df)


class DataFeed:
    """שומר את נתוני השעה בזיכרון ומרענן אותם רק כל 30 דקות, כדי לחסוך בקשות."""

    H1_REFRESH = 30 * 60

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._h1: pd.DataFrame | None = None
        self._h1_at = 0.0

    @property
    def symbol(self) -> str:
        return "XAU/USD" if self.cfg.provider == "twelvedata" else f"{self.cfg.yf_symbol} (חוזה עתידי)"

    def _fetch(self, tf: str) -> pd.DataFrame:
        if self.cfg.provider == "twelvedata":
            interval = {"5m": "5min", "1h": "1h"}[tf]
            return fetch_twelvedata(self.cfg.td_symbol, interval, 5000, self.cfg.twelvedata_api_key)
        period = {"5m": "30d", "1h": "1y"}[tf]
        return fetch_yfinance(self.cfg.yf_symbol, tf, period)

    def get(self) -> MarketData:
        m5 = self._fetch("5m")
        if self._h1 is None or time.time() - self._h1_at > self.H1_REFRESH:
            self._h1 = self._fetch("1h")
            self._h1_at = time.time()
        # משלימים את השעות האחרונות מנתוני ה-5 דקות כדי שה-1H/4H יהיו עדכניים
        recent = resample(m5, "1h").iloc[1:]  # השעה הראשונה עלולה להיות חלקית
        h1 = pd.concat([self._h1[self._h1.index < recent.index[0]], recent])
        return MarketData(m5=m5, h1=h1, symbol=self.symbol, source=self.cfg.provider)


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return (
        df.resample(rule, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )
