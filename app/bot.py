"""בוט טלגרם (long polling): פקודות, כפתור Mini App ושליחת התראות."""
import asyncio
import logging

import httpx
import pandas as pd

from .backtest import backtest_report
from .config import Settings
from .messages import status_message
from .signals import parse_signal, report as signals_report
from .storage import Store

log = logging.getLogger(__name__)

HELP = (
    "🥇 <b>סיגנלים לזהב (XAUUSD)</b>\n\n"
    "📡 אני שולח סיגנלים בשיטת הערוץ: אזור כניסה, TP1 / TP2 / TP3 ו-SL.\n\n"
    "🕒 <b>מתי:</b> שני עד שישי, בשעון ישראל: 09:15-10:30 · 14:00-16:15 · 17:15-19:45. "
    "עד 3 סיגנלים ביום, רק כשהזהב זז מספיק.\n"
    "🔁 <b>ניהול:</b> שליש בכל יעד. אחרי TP1 להזיז את ה-SL לכניסה.\n"
    "🔔 אחרי כל סיגנל תקבל עדכון: כניסה, כל TP, וסגירה.\n\n"
    "/status - מצב השוק עכשיו\n"
    "/backtest - בדיקה היסטורית על 6 החודשים האחרונים\n"
    "/signals - בדיקת סיגנלים שהעברת מקבוצה (Forward של ההודעות לכאן)\n"
    "/alerts_on - הפעלת התראות\n"
    "/alerts_off - השתקת התראות\n"
    "/app - פתיחת האפליקציה"
)


class Bot:
    def __init__(self, cfg: Settings, store: Store, get_snapshot):
        self.cfg = cfg
        self.store = store
        self.get_snapshot = get_snapshot
        self._backtest_lock = asyncio.Lock()
        self.client = httpx.AsyncClient(base_url=f"https://api.telegram.org/bot{cfg.bot_token}/", timeout=70)

    async def call(self, method: str, **params):
        r = await self.client.post(method, json=params)
        body = r.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method}: {body.get('description')}")
        return body["result"]

    def allowed(self, user_id: int) -> bool:
        return not self.cfg.allowed_user_ids or user_id in self.cfg.allowed_user_ids

    def app_button(self, text: str = "📊 פתח ניתוח מלא"):
        if not self.cfg.webapp_url:
            return None
        return {"inline_keyboard": [[{"text": text, "web_app": {"url": self.cfg.webapp_url}}]]}

    async def send(self, chat_id: int, text: str, with_button: bool = False):
        params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        markup = self.app_button() if with_button else None
        if markup:
            params["reply_markup"] = markup
        try:
            await self.call("sendMessage", **params)
        except Exception as e:  # משתמש שחסם את הבוט וכו'
            log.warning("שליחה ל-%s נכשלה: %s", chat_id, e)
            if "blocked" in str(e) or "chat not found" in str(e):
                self.store.set_subscription(chat_id, 0, "", False)

    async def broadcast(self, text: str, with_button: bool = True):
        for chat_id in self.store.subscribers():
            await self.send(chat_id, text, with_button)

    async def setup(self):
        await self.call("deleteWebhook")
        await self.call("setMyCommands", commands=[
            {"command": "status", "description": "הניתוח העדכני של הזהב"},
            {"command": "alerts_on", "description": "הפעלת התראות לונג/שורט"},
            {"command": "alerts_off", "description": "השתקת התראות"},
            {"command": "app", "description": "פתיחת האפליקציה"},
            {"command": "backtest", "description": "בדיקה היסטורית של השיטה"},
            {"command": "signals", "description": "בדיקת סיגנלים שהועברו מקבוצה"},
        ])
        if self.cfg.webapp_url:
            await self.call("setChatMenuButton", menu_button={
                "type": "web_app", "text": "זהב 📊", "web_app": {"url": self.cfg.webapp_url}})

    async def backtest(self, months: int = 6) -> str:
        async with self._backtest_lock:  # לא מריצים שתי בדיקות במקביל (מגבלת בקשות של ספק הנתונים)
            try:
                return await asyncio.to_thread(backtest_report, self.cfg, months)
            except Exception as e:
                log.exception("backtest")
                return f"❌ הבדיקה ההיסטורית נכשלה: {e}"

    async def run(self):
        await self.setup()
        offset = 0
        while True:
            try:
                updates = await self.call("getUpdates", offset=offset, timeout=50, allowed_updates=["message"])
                for u in updates:
                    offset = u["update_id"] + 1
                    if "message" in u:
                        await self.handle(u["message"])
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("polling: %s", e)
                await asyncio.sleep(5)

    async def save_group_signal(self, chat_id: int, msg: dict, sig: dict):
        """סיגנל שהועבר (Forward) מקבוצה: שומרים עם שעת השליחה המקורית."""
        origin = msg.get("forward_origin") or {}
        ts = origin.get("date") or msg.get("forward_date")
        forwarded = ts is not None
        ts = ts or msg.get("date")
        t = pd.Timestamp(ts, unit="s", tz="UTC").isoformat()
        sigs = self.store.get("group_signals", [])
        if any(x["t"] == t and x["sl"] == sig["sl"] for x in sigs):
            await self.send(chat_id, "ℹ️ הסיגנל הזה כבר שמור.")
            return
        sigs.append({**sig, "t": t, "forwarded": forwarded})
        sigs.sort(key=lambda x: x["t"])
        self.store.put("group_signals", sigs)
        when = pd.Timestamp(t).tz_convert("Asia/Jerusalem").strftime("%d/%m/%Y %H:%M")
        note = "" if forwarded else "\n⚠️ זו לא הודעה מועברת, אז נשמרה שעת ההדבקה. לבדיקה מדויקת עדיף Forward."
        await self.send(chat_id, f"✅ נשמר סיגנל #{len(sigs)}: {'קנייה' if sig['direction'] == 1 else 'מכירה'} "
                                 f"{sig['zone_lo']:g}-{sig['zone_hi']:g}, SL {sig['sl']:g}, {len(sig['tps'])} יעדים · {when}"
                                 f"{note}\nכשתסיים להעביר, שלח /signals לבדיקה.")

    async def handle(self, msg: dict):
        text = (msg.get("text") or "").strip()
        chat_id, user = msg["chat"]["id"], msg.get("from", {})
        if not self.allowed(user.get("id", 0)):
            await self.send(chat_id, f"⛔ בוט פרטי. ה-ID שלך: <code>{user.get('id')}</code>")
            return
        cmd = text.split()[0].split("@")[0].lower() if text else ""
        name = user.get("first_name", "")
        if not cmd.startswith("/") and (sig := parse_signal(text or msg.get("caption") or "")):
            await self.save_group_signal(chat_id, msg, sig)
            return
        if cmd in ("/start", "/alerts_on"):
            self.store.set_subscription(chat_id, user.get("id", 0), name, True)
            prefix = f"שלום {name}! " if cmd == "/start" else ""
            await self.send(chat_id, f"{prefix}🔔 ההתראות פעילות.\n\n{HELP}", with_button=True)
        elif cmd == "/alerts_off":
            self.store.set_subscription(chat_id, user.get("id", 0), name, False)
            await self.send(chat_id, "🔕 ההתראות הושתקו. /alerts_on כדי להפעיל מחדש.")
        elif cmd == "/status":
            snap = self.get_snapshot()
            await self.send(chat_id, status_message(snap) if snap else "⏳ הניתוח הראשון עוד רץ, נסה שוב בעוד דקה.",
                            with_button=True)
        elif cmd == "/backtest":
            await self.send(chat_id, "⏳ מריץ את השיטה על 6 החודשים האחרונים של הזהב. זה לוקח כ-3 דקות...")
            await self.send(chat_id, await self.backtest())
        elif cmd == "/signals":
            sigs = self.store.get("group_signals", [])
            if not sigs:
                await self.send(chat_id, "אין סיגנלים שמורים. עשה Forward להודעות הסיגנל מהקבוצה אל הבוט.")
                return
            if text.split()[1:2] == ["clear"]:
                self.store.put("group_signals", [])
                await self.send(chat_id, "🗑 הסיגנלים השמורים נמחקו.")
                return
            await self.send(chat_id, f"⏳ בודק {len(sigs)} סיגנלים מול נרות דקה אמיתיים (כ-10 שניות לסיגנל)...")
            async with self._backtest_lock:
                text_out = await asyncio.to_thread(signals_report, sigs, self.cfg.td_symbol, self.cfg.twelvedata_api_key)
            for i in range(0, len(text_out), 3800):
                await self.send(chat_id, text_out[i:i + 3800])
        elif cmd == "/app":
            await self.send(chat_id, "פתח את האפליקציה:", with_button=True)
        else:
            await self.send(chat_id, HELP, with_button=True)
