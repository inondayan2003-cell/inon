"""תיק דמו: כל עסקה שהבוט סוגר נרשמת כאילו נסחרה בחשבון אמיתי, וכל ערב נשלח דוח.

גודל עסקה: מסכנים RISK_PCT מהיתרה (ברגע הכניסה) עד הסטופ. לוט = 100 אונקיות, מינימום 0.01.
הרווח בדולרים = result_r של העסקה (כולל שליש בכל יעד והזזת סטופ לכניסה) × הסיכון בפועל, פחות ספרד.
"""
import pandas as pd

from .storage import Store

KEY = "portfolio"
START = 10_000.0
RISK_PCT = 1.0
SPREAD = 0.35   # דולר לאונקיה לעסקה (ספרד + עמלה)
IL = "Asia/Jerusalem"


def get(store: Store) -> dict:
    p = store.get(KEY)
    if not p:
        p = reset(store, START)
    return p


def reset(store: Store, balance: float, risk_pct: float = RISK_PCT) -> dict:
    p = {"start": float(balance), "balance": float(balance), "risk_pct": float(risk_pct),
         "since": pd.Timestamp.now(tz="UTC").isoformat(), "ledger": []}
    store.put(KEY, p)
    return p


def replay(store: Store, balance: float, risk_pct: float = RISK_PCT, method: str = "channel_fade") -> dict:
    """מתחיל תיק חדש ומריץ עליו לפי הסדר את כל העסקאות שהבוט כבר סגר."""
    done = [t for t in store.trades(10_000) if t.get("method") == method and t.get("result_r") is not None
            and t.get("closed_at")]
    done.sort(key=lambda t: t["closed_at"])
    p = reset(store, balance, risk_pct)
    if done:
        p["since"] = min(t["opened_at"] for t in done)
        store.put(KEY, p)
    for t in done:
        record(store, t)
    return get(store)


def history(store: Store) -> str:
    """כל העסקאות בתיק, אחת בשורה, עם היתרה אחרי כל אחת."""
    p = get(store)
    if not p["ledger"]:
        return "אין עדיין עסקאות סגורות בתיק."
    il = lambda t: pd.Timestamp(t).tz_convert(IL)
    lines = [f"📜 <b>כל העסקאות ({len(p['ledger'])})</b> · התחלה {p['start']:,.0f}$", ""]
    for x in p["ledger"]:
        lines.append(f"{il(x['opened_at']):%d/%m %H:%M} · {'BUY' if x['direction'] == 1 else 'SELL'} {x['entry']:.0f} · "
                     f"{STATUS.get(x['status'], x['status'])} · <b>{_money(x['pnl'])}</b> → {x['balance']:,.0f}$")
    return "\n".join(lines)


def record(store: Store, trade: dict) -> dict | None:
    """עסקה שנסגרה: מחשבים לוטים ורווח ומעדכנים את היתרה. מחזיר את השורה שנרשמה."""
    if trade.get("result_r") is None or not trade.get("entry") or trade.get("entry") == trade.get("sl"):
        return None
    p = get(store)
    if any(x["id"] == trade["id"] and x["opened_at"] == trade["opened_at"] for x in p["ledger"]):
        return None   # כבר נרשמה
    stop = abs(trade["entry"] - trade["sl"])
    risk = p["balance"] * p["risk_pct"] / 100
    lots = max(0.01, round(risk / (stop * 100), 2))
    oz = lots * 100
    pnl = round(trade["result_r"] * stop * oz - SPREAD * oz, 2)
    p["balance"] = round(p["balance"] + pnl, 2)
    row = {"id": trade["id"], "direction": trade["direction"], "opened_at": trade["opened_at"],
           "closed_at": trade.get("closed_at"), "entry": trade["entry"], "sl": trade["sl"],
           "exit": trade.get("exit_price"), "status": trade.get("status"), "r": trade["result_r"],
           "lots": lots, "pnl": pnl, "balance": p["balance"]}
    p["ledger"].append(row)
    store.put(KEY, p)
    return row


STATUS = {"tp2": "✅ כל היעדים", "be": "⚖️ TP ואז כניסה", "sl": "❌ סטופ", "expired": "⏰ נסגר בזמן"}


def _money(x: float) -> str:
    return f"{'+' if x > 0 else '-' if x < 0 else ''}{abs(x):,.2f}$"


def report(store: Store, day: str | None = None, open_trades: list | None = None) -> str:
    """דוח לתיק: עסקאות שנסגרו היום (לפי שעון ישראל) וסיכום מההתחלה."""
    p = get(store)
    day = day or pd.Timestamp.now(tz=IL).date().isoformat()
    il = lambda t: pd.Timestamp(t).tz_convert(IL)
    today = [x for x in p["ledger"] if x.get("closed_at") and il(x["closed_at"]).date().isoformat() == day]
    led = p["ledger"]
    total = p["balance"] - p["start"]
    wins = [x for x in led if x["pnl"] > 0]
    lines = [f"💼 <b>תיק דמו · {pd.Timestamp(day):%d/%m/%Y}</b>", ""]
    if today:
        lines.append(f"<b>עסקאות שנסגרו היום ({len(today)}):</b>")
        for x in today:
            side = "BUY" if x["direction"] == 1 else "SELL"
            lines.append(f"{STATUS.get(x['status'], x['status'])} · #{x['id']} {side} {x['entry']:.0f} · "
                         f"{x['lots']:.2f} לוט · <b>{_money(x['pnl'])}</b>")
        day_pnl = sum(x["pnl"] for x in today)
        lines += ["", f"📅 רווח/הפסד היום: <b>{_money(day_pnl)}</b>"]
    else:
        lines.append("לא נסגרו עסקאות היום.")
    for t in open_trades or []:
        side = "BUY" if t["direction"] == 1 else "SELL"
        lines.append(f"⏳ פתוחה: #{t['id']} {side} {t['entry']:.0f} · SL {t['sl']:.0f}"
                     + (f" · {t.get('hits', 0)} יעדים הושגו" if t.get("hits") else ""))
    lines += ["", f"💰 יתרה: <b>{p['balance']:,.2f}$</b> (התחלה {p['start']:,.0f}$ · {_money(total)}, "
                  f"{100 * total / p['start']:+.1f}%)",
              f"📊 מאז {il(p['since']):%d/%m}: {len(led)} עסקאות · {len(wins)} ברווח"
              + (f" ({100 * len(wins) / len(led):.0f}%)" if led else "")
              + (f" · הכי טובה {_money(max(x['pnl'] for x in led))} · הכי גרועה {_money(min(x['pnl'] for x in led))}" if led else ""),
              f"<i>סיכון {p['risk_pct']:g}% מהיתרה לעסקה, כולל ספרד {SPREAD}$ לאונקיה. כסף וירטואלי בלבד.</i>"]
    return "\n".join(lines)
