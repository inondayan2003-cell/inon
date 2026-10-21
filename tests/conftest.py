import numpy as np
import pandas as pd
import pytest

from app.data import MarketData, resample


def synthetic_m5(days: int = 40, seed: int = 7, end: str = "2026-10-21 12:00") -> pd.DataFrame:
    """הילוך אקראי עם משטרי מגמה מתחלפים, דומה לתנודתיות של זהב."""
    rng = np.random.default_rng(seed)
    n = days * 288
    idx = pd.date_range(end=pd.Timestamp(end, tz="UTC"), periods=n, freq="5min")
    drift = np.repeat(rng.choice([-0.35, 0.0, 0.35], size=n // 144 + 1), 144)[:n]
    close = 2400 + np.cumsum(drift + rng.normal(0, 1.2, n))
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, 0.8, (2, n)))
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + wick[0],
                         "low": np.minimum(open_, close) - wick[1], "close": close}, index=idx)


@pytest.fixture
def market() -> MarketData:
    m5 = synthetic_m5(days=200)
    return MarketData(m5=m5.iloc[-40 * 288:], h1=resample(m5, "1h"), symbol="TEST", source="test")
