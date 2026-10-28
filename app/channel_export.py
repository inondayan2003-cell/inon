"""ייצוא ובדיקה של ערוץ סיגנלים מוגן (בלי Forward ובלי תצוגת רשת) דרך החשבון שלך בטלגרם.

הרצה על השרת (פעם ראשונה מבקשת: API ID/Hash מ-my.telegram.org, מספר טלפון, קוד שטלגרם שולח,
וסיסמת אימות דו-שלבי אם יש). ההתחברות נשמרת רק בשרת שלך (data/tg_user.session):

    cd /opt/gold-analyzer && sudo docker compose exec app python -m app.channel_export Cryptonew84

אפשרויות: --months 6 (כמה חודשים אחורה לבדוק), --hours 24 (כמה זמן אחרי סיגנל לעקוב).
הדוח נשלח לכל מי שרשום לבוט, ונשמר גם ב-data/channel_<שם>.json.
"""
import argparse
import json
import os
from pathlib import Path

import httpx
import pandas as pd

from .backtest import fetch_twelvedata_history
from .config import settings
from .signals import channel_signals, report_from_bars
from .storage import Store

DATA = Path(os.getenv("DB_PATH", "data/bot.db")).parent


def _ask(env: str, prompt: str) -> str:
    v = os.getenv(env, "").strip()
    return v or input(prompt).strip()


def normalize_phone(raw: str) -> str | None:
    """מקבל 050-1234567 / 0501234567 / 972501234567 / +972501234567 ומחזיר +972501234567."""
    d = "".join(ch for ch in raw if ch.isdigit())
    if d.startswith("0"):
        d = "972" + d[1:]
    if d.startswith("972") and len(d) != 12:
        return None   # נייד ישראלי: 972 + 9 ספרות
    return "+" + d if 10 <= len(d) <= 15 else None


def _ask_phone() -> str:
    while True:
        p = normalize_phone(input("מספר הטלפון שלך (למשל 050-1234567): "))
        if p:
            print(f"מתחבר עם {p[:6]}****{p[-2:]}")
            return p
        print("המספר לא שלם. נייד ישראלי הוא 10 ספרות שמתחילות ב-05, למשל 050-1234567.")


def export(channel: str, months: int) -> list[dict]:
    from telethon.sync import TelegramClient

    cfg_file = DATA / "tg_api.json"
    if cfg_file.exists():
        api = json.loads(cfg_file.read_text())
    else:
        print("צריך API ID ו-API Hash מ-https://my.telegram.org → API development tools (פעם אחת).")
        api = {"id": int(_ask("TG_API_ID", "API ID: ")), "hash": _ask("TG_API_HASH", "API Hash: ")}
        cfg_file.write_text(json.dumps(api))
        cfg_file.chmod(0o600)
    since = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=months) if months else pd.Timestamp("2000-01-01", tz="UTC")
    msgs = []
    client = TelegramClient(str(DATA / "tg_user"), api["id"], api["hash"])
    client.start(phone=_ask_phone)   # מבקש טלפון וקוד רק בפעם הראשונה
    with client:
        for m in client.iter_messages(channel.strip("@/ ").split("/")[-1]):
            if m.date < since:
                break
            msgs.append({"id": m.id, "t": pd.Timestamp(m.date).tz_convert("UTC").isoformat(), "text": m.message or "",
                         "reply_to": getattr(m, "reply_to_msg_id", None), "media": m.media is not None})
    msgs.sort(key=lambda x: x["id"])
    (DATA / f"channel_{channel}.json").write_text(json.dumps(msgs, ensure_ascii=False))
    return msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("channel")
    ap.add_argument("--months", type=int, default=0, help="כמה חודשים אחורה (0 = כל ההיסטוריה של הערוץ)")
    ap.add_argument("--hours", type=float, default=24)
    ap.add_argument("--audit", action="store_true", help="רק פירוט של סוגי ההודעות בערוץ (בלי בדיקת מחירים)")
    ap.add_argument("--csv", action="store_true", help="קובץ CSV של כל סיגנלי הזהב (עם תוצאה מול המחיר) - נשלח בבוט")
    ap.add_argument("--cached", action="store_true", help="להשתמש בהודעות שכבר נשמרו בלי לקרוא שוב מטלגרם")
    a = ap.parse_args()
    f = DATA / f"channel_{a.channel}.json"
    msgs = json.loads(f.read_text()) if a.cached and f.exists() else export(a.channel, a.months)
    if a.audit:
        print(audit(msgs))
        return
    sigs = channel_signals(msgs)
    print(f"נקראו {len(msgs)} הודעות ({msgs[0]['t'][:10]} עד {msgs[-1]['t'][:10]}), זוהו {len(sigs)} סיגנלי זהב.")
    if not sigs:
        for m in msgs[-5:]:
            print("---\n" + m["text"][:300])
        return
    if a.csv:
        path = write_csv(a.channel, msgs, sigs, a.hours)
        send_file(path, f"📄 כל סיגנלי הזהב מ-{a.channel}: {len(sigs)} סיגנלים (טבלה לאקסל)")
        send_file(path.with_suffix(".txt"), f"📝 אותם {len(sigs)} סיגנלים כטקסט (להדבקה בצ'אט)")
        return
    start = pd.Timestamp(sigs[0]["t"]) - pd.Timedelta(hours=26)
    days = (pd.Timestamp.now(tz="UTC") - start).days
    need = int(days * 1440 * 5 / 7 / 4800) + 3
    print(f"מושך נרות דקה מ-Twelve Data: {days} ימים, עד {need} בקשות (כ-10 שניות לבקשה)...")
    m1 = fetch_twelvedata_history(settings.td_symbol, "1min", start, settings.twelvedata_api_key, max_requests=need)
    print(f"התקבלו נרות מ-{m1.index[0]:%Y-%m-%d} עד {m1.index[-1]:%Y-%m-%d}")
    from .signals import reverse_engineer
    sections = ["📋 <b>מה יש בערוץ</b>\n" + audit(msgs).split("\nהודעות שמזכירות")[0],
                report_from_bars(sigs, m1, a.hours, title=f"{a.channel} (זהב בלבד)"), reverse_engineer(sigs, m1),
                gold_claims(msgs, sigs)]
    for sec in sections:
        print(sec + "\n")
    if settings.bot_token:
        for chat in Store(settings.db_path).subscribers():
            for sec in sections:
                for part in _chunks(sec):
                    r = httpx.post(f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                                   json={"chat_id": chat, "text": part, "parse_mode": "HTML"}, timeout=30)
                    if not r.json().get("ok"):   # HTML שבור? שולחים כטקסט רגיל
                        httpx.post(f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
                                   json={"chat_id": chat, "text": part}, timeout=30)
        print("הדוחות נשלחו בבוט.")


def audit(msgs: list[dict]) -> str:
    """לאן הולכות כל ההודעות: סיגנלים, הודעות רווח, תמונות בלי טקסט, נכסים אחרים, ומה לא זוהה."""
    import re
    from .signals import parse_signal
    cats = {"סיגנל זהב שזוהה": 0, "הודעת Profit": 0, "תמונה/וידאו בלי טקסט": 0, "ביטקוין/את'ריום/קריפטו": 0,
            "פורקס אחר": 0, "מזכיר זהב אבל לא זוהה": 0, "אחר (פרסום/צ'אט)": 0}
    unparsed = []
    for m in msgs:
        t = m.get("text", "")
        if parse_signal(t):
            cats["סיגנל זהב שזוהה"] += 1
        elif re.search(r"profit", t, re.I):
            cats["הודעת Profit"] += 1
        elif not t.strip():
            cats["תמונה/וידאו בלי טקסט"] += 1
        elif re.search(r"btc|eth|bitcoin|crypto|usdt|sol\b", t, re.I):
            cats["ביטקוין/את'ריום/קריפטו"] += 1
        elif re.search(r"gold|xau", t, re.I):
            cats["מזכיר זהב אבל לא זוהה"] += 1
            unparsed.append(m)
        elif re.search(r"eur|gbp|jpy|usd|aud|cad|chf|nzd|us30|nas", t, re.I):
            cats["פורקס אחר"] += 1
        else:
            cats["אחר (פרסום/צ'אט)"] += 1
    lines = [f"{len(msgs)} הודעות ({msgs[0]['t'][:10]} עד {msgs[-1]['t'][:10]}):"]
    lines += [f"  {k}: {v}" for k, v in cats.items()]
    lines.append(f"\nהודעות שמזכירות זהב ולא זוהו כסיגנל ({len(unparsed)}), עד 15 לדוגמה:")
    for m in unparsed[:15]:
        lines.append(f"--- {m['t'][:16]}\n{m['text'][:400]}")
    return "\n".join(lines)


def write_csv(channel: str, msgs: list[dict], sigs: list[dict], hours: float = 24) -> Path:
    """CSV (נפתח באקסל/גוגל שיטס) עם כל סיגנל: זמן, כיוון, אזור, סטופ, יעדים, הטקסט המקורי,
    ומה קרה בפועל מול נרות דקה (אם אפשר למשוך אותם)."""
    import csv
    from .signals import evaluate
    m1 = None
    try:
        start = pd.Timestamp(sigs[0]["t"]) - pd.Timedelta(hours=1)
        days = (pd.Timestamp.now(tz="UTC") - start).days
        need = int(days * 1440 * 5 / 7 / 4800) + 3
        print(f"מושך נרות דקה לבדיקת התוצאות ({need} בקשות לכל היותר)...")
        m1 = fetch_twelvedata_history(settings.td_symbol, "1min", start, settings.twelvedata_api_key, max_requests=need)
    except Exception as e:  # noqa: BLE001
        print("בלי תוצאות (אין נתוני מחיר):", e)
    text_by_id = {m["id"]: m["text"] for m in msgs}
    replies = {}
    for m in msgs:
        if m.get("reply_to"):
            replies.setdefault(m["reply_to"], []).append(m["text"].replace("\n", " ")[:80])
    path = DATA / f"signals_{channel}.csv"
    cols = ["#", "תאריך", "שעה (ישראל)", "כיוון", "אזור מ-", "אזור עד", "סטופ", "TP1", "TP2", "TP3", "TP4",
            "התמלא", "יעדים שהושגו", "סטופ נלקח", "R (חלוקה שווה)", "R רק TP1", "ירידה נגדך עד TP1 ($)",
            "מה הערוץ פרסם אחר כך", "טקסט מקורי"]
    blocks = []
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig = עברית תקינה באקסל
        w = csv.writer(f)
        w.writerow(cols)
        for i, s in enumerate(sigs, 1):
            t = pd.Timestamp(s["t"]).tz_convert("Asia/Jerusalem")
            tps = (s["tps"] + [None] * 4)[:4]
            row = [i, t.strftime("%d/%m/%Y"), t.strftime("%H:%M"), "קנייה" if s["direction"] == 1 else "מכירה",
                   s["zone_lo"], s["zone_hi"], s["sl"] if s.get("sl") is not None else "מוסתר (VIP)", *tps]
            r = {}
            if m1 is not None and len(m1):
                ts = pd.Timestamp(s["t"])
                bars = m1[(m1.index >= ts) & (m1.index < ts + pd.Timedelta(hours=hours))]
                if len(bars) and ts >= m1.index[0]:
                    r = evaluate(s, bars, hours)
            if r.get("filled"):
                row += ["כן", f"{r['tp_hits']}/{len(s['tps'])}", "כן" if r["stopped"] else "לא",
                        r["r_split"], r["r_tp1_only"], r["mae"]]
            elif r:
                row += ["לא", "", "", "", "", ""]
            else:
                row += ["אין נתונים", "", "", "", "", ""]
            row += [" | ".join(replies.get(s.get("id"), [])), text_by_id.get(s.get("id"), "").replace("\n", " / ")]
            w.writerow(row)
            blocks.append(f"#{i} · {t:%d/%m/%Y %H:%M} (שעון ישראל) · {row[3]}\n"
                          f"{text_by_id.get(s.get('id'), '').strip()}\n"
                          f"→ תוצאה: התמלא={row[11]}, יעדים={row[12]}, סטופ נלקח={row[13]}, R={row[14]}")
    path.with_suffix(".txt").write_text(f"סיגנלי זהב מהערוץ {channel} ({len(sigs)} סיגנלים)\n\n" + "\n\n".join(blocks),
                                        encoding="utf-8")
    print(f"נשמר: {path} + {path.with_suffix('.txt')}")
    return path


def send_file(path: Path, caption: str):
    if not settings.bot_token:
        return
    for chat in Store(settings.db_path).subscribers():
        with open(path, "rb") as fh:
            httpx.post(f"https://api.telegram.org/bot{settings.bot_token}/sendDocument",
                       data={"chat_id": chat, "caption": caption},
                       files={"document": (path.name, fh, "text/csv" if path.suffix == ".csv" else "text/plain")},
                       timeout=60)
    print("הקובץ נשלח בבוט.")


def _chunks(text: str, size: int = 3800) -> list[str]:
    """חותך רק בסוף שורה, כדי לא לשבור תגיות HTML."""
    out, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size and cur:
            out.append(cur)
            cur = ""
        cur += line + "\n"
    return out + [cur] if cur.strip() else out


def gold_claims(msgs: list[dict], sigs: list[dict]) -> str:
    """הודעות 'Profit' שהן תגובה לסיגנל זהב (או מזכירות זהב) מול מה שקרה."""
    import re
    gold_ids = {s["id"] for s in sigs if "id" in s}
    claims, losses = [], 0
    for m in msgs:
        is_gold = m.get("reply_to") in gold_ids or re.search(r"gold|xau", m["text"], re.I)
        if not is_gold:
            continue
        claims += [int(x) for x in re.findall(r"profit\W*\+?\s*(\d+)\s*pips", m["text"], re.I)]
        if re.search(r"\b(sl hit|stop ?loss hit|loss|hit sl)\b", m["text"], re.I) and not re.search(r"\bsl\s*[:@]", m["text"], re.I):
            losses += 1
    linked = sum(1 for m in msgs if m.get("reply_to") in gold_ids)
    return (f"📣 <b>מה הערוץ פרסם על הזהב:</b> {len(claims)} הודעות 'Profit' (סה\"כ +{sum(claims)} פיפס = "
            f"+{sum(claims) / 10:.0f}$ לאונקיה), {losses} הודעות על הפסד. {linked} הודעות הן תגובה ישירה לסיגנל זהב.\n"
            f"<i>פיפס בזהב = 0.1$, כלומר '+50 PIPS' = תנועה של 5$.</i>")


if __name__ == "__main__":
    main()
