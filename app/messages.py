"""ניסוח הודעות הבוט בעברית (HTML)."""
from datetime import datetime
from zoneinfo import ZoneInfo

IL = ZoneInfo("Asia/Jerusalem")
DISCLAIMER = "<i>⚠️ ניתוח טכני אוטומטי, לא ייעוץ השקעות. נהל סיכונים.</i>"


def _p(x: float) -> str:
    return f"{x:,.2f}"


def _time(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(IL).strftime("%H:%M")


def _dir(d: int) -> tuple[str, str]:
    return ("🟢", "לונג") if d == 1 else ("🔴", "שורט")


def _align(snapshot: dict | None) -> str:
    if not snapshot:
        return ""
    marks = " | ".join(f"{t['tf']} {'🟢' if t['score'] >= 20 else '🔴' if t['score'] <= -20 else '⚪'}"
                       for t in snapshot["timeframes"])
    return f"\nיישור טווחים: {marks}"


def signal_message(trade: dict, snapshot: dict | None) -> str:
    icon, name = _dir(trade["direction"])
    risk = abs(trade["entry"] - trade["sl"])
    lines = [
        f"{icon} <b>סיגנל {name} - זהב</b> · {_time(trade['opened_at'])}",
        "",
        f"💰 כניסה: <b>{_p(trade['entry'])}</b>",
        f"🛑 סטופ: {_p(trade['sl'])} ({risk:.2f}$)",
        f"🎯 יעד 1: {_p(trade['tp1'])} (1R · סגור חצי, הזז סטופ לכניסה)",
        f"🎯 יעד 2: {_p(trade['tp2'])} (2R)",
        "",
        f"ציון משוקלל: <b>{trade['score']:+.0f}</b>/100{_align(snapshot)}",
    ]
    if snapshot and snapshot.get("reasons"):
        lines += [""] + [f"• {r}" for r in snapshot["reasons"]]
    return "\n".join(lines + ["", DISCLAIMER])


def event_message(ev: dict, snapshot: dict | None = None) -> str | None:
    kind = ev["type"]
    if kind == "signal":
        return signal_message(ev["trade"], snapshot)
    if kind == "weak":
        icon, name = _dir(ev["direction"])
        return (f"⚠️ <b>הסיגנל ל{name} נחלש</b> · {_time(ev['t'])}\n"
                f"הציון ירד ל-{ev['score']:+.0f}. כדאי להדק סטופ או לממש.")
    tr = ev["trade"]
    _, name = _dir(tr["direction"])
    if kind == "tp1":
        return (f"✅ <b>יעד 1 הושג ({name} #{tr['id']})</b>\n"
                f"מחיר {_p(tr['tp1'])}. מומלץ לסגור חצי ולהזיז סטופ לכניסה ({_p(tr['entry'])}).")
    if kind == "closed":
        titles = {"tp2": "🏆 יעד 2 הושג - העסקה נסגרה", "sl": "🛑 הסטופ נלקח",
                  "be": "⚖️ נסגר בנקודת כניסה (אחרי יעד 1)", "expired": "⏰ העסקה נסגרה (זמן מקסימלי)",
                  "reversed": "🔄 העסקה נסגרה - סיגנל הפוך"}
        return (f"<b>{titles[tr['status']]}</b> ({name} #{tr['id']})\n"
                f"יציאה: {_p(tr['exit_price'])} · תוצאה: <b>{tr['result_r']:+.2f}R</b>")
    return None


def status_message(s: dict) -> str:
    icon = "🟢" if s["lean"] == 1 else "🔴" if s["lean"] == -1 else "⚪"
    lines = [
        f"<b>זהב {_p(s['price'])}</b> ({s['symbol']})",
        f"{icon} <b>{s['verdict']}</b> · ציון {s['composite']:+.0f} · ביטחון {s['confidence']}",
        "",
    ]
    for t in s["timeframes"]:
        lines.append(f"{t['tf']}: {t['trend']} ({t['score']:+.0f}) · RSI {t['rsi']:.0f}")
    if s.get("plan") and s["direction"]:
        p = s["plan"]
        lines += ["", f"כניסה {_p(p['entry'])} · סטופ {_p(p['sl'])} · יעדים {_p(p['tp1'])} / {_p(p['tp2'])}"]
    if not s["market_open"]:
        lines += ["", "😴 השוק סגור כרגע"]
    return "\n".join(lines)
