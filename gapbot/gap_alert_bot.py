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
import re
import json
import math
import os
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
MIN_TARGET_PCT = 5.0    # יעד מינימלי (%) - אם היעד קטן מזה, לא שולח
RR = 3.0                # יחס סיכוי:סיכון
PAPER_TRADING = True    # לבצע כל סיגנל בחשבון הדמו של Alpaca
RISK_PER_TRADE = 100.0  # כמה $ מסכנים בכל עסקה (בדמו)
MAX_POSITION = 10000.0  # גודל פוזיציה מקסימלי ($)
EOD_CLOSE = dt.time(15, 55)   # סגירת כל הפוזיציות (שעון ניו יורק)
EOD_REPORT = dt.time(16, 5)   # שליחת דוח יומי
SIGNAL_WINDOW_MIN = 90  # סיגנלים רק ב-X הדקות הראשונות של המסחר
MIN_RVOL = 2.0          # ווליום יחסי מינימלי (היום מול ממוצע 20 יום, לפי השעה)
SCAN_EVERY_SEC = 60     # תדירות סריקה
# ============================================

NY = ZoneInfo("America/New_York")
DATA = "https://data.alpaca.markets"
TRADE = "https://paper-api.alpaca.markets"
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


def bars_today(symbol, now):
    start = now.replace(hour=9, minute=30, second=0, microsecond=0)
    r = requests.get(f"{DATA}/v2/stocks/{symbol}/bars", headers=HDR, timeout=15,
                     params={"timeframe": "5Min", "start": start.isoformat(),
                             "feed": "iex", "limit": 200})
    r.raise_for_status()
    return r.json().get("bars") or []


def last_closed_bar(bars):
    if len(bars) >= 2:
        return bars[-2]           # הנר האחרון שנסגר
    return bars[-1] if bars else None


def last_closed_5m_low(symbol, now):
    b = last_closed_bar(bars_today(symbol, now))
    return b["l"] if b else None


def rvol(symbol, now, bars):
    """ווליום היום עד עכשיו, מול ממוצע 20 יום מחולק לפי הזמן שעבר מהפתיחה."""
    r = requests.get(f"{DATA}/v2/stocks/{symbol}/bars", headers=HDR, timeout=15,
                     params={"timeframe": "1Day", "feed": "iex", "limit": 30,
                             "start": (now - dt.timedelta(days=45)).date().isoformat()})
    r.raise_for_status()
    days = [b for b in (r.json().get("bars") or []) if b["t"][:10] < now.date().isoformat()][-20:]
    if not days:
        return 0.0
    avg = sum(b["v"] for b in days) / len(days)
    mins = (now - now.replace(hour=9, minute=30, second=0, microsecond=0)).total_seconds() / 60
    frac = max(mins / 390, 0.05)
    today = sum(b["v"] for b in bars)
    return today / (avg * frac) if avg else 0.0


def last_price(symbol):
    r = requests.get(f"{DATA}/v2/stocks/{symbol}/trades/latest", headers=HDR,
                     params={"feed": "iex"}, timeout=15)
    r.raise_for_status()
    return r.json()["trade"]["p"]


DILUTION = ("offering", "warrant", "reverse split", "reverse stock split",
            "dilut", "private placement", "shelf", "atm program", "registered direct")


# הודעות שגרתיות שלא נחשבות קטליסט
ROUTINE = [
    r"\bto (announce|report|release|host|hold)\b.*\b(results|earnings|call|webcast)\b",
    r"\b(announces?|sets|schedules?)\b.*\b(date|timing)\b.*\b(results|earnings|call)\b",
    r"\bconference call\b", r"\bwebcast\b",
    r"\bto (present|participate|ring|attend|speak)\b",
    r"\b(investor|healthcare|industry) conference\b", r"\bfireside chat\b",
    r"\bdeclares? (quarterly |monthly |regular )?(cash )?dividend\b",
    r"\b(annual|special) (general )?meeting\b",
    r"\bshareholder (letter|update)\b",
    r"\blaw firm\b|\bclass action\b|\binvestigation (on behalf|of)\b|\bshareholder alert\b",
    r"\b(stocks?|shares?) (moving|trading) (higher|lower|in)\b|\bmid-day movers\b|\bpremarket movers\b",
]
ROUTINE_RE = [re.compile(x, re.I) for x in ROUTINE]


def meaningful(news):
    return [n for n in news if not any(r.search(n.get("headline", "")) for r in ROUTINE_RE)]


def news_since_last_close(symbol, now):
    d = now.date() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    start = dt.datetime.combine(d, dt.time(16, 0), NY)
    r = requests.get(f"{DATA}/v1beta1/news", headers=HDR, timeout=15,
                     params={"symbols": symbol, "start": start.isoformat(),
                             "limit": 5, "sort": "desc"})
    r.raise_for_status()
    return meaningful(r.json().get("news") or [])


def news_text(news):
    if not news:
        return "⚠️ אין חדשות משמעותיות מאז הסגירה\n"
    n = news[0]
    h = n.get("headline", "")
    flag = "🚩 חשד לדילול/הנפקה!\n" if any(k in h.lower() for k in DILUTION) else ""
    return f"📰 {h}\n{flag}🔗 {n.get('url', '')}\n"


def send_tg(text):
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                  data={"chat_id": TG_CHAT_ID, "text": text}, timeout=15)


# ================== מסחר דמו ==================
TRADES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades")


def trades_file(day):
    os.makedirs(TRADES_DIR, exist_ok=True)
    return os.path.join(TRADES_DIR, f"{day}.json")


def load_trades(day):
    try:
        with open(trades_file(day)) as f:
            return json.load(f)
    except Exception:
        return []


def save_trade(day, t):
    trades = load_trades(day)
    trades.append(t)
    with open(trades_file(day), "w") as f:
        json.dump(trades, f, ensure_ascii=False, indent=1)


def px(x):
    return round(x, 2) if x >= 1 else round(x, 4)


def place_bracket(sym, price, stop, target):
    qty = math.floor(min(RISK_PER_TRADE / (price - stop), MAX_POSITION / price))
    if qty < 1:
        return None, "כמות קטנה מ-1"
    order = {"symbol": sym, "qty": str(qty), "side": "buy", "type": "market",
             "time_in_force": "day", "order_class": "bracket",
             "take_profit": {"limit_price": str(px(target))},
             "stop_loss": {"stop_price": str(px(stop))}}
    r = requests.post(f"{TRADE}/v2/orders", headers=HDR, json=order, timeout=15)
    if r.status_code >= 300:
        return None, r.text[:200]
    return qty, None


def close_all():
    """מבטל סטופים/יעדים פתוחים ואז סוגר את כל הפוזיציות. מחזיר True אם הכל סגור."""
    requests.delete(f"{TRADE}/v2/orders", headers=HDR, timeout=15)
    for _ in range(15):  # מחכה שהביטולים יסתיימו - אחרת המניות "תפוסות"
        r = requests.get(f"{TRADE}/v2/orders", headers=HDR, params={"status": "open"}, timeout=15)
        if r.ok and not r.json():
            break
        time.sleep(2)
    requests.delete(f"{TRADE}/v2/positions", headers=HDR, params={"cancel_orders": "true"}, timeout=15)
    time.sleep(5)
    r = requests.get(f"{TRADE}/v2/positions", headers=HDR, timeout=15)
    return r.ok and not r.json()


def market_was_open(day):
    r = requests.get(f"{TRADE}/v2/calendar", headers=HDR, timeout=15,
                     params={"start": str(day), "end": str(day)})
    return bool(r.ok and r.json())


def daily_report(day):
    trades = load_trades(day)
    if not trades:
        return f"📊 דוח יומי {day}\nהיום לא היו עסקאות."
    r = requests.get(f"{TRADE}/v2/account/activities/FILL", headers=HDR, timeout=15,
                     params={"date": str(day)})
    fills = r.json() if r.ok else []
    agg = {}
    for f in fills:
        a = agg.setdefault(f["symbol"], {"bq": 0, "bv": 0.0, "sq": 0, "sv": 0.0})
        q, p = float(f["qty"]), float(f["price"])
        if f["side"] == "buy":
            a["bq"] += q; a["bv"] += q * p
        else:
            a["sq"] += q; a["sv"] += q * p
    lines, total, wins, done = [], 0.0, 0, 0
    for t in trades:
        a = agg.get(t["symbol"])
        if not a or not a["bq"]:
            lines.append(f"⚪ {t['symbol']} - לא בוצע")
            continue
        entry = a["bv"] / a["bq"]
        exit_ = a["sv"] / a["sq"] if a["sq"] else None
        if exit_ is None:
            lines.append(f"⏳ {t['symbol']} - עדיין פתוחה (כניסה ${entry:.2f})")
            continue
        pnl = a["sv"] - a["bv"]
        total += pnl; done += 1
        if exit_ >= t["target"] * 0.995:
            icon, why = "🎯", "יעד"
        elif exit_ <= t["stop"] * 1.005:
            icon, why = "🛑", "סטופ"
        else:
            icon, why = "⏰", "סגירת יום"
        if pnl > 0:
            wins += 1
        lines.append(f"{icon} {t['symbol']}  ${entry:.2f} → ${exit_:.2f}  ({why})  "
                     f"{'+' if pnl >= 0 else ''}{pnl:.0f}$")
    acct = requests.get(f"{TRADE}/v2/account", headers=HDR, timeout=15).json()
    wr = f"{wins / done * 100:.0f}%" if done else "-"
    return (f"📊 דוח יומי {day}\n\n" + "\n".join(lines) +
            f"\n\nעסקאות: {done} | הצלחות: {wins} ({wr})\n"
            f"רווח/הפסד היום: {'+' if total >= 0 else ''}{total:.0f}$\n"
            f"יתרת חשבון דמו: ${float(acct.get('equity', 0)):,.0f}")


def build_signal(sym, pct, price, stop, now, demo=False, news=""):
    risk = price - stop
    target = price + RR * risk
    head = "🧪 סיגנל דמו (בדיקה בלבד)\n" if demo else ""
    return (f"{head}🚀 {sym}  +{pct:.1f}%\n{news}"
            f"כניסה בפריצה מעל: ${price:.2f}\n"
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
                elif text.startswith("/report"):
                    send_tg(daily_report(dt.datetime.now(NY).date()))
                elif text.startswith("/start") or text.startswith("/help"):
                    send_tg("פקודות:\n/test - סיגנל דמו לבדיקה שהכל עובד\n"
                            "/report - דוח מסחר הדמו של היום")
        except Exception as e:
            print("listener error:", e)
            time.sleep(5)


def main():
    threading.Thread(target=command_listener, daemon=True).start()
    day = None
    closed = reported = False
    send_tg("✅ הבוט פועל - סורק גאפים בפתיחת המסחר")
    while True:
        now = dt.datetime.now(NY)
        if now.date() != day:
            day = now.date()
            alerted = {t["symbol"] for t in load_trades(day)}
            pending = {}
            closed = reported = False
        if PAPER_TRADING and now.weekday() < 5:
            try:
                if not closed and now.time() >= EOD_CLOSE:
                    closed = close_all()  # אם לא הצליח - ינסה שוב בסיבוב הבא
                if not reported and now.time() >= EOD_REPORT:
                    reported = True
                    if market_was_open(day):
                        send_tg(daily_report(day))
            except Exception as e:
                print("eod error:", e)
        if not market_open(now) or now.time() >= EOD_CLOSE:
            time.sleep(60)
            continue
        open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
        in_window = now < open_t + dt.timedelta(minutes=SIGNAL_WINDOW_MIN)
        try:
            # 1) בדיקת פריצות שממתינות (מסחר דמו)
            for sym, t in list(pending.items()):
                if not in_window:
                    pending.pop(sym)
                    continue
                lp = last_price(sym)
                if lp >= t["price"]:
                    pending.pop(sym)
                    if lp > t["price"] * 1.02:      # קפץ רחוק מעל נקודת הכניסה - לא רודפים
                        print("skip chase", sym, lp)
                        continue
                    qty, err = place_bracket(sym, lp, t["stop"], t["target"])
                    t.update(qty=qty or 0, fill=lp, time=f"{now:%H:%M}")
                    if err:
                        t["err"] = err
                        print("paper order failed:", sym, err)
                    save_trade(str(day), t)
                elif lp <= t["stop"]:                 # נשבר לפני פריצה - מבטלים
                    pending.pop(sym)
            # 2) סיגנלים חדשים - רק בחלון הזמן
            if not in_window:
                time.sleep(SCAN_EVERY_SEC)
                continue
            for g in get_gainers():
                sym, pct, price = g["symbol"], g["percent_change"], g["price"]
                if sym in alerted or pct < MIN_GAP_PCT:
                    continue
                if MAX_GAP_PCT and pct > MAX_GAP_PCT:
                    continue
                if not (MIN_PRICE <= price <= MAX_PRICE):
                    continue
                bars = bars_today(sym, now)
                b = last_closed_bar(bars)
                if not b:
                    continue
                entry, stop = px(b["h"] + 0.01), b["l"]
                if price > entry * 1.02:              # כבר פרץ ורחוק - לא רודפים
                    continue
                entry = max(entry, px(price))
                risk = entry - stop
                if risk <= 0 or risk / entry * 100 > MAX_RISK_PCT:
                    continue
                if RR * risk / entry * 100 < MIN_TARGET_PCT:
                    continue
                if rvol(sym, now, bars) < MIN_RVOL:
                    continue
                news = news_since_last_close(sym, now)
                if REQUIRE_NEWS and not news:
                    continue
                alerted.add(sym)
                target = entry + RR * risk
                send_tg(build_signal(sym, pct, entry, stop, now, news=news_text(news)))
                if PAPER_TRADING:
                    pending[sym] = {"symbol": sym, "price": entry, "stop": stop, "target": target}
        except Exception as e:
            print("error:", e)
        time.sleep(SCAN_EVERY_SEC)


if __name__ == "__main__":
    main()
