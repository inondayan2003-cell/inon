"""שרת FastAPI: מגיש את ה-Mini App, ה-API, ומריץ את הבוט ואת לולאת הניתוח."""
import asyncio
import logging
import math
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analysis import TIMEFRAMES
from .auth import validate_init_data
from .bot import Bot
from .config import settings
from .service import GoldService
from .storage import Store, trade_stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gold")

store = Store(settings.db_path)
service = GoldService(settings, store)
bot = Bot(settings, store, lambda: service.snapshot) if settings.bot_token else None


BACKTEST_ID = "v1"  # מעלים כשהשיטה משתנה, כדי שהבוט ישלח דוח מעודכן אחרי עדכון גרסה


async def send_backtest_once():
    """אחרי עדכון גרסה: מריץ בדיקה היסטורית פעם אחת ושולח את הדוח לכל המנויים."""
    if store.get("backtest_sent") == BACKTEST_ID:
        return
    await asyncio.sleep(90)  # נותנים לניתוח החי לרוץ קודם
    report = await bot.backtest()
    await bot.broadcast(report, with_button=False)
    if not report.startswith("❌"):
        store.put("backtest_sent", BACKTEST_ID)


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = [asyncio.create_task(service.run())]
    if bot:
        service.notify = bot.broadcast
        tasks.append(asyncio.create_task(bot.run()))
        tasks.append(asyncio.create_task(send_backtest_once()))
    else:
        log.warning("BOT_TOKEN לא הוגדר - הבוט לא פעיל, רק ה-API")
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Gold Analyzer", lifespan=lifespan)


@app.get("/health")
def health():
    return {"ok": True, "has_data": service.snapshot is not None, "error": service.last_error}


@app.get("/api/analysis")
def get_analysis():
    if not service.snapshot:
        raise HTTPException(503, service.last_error or "הניתוח הראשון עוד רץ")
    trade = service.strategy_state().get("trade")
    return {**service.snapshot, "active_trade": trade, "error": service.last_error}


@app.get("/api/candles")
def get_candles(tf: str = "15m", limit: int = 200):
    if tf not in TIMEFRAMES:
        raise HTTPException(400, "טווח לא חוקי")
    if not service.analysis:
        raise HTTPException(503, "אין נתונים עדיין")
    df = service.analysis.enriched[tf].tail(min(limit, 500))

    def num(v):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 2)

    return [{"time": int(ts.timestamp()), "open": num(r.open), "high": num(r.high), "low": num(r.low),
             "close": num(r.close), "ema21": num(r.ema21), "ema50": num(r.ema50), "ema200": num(r.ema200)}
            for ts, r in df.iterrows()]


@app.get("/api/trades")
def get_trades():
    trades = store.trades(100)
    return {"trades": trades[:30], "stats": trade_stats(trades)}


def _user(init_data: str) -> dict:
    user = validate_init_data(init_data, settings.bot_token)
    if not user:
        raise HTTPException(401, "אימות טלגרם נכשל")
    if settings.allowed_user_ids and user.get("id") not in settings.allowed_user_ids:
        raise HTTPException(403, "בוט פרטי")
    return user


@app.get("/api/me")
def me(x_telegram_init_data: str = Header("")):
    user = _user(x_telegram_init_data)
    return {"id": user["id"], "name": user.get("first_name"), "alerts": store.is_subscribed(user["id"])}


class AlertsBody(BaseModel):
    enabled: bool


@app.post("/api/alerts")
def set_alerts(body: AlertsBody, x_telegram_init_data: str = Header("")):
    user = _user(x_telegram_init_data)
    # בצ'אט פרטי עם הבוט, ה-chat_id זהה ל-user_id
    store.set_subscription(user["id"], user["id"], user.get("first_name", ""), body.enabled)
    return {"alerts": body.enabled}


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "webapp", html=True), name="webapp")
