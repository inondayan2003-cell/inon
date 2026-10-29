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
import threading
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
MAX_GAP_PCT = 0         # תקרת עלייה (%). 0 = בלי תקרה
REQUIRE_NEWS = True     # לשלוח רק מניות שיש עליהן חדשות מאז הסגירה הקודמת
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


DILUTION = ("offering", "warrant", "reverse split", "reverse stock split",
            "dilut", "private placement", "shelf", "atm program", "registered direct")


def news_since_last_close(symbol, now):
    d = now.date() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    start = dt.datetime.combine(d, dt.time(16, 0), NY)
    r = requests.get(f"{DATA}/v1beta1/news", headers=HDR, timeout=15,
                     params={"symbols": symbol, "start": start.isoformat(),
                             "limit": 5, "sort": "desc"})
    r.raise_for_status()
    return r.json().get("news") or []


def news_text(news):
    if not news:
        return "⚠️ אין חדשות מאז הסגירה\n"
    n = news[0]
    h = n.get("headline", "")
    flag = "🚩 חשד לדילול/הנפקה!\n" if any(k in h.lower() for k in DILUTION) else ""
    return f"📰 {h}\n{flag}🔗 {n.get('url', '')}\n"


def send_tg(text):
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  data={"chat_id": TG_CHAT_ID, "text": text}, timeout=15)


def build_signal(sym, pct, price, stop, now, demo=False, news=""):
    risk = price - stop
    target = price + RR * risk
    head = "🧪 סיגנל דמו (בדיקה בלבד)\n" if demo else ""
    return (f"{head}🚀 {sym}  +{pct:.1f}%\n{news}"
            f"כניסה: ${price:.2f}\n"
            f"סטופ:  ${stop:.2f}  (-{risk / price * 100:.1f}%)\n"
            f"יעד:   ${target:.2f}  (+{RR * risk / price * 100:.1f}%)\n"
            f"🕒 {now:%H:%M} NY")


def demo_signal():
    now = dt.datetime.now(NY)
    try:  # נתונים אמיתיים: המניה הכי עולה כרגע / בסשן האחרון
        g = get_gainers()[0]
        sym, pct, price = g["symbol"], g["percent_change"], g["price"]
        src = "✅ Alpaca מחובר"
        try:
            nt = news_text(news_since_last_close(sym, now))
        except Exception as e:
            nt = f"⚠️ חדשות לא זמינות: {e}\n"
    except Exception as e:
        sym, pct, price = "DEMO", 12.5, 5.00
        src = f"⚠️ Alpaca לא הגיב: {e}"
        nt = ""
    stop = round(price * 0.96, 2)
    return build_signal(sym, pct, price, stop, now, demo=True, news=nt) + f"\n{src}"


def command_listener():
    offset = None
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                             params={"timeout": 50, "offset": offset}, timeout=60)
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(TG_CHAT_ID):
                    continue
                text = (msg.get("text") or "").strip().lower()
                if text.startswith("/test"):
                    send_tg(demo_signal())
                elif text.startswith("/start") or text.startswith("/help"):
                    send_tg("פקודות:\n/test - סיגנל דמו לבדיקה שהכל עובד")
        except Exception as e:
            print("listener error:", e)
            time.sleep(5)


def main():
    threading.Thread(target=command_listener, daemon=True).start()
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
                if MAX_GAP_PCT and pct > MAX_GAP_PCT:
                    continue
                if not (MIN_PRICE <= price <= MAX_PRICE):
                    continue
                stop = last_closed_5m_low(sym, now)
                if stop is None or stop >= price:
                    continue
                risk = price - stop
                if risk / price * 100 > MAX_RISK_PCT:
                    continue
                news = news_since_last_close(sym, now)
                if REQUIRE_NEWS and not news:
                    continue
                alerted.add(sym)
                send_tg(build_signal(sym, pct, price, stop, now, news=news_text(news)))
        except Exception as e:
            print("error:", e)
        time.sleep(SCAN_EVERY_SEC)


if __name__ == "__main__":
    main()
