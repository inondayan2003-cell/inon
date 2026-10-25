"""הגדרות האפליקציה - נקראות ממשתני סביבה."""
import os
from dataclasses import dataclass, field


def _int_set(raw: str) -> frozenset[int]:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x)


@dataclass(frozen=True)
class Settings:
    bot_token: str = ""
    webapp_url: str = ""
    twelvedata_api_key: str = ""
    # auto = Twelve Data (XAU/USD ספוט) אם יש מפתח, אחרת Yahoo (חוזה עתידי GC=F)
    data_provider: str = "auto"
    yf_symbol: str = "GC=F"
    td_symbol: str = "XAU/USD"
    check_interval: int = 120
    db_path: str = "data/bot.db"
    allowed_user_ids: frozenset[int] = field(default_factory=frozenset)
    # אילו שיטות שולחות התראות. מגמה הפסידה בבדיקה של 6 חודשים (PF 0.88) - רצה רק במעקב
    alert_methods: frozenset[str] = frozenset({"liquidity"})

    # פרמטרים של אסטרטגיית הסיגנלים
    entry_threshold: float = 50.0     # ציון משוקלל מינימלי לכניסה
    exit_threshold: float = 20.0      # מתחת לזה הסיגנל נחשב "נחלש"
    min_adx: float = 18.0             # עוצמת מגמה מינימלית ב-15M
    max_stretch_atr: float = 2.0      # לא רודפים: מרחק מקסימלי מ-EMA21 ב-15M ביחידות ATR
    cooldown_minutes: int = 45        # מניעת סיגנלים חוזרים לאותו כיוון
    trade_expiry_hours: int = 8       # עסקה יומית נסגרת אחרי X שעות
    sl_atr_mult: float = 1.5

    @property
    def provider(self) -> str:
        if self.data_provider != "auto":
            return self.data_provider
        return "twelvedata" if self.twelvedata_api_key else "yfinance"


def load_settings() -> Settings:
    e = os.environ.get
    provider = e("DATA_PROVIDER", "auto").lower()
    has_td = bool(e("TWELVEDATA_API_KEY")) and provider in ("auto", "twelvedata")
    return Settings(
        bot_token=e("BOT_TOKEN", ""),
        webapp_url=e("WEBAPP_URL", "").rstrip("/"),
        twelvedata_api_key=e("TWELVEDATA_API_KEY", ""),
        data_provider=provider,
        yf_symbol=e("YF_SYMBOL", "GC=F"),
        td_symbol=e("TD_SYMBOL", "XAU/USD"),
        # Twelve Data בחינם = 800 בקשות ביום, לכן בודקים כל 5 דקות
        check_interval=int(e("CHECK_INTERVAL_SECONDS", "300" if has_td else "120")),
        db_path=e("DB_PATH", "data/bot.db"),
        allowed_user_ids=_int_set(e("ALLOWED_USER_IDS", "")),
        alert_methods=frozenset(e("ALERT_METHODS", "liquidity").replace(" ", "").split(",")),
    )


settings = load_settings()
