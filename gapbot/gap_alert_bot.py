"""
Gap-Up Alert Bot -> Telegram
סורק מניות אמריקאיות שעולות (גאפ מסגירת אתמול) ושולח לטלגרם:
מניה, מחיר כניסה, סטופ (שפל נר 5 דק' האחרון), יעד 1:3.
מקור נתונים: Alpaca (חינמי, IEX בזמן אמת).
הרצה: pip install requests   ואז   python gap_alert_bot.py
"""
import time
import datetime as dt
from zoneinfo import ZoneInfo
import requests

# ================== הגדרות ==================
ALPACA_KEY = "YOUR_ALPACA_KEY_ID"
ALPACA_SECRET = "YOUR_ALPACA_SECRET"
TG_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
TG_CHAT_ID = "YOUR_CHAT_ID"

MIN_GAP_PCT = 10.0      # עלייה מינימלית מסגירת אתמול (%)
MIN_PRICE = 1.0         # מחיר מינימלי ($)
MAX_PRICE = 20.0        # מחיר מקסימלי ($)
MAX_RISK_PCT = 8.0      # אם הסטופ רחוק יותר מזה (%) - לא שולח
RR = 3.0                # יחס סיכוי:סיכון
SCAN_EVERY_SEC = 60     # תדירות סריקה
# ============================================

NY = ZoneInfo("America/New_York")
DATA = "https://data.alpaca.markets"
HDR = {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}


def market_open(now):
    if now.weekday() >= 5:
        return False
    t = now.time()
    return dt.time(9, 30) <= t <= dt.time(16, 0)


def get_gainers():
    r = requests.get(f"{DATA}/v1beta1/screener/stocks/movers",
                     headers=HDR, params={"top": 50}, timeout=15)
    r.raise_for_status()
    return r.json().get("gainers", [])


def last_closed_5m_low(symbol, now):
    start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    r = requests.get(f"{DATA}/v2/stocks/{symbol}/bars", headers=HDR, timeout=15,
                     params={"timeframe": "5Min", "start": start.isoformat(),
                             "feed": "iex", "limit": 200})
    r.raise_for_status()
    bars = r.json().get("bars") or []
    if len(bars) >= 2:
        return bars[-2]["l"]      # הנר האחרון שנסגר
    if bars:
        return bars[-1]["l"]
    return None


def send_tg(text):
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  data={"chat_id": TG_CHAT_ID, "text": text}, timeout=15)


def main():
    alerted, day = set(), None
    send_tg("✅ הבוט פועל - סורק גאפים בפתיחת המסחר")
    while True:
        now = dt.datetime.now(NY)
        if now.date() != day:
            alerted, day = set(), now.date()
        if not market_open(now):
            time.sleep(60)
            continue
        try:
            for g in get_gainers():
                sym, pct, price = g["symbol"], g["percent_change"], g["price"]
                if sym in alerted or pct < MIN_GAP_PCT:
                    continue
                if not (MIN_PRICE <= price <= MAX_PRICE):
                    continue
                stop = last_closed_5m_low(sym, now)
                if stop is None or stop >= price:
                    continue
                risk = price - stop
                if risk / price * 100 > MAX_RISK_PCT:
                    continue
                target = price + RR * risk
                alerted.add(sym)
                send_tg(
                    f"🚀 {sym}  +{pct:.1f}%\n"
                    f"כניסה: ${price:.2f}\n"
                    f"סטופ:  ${stop:.2f}  (-{risk / price * 100:.1f}%)\n"
                    f"יעד:   ${target:.2f}  (+{RR * risk / price * 100:.1f}%)\n"
                    f"🕒 {now:%H:%M} NY"
                )
        except Exception as e:
            print("error:", e)
        time.sleep(SCAN_EVERY_SEC)


if __name__ == "__main__":
    main()
