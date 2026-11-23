# סקריפט TradingView: לונג יומי

`gold_daily_long.pine` הוא אסטרטגיה (Pine Script v6) שמציירת על הגרף את הלונג היומי של הבוט:
אזור כניסה צהוב שקוף, אזור סטופ סגול שקוף, ממוצע 200 כתום, ורקע ירוק כשמותר לקנות.

## התקנה (פעם אחת)
1. ב-TradingView פותחים גרף של XAUUSD (או כל נכס אחר) ובוחרים טווח יומי: **1D**.
2. למטה: **Pine Editor**, מוחקים את מה שיש שם, ומדביקים את כל התוכן של `gold_daily_long.pine`.
3. **Save** ואז **Add to chart**.
4. הלשונית **Strategy Tester** מראה את התוצאות על כל ההיסטוריה: רווח, אחוז הצלחה, ירידה מקסימלית.

## הגדרות (גלגל השיניים ליד שם האינדיקטור)
ממוצע, ATR, גודל הסטופ, ימי החזקה, אחוז סיכון לעסקה, צבעים ושקיפות.

## התראות
**Alert** ← Condition: "Gold Daily Long" ← "alert() function calls only". מקבלים הודעה ב-BUY וב-EXIT.

## הבדלים מהבוט
- כאן הכניסה בפתיחת הנר היומי הבא, בבוט ב-08:00 שעון ישראל. המספרים יהיו קרובים, לא זהים.
- העמלה מוגדרת כ-0.35$ ליחידה, ו-1% סיכון לעסקה. אפשר לשנות במאפייני האסטרטגיה.

---

# Ultimate Gold (XAUUSD 4H): SMC / ICT
`Ultimate_Gold_Indicator.pine` ו-`Ultimate_Gold_Strategy.pine` נבנים מ-`src/ultimate_gold.src.pine`
עם `python tradingview/build_ultimate_gold.py`. אסור לערוך אותם ישירות.
הסבר, התקנה, התראות ומגבלות: `docs/ULTIMATE_GOLD.md`. תוצאות הבדיקה: `docs/ULTIMATE_GOLD_BACKTEST.md`.
