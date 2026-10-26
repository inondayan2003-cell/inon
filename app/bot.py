"""בוט טלגרם (long polling): פקודות, כפתור Mini App ושליחת התראות."""
import asyncio
import logging

import httpx

from .backtest import backtest_report
from .config import Settings
from .messages import status_message
from .storage import Store

log = logging.getLogger(__name__)

HELP = (
    "🥇 <b>אנליסט הזהב שלך</b>\n\n"
    "🇬🇧 <b>שיטה אחת: שורט לונדון.</b> בשעות לונדון אני מחפש רגע של תנודתיות נמוכה, בלי עלייה חזקה "
    "ובלי פתיל עליון גדול, ושולח סיגנל שורט עם סטופ ויעד ביחס 1:2. אחר כך אני מעדכן כשהעסקה מגיעה "
    "ליעד, לסטופ או לזמן הסגירה.\n\n"
    "🧪 מבחן חי - לסחור בחשבון דמו בלבד.\n\n"
    "/status - מצב השוק עכשיו\n"
    "/backtest - בדיקה היסטורית על 6 החודשים האחרונים\n"
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

    async def handle(self, msg: dict):
        text = (msg.get("text") or "").strip()
        chat_id, user = msg["chat"]["id"], msg.get("from", {})
        if not self.allowed(user.get("id", 0)):
            await self.send(chat_id, f"⛔ בוט פרטי. ה-ID שלך: <code>{user.get('id')}</code>")
            return
        cmd = text.split()[0].split("@")[0].lower() if text else ""
        name = user.get("first_name", "")
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
        elif cmd == "/app":
            await self.send(chat_id, "פתח את האפליקציה:", with_button=True)
        else:
            await self.send(chat_id, HELP, with_button=True)
