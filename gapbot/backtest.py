"""
בדיקה לאחור (Backtest) של אסטרטגיית הסיגנלים על X ימי מסחר אחרונים.
משחזר את מה שהבוט היה עושה בזמן אמת: גאפ, נר 5 דק' סגור, פריצה, ווליום יחסי, חדשות, ציון,
ואז כניסה בפריצה עם תקרה, סטופ/יעד/סגירת יום - לפי נרות 5 דקות היסטוריים (SIP).
רץ בשרת (ל-Alpaca יש מגבלה של ~200 קריאות לדקה, אז זה לוקח 15-40 דקות).
"""
import csv
import datetime as dt
import math
import os
import time
from collections import defaultdict

import requests

EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"}
PAUSE = 0.35          # ~170 קריאות לדקה
bot = None


def _get(url, params=None, tries=5):
    for i in range(tries):
        time.sleep(PAUSE)
        try:
            r = requests.get(url, headers=bot.HDR, params=params, timeout=30)
        except Exception:
            time.sleep(5)
            continue
        if r.status_code == 429:
            time.sleep(20 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Alpaca לא עונה: {url}")


def _paged(url, params, key):
    """מאחד את כל הדפים של תשובה (next_page_token)."""
    params = dict(params)
    out = defaultdict(list) if key == "bars" else []
    while True:
        j = _get(url, params)
        data = j.get(key) or ({} if key == "bars" else [])
        if key == "bars":
            for s, b in data.items():
                out[s].extend(b)
        else:
            out.extend(data)
        tok = j.get("next_page_token")
        if not tok:
            return out
        params["page_token"] = tok


def _ny(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(bot.NY)


def simulate_symbol(sym, bars, prev_close, avg_vol, news, o, c, S):
    """מריץ את לוגיקת הבוט על מניה אחת ביום אחד. מחזיר עסקה או None."""
    window_end = o + dt.timedelta(minutes=S["SIGNAL_WINDOW_MIN"])
    eod = c - dt.timedelta(minutes=5)
    times = [_ny(b["t"]) for b in bars]
    sig = None
    retry_after = None
    for k in range(1, len(bars)):
        T = times[k]                       # רגע הסריקה: תחילת נר k (נר k-1 נסגר)
        if T >= window_end:
            break
        if retry_after and T < retry_after:
            continue
        b = bars[k - 1]
        price = b["c"]
        pct = (price / prev_close - 1) * 100
        if pct < S["MIN_GAP_PCT"] or (S["MAX_GAP_PCT"] and pct > S["MAX_GAP_PCT"]):
            continue
        if not (S["MIN_PRICE"] <= price <= S["MAX_PRICE"]):
            continue
        entry, stop = bot.px(b["h"] + 0.01), b["l"]
        if price > entry * 1.02:
            continue
        entry = max(entry, bot.px(price))
        risk = entry - stop
        if risk <= 0 or risk / entry * 100 > S["MAX_RISK_PCT"] or S["RR"] * risk / entry * 100 < S["MIN_TARGET_PCT"]:
            continue
        mins = (T - o).total_seconds() / 60
        rv = sum(x["v"] for x in bars[:k]) / (avg_vol * max(mins / 390, 0.05)) if avg_vol else 0
        if rv < S["MIN_RVOL"]:
            continue
        hl = [n for n in news if _ny(n["created_at"]) <= T]
        if S["REQUIRE_NEWS"] and not hl:
            retry_after = T + dt.timedelta(minutes=15)
            continue
        sc = bot.score_signal([n.get("headline", "") for n in hl], risk / entry * 100, entry,
                              T >= o + dt.timedelta(minutes=10), rv)
        sig = dict(symbol=sym, signal_time=f"{T:%H:%M}", gap_pct=round(pct, 1), rvol=round(rv, 1),
                   risk_pct=round(risk / entry * 100, 2), price=entry, stop=stop,
                   target=bot.px(entry + S["RR"] * risk), score=sc,
                   headline=(hl[-1].get("headline", "") if hl else "")[:200], k=k)
        break
    if not sig:
        return None

    # כניסה בפריצה (עם תקרה כמו בבוט), ביטול אם נשבר לסטופ לפני או אם נגמר החלון
    entry, stop, target = sig["price"], sig["stop"], sig["target"]
    limit = entry * (1 + bot.ENTRY_LIMIT_PCT / 100)
    fill = fill_j = None
    for j in range(sig["k"], len(bars)):
        bj = bars[j]
        if times[j] >= window_end:
            break
        if bj["h"] >= entry:
            if bj["l"] <= stop and bj["o"] < entry:     # באותו נר ירד לסטופ ועלה - לא ודאי, שמרני: מבטל
                break
            if bj["o"] > entry * 1.02:                 # נפתח רחוק מעל הפריצה - הבוט לא רודף
                break
            fill, fill_j = min(max(entry, bj["o"]), limit), j
            break
        if bj["l"] <= stop:
            break
    sig.pop("k")
    if fill is None:
        return dict(sig, result="לא נכנס", entry_fill="", exit_fill="", pnl="", qty=0)

    qty = math.floor(min(bot.RISK_PER_TRADE / (fill - stop), bot.MAX_POSITION / fill)) if fill > stop else 0
    if qty < 1:
        return dict(sig, result="לא נכנס", entry_fill="", exit_fill="", pnl="", qty=0)
    exit_p, why = None, None
    if bars[fill_j]["c"] <= stop:                      # נכנס ונפל לסטופ באותו נר
        exit_p, why = stop, "סטופ"
    for m in range(fill_j + 1, len(bars)):
        if exit_p is not None:
            break
        bm = bars[m]
        if times[m] >= eod:
            exit_p, why = bm["o"], "סגירת יום"
        elif bm["l"] <= stop:                          # אם גם סטופ וגם יעד באותו נר - מניחים סטופ (שמרני)
            exit_p, why = min(stop, bm["o"]), "סטופ"
        elif bm["h"] >= target:
            exit_p, why = max(target, bm["o"]), "יעד"
    if exit_p is None:
        exit_p, why = bars[-1]["c"], "סגירת יום"
    return dict(sig, result=why, entry_fill=round(fill, 4), exit_fill=round(exit_p, 4),
                pnl=round((exit_p - fill) * qty, 2), qty=qty)


def _stats(rows):
    done = [r for r in rows if r["pnl"] != ""]
    if not done:
        return "0 עסקאות"
    p = [r["pnl"] for r in done]
    w = [x for x in p if x > 0]
    return (f"{len(done)} עסקאות | ברווח {len(w) / len(done) * 100:.0f}% | "
            f"יעד {sum(r['result'] == 'יעד' for r in done)} | {sum(p):+,.0f}$ ({sum(p) / len(done):+.0f}$ לעסקה)")


def summary(rows, days, first, last):
    done = [r for r in rows if r["pnl"] != ""]
    out = [f"🧪 בדיקה לאחור: {days} ימי מסחר ({first} עד {last})",
           f"סיגנלים: {len(rows)} | נכנסו: {len(done)}",
           f"סה\"כ: {_stats(rows)}", "", "לפי ציון:"]
    for lo, hi in ((1, 5), (6, 7), (8, 10)):
        out.append(f"  {lo}-{hi}: {_stats([r for r in done if lo <= r['score'] <= hi])}")
    out.append("סף מינימלי:")
    for th in (6, 7, 8, 9):
        out.append(f"  {th}+: {_stats([r for r in done if r['score'] >= th])}")
    groups = [
        ("סטופ", lambda r: "עד 4%" if r["risk_pct"] <= 4 else ("4-5.5%" if r["risk_pct"] <= 5.5 else "מעל 5.5%")),
        ("מחיר", lambda r: "<$2" if r["price"] < 2 else ("$2-5" if r["price"] < 5 else ">$5")),
        ("חדשה", lambda r: "דוחות" if bot.EARN_RE.search(r["headline"]) else
            ("קטליסט" if bot.CAT_RE.search(r["headline"]) else "אחר")),
        ("שעה", lambda r: "עד 9:40" if r["signal_time"] < "09:40" else "אחרי 9:40"),
    ]
    for name, fn in groups:
        out.append(f"\nלפי {name}:")
        g = defaultdict(list)
        for r in done:
            g[fn(r)].append(r)
        for k, v in g.items():
            out.append(f"  {k}: {_stats(v)}")
    out.append("\n⚠️ סימולציה על נרות 5 דק'. בלי מניות שנמחקו מהבורסה ובלי עמלות - התוצאה האמיתית תהיה מעט חלשה יותר.")
    return "\n".join(out)


def run(bot_module, days=200, notify=print):
    global bot
    bot = bot_module
    S = bot.get_settings()
    today = dt.datetime.now(bot.NY).date()
    cal = _get(f"{bot.TRADE}/v2/calendar",
               {"start": str(today - dt.timedelta(days=int(days * 1.6) + 60)),
                "end": str(today - dt.timedelta(days=1))})
    sessions = {d["date"]: (dt.datetime.combine(dt.date.fromisoformat(d["date"]), dt.time.fromisoformat(d["open"]), bot.NY),
                            dt.datetime.combine(dt.date.fromisoformat(d["date"]), dt.time.fromisoformat(d["close"]), bot.NY))
                for d in cal}
    all_days = sorted(sessions)
    test_days = set(all_days[-days:])
    first, last = all_days[-days], all_days[-1]

    assets = _get(f"{bot.TRADE}/v2/assets", {"asset_class": "us_equity"})
    syms = sorted({a["symbol"] for a in assets if a.get("exchange") in EXCHANGES
                   and a["symbol"].isalpha() and len(a["symbol"]) <= 5})
    notify(f"🧪 בדיקה לאחור התחילה: {days} ימים, {len(syms)} מניות. שלב 1/2 - מחפש גאפים...")

    # שלב 1: נרות יומיים -> ימים שבהם מניה עלתה 10%+ מעל הסגירה הקודמת
    cands = defaultdict(list)       # יום -> [(מניה, סגירה קודמת, ממוצע ווליום 20 יום)]
    start = all_days[max(0, len(all_days) - days - 25)]
    for i in range(0, len(syms), 100):
        batch = syms[i:i + 100]
        bars = _paged(f"{bot.DATA}/v2/stocks/bars",
                      {"symbols": ",".join(batch), "timeframe": "1Day", "start": start,
                       "end": last, "feed": "sip", "limit": 10000, "adjustment": "split"}, "bars")
        for s, bl in bars.items():
            for n in range(20, len(bl)):
                d = bl[n]["t"][:10]
                prev = bl[n - 1]["c"]
                if d in test_days and prev > 0 and bl[n]["h"] >= prev * (1 + S["MIN_GAP_PCT"] / 100) \
                        and bl[n]["l"] <= S["MAX_PRICE"] and bl[n]["h"] >= S["MIN_PRICE"]:
                    cands[d].append((s, prev, sum(x["v"] for x in bl[n - 20:n]) / 20))
        if (i // 100) % 15 == 14:
            notify(f"🧪 שלב 1: {min(i + 100, len(syms))}/{len(syms)} מניות נסרקו")

    total = sum(len(v) for v in cands.values())
    notify(f"🧪 שלב 2/2: {total} ימי-גאפ נמצאו. מריץ את הבוט על כל אחד...")

    # שלב 2: לכל יום - נרות 5 דק' + חדשות של המועמדים, וסימולציה
    rows = []
    for n, d in enumerate(sorted(cands)):
        o, c = sessions[d]
        dd = dt.date.fromisoformat(d)
        prev_d = all_days[all_days.index(d) - 1]
        news_start = sessions[prev_d][1]
        group = cands[d]
        for i in range(0, len(group), 50):
            part = group[i:i + 50]
            ss = ",".join(x[0] for x in part)
            bars = _paged(f"{bot.DATA}/v2/stocks/bars",
                          {"symbols": ss, "timeframe": "5Min", "start": o.isoformat(), "end": c.isoformat(),
                           "feed": "sip", "limit": 10000, "adjustment": "split"}, "bars")
            news = _paged(f"{bot.DATA}/v1beta1/news",
                          {"symbols": ss, "start": news_start.isoformat(), "end": c.isoformat(),
                           "limit": 50, "sort": "asc"}, "news")
            news = bot.meaningful(news)
            by_sym = defaultdict(list)
            for it in news:
                for s in it.get("symbols") or []:
                    by_sym[s].append(it)
            for s, prev, avg in part:
                bl = bars.get(s) or []
                if len(bl) < 3:
                    continue
                t = simulate_symbol(s, bl, prev, avg, by_sym.get(s, []), o, c, S)
                if t:
                    t["date"] = d
                    rows.append(t)
        if n % 40 == 39:
            notify(f"🧪 שלב 2: {n + 1}/{len(cands)} ימים, {len(rows)} סיגנלים עד עכשיו")
        del dd

    path = os.path.join(bot.TRADES_DIR, f"backtest_{days}d.csv")
    os.makedirs(bot.TRADES_DIR, exist_ok=True)
    cols = ["date", "symbol", "score", "signal_time", "gap_pct", "rvol", "risk_pct", "price", "stop",
            "target", "qty", "entry_fill", "exit_fill", "pnl", "result", "headline"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["date"], r["signal_time"])))
    return summary(rows, days, first, last), path
