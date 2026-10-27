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
    t = text.replace("‏", "").replace("‎", "")
    m = re.search(rf"(?:gold|xau(?:usd)?)\W*(buy|sell)\w*\s*(?:now|limit)?\s*@?\s*{NUM}(?:\s*[-–/to]+\s*{NUM})?", t, re.I)
    if not m:
        m = re.search(rf"(buy|sell)\w*\s+(?:gold|xau(?:usd)?)\s*(?:now|limit)?\s*@?\s*{NUM}(?:\s*[-–/to]+\s*{NUM})?", t, re.I)
    sl = re.search(rf"\bs\.?\s*l\b\W*{NUM}", t, re.I)
    tps = [float(x) for x in re.findall(rf"\bt\.?\s*p\s*\d?\b\W*{NUM}", t, re.I)]
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
    done = [r for _, r in rows if r.get("filled")]
    lines = [f"🔍 <b>בדיקת סיגנלים של הקבוצה</b> · {len(signals)} סיגנלים · {len(done)} התמלאו", ""]
    for s, r in rows:
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
                  "<i>כניסה בנגיעה הראשונה באזור (הקצה הקרוב), סטופ אחד לכל החלקים, בלי עמלות. "
                  f"אחרי {hours:g} שעות עסקה פתוחה נמדדת במחיר האחרון.</i>"]
    return "\n".join(lines)
