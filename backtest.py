"""בדיקה היסטורית של האסטרטגיה, עם אותו קוד שרץ בבוט.

שימוש:  python backtest.py            (Yahoo, 60 הימים האחרונים בנרות 5 דקות)
        TWELVEDATA_API_KEY=... python backtest.py
"""
import sys

import pandas as pd

from app.analysis import analyze
from app.config import load_settings
from app.data import DataFeed, MarketData, fetch_yfinance
from app.storage import trade_stats
from app.strategy import Strategy


def run(md: MarketData, cfg) -> list[dict]:
    now = md.m5.index[-1] + pd.Timedelta(minutes=5)
    timeline = analyze(md, now, cfg).timeline
    strat, trades = Strategy(cfg), []
    for _, row in timeline.iterrows():
        for ev in strat.on_bar(row):
            if ev["type"] == "closed":
                trades.append(ev["trade"])
    return trades


def main():
    cfg = load_settings()
    if cfg.provider == "yfinance":
        md = MarketData(m5=fetch_yfinance(cfg.yf_symbol, "5m", "60d"),
                        h1=fetch_yfinance(cfg.yf_symbol, "1h", "2y"), symbol=cfg.yf_symbol, source="yfinance")
    else:
        md = DataFeed(cfg).get()
    trades = run(md, cfg)
    print(f"{md.symbol}: {md.m5.index[0]:%Y-%m-%d} עד {md.m5.index[-1]:%Y-%m-%d}")
    for t in trades:
        side = "LONG " if t["direction"] == 1 else "SHORT"
        print(f"{t['opened_at'][:16]}  {side} {t['entry']:>9.2f}  {t['status']:<8} {t['result_r']:+.2f}R")
    stats = trade_stats(trades)
    if not stats["count"]:
        print("אין עסקאות בתקופה")
        return 1
    print(f"\nעסקאות: {stats['count']} · הצלחה: {stats['win_rate']}% · "
          f"סה\"כ: {stats['total_r']:+.2f}R · ממוצע: {stats['avg_r']:+.2f}R")
    return 0


if __name__ == "__main__":
    sys.exit(main())
