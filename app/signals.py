"""בדיקת סיגנלים של קבוצות טלגרם: מפענחים הודעה כמו
    Gold buy @ 4003 - 3995 / Sl @ 3988 / Tp1 @ 4006 ... Tp4 @ 4015
ובודקים מה באמת קרה במחיר אחרי שעת השליחה המקורית (נרות דקה מ-Twelve Data).
"""
import logging
import re
import time

import pandas as pd

log = logging.getLogger(__name__)

NUM = r"(\d{3,5}(?:\.\d+)?)"


def parse_signal(text: str) -> dict | None:
    """מזהה סיגנל זהב בכמה פורמטים נפוצים, למשל:
    'Gold buy @ 4003 - 3995 / Sl @ 3988 / Tp1 @ 4006'  או
    'Product: Gold (XAUUSD) / 🟢BUY：4130-4120 / 🎯 TP1: 4135 / ⛔️ SL: 4110'."""
    t = (text.replace("\u200f", "").replace("\u200e", "").replace("：", ":").replace("－", "-")
         .replace("–", "-").replace("—", "-"))
    if not re.search(r"gold|xau", t, re.I):
        return None
    m = re.search(rf"\b(buy|sell)\b[^\d\n]{{0,25}}{NUM}(?:\s*(?:-|/|to)\s*{NUM})?", t, re.I)
    sl = re.search(rf"\bs\.?\s*l\b[^\d\n]{{0,10}}{NUM}", t, re.I)
    tps = [float(x) for x in re.findall(rf"\bt\.?\s*p\s*\d?\b[^\d\n]{{0,10}}{NUM}", t, re.I)]
    if not m or not sl or not tps:
        return None
    d = 1 if m.group(1).lower() == "buy" else -1
    a = float(m.group(2))
    b = float(m.group(3)) if m.group(3) else a
    sig = {"direction": d, "zone_hi": max(a, b), "zone_lo": min(a, b), "sl": float(sl.group(1)), "tps": tps}
    # בדיקת שפיות: סטופ בצד הנכון והיעדים בכיוון העסקה
    entry = sig["zone_hi"] if d == 1 else sig["zone_lo"]
    if (entry - sig["sl"]) * d <= 0 or any((tp - entry) * d <= 0 for tp in tps):
        return None
    return sig


def evaluate(sig: dict, bars: pd.DataFrame, hours: float = 24) -> dict:
    """bars = נרות דקה מהשליחה והלאה. כניסה בנגיעה הראשונה באזור (הקצה הקרוב), סטופ אחד לכל החלקים,
    חלוקה שווה בין היעדים. גם גרסה של 'סטופ לכניסה אחרי TP1'. סטופ נבדק לפני יעד באותו נר."""
    d, sl, tps = sig["direction"], sig["sl"], sig["tps"]
    near = sig["zone_hi"] if d == 1 else sig["zone_lo"]
    far = sig["zone_lo"] if d == 1 else sig["zone_hi"]
    bars = bars[bars.index < bars.index[0] + pd.Timedelta(hours=hours)] if len(bars) else bars
    hi, lo = bars["high"].to_numpy(), bars["low"].to_numpy()
    touch = (lo <= near) if d == 1 else (hi >= near)
    if not len(bars) or not touch.any():
        return {"filled": False}
    i0 = int(touch.argmax())
    entry = near
    deep = ((lo[i0:] <= far) if d == 1 else (hi[i0:] >= far)).any()
    risk = abs(entry - sl)
    hit, stopped, be_stopped, n_hit_be = [], False, False, 0
    for j in range(i0, len(bars)):
        if (lo[j] <= sl) if d == 1 else (hi[j] >= sl):
            stopped = True
            break
        while len(hit) < len(tps) and ((hi[j] >= tps[len(hit)]) if d == 1 else (lo[j] <= tps[len(hit)])):
            hit.append(j)
        if len(hit) == len(tps):
            break
    # גרסת "סטופ לכניסה אחרי TP1"
    if hit:
        for j in range(hit[0] + 1, len(bars)):
            n_hit_be = sum(1 for h in hit if h <= j)
            if (lo[j] <= entry) if d == 1 else (hi[j] >= entry):
                be_stopped = True
                break
            if n_hit_be == len(tps):
                break
        n_hit_be = n_hit_be if be_stopped else len(hit)
    k = len(tps)
    gains = [abs(tp - entry) / risk for tp in tps]
    last = float(bars["close"].iloc[-1])
    open_r = (last - entry) * d / risk
    if stopped:
        r_split = (sum(gains[: len(hit)]) - (k - len(hit))) / k
    else:
        r_split = (sum(gains[: len(hit)]) + (k - len(hit)) * open_r) / k
    r_be = (sum(gains[:n_hit_be])) / k if hit else r_split
    return {"filled": True, "entry": entry, "deep_fill": bool(deep), "risk": round(risk, 2), "tp_hits": len(hit),
            "stopped": stopped, "r_split": round(r_split, 2), "r_be": round(r_be, 2),
            "r_tp1_only": round(gains[0] if hit else (-1.0 if stopped else open_r), 2),
            "rr": [round(g, 2) for g in gains], "fill_minutes": i0}


def _html_text(fragment: str) -> str:
    import html
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t).strip()


def parse_channel_page(page: str) -> list[dict]:
    """עמוד t.me/s/<ערוץ>: מחזיר [{id, t, text}] לכל הודעה (טקסט ושעת פרסום ב-UTC)."""
    out = []
    for block in re.split(r'(?=<div class="tgme_widget_message_wrap)', page)[1:]:
        pid = re.search(r'data-post="[^"/]+/(\d+)"', block)
        tm = re.search(r'<time[^>]+datetime="([^"]+)"', block)
        tx = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        if pid and tm and tx:
            out.append({"id": int(pid.group(1)), "t": pd.Timestamp(tm.group(1)).tz_convert("UTC").isoformat(),
                        "text": _html_text(tx.group(1))})
    return out


def fetch_channel(name: str, max_pages: int = 60, pause: float = 1.0) -> list[dict]:
    """קורא ערוץ ציבורי מתצוגת הרשת של טלגרם (t.me/s/...), מהחדש לישן, עד max_pages עמודים."""
    import httpx
    url = f"https://t.me/s/{name.strip('@/ ').split('/')[-1]}"
    msgs, before = {}, None
    with httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as c:
        for _ in range(max_pages):
            r = c.get(url, params={"before": before} if before else None)
            r.raise_for_status()
            page = parse_channel_page(r.text)
            new = [m for m in page if m["id"] not in msgs]
            if not new:
                break
            msgs.update({m["id"]: m for m in new})
            before = min(m["id"] for m in page)
            time.sleep(pause)
    return sorted(msgs.values(), key=lambda m: m["id"])


def channel_signals(msgs: list[dict]) -> list[dict]:
    out = []
    for m in msgs:
        sig = parse_signal(m["text"])
        if sig:
            out.append({**sig, "t": m["t"], "id": m["id"], "forwarded": True})
    return out


def _by_hour(rows) -> dict:
    out = {}
    for s, r in rows:
        if r.get("filled"):
            h = pd.Timestamp(s["t"]).tz_convert("Asia/Jerusalem").hour
            out.setdefault(h, []).append(r["r_split"])
    return out


def fetch_minutes_td(symbol: str, start: pd.Timestamp, hours: float, key: str) -> pd.DataFrame:
    import httpx
    params = {"symbol": symbol, "interval": "1min", "outputsize": 5000, "timezone": "UTC", "order": "ASC", "apikey": key,
              "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
              "end_date": (start + pd.Timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")}
    body = httpx.get("https://api.twelvedata.com/time_series", params=params, timeout=60).json()
    if body.get("status") != "ok":
        raise RuntimeError(f"Twelve Data: {body.get('message', body)}")
    df = pd.DataFrame(body["values"])
    idx = pd.DatetimeIndex(pd.to_datetime(df.pop("datetime")))
    df.index = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return df[["open", "high", "low", "close"]].astype(float)


def report_from_bars(signals: list[dict], m1: pd.DataFrame, hours: float = 24, title: str = "") -> str:
    """כמו report, אבל עם נרות דקה שכבר נמשכו (מהיר: בלי בקשה לכל סיגנל)."""
    end = m1.index[-1] if len(m1) else pd.Timestamp.now(tz="UTC")
    rows = []
    for s in signals:
        t = pd.Timestamp(s["t"])
        if t < m1.index[0] or t + pd.Timedelta(hours=hours) > end + pd.Timedelta(minutes=5):
            rows.append((s, {"filled": None, "error": "מחוץ לטווח הנתונים"}))
            continue
        rows.append((s, evaluate(s, m1[(m1.index >= t) & (m1.index < t + pd.Timedelta(hours=hours))], hours)))
    return _format(rows, signals, hours, title)


def report(signals: list[dict], symbol: str, key: str, hours: float = 24) -> str:
    rows = []
    for i, s in enumerate(signals):
        t = pd.Timestamp(s["t"])
        if t > pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=1):
            rows.append((s, {"filled": None}))
            continue
        try:
            if i:
                time.sleep(8)   # החבילה החינמית: 8 בקשות בדקה
            bars = fetch_minutes_td(symbol, t, hours, key)
            rows.append((s, evaluate(s, bars, hours)))
        except Exception as e:  # noqa: BLE001
            log.warning("signal %s: %s", s.get("t"), e)
            rows.append((s, {"filled": None, "error": str(e)}))
    return _format(rows, signals, hours)


def _format(rows, signals, hours, title=""):
    done = [r for _, r in rows if r.get("filled")]
    lines = [f"🔍 <b>בדיקת סיגנלים{' - ' + title if title else ' של הקבוצה'}</b> · {len(signals)} סיגנלים · {len(done)} התמלאו", ""]
    if len(rows) > 40:   # הרבה סיגנלים: מציגים רק את 25 האחרונים בפירוט
        rows_shown = [x for x in rows if x[1].get("filled") is not None][-25:]
        lines.append(f"<i>מוצגים 25 האחרונים מתוך {len(rows)}; הסיכום למטה על כולם.</i>")
    else:
        rows_shown = rows
    for s, r in rows_shown:
        when = pd.Timestamp(s["t"]).tz_convert("Asia/Jerusalem").strftime("%d/%m %H:%M")
        side = "קנייה" if s["direction"] == 1 else "מכירה"
        head = f"{when} {side} {s['zone_lo']:g}-{s['zone_hi']:g} SL {s['sl']:g}"
        if r.get("filled") is None:
            lines.append(f"• {head}: ⏳ עוד אין נתונים" + (f" ({r['error'][:60]})" if r.get("error") else ""))
        elif not r["filled"]:
            lines.append(f"• {head}: לא התמלא")
        else:
            res = "🛑 סטופ" if r["stopped"] else ("🏆 כל היעדים" if r["tp_hits"] == len(s["tps"]) else "⏰ פתוח/נסגר בזמן")
            lines.append(f"• {head}: TP {r['tp_hits']}/{len(s['tps'])} · {res} · חלוקה שווה {r['r_split']:+.2f}R · "
                         f"עם סטופ לכניסה אחרי TP1 {r['r_be']:+.2f}R")
    if done:
        tp1 = sum(r["tp_hits"] > 0 for r in done)
        sl = sum(r["stopped"] for r in done)
        tot = sum(r["r_split"] for r in done)
        tot_be = sum(r["r_be"] for r in done)
        rr1 = sum(r["rr"][0] for r in done) / len(done)
        lines += ["", f"<b>סיכום:</b> TP1 הושג ב-{tp1}/{len(done)} ({100 * tp1 / len(done):.0f}%) · סטופ ב-{sl}/{len(done)}",
                  f"סך הכל (חלוקה שווה בין היעדים): <b>{tot:+.2f}R</b> · עם סטופ לכניסה אחרי TP1: <b>{tot_be:+.2f}R</b>",
                  f"יחס ממוצע של TP1 מהכניסה: 1:{rr1:.2f}",
                  "לפי שעה (ישראל): " + " · ".join(
                      f"{h:02d}:00 {len(v)}× {sum(v):+.1f}R" for h, v in sorted(_by_hour(rows).items())),
                  "<i>כניסה בנגיעה הראשונה באזור (הקצה הקרוב), סטופ אחד לכל החלקים, בלי עמלות. "
                  f"אחרי {hours:g} שעות עסקה פתוחה נמדדת במחיר האחרון.</i>"]
    return "\n".join(lines)


def reverse_engineer(signals: list[dict], m1: pd.DataFrame) -> str:
    """הנדסה הפוכה: מה היה בשוק ברגע השליחה של כל סיגנל, ואיך נבנו המספרים.
    מחפש כלל קבוע: גאומטריה (אזור/יעדים/סטופ), שעה, מיקום האזור ביחס למחיר, מגמה, רמות ומספרים עגולים."""
    import numpy as np
    rows = []
    c = m1["close"]
    for s in signals:
        t = pd.Timestamp(s["t"])
        past = m1[m1.index < t]
        if len(past) < 60 * 24:
            continue
        p = float(past["close"].iloc[-1])
        d = s["direction"]
        near = s["zone_hi"] if d == 1 else s["zone_lo"]
        far = s["zone_lo"] if d == 1 else s["zone_hi"]
        day = past[past.index >= t - pd.Timedelta(hours=24)]
        h4 = past[past.index >= t - pd.Timedelta(hours=4)]
        h1 = past[past.index >= t - pd.Timedelta(hours=1)]
        ema = float(c[c.index < t].iloc[-60 * 50:].ewm(span=60 * 20).mean().iloc[-1])   # מגמה של בערך יום
        rows.append({
            "hour_il": t.tz_convert("Asia/Jerusalem").hour, "dir": d,
            "width": abs(s["zone_hi"] - s["zone_lo"]),
            "tp_off": tuple(round((tp - near) * d, 1) for tp in s["tps"]),
            "sl_off": round((far - s["sl"]) * d, 1),
            "near_vs_price": round((near - p) * d, 1),          # שלילי = האזור "מאחורי" המחיר (מחכים לתיקון)
            "in_zone": min(s["zone_lo"], s["zone_hi"]) <= p <= max(s["zone_lo"], s["zone_hi"]),
            "mv1": (p - float(h1["close"].iloc[0])) * d, "mv4": (p - float(h4["close"].iloc[0])) * d,
            "mv24": (p - float(day["close"].iloc[0])) * d,
            "trend": 1 if p > ema else -1,
            "from_low24": p - float(day["low"].min()), "from_high24": float(day["high"].max()) - p,
            "far_round10": float(far) % 10 == 0, "near_round10": float(near) % 10 == 0,
            "sl_round10": s["sl"] % 10 == 0,
        })
    if not rows:
        return "אין מספיק נתוני מחיר לפני הסיגנלים לניתוח."
    df = pd.DataFrame(rows)
    n = len(df)
    pct = lambda m: f"{100 * m.mean():.0f}%"
    top = lambda col: ", ".join(f"{k} ({v})" for k, v in df[col].value_counts().head(3).items())
    med = lambda col: f"{df[col].median():+.1f}"
    buys = df[df.dir == 1]
    lines = [f"🧬 <b>הנדסה הפוכה - {n} סיגנלים</b>", "",
             "<b>1. איך בנויים המספרים:</b>",
             f"• רוחב האזור: {top('width')}",
             f"• יעדים ביחס לראש האזור ($): {top('tp_off')}",
             f"• סטופ מתחת לתחתית האזור ($): {top('sl_off')}",
             f"• סטופ על מספר עגול (x0): {pct(df.sl_round10)} · תחתית אזור עגולה: {pct(df.far_round10)} · ראש אזור עגול: {pct(df.near_round10)}",
             "", "<b>2. מתי:</b>",
             "• שעה (ישראל): " + " · ".join(f"{h:02d}:00×{k}" for h, k in df.hour_il.value_counts().sort_index().items()),
             f"• קנייה/מכירה: {len(buys)}/{n - len(buys)}",
             "", "<b>3. איפה המחיר היה ברגע השליחה:</b>",
             f"• המחיר כבר בתוך האזור: {pct(df.in_zone)}",
             f"• ראש האזור ביחס למחיר (בכיוון העסקה, $): חציון {med('near_vs_price')} "
             f"(שלילי = מחכים שהמחיר יחזור אליו)",
             "", "<b>4. מה השוק עשה לפני (בכיוון העסקה, $):</b>",
             f"• שעה אחרונה: חציון {med('mv1')} · 4 שעות: {med('mv4')} · 24 שעות: {med('mv24')}",
             f"• העסקה בכיוון המגמה היומית: {pct(df.dir == df.trend)}",
             f"• מרחק מהשפל של 24 שעות: חציון {df.from_low24.median():.1f}$ · מהשיא: {df.from_high24.median():.1f}$",
             ""]
    # ניסוח השערה
    hyp = []
    if df.tp_off.nunique() <= 3:
        hyp.append(f"היעדים קבועים: {df.tp_off.mode()[0]} מעל ראש האזור")
    if df.sl_off.nunique() <= 3:
        hyp.append(f"הסטופ קבוע: {df.sl_off.mode()[0]}$ מתחת לתחתית")
    if (df.dir == df.trend).mean() > 0.7:
        hyp.append("כמעט תמיד בכיוון המגמה (קונים ירידות במגמה עולה)")
    if df.in_zone.mean() > 0.6:
        hyp.append("האזור נבנה סביב המחיר הנוכחי (כניסה מיידית)")
    elif (df.near_vs_price < 0).mean() > 0.6:
        hyp.append("האזור מתחת/מעל למחיר - לימיט שמחכה לתיקון")
    lines += ["<b>השערה לכלל:</b> " + ("; ".join(hyp) if hyp else "לא נמצא דפוס חד")]
    return "\n".join(lines)
