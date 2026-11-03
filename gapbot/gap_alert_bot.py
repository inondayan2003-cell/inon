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
WATCHLIST_TIME = dt.time(8, 30)  # רשימת מעקב לפני הפתיחה (שעון ניו יורק)
WATCHLIST_SIZE = 5
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
    r"\bdowngrades?\b|\bdowngraded\b",
    r"\b(lowers|cuts|reduces|adjusts?|maintains|reiterates)\b.*\bprice target\b",
    r"\banalysts? (adjust|weigh|react|see)\b|\bearnings call transcript\b|\btranscript\b",
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


def all_news_since_last_close(now, pages=4):
    d = now.date() - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    start = dt.datetime.combine(d, dt.time(16, 0), NY)
    out, token = [], None
    for _ in range(pages):
        params = {"start": start.isoformat(), "limit": 50, "sort": "desc"}
        if token:
            params["page_token"] = token
        r = requests.get(f"{DATA}/v1beta1/news", headers=HDR, params=params, timeout=15)
        r.raise_for_status()
        j = r.json()
        out += j.get("news") or []
        token = j.get("next_page_token")
        if not token:
            break
    return meaningful(out)


def build_watchlist(now):
    news = all_news_since_last_close(now)
    by_sym = {}
    for n in news:
        for sym in n.get("symbols") or []:
            by_sym.setdefault(sym, n)            # החדשה הכי עדכנית לכל מניה
    try:
        for g in get_gainers():
            by_sym.setdefault(g["symbol"], None)
    except Exception:
        pass
    syms = list(by_sym)
    snaps = {}
    for i in range(0, len(syms), 100):
        r = requests.get(f"{DATA}/v2/stocks/snapshots", headers=HDR, timeout=20,
                         params={"symbols": ",".join(syms[i:i + 100]), "feed": "iex"})
        if r.ok:
            snaps.update(r.json())
    pre_start = now.replace(hour=4, minute=0, second=0, microsecond=0)
    rows = []
    for sym, sn in snaps.items():
        try:
            price = sn["latestTrade"]["p"]
            prev = sn["prevDailyBar"]["c"]
        except (KeyError, TypeError):
            continue
        pct = (price / prev - 1) * 100
        if pct < MIN_GAP_PCT or not (MIN_PRICE <= price <= MAX_PRICE):
            continue
        n = by_sym.get(sym) or (news_since_last_close(sym, now) or [None])[0]
        if REQUIRE_NEWS and not n:
            continue
        rows.append([sym, pct, price, prev, n])
    rows.sort(key=lambda x: -x[1])
    rows = rows[:WATCHLIST_SIZE]
    for row in rows:           # גבוה/נמוך של המסחר המוקדם
        sym, price = row[0], row[2]
        try:
            r = requests.get(f"{DATA}/v2/stocks/{sym}/bars", headers=HDR, timeout=15,
                             params={"timeframe": "1Min", "start": pre_start.isoformat(),
                                     "feed": "iex", "limit": 1000})
            bars = r.json().get("bars") or []
        except Exception:
            bars = []
        if not bars:               # אין מסחר מוקדם היום - אין רמות אמיתיות
            row.append(None)
            continue
        hi = max([b["h"] for b in bars] + [price])
        lo = min([b["l"] for b in bars] + [price])
        row += [hi, lo]
    return [r for r in rows if r[-1] is not None]


def closed_today_text(now):
    """אם השוק בארה"ב סגור היום - מחזיר הודעה עם מועד הפתיחה הבא, אחרת None."""
    if now.weekday() < 5 and market_was_open(now.date()):
        return None
    why = "סוף שבוע" if now.weekday() >= 5 else "חג בארה\"ב"
    try:
        nxt = requests.get(f"{TRADE}/v2/clock", headers=HDR, timeout=15).json()["next_open"]
        nxt = dt.datetime.fromisoformat(nxt.replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Jerusalem"))
        days = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        when = f"\nהפתיחה הבאה: יום {days[nxt.weekday()]} {nxt:%d/%m} ב-{nxt:%H:%M} (שעון ישראל)"
    except Exception:
        when = ""
    return f"🔒 השוק בארה\"ב סגור היום ({why}).{when}"


LAST_WATCH = {"time": None, "items": []}   # הרשימה האחרונה שחושבה (למיני-אפ)


def watchlist_items(now):
    """מחשב את רשימת המעקב כרשימת מילונים עם רמות."""
    items = []
    for sym, pct, price, prev, n, hi, lo in build_watchlist(now):
        level = px(hi + 0.01)
        stop = lo if (level - lo) / level * 100 <= MAX_RISK_PCT else px(level * (1 - MAX_RISK_PCT / 100))
        stop = min(stop, px(level * (1 - MIN_TARGET_PCT / RR / 100)))   # יעד של לפחות MIN_TARGET_PCT
        target = px(level + RR * (level - stop))
        h = (n or {}).get("headline", "")
        items.append({"symbol": sym, "gap_pct": round(pct, 1), "pre_price": price, "prev_close": prev,
                      "price": level, "stop": stop, "target": target,
                      "risk_pct": round((level - stop) / level * 100, 2),
                      "headline": h[:200], "url": (n or {}).get("url", ""),
                      "dilution": any(k in h.lower() for k in DILUTION)})
    LAST_WATCH.update(time=now.isoformat(), items=items)
    return items


def watchlist_text(now, levels=None):
    closed = closed_today_text(now)
    if closed:
        return closed
    if not (now.weekday() < 5 and dt.time(4, 0) <= now.time() < dt.time(9, 30)):
        return ("📋 רשימת מעקב זמינה רק בימי מסחר בין 11:00 לפתיחה (שעון ישראל).\n"
                "עכשיו אין מסחר מוקדם, אז אין רמות אמיתיות לחשב.")
    items = watchlist_items(now)
    open_il = now.replace(hour=9, minute=30).astimezone(ZoneInfo("Asia/Jerusalem"))
    if not items:
        return f"📋 רשימת מעקב להיום\nאין הבוקר מניות עם חדשה + עלייה של {MIN_GAP_PCT:.0f}%+ במסחר המוקדם."
    out = [f"📋 רשימת מעקב להיום (פתיחה ב-{open_il:%H:%M})\n"]
    for i, it in enumerate(items, 1):
        if levels is not None:
            levels.append({"symbol": it["symbol"], "price": it["price"], "stop": it["stop"],
                           "target": it["target"], "source": "watchlist", "signal_time": "pre",
                           "gap_pct": it["gap_pct"], "risk_pct": it["risk_pct"],
                           "headline": it["headline"]})
        flag = " 🚩דילול?" if it["dilution"] else ""
        out.append(f"{i}. {it['symbol']}  +{it['gap_pct']:.1f}%  (עכשיו ${it['pre_price']:.2f})\n"
                   f"📰 {it['headline'][:120]}{flag}\n"
                   f"🎯 פריצה מעל: ${it['price']:.2f} | סטופ: ${it['stop']:.2f} | יעד: ${it['target']:.2f}\n")
    out.append("⚠️ לא הוראת קנייה - רמות להכנה. בבלינק עדיף Buy Stop/Limit ולא פקודת שוק לפתיחה.")
    return "\n".join(out)


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
    by_src = {}
    for t in trades:
        tag = "📋" if t.get("source") == "watchlist" else "⚡"
        a = agg.get(t["symbol"])
        if not a or not a["bq"]:
            lines.append(f"{tag}⚪ {t['symbol']} - לא בוצע")
            continue
        entry = a["bv"] / a["bq"]
        exit_ = a["sv"] / a["sq"] if a["sq"] else None
        if exit_ is None:
            lines.append(f"{tag}⏳ {t['symbol']} - עדיין פתוחה (כניסה ${entry:.2f})")
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
        t.update(entry_fill=round(entry, 4), exit_fill=round(exit_, 4),
                 pnl=round(pnl, 2), result=why)
        b = by_src.setdefault(tag, [0, 0, 0.0])
        b[0] += 1; b[1] += pnl > 0; b[2] += pnl
        lines.append(f"{tag}{icon} {t['symbol']}  ${entry:.2f} → ${exit_:.2f}  ({why})  "
                     f"{'+' if pnl >= 0 else ''}{pnl:.0f}$")
    with open(trades_file(day), "w") as f:
        json.dump(trades, f, ensure_ascii=False, indent=1)
    acct = requests.get(f"{TRADE}/v2/account", headers=HDR, timeout=15).json()
    wr = f"{wins / done * 100:.0f}%" if done else "-"
    names = {"📋": "רשימת מעקב", "⚡": "סיגנלים בזמן אמת"}
    src_lines = "".join(f"{k} {names[k]}: {v[0]} עסקאות | הצלחות: {v[1]} | "
                        f"{'+' if v[2] >= 0 else ''}{v[2]:.0f}$\n" for k, v in by_src.items())
    return (f"📊 דוח יומי {day}\n\n" + "\n".join(lines) + "\n\n" + src_lines +
            f"\nעסקאות: {done} | הצלחות: {wins} ({wr})\n"
            f"רווח/הפסד היום: {'+' if total >= 0 else ''}{total:.0f}$\n"
            f"יתרת חשבון דמו: ${float(acct.get('equity', 0)):,.0f}")


def export_csv():
    import csv
    cols = ["date", "source", "symbol", "signal_time", "time", "gap_pct", "rvol", "risk_pct", "price",
            "stop", "target", "qty", "entry_fill", "exit_fill", "pnl", "result", "headline", "err"]
    path = os.path.join(TRADES_DIR, "all_trades.csv")
    os.makedirs(TRADES_DIR, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for fn in sorted(os.listdir(TRADES_DIR)):
            if fn.endswith(".json"):
                for t in load_trades(fn[:-5]):
                    w.writerow({"date": fn[:-5], **t})
    with open(path, "rb") as f:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendDocument",
                      data={"chat_id": TG_CHAT_ID, "caption": "📁 כל עסקאות הדמו"},
                      files={"document": ("trades.csv", f)}, timeout=30)


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
                elif text.startswith("/watch"):
                    send_tg(watchlist_text(dt.datetime.now(NY)))
                elif text.startswith("/export"):
                    export_csv()
                elif text.startswith("/report"):
                    send_tg(daily_report(dt.datetime.now(NY).date()))
                elif text.startswith("/start") or text.startswith("/help"):
                    send_tg("פקודות:\n/test - סיגנל דמו לבדיקה שהכל עובד\n"
                            "/report - דוח מסחר הדמו של היום\n"
                            "/watch - רשימת מעקב (מניות עם חדשות שעולות)\n"
                            "/export - קובץ אקסל עם כל עסקאות הדמו")
        except Exception as e:
            print("listener error:", e)
            time.sleep(5)


def set_commands():
    cmds = [{"command": "test", "description": "סיגנל דמו - בדיקה שהכל עובד"},
            {"command": "watch", "description": "רשימת מעקב - מניות עם חדשות שעולות"},
            {"command": "report", "description": "דוח מסחר הדמו של היום"},
            {"command": "export", "description": "קובץ אקסל עם כל עסקאות הדמו"},
            {"command": "help", "description": "רשימת הפקודות"}]
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/setMyCommands",
                      json={"commands": cmds}, timeout=15)
    except Exception as e:
        print("setMyCommands error:", e)


SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
EDITABLE = {  # שם: (סוג, מינימום, מקסימום)
    "MIN_GAP_PCT": (float, 1, 200), "MAX_GAP_PCT": (float, 0, 1000),
    "MIN_PRICE": (float, 0.1, 1000), "MAX_PRICE": (float, 0.5, 5000),
    "MIN_TARGET_PCT": (float, 0, 100), "MAX_RISK_PCT": (float, 0.5, 50),
    "RR": (float, 0.5, 20), "MIN_RVOL": (float, 0, 50),
    "SIGNAL_WINDOW_MIN": (int, 5, 390), "WATCHLIST_SIZE": (int, 1, 20),
    "REQUIRE_NEWS": (bool, None, None), "PAPER_TRADING": (bool, None, None),
    "RISK_PER_TRADE": (float, 1, 100000), "MAX_POSITION": (float, 10, 1000000),
}


def get_settings():
    g = globals()
    return {k: g[k] for k in EDITABLE}


def apply_settings(new, save=True):
    g = globals()
    for k, v in new.items():
        if k not in EDITABLE:
            continue
        typ, lo, hi = EDITABLE[k]
        v = (v in (True, "true", "1", 1)) if typ is bool else typ(v)
        if lo is not None:
            v = min(max(v, lo), hi)
        g[k] = v
    if save:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(get_settings(), f, indent=1)
    return get_settings()


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            apply_settings(json.load(f), save=False)
    except FileNotFoundError:
        pass
    except Exception as e:
        print("settings load error:", e)


def start_webapp():
    try:
        import sys
        import webapp
        url = webapp.start(sys.modules[__name__])
        if url:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/setChatMenuButton", timeout=15,
                          json={"chat_id": int(TG_CHAT_ID), "menu_button": {
                              "type": "web_app", "text": "📊 אפליקציה", "web_app": {"url": url}}})
    except Exception as e:
        print("webapp error:", e)


def main():
    load_settings()
    start_webapp()
    set_commands()
    threading.Thread(target=command_listener, daemon=True).start()
    day = None
    closed = reported = watched = False
    send_tg("✅ הבוט פועל - סורק גאפים בפתיחת המסחר")
    while True:
        now = dt.datetime.now(NY)
        if now.date() != day:
            day = now.date()
            traded = {t["symbol"] for t in load_trades(day)}
            alerted = {t["symbol"] for t in load_trades(day) if t.get("source") != "watchlist"}
            pending = {}
            closed = reported = watched = False
        if not watched and now.weekday() < 5 and WATCHLIST_TIME <= now.time() < dt.time(9, 30):
            watched = True
            try:
                if not market_was_open(day):
                    send_tg(closed_today_text(now))
                else:
                    lv = []
                    send_tg(watchlist_text(now, lv))
                    if PAPER_TRADING:
                        for t in lv:
                            pending[t["symbol"] + ":w"] = t
            except Exception as e:
                print("watchlist error:", e)
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
            for key, t in list(pending.items()):
                sym = t["symbol"]
                if not in_window or sym in traded:
                    pending.pop(key)
                    continue
                lp = last_price(sym)
                if lp >= t["price"]:
                    pending.pop(key)
                    if lp > t["price"] * 1.02:      # קפץ רחוק מעל נקודת הכניסה - לא רודפים
                        print("skip chase", sym, lp)
                        continue
                    qty, err = place_bracket(sym, lp, t["stop"], t["target"])
                    t.update(qty=qty or 0, fill=lp, time=f"{now:%H:%M}")
                    if err:
                        t["err"] = err
                        print("paper order failed:", sym, err)
                    traded.add(sym)
                    save_trade(str(day), t)
                elif lp <= t["stop"]:                 # נשבר לפני פריצה - מבטלים
                    pending.pop(key)
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
                rv = rvol(sym, now, bars)
                if rv < MIN_RVOL:
                    continue
                news = news_since_last_close(sym, now)
                if REQUIRE_NEWS and not news:
                    continue
                alerted.add(sym)
                target = entry + RR * risk
                send_tg(build_signal(sym, pct, entry, stop, now, news=news_text(news)))
                if PAPER_TRADING:
                    pending[sym] = {"symbol": sym, "source": "signal", "price": entry, "stop": stop, "target": target,
                                    "signal_time": f"{now:%H:%M}", "gap_pct": round(pct, 1),
                                    "rvol": round(rv, 1), "risk_pct": round(risk / entry * 100, 2),
                                    "headline": (news[0].get("headline", "") if news else "")[:200]}
        except Exception as e:
            print("error:", e)
        time.sleep(SCAN_EVERY_SEC)


if __name__ == "__main__":
    main()
