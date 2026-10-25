"""בדיקה היסטורית (backtest) על נתונים אמיתיים, עם אותו קוד שרץ בבוט החי."""
import logging
import time

import pandas as pd

from .analysis import analyze
from .config import Settings
from .data import MarketData, _clean, drop_closed, fetch_yfinance, resample
from .strategy import Strategy

log = logging.getLogger(__name__)


def fetch_twelvedata_history(symbol: str, interval: str, start: pd.Timestamp, key: str,
                             max_requests: int = 15, pause: float = 9.0) -> pd.DataFrame:
    """מושך היסטוריה ארוכה בדפים של 5000 נרות (אחורה בזמן), בקצב שמתאים לחבילה החינמית."""
    import httpx

    frames, end = [], None
    for i in range(max_requests):
        params = {"symbol": symbol, "interval": interval, "outputsize": 5000,
                  "timezone": "UTC", "order": "ASC", "apikey": key}
        if end is not None:
            params["end_date"] = end.strftime("%Y-%m-%d %H:%M:%S")
        if i:
            time.sleep(pause)  # החבילה החינמית: עד 8 בקשות בדקה
        body = httpx.get("https://api.twelvedata.com/time_series", params=params, timeout=60).json()
        if body.get("status") != "ok":
            if frames:  # הגענו לסוף ההיסטוריה הזמינה
                log.warning("Twelve Data עצר: %s", body.get("message"))
                break
            raise RuntimeError(f"Twelve Data: {body.get('message', body)}")
        df = pd.DataFrame(body["values"])
        df.index = pd.to_datetime(df.pop("datetime"))
        df = _clean(df)
        frames.append(df)
        if df.index[0] <= start or len(df) < 4500:
            break
        end = df.index[0]
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated(keep="last")]


def fetch_history(cfg: Settings, months: int) -> MarketData:
    start = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=months)
    if cfg.provider == "twelvedata":
        m5 = fetch_twelvedata_history(cfg.td_symbol, "5min", start, cfg.twelvedata_api_key)
        h1 = fetch_twelvedata_history(cfg.td_symbol, "1h", start - pd.DateOffset(months=3), cfg.twelvedata_api_key,
                                      max_requests=2)
        symbol = "XAU/USD"
    else:  # Yahoo נותן רק 60 יום של נרות 5 דקות
        m5 = fetch_yfinance(cfg.yf_symbol, "5m", "60d")
        h1 = fetch_yfinance(cfg.yf_symbol, "1h", "2y")
        symbol = cfg.yf_symbol
    m5, h1 = drop_closed(m5), drop_closed(h1)
    # משלימים את ה-1H מתוך ה-5M בתקופה החופפת, כמו בבוט החי
    recent = resample(m5, "1h").iloc[1:]
    h1 = pd.concat([h1[h1.index < recent.index[0]], recent])
    return MarketData(m5=m5, h1=h1, symbol=symbol, source=cfg.provider)


def run(md: MarketData, cfg: Settings) -> list[dict]:
    now = md.m5.index[-1] + pd.Timedelta(minutes=5)
    timeline = analyze(md, now, cfg).timeline
    strat, trades = Strategy(cfg), []
    for row in timeline.to_dict("records"):
        for ev in strat.on_bar(pd.Series(row)):
            if ev["type"] == "closed":
                trades.append(ev["trade"])
    return trades


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"count": 0}
    r = pd.Series([t["result_r"] for t in trades], dtype=float)
    equity = r.cumsum()
    losses = (r <= 0).astype(int)
    streak = losses.groupby((losses != losses.shift()).cumsum()).cumsum().max()
    gross_win, gross_loss = r[r > 0].sum(), -r[r < 0].sum()
    months = {}
    for t in trades:
        m = t["opened_at"][:7]
        months[m] = months.get(m, 0.0) + t["result_r"]

    def side(d):
        rs = [t["result_r"] for t in trades if t["direction"] == d]
        return {"count": len(rs), "win_rate": round(100 * sum(x > 0 for x in rs) / len(rs), 1) if rs else 0,
                "total_r": round(sum(rs), 2)}

    statuses = {}
    for t in trades:
        statuses[t["status"]] = statuses.get(t["status"], 0) + 1
    return {
        "count": len(trades),
        "win_rate": round(100 * (r > 0).mean(), 1),
        "total_r": round(r.sum(), 2),
        "avg_r": round(r.mean(), 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "max_drawdown_r": round(float((equity.cummax().clip(lower=0) - equity).max()), 2),
        "max_losing_streak": int(streak),
        "long": side(1), "short": side(-1),
        "months": {k: round(v, 2) for k, v in sorted(months.items())},
        "statuses": statuses,
    }


def format_report(s: dict, md: MarketData) -> str:
    start, end = md.m5.index[0], md.m5.index[-1]
    head = f"📊 <b>בדיקה היסטורית - {md.symbol}</b>\n{start:%d/%m/%Y} עד {end:%d/%m/%Y}\n"
    if not s["count"]:
        return head + "\nלא היו סיגנלים בתקופה הזאת."
    verdict = ("✅ השיטה הייתה רווחית בתקופה הזאת" if s["total_r"] > 0
               else "❌ השיטה הפסידה בתקופה הזאת - לא לסחור לפיה עם כסף אמיתי")
    pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] is not None else "—"
    names = {"tp2": "🏆 יעד 2", "be": "⚖️ יעד 1 ואז כניסה", "sl": "🛑 סטופ", "expired": "⏰ פג זמן", "reversed": "🔄 התהפך"}
    lines = [
        head,
        f"<b>{verdict}</b>",
        "",
        f"עסקאות: <b>{s['count']}</b>",
        f"אחוז הצלחה: <b>{s['win_rate']}%</b>",
        f"רווח כולל: <b>{s['total_r']:+.1f}R</b> (ממוצע {s['avg_r']:+.2f}R לעסקה)",
        f"Profit Factor: <b>{pf}</b> (מעל 1.3 = טוב)",
        f"ירידה מקסימלית: {s['max_drawdown_r']:.1f}R · רצף הפסדים ארוך: {s['max_losing_streak']}",
        "",
        f"🟢 לונג: {s['long']['count']} עסקאות · {s['long']['win_rate']}% · {s['long']['total_r']:+.1f}R",
        f"🔴 שורט: {s['short']['count']} עסקאות · {s['short']['win_rate']}% · {s['short']['total_r']:+.1f}R",
        "",
        "<b>לפי חודש:</b>",
    ]
    lines += [f"{m}: {r:+.1f}R {'🟢' if r > 0 else '🔴'}" for m, r in s["months"].items()]
    lines += ["", "<b>איך נסגרו:</b>"] + [f"{names.get(k, k)}: {v}" for k, v in s["statuses"].items()]
    lines += ["", "<i>R = הסכום שאתה מסכן בעסקה. למשל, בסיכון של 100$ לעסקה, ‎+10R = רווח של 1,000$. "
                  "ביצועי עבר לא מבטיחים ביצועים בעתיד. לא כולל עמלות ומרווח.</i>"]
    return "\n".join(lines)


def backtest_report(cfg: Settings, months: int = 6) -> str:
    md = fetch_history(cfg, months)
    return format_report(summarize(run(md, cfg)), md)
