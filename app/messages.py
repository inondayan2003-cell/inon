"""ניסוח הודעות הבוט בעברית (HTML)."""
from datetime import datetime
from zoneinfo import ZoneInfo

IL = ZoneInfo("Asia/Jerusalem")
DISCLAIMER = "<i>⚠️ ניתוח טכני אוטומטי, לא ייעוץ השקעות. נהל סיכונים.</i>"


def _p(x: float) -> str:
    return f"{x:,.2f}"


def _time(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(IL).strftime("%H:%M")


def _when(iso: str) -> str:
    d = datetime.fromisoformat(iso).astimezone(IL)
    today = datetime.now(IL).date()
    return d.strftime("%H:%M") if d.date() == today else d.strftime("%d/%m %H:%M")


def _dir(d: int) -> tuple[str, str]:
    return ("🟢", "לונג") if d == 1 else ("🔴", "שורט")


def _align(snapshot: dict | None) -> str:
    if not snapshot:
        return ""
    marks = " | ".join(f"{t['tf']} {'🟢' if t['score'] >= 20 else '🔴' if t['score'] <= -20 else '⚪'}"
                       for t in snapshot["timeframes"])
    return f"\nיישור טווחים: {marks}"


METHODS = {"smc": "🏦 SMC", "trend": "📈 מגמה", "liquidity": "💧 נזילות", "range": "🎯 טווחים"}


def _label(tr: dict) -> str:
    _, name = _dir(tr["direction"])
    return f"{METHODS.get(tr.get('method', 'trend'))} · {name} #{tr['id']}"


def _rr(tr: dict) -> str:
    return f"{abs(tr['tp2'] - tr['entry']) / abs(tr['entry'] - tr['sl']):.1f}R"


def setup_message(s: dict) -> str:
    icon, name = _dir(s["direction"])
    order = "Buy Limit" if s["direction"] == 1 else "Sell Limit"
    risk = abs(s["entry"] - s["sl"])
    r = lambda x: f"{abs(x - s['entry']) / risk:.1f}R"
    if s.get("method") == "smc":
        title = f"🏦{icon} <b>סיגנל SMC {name} - זהב</b> · {_time(s['created'])}"
        if s["note"].startswith("מודל B"):
            why = s["note"]
        else:
            side = "מתחת ל" if s["direction"] == 1 else "מעל ל"
            why = f"מודל A: Sweep {side}{s['note']} ({_p(s['level'])}), Displacement ושבירת מבנה ב-5M, FVG בכיוון ההפוך."
    else:
        title = f"💧{icon} <b>סיגנל נזילות {name} - זהב</b> · {_time(s['created'])}"
        side = "מתחת ל" if s["direction"] == 1 else "מעל ל"
        back = "מעליו" if s["direction"] == 1 else "מתחתיו"
        why = f"המחיר לקח את הנזילות {side}{s['note']} ({_p(s['level'])}), חזר {back} ושבר מבנה ב-5M."
    return "\n".join([
        title, "", why, "",
        f"📌 הזמנת <b>{order}</b>: <b>{_p(s['entry'])}</b> (אמצע ה-FVG)",
        f"🛑 סטופ: {_p(s['sl'])} ({risk:.2f}$, מעבר לקצה הסוויפ)",
        f"🎯 יעד 1: {_p(s['tp1'])} ({r(s['tp1'])} · סגור חצי, הזז סטופ לכניסה)",
        f"🎯 יעד סופי: {_p(s['tp2'])} ({r(s['tp2'])} · הנזילות הנגדית)",
        f"⏳ ההזמנה בתוקף עד {_time(s['expires'])}. אם לא התמלאה עד אז - לבטל.",
        "",
        "📏 סיכון מומלץ: 0.5%-1% מהחשבון לעסקה.",
        "🧪 <b>מצב ניסיון - לסחור בחשבון דמו בלבד.</b> בבדיקה של שנתיים: 38 עסקאות, 32% הצלחה, ‎-7.9R." if s.get("method") == "smc" else "",
        DISCLAIMER,
    ])


def range_message(ev: dict) -> str:
    tr = ev["trade"]
    icon, name = _dir(tr["direction"])
    risk = abs(tr["entry"] - tr["sl"])
    return "\n".join([
        f"🎯{icon} <b>סיגנל {name} - זהב</b> · {_time(tr['opened_at'])}",
        f"<i>{tr['note']}</i> (רמה {_p(ev['level'])})",
        "",
        f"💰 כניסה עכשיו: <b>{_p(tr['entry'])}</b>",
        f"🛑 סטופ: {_p(tr['sl'])} ({risk:.2f}$)",
        f"🎯 יעד: {_p(tr['tp2'])} (1.5R)",
        f"⏳ אם לא הגיע ליעד או לסטופ עד {_time(ev['expires'])} - לסגור במחיר השוק.",
        "",
        "🧪 <b>מצב ניסיון - לסחור בחשבון דמו בלבד.</b>",
        "<i>בבדיקה של שנתיים השיטה הרוויחה (כ-2 עסקאות ביום, 48% הצלחה), אבל ב-7 החודשים "
        "האחרונים היא יצאה באפס. הבוט אוסף עכשיו תוצאות חיות - נחליט לפיהן.</i>",
        "",
        DISCLAIMER,
    ])


def signal_message(trade: dict, snapshot: dict | None) -> str:
    icon, name = _dir(trade["direction"])
    risk = abs(trade["entry"] - trade["sl"])
    lines = [
        f"📈{icon} <b>סיגנל מגמה {name} - זהב</b> · {_time(trade['opened_at'])}",
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
        if ev["trade"].get("method") == "range":
            return range_message(ev)
        return signal_message(ev["trade"], snapshot)
    if kind == "setup":
        return setup_message(ev["setup"])
    if kind == "cancelled":
        s = ev["setup"]
        _, name = _dir(s["direction"])
        return f"❌ <b>הזמנת ה-{'SMC' if s.get('method') == 'smc' else 'נזילות'} ({name} #{s['id']}) בוטלה</b>\n{ev['reason']}. אם שמת לימיט אצל הברוקר - בטל אותו."
    if kind == "weak":
        icon, name = _dir(ev["direction"])
        return (f"⚠️ <b>סיגנל המגמה ל{name} נחלש</b> · {_time(ev['t'])}\n"
                f"הציון ירד ל-{ev['score']:+.0f}. כדאי להדק סטופ או לממש.")
    tr = ev["trade"]
    if kind == "filled":
        return (f"✅ <b>הלימיט התמלא ({_label(tr)})</b> ב-{_p(tr['entry'])}\n"
                f"סטופ {_p(tr['sl'])} · יעדים {_p(tr['tp1'])} / {_p(tr['tp2'])}")
    if kind == "tp1":
        return (f"✅ <b>יעד 1 הושג ({_label(tr)})</b>\n"
                f"מחיר {_p(tr['tp1'])}. מומלץ לסגור חצי ולהזיז סטופ לכניסה ({_p(tr['entry'])}).")
    if kind == "closed":
        if tr.get("method") == "range" and tr["status"] == "tp2":
            return f"🏆 <b>היעד הושג</b> ({_label(tr)})\nיציאה: {_p(tr['exit_price'])} · תוצאה: <b>{tr['result_r']:+.2f}R</b>"
        titles = {"tp2": "🏆 יעד 2 הושג - העסקה נסגרה", "sl": "🛑 הסטופ נלקח",
                  "be": "⚖️ נסגר בנקודת כניסה (אחרי יעד 1)", "expired": "⏰ הזמן נגמר - לסגור במחיר השוק",
                  "reversed": "🔄 העסקה נסגרה - סיגנל הפוך"}
        return (f"<b>{titles[tr['status']]}</b> ({_label(tr)})\n"
                f"יציאה: {_p(tr['exit_price'])} · תוצאה: <b>{tr['result_r']:+.2f}R</b>")
    return None


def status_message(s: dict) -> str:
    icon = "🟢" if s["lean"] == 1 else "🔴" if s["lean"] == -1 else "⚪"
    lines = [
        f"<b>זהב {_p(s['price'])}</b> ({s['symbol']}) · מחיר נכון ל-{_when(s.get('price_time') or s['updated_at'])}",
        f"{icon} <b>{s['verdict']}</b> · ציון {s['composite']:+.0f} · ביטחון {s['confidence']}",
        "",
    ]
    for t in s["timeframes"]:
        lines.append(f"{t['tf']}: {t['trend']} ({t['score']:+.0f}) · RSI {t['rsi']:.0f}")
    if s.get("plan") and s["direction"]:
        p = s["plan"]
        lines += ["", f"כניסה {_p(p['entry'])} · סטופ {_p(p['sl'])} · יעדים {_p(p['tp1'])} / {_p(p['tp2'])}"]
    if s["direction"] or s["lean"]:
        lines += ["", "ℹ️ הכיוון למעלה הוא לפי שיטת המגמה - לניתוח בלבד, לא סיגנל כניסה. "
                      "סיגנלים נשלחים מאסטרטגיית ה-SMC 🏦"]
    if s.get("killzone"):
        lines += ["", f"🕐 סשן {s['killzone']} פעיל"]
    if not s["market_open"]:
        lines += ["", "😴 השוק סגור כרגע - זה מחיר הסגירה האחרון. השוק נפתח מחדש בלילה שבין ראשון לשני, בסביבות חצות-01:00 שעון ישראל"]
    return "\n".join(lines)
