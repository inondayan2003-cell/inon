"""
שרת קטן למיני-אפ של טלגרם.
מאזין על 127.0.0.1:8080; Caddy מול זה מספק https.
כל בקשת API מאומתת לפי initData של טלגרם - רק בעל הבוט רואה נתונים.
"""
import datetime as dt
import hashlib
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlparse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
URL_FILE = os.path.join(HERE, "webapp_url.txt")
PORT = 8080
bot = None  # מודול הבוט (מוזרק ב-start)


def check_init_data(init_data):
    """אימות חתימת טלגרם + שהמשתמש הוא בעל הבוט."""
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        got = pairs.pop("hash", "")
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret = hmac.new(b"WebAppData", bot.TG_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return False
        if time.time() - int(pairs.get("auth_date", 0)) > 7 * 86400:
            return False
        uid = json.loads(pairs.get("user", "{}")).get("id")
        return str(uid) == str(bot.TG_CHAT_ID)
    except Exception:
        return False


def market_clock():
    try:
        r = requests.get(f"{bot.TRADE}/v2/clock", headers=bot.HDR, timeout=10)
        return r.json() if r.ok else {}
    except Exception:
        return {}


def live_watchlist():
    items = [dict(i) for i in bot.LAST_WATCH["items"]]
    if items:
        try:
            r = requests.get(f"{bot.DATA}/v2/stocks/snapshots", headers=bot.HDR, timeout=10,
                             params={"symbols": ",".join(i["symbol"] for i in items), "feed": "iex"})
            snaps = r.json() if r.ok else {}
        except Exception:
            snaps = {}
        for i in items:
            try:
                p = snaps[i["symbol"]]["latestTrade"]["p"]
            except (KeyError, TypeError):
                p = None
            i["last"] = p
            if p is None:
                i["status"] = "unknown"
            elif p >= i["target"]:
                i["status"] = "target"
            elif p >= i["price"]:
                i["status"] = "broke"
            elif p <= i["stop"]:
                i["status"] = "stopped"
            else:
                i["status"] = "waiting"
    return {"time": bot.LAST_WATCH["time"], "items": items}


def portfolio():
    """מצב תיק הדמו: חשבון, פוזיציות פתוחות, פריצות שממתינות, עסקאות היום והיסטוריה מההתחלה."""
    import re
    out = {"account": None, "positions": [], "pending": list(getattr(bot, "PENDING_VIEW", [])),
           "today": [], "days": [], "totals": None}
    try:
        a = requests.get(f"{bot.TRADE}/v2/account", headers=bot.HDR, timeout=10).json()
        eq, last = float(a.get("equity", 0)), float(a.get("last_equity", 0))
        out["account"] = {"equity": eq, "day_pl": eq - last if last else 0}
        pos = requests.get(f"{bot.TRADE}/v2/positions", headers=bot.HDR, timeout=10).json()
        out["positions"] = [{"symbol": p["symbol"], "qty": float(p["qty"]),
                             "entry": float(p["avg_entry_price"]), "last": float(p["current_price"]),
                             "pl": float(p["unrealized_pl"]), "plpc": float(p["unrealized_plpc"]) * 100}
                            for p in pos]
    except Exception as e:
        out["account_error"] = str(e)[:120]
    today = str(dt.datetime.now(bot.NY).date())
    days, allt = [], []
    try:
        files = sorted(f for f in os.listdir(bot.TRADES_DIR) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f))
    except FileNotFoundError:
        files = []
    for f in files:
        d = f[:-5]
        trades = bot.load_trades(d)
        if d == today:
            out["today"] = [{k: t.get(k) for k in ("symbol", "source", "score", "time", "price", "stop",
                                                  "target", "qty", "pnl", "result", "err")} for t in trades]
        done = [t for t in trades if isinstance(t.get("pnl"), (int, float))]
        if done:
            days.append({"date": d, "n": len(done), "wins": sum(t["pnl"] > 0 for t in done),
                         "pnl": round(sum(t["pnl"] for t in done), 2)})
            allt += done
    out["days"] = days
    if allt:
        w = [t["pnl"] for t in allt if t["pnl"] > 0]
        l = [t["pnl"] for t in allt if t["pnl"] <= 0]
        out["totals"] = {"n": len(allt), "wins": len(w), "targets": sum(t.get("result") == "יעד" for t in allt),
                         "pnl": round(sum(w) + sum(l), 2), "avg_win": round(sum(w) / len(w), 1) if w else 0,
                         "avg_loss": round(sum(l) / len(l), 1) if l else 0, "since": days[0]["date"]}
    return out


def refresh_watchlist():
    now = dt.datetime.now(bot.NY)
    closed = bot.closed_today_text(now)
    if closed:
        return {"error": closed}
    if not (dt.time(4, 0) <= now.time() < dt.time(9, 30)):
        return {"error": "חישוב רשימה חדשה אפשרי רק במסחר המוקדם (11:00 עד הפתיחה, שעון ישראל). "
                         "מוצגת הרשימה האחרונה."}
    bot.watchlist_items(now)
    return {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _auth(self):
        if check_init_data(self.headers.get("X-Init-Data", "")):
            return True
        self._send(403, {"error": "אין הרשאה - פתח את האפליקציה מתוך הבוט בטלגרם"})
        return False

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if not path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        if not self._auth():
            return
        if path == "/api/state":
            return self._send(200, {"server_now": time.time(), "clock": market_clock(),
                                    "settings": bot.get_settings()})
        if path == "/api/watchlist":
            return self._send(200, live_watchlist())
        if path == "/api/portfolio":
            return self._send(200, portfolio())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._auth():
            return
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if path == "/api/settings":
            try:
                return self._send(200, {"settings": bot.apply_settings(body)})
            except Exception as e:
                return self._send(400, {"error": str(e)})
        if path == "/api/watchlist/refresh":
            res = refresh_watchlist()
            res.update(live_watchlist())
            return self._send(200, res)
        self._send(404, {"error": "not found"})


def start(bot_module):
    """מפעיל את השרת ברקע. מחזיר את כתובת ה-https אם הוגדרה."""
    global bot
    bot = bot_module
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with open(URL_FILE) as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None
