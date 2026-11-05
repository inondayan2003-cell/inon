//+------------------------------------------------------------------+
//|                                              BreakoutTrail.mq5   |
//|  Gold breakout scalper (XAUUSD) - version 2.00                   |
//|                                                                  |
//|  Entry:                                                          |
//|   - Buy level above price and Sell level below price, both       |
//|     always following the price. A fast move (breakout) hits one. |
//|   - Mode "Stop orders": real Buy Stop / Sell Stop at the broker. |
//|   - Mode "Virtual (mid)": levels are watched by the EA on the    |
//|     MID price ((bid+ask)/2), so a spread spike alone never       |
//|     triggers an entry. Entry is sent as a market order.          |
//|   - Reverse mode: while in a trade the opposite level keeps      |
//|     following the price; if it is hit the trade is flipped.      |
//|                                                                  |
//|  Spread protection:                                              |
//|   - Running average of the spread; spikes pause all entries.     |
//|   - Entry distance and SL are never smaller than spread x mult.  |
//|                                                                  |
//|  Exit: initial SL, break-even, stepped trailing stop (3 steps).  |
//|                                                                  |
//|  Risk: daily loss limit, daily profit target, pause after a      |
//|  losing streak, hard max lot, Friday close.                      |
//|                                                                  |
//|  Filters: max spread, session hours, rollover (midnight),        |
//|  economic news (MT5 calendar, live only).                        |
//|                                                                  |
//|  Logging: CSV file per deal in MQL5\Files + panel on the chart.  |
//|                                                                  |
//|  All distances are in PRICE units. For XAUUSD 1.0 = $1 move.     |
//+------------------------------------------------------------------+
#property copyright "inon"
#property version   "2.01"
#property description "Gold breakout scalper: trailing entries, reverse mode, spread protection, daily risk limits"

#include <Trade\Trade.mqh>

enum ENUM_ENTRY_MODE
{
   ENTRY_STOP_ORDERS = 0,   // Stop orders at the broker
   ENTRY_VIRTUAL_MID = 1    // Virtual levels on mid price
};

//=== Volume ========================================================
input group "=== Volume ==="
input double InpLots            = 0.01;   // Fixed lot size
input bool   InpUseRisk         = false;  // Use risk % instead of fixed lot
input double InpRiskPercent     = 1.0;    // Risk % of balance per trade (if enabled)
input double InpMaxLots         = 5.0;    // Hard maximum lot size

//=== Entry =========================================================
input group "=== Entry ==="
input ENUM_ENTRY_MODE InpEntryMode    = ENTRY_STOP_ORDERS; // Entry mode
input double          InpDistance     = 0.30;  // Distance of entry levels from price
input double          InpStopLoss     = 0.60;  // Initial stop loss
input double          InpTakeProfit   = 0.0;   // Take profit (0 = none, trailing only)
input double          InpDistSpreadMult = 1.2; // Entry distance is at least spread x this
input double          InpSLSpreadMult = 2.0;   // Stop loss is at least spread x this
input bool            InpUseATR       = false; // Use ATR for distance & SL instead of fixed
input ENUM_TIMEFRAMES InpATRTf        = PERIOD_M1; // ATR timeframe
input int             InpATRPeriod    = 14;    // ATR period
input double          InpDistATR      = 0.5;   // Distance = ATR x this
input double          InpSLATR        = 1.0;   // Stop loss = ATR x this
input double          InpStep         = 0.05;  // Move entry levels only if target changed by at least this
input int             InpModifyMs     = 200;   // Minimum time between level moves (ms)

//=== Reverse mode ==================================================
input group "=== Reverse mode ==="
input bool   InpReverseMode     = true;   // Keep the opposite entry while in a trade
input bool   InpCloseOnReverse  = true;   // When the opposite entry fills, close the old trade (flip)

//=== Exit ==========================================================
input group "=== Break-even & stepped trailing stop ==="
input double InpBreakEven       = 0.15;   // Move SL to entry after this profit (0 = off)
input double InpBELock          = 0.05;   // Profit locked at break-even
input double InpTrailStart      = 0.20;   // Trailing step 1: start after this profit
input double InpTrailDist       = 0.15;   // Trailing step 1: distance from price (0 = off)
input double InpTrail2Start     = 0.0;    // Trailing step 2: start after this profit (0 = off)
input double InpTrail2Dist      = 0.25;   // Trailing step 2: distance from price
input double InpTrail3Start     = 0.0;    // Trailing step 3: start after this profit (0 = off)
input double InpTrail3Dist      = 0.40;   // Trailing step 3: distance from price
input double InpTrailStep       = 0.05;   // Move SL only in steps of at least this

//=== Spread protection =============================================
input group "=== Spread protection ==="
input double InpMaxSpread       = 0.50;   // Absolute max spread (no new entries above)
input double InpSpikeMult       = 1.8;    // Spike = spread above average x this (0 = off)
input int    InpSpreadAvgTicks  = 300;    // Number of ticks in the spread average

//=== Daily risk ====================================================
input group "=== Daily risk protection ==="
input double InpDailyLossMoney  = 0.0;    // Daily loss limit in money (0 = off)
input double InpDailyLossPct    = 3.0;    // Daily loss limit in % of day start balance (0 = off)
input double InpDailyProfitMoney= 0.0;    // Daily profit target in money (0 = off)
input double InpDailyProfitPct  = 0.0;    // Daily profit target in % (0 = off)
input int    InpMaxConsecLosses = 6;      // Pause after this many losses in a row (0 = off)
input int    InpPauseMinutes    = 10;     // Pause length after a losing streak (minutes)
input int    InpMaxTradesDay    = 0;      // Max entries per day (0 = unlimited)
input int    InpCooldownSec     = 0;      // Seconds to wait after a trade closes (when flat)

//=== Time filters ==================================================
input group "=== Time filters (server time) ==="
input bool   InpUseSession      = false;  // Trade only between hours
input int    InpStartHour       = 1;      // Session start hour
input int    InpEndHour         = 23;     // Session end hour
input int    InpRolloverBefore  = 15;     // No new entries X minutes before midnight (0 = off)
input int    InpRolloverAfter   = 30;     // No new entries X minutes after midnight (0 = off)
input int    InpFridayCloseHour = 22;     // Friday: close all and stop at this hour (-1 = off)

//=== News filter ===================================================
input group "=== News filter (live trading only) ==="
input bool   InpUseNews         = true;   // Pause around economic news
input string InpNewsCurrency    = "USD";  // News currency
input bool   InpNewsHighOnly    = true;   // Only high impact news (false = also medium)
input int    InpNewsBeforeMin   = 5;      // Minutes before news
input int    InpNewsAfterMin    = 5;      // Minutes after news

//=== Logging =======================================================
input group "=== Logging & display ==="
input bool   InpWriteCsv        = true;   // Write every deal to MQL5\Files\BreakoutTrail_<symbol>.csv
input bool   InpShowPanel       = true;   // Show info panel on the chart
input bool   InpDrawVirtual     = true;   // Draw virtual entry levels on the chart

//=== General =======================================================
input group "=== General ==="
input long   InpMagic           = 20261104;        // Magic number
input int    InpDeviation       = 50;              // Max deviation for market orders (points)
input string InpComment         = "BreakoutTrail"; // Order comment

//--- Globals --------------------------------------------------------
CTrade   trade;
int      atrHandle       = INVALID_HANDLE;
double   tickSize        = 0.0;
int      digits          = 0;

ulong    lastModifyMs    = 0;
ulong    lastVirtualMs   = 0;
double   vBuy            = 0.0;     // virtual buy level (0 = none)
double   vSell           = 0.0;     // virtual sell level (0 = none)
double   lastRequested   = 0.0;     // requested price of the last market entry

datetime lastCloseTime   = 0;
datetime pauseUntil      = 0;
int      prevPositions   = 0;

int      currentDay      = -1;
int      tradesToday     = 0;
int      winsToday       = 0;
int      lossesToday     = 0;
int      consecLosses    = 0;
double   realizedToday   = 0.0;
double   dayStartBalance = 0.0;
double   slipSum         = 0.0;
int      slipCount       = 0;
bool     haltedToday     = false;
string   haltReason      = "";

double   avgSpread       = 0.0;
double   gDist           = 0.0;
double   gSL             = 0.0;
string   gState          = "";

datetime newsTimes[];
datetime lastNewsLoad    = 0;

const string OBJ_VBUY  = "BT_VBUY";
const string OBJ_VSELL = "BT_VSELL";

//+------------------------------------------------------------------+
//| Init / deinit                                                     |
//+------------------------------------------------------------------+
int OnInit()
{
   tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0.0) tickSize = _Point;
   digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   if(InpDistance <= 0 || InpStopLoss <= 0 || InpStep < 0 || InpLots <= 0)
   {
      Print("Invalid inputs: lots, distance and stop loss must be > 0");
      return INIT_PARAMETERS_INCORRECT;
   }

   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpDeviation);
   trade.SetTypeFillingBySymbol(_Symbol);
   trade.SetAsyncMode(false);

   if(InpUseATR)
   {
      atrHandle = iATR(_Symbol, InpATRTf, InpATRPeriod);
      if(atrHandle == INVALID_HANDLE)
      {
         Print("Failed to create ATR handle, error ", GetLastError());
         return INIT_FAILED;
      }
   }

   MqlTick t;
   if(SymbolInfoTick(_Symbol, t)) avgSpread = t.ask - t.bid;

   currentDay = -1;
   CheckNewDay();
   prevPositions = CountPositions();
   gState = "Starting";
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   // If the EA is removed, do not leave orders that no longer follow the price
   if(reason == REASON_REMOVE || reason == REASON_CHARTCLOSE)
      DeleteAllPendings();
   ObjectDelete(0, OBJ_VBUY);
   ObjectDelete(0, OBJ_VSELL);
   if(atrHandle != INVALID_HANDLE) IndicatorRelease(atrHandle);
   Comment("");
}

//+------------------------------------------------------------------+
//| Main loop                                                         |
//+------------------------------------------------------------------+
void OnTick()
{
   MqlTick t;
   if(!SymbolInfoTick(_Symbol, t)) return;
   double spread = t.ask - t.bid;

   UpdateSpreadAverage(spread);
   CheckNewDay();
   LoadNews();

   //--- 1. Manage open positions (break-even + trailing)
   int positions = ManagePositions(t);
   if(prevPositions > 0 && positions == 0) lastCloseTime = TimeCurrent();
   prevPositions = positions;

   bool hasLong = false, hasShort = false;
   if(positions > 0) GetPositionSides(hasLong, hasShort);

   //--- 2. Hard stops: daily limits and Friday close
   if(!haltedToday) CheckDailyLimits();
   if(haltedToday)
   {
      if(positions > 0) CloseAllPositions();
      CancelEntries();
      gState = haltReason + " - stopped until tomorrow";
      ShowPanel(t);
      return;
   }
   if(IsFridayClose())
   {
      if(positions > 0) CloseAllPositions();
      CancelEntries();
      gState = "Friday close - waiting for next week";
      ShowPanel(t);
      return;
   }

   //--- 3. Without reverse mode: no entries while in a trade
   if(positions > 0 && !InpReverseMode)
   {
      CancelEntries();
      gState = "In trade - trailing";
      ShowPanel(t);
      return;
   }

   //--- 4. Entry filters (cooldown only when flat)
   string reason = "";
   if(!CanTrade(t, spread, reason, positions == 0))
   {
      CancelEntries();
      gState = (positions > 0) ? "In trade - trailing | " + reason : reason;
      ShowPanel(t);
      return;
   }

   //--- 5. Distances
   if(!GetDistances(spread, gDist, gSL))
   {
      gState = "Waiting for ATR data";
      ShowPanel(t);
      return;
   }

   //--- 6. Entry levels
   bool allowBuy  = (positions == 0) || (hasShort && !hasLong);
   bool allowSell = (positions == 0) || (hasLong && !hasShort);

   if(InpEntryMode == ENTRY_STOP_ORDERS)
      TrackPendings(t, gDist, gSL, allowBuy, allowSell);
   else
      TrackVirtual(t, gDist, gSL, allowBuy, allowSell);

   if(positions == 0)
      gState = "Waiting for breakout";
   else if(hasLong)
      gState = "In BUY - trailing | sell entry ready to flip";
   else
      gState = "In SELL - trailing | buy entry ready to flip";

   ShowPanel(t);
}

//+------------------------------------------------------------------+
//| Every deal: statistics, flip, CSV                                 |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   ulong deal = trans.deal;
   if(!HistoryDealSelect(deal)) return;
   if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) return;
   if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic) return;

   long   entry    = HistoryDealGetInteger(deal, DEAL_ENTRY);
   long   dealType = HistoryDealGetInteger(deal, DEAL_TYPE);
   double price    = HistoryDealGetDouble(deal, DEAL_PRICE);
   double volume   = HistoryDealGetDouble(deal, DEAL_VOLUME);
   double money    = HistoryDealGetDouble(deal, DEAL_PROFIT)
                   + HistoryDealGetDouble(deal, DEAL_COMMISSION)
                   + HistoryDealGetDouble(deal, DEAL_SWAP);
   string reason   = EnumToString((ENUM_DEAL_REASON)HistoryDealGetInteger(deal, DEAL_REASON));

   double spread = 0.0;
   MqlTick t;
   if(SymbolInfoTick(_Symbol, t)) spread = t.ask - t.bid;

   realizedToday += money;

   if(entry == DEAL_ENTRY_IN)
   {
      tradesToday++;

      //--- slippage: positive = worse than requested
      double requested = 0.0;
      if(InpEntryMode == ENTRY_VIRTUAL_MID)
         requested = lastRequested;
      else
      {
         ulong order = (ulong)HistoryDealGetInteger(deal, DEAL_ORDER);
         if(order > 0 && HistoryOrderSelect(order))
            requested = HistoryOrderGetDouble(order, ORDER_PRICE_OPEN);
      }
      double slip = 0.0;
      if(requested > 0)
      {
         slip = (dealType == DEAL_TYPE_BUY) ? price - requested : requested - price;
         slipSum += slip;
         slipCount++;
      }

      WriteCsv("IN", deal, (dealType == DEAL_TYPE_BUY) ? "BUY" : "SELL",
               volume, price, requested, slip, spread, money, reason);

      if(!InpReverseMode)
         DeleteAllPendings();
      else if(InpCloseOnReverse)
      {
         if(dealType == DEAL_TYPE_BUY)  ClosePositions(POSITION_TYPE_SELL);
         if(dealType == DEAL_TYPE_SELL) ClosePositions(POSITION_TYPE_BUY);
      }
   }
   else if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
   {
      lastCloseTime = TimeCurrent();

      if(money >= 0)
      {
         winsToday++;
         consecLosses = 0;
      }
      else
      {
         lossesToday++;
         consecLosses++;
         if(InpMaxConsecLosses > 0 && consecLosses >= InpMaxConsecLosses)
         {
            pauseUntil   = TimeCurrent() + InpPauseMinutes * 60;
            consecLosses = 0;
            Print("Losing streak - pausing new entries for ", InpPauseMinutes, " minutes");
         }
      }

      // a closing BUY deal closes a SELL position and vice versa
      WriteCsv("OUT", deal, (dealType == DEAL_TYPE_BUY) ? "SELL" : "BUY",
               volume, price, 0.0, 0.0, spread, money, reason);
   }
}

//+------------------------------------------------------------------+
//| Entry: real stop orders                                           |
//+------------------------------------------------------------------+
void TrackPendings(const MqlTick &t, double dist, double slDist, bool allowBuy, bool allowSell)
{
   ResetVirtual();

   ulong buyT = 0, sellT = 0;
   FindPendings(buyT, sellT);

   if(!allowBuy && buyT != 0)   { trade.OrderDelete(buyT);  buyT = 0; }
   if(!allowSell && sellT != 0) { trade.OrderDelete(sellT); sellT = 0; }

   double lots      = CalcLots(slDist);
   double buyPrice  = NormPrice(t.ask + dist);
   double sellPrice = NormPrice(t.bid - dist);
   double buySL     = NormPrice(buyPrice - slDist);
   double sellSL    = NormPrice(sellPrice + slDist);
   double buyTP     = (InpTakeProfit > 0) ? NormPrice(buyPrice + InpTakeProfit) : 0.0;
   double sellTP    = (InpTakeProfit > 0) ? NormPrice(sellPrice - InpTakeProfit) : 0.0;

   double freeze    = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL) * _Point;
   bool   canModify = ((ulong)t.time_msc - lastModifyMs) >= (ulong)InpModifyMs;

   //--- Buy Stop
   if(allowBuy)
   {
      if(buyT == 0)
      {
         if(!trade.BuyStop(lots, buyPrice, _Symbol, buySL, buyTP, ORDER_TIME_GTC, 0, InpComment))
            Print("BuyStop failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      }
      else if(canModify && OrderSelect(buyT))
      {
         double cur    = OrderGetDouble(ORDER_PRICE_OPEN);
         bool   frozen = (freeze > 0 && cur - t.ask <= freeze);
         if(MathAbs(cur - buyPrice) >= InpStep && !frozen)
         {
            if(trade.OrderModify(buyT, buyPrice, buySL, buyTP, ORDER_TIME_GTC, 0))
               lastModifyMs = (ulong)t.time_msc;
         }
      }
   }

   //--- Sell Stop
   if(allowSell)
   {
      if(sellT == 0)
      {
         if(!trade.SellStop(lots, sellPrice, _Symbol, sellSL, sellTP, ORDER_TIME_GTC, 0, InpComment))
            Print("SellStop failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
      }
      else if(canModify && OrderSelect(sellT))
      {
         double cur    = OrderGetDouble(ORDER_PRICE_OPEN);
         bool   frozen = (freeze > 0 && t.bid - cur <= freeze);
         if(MathAbs(cur - sellPrice) >= InpStep && !frozen)
         {
            if(trade.OrderModify(sellT, sellPrice, sellSL, sellTP, ORDER_TIME_GTC, 0))
               lastModifyMs = (ulong)t.time_msc;
         }
      }
   }
}

void FindPendings(ulong &buyT, ulong &sellT)
{
   buyT = 0; sellT = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;

      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type == ORDER_TYPE_BUY_STOP)
      {
         if(buyT == 0) buyT = ticket; else trade.OrderDelete(ticket);   // remove duplicates
      }
      else if(type == ORDER_TYPE_SELL_STOP)
      {
         if(sellT == 0) sellT = ticket; else trade.OrderDelete(ticket);
      }
   }
}

void DeleteAllPendings()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0) continue;
      if(OrderGetString(ORDER_SYMBOL) != _Symbol) continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagic) continue;
      ENUM_ORDER_TYPE type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
      if(type == ORDER_TYPE_BUY_STOP || type == ORDER_TYPE_SELL_STOP)
         trade.OrderDelete(ticket);
   }
}

//+------------------------------------------------------------------+
//| Entry: virtual levels on the mid price                            |
//+------------------------------------------------------------------+
void TrackVirtual(const MqlTick &t, double dist, double slDist, bool allowBuy, bool allowSell)
{
   DeleteAllPendings();   // this mode never keeps orders at the broker

   double mid = (t.bid + t.ask) / 2.0;

   if(!allowBuy)  vBuy  = 0.0;
   if(!allowSell) vSell = 0.0;

   //--- triggers first
   if(allowBuy && vBuy > 0 && mid >= vBuy)
   {
      OpenMarket(true, t, slDist);
      vBuy = 0.0; vSell = 0.0;
      DrawVirtual();
      return;
   }
   if(allowSell && vSell > 0 && mid <= vSell)
   {
      OpenMarket(false, t, slDist);
      vBuy = 0.0; vSell = 0.0;
      DrawVirtual();
      return;
   }

   //--- follow the price
   bool canUpdate = ((ulong)t.time_msc - lastVirtualMs) >= (ulong)InpModifyMs;
   bool updated   = false;

   if(allowBuy)
   {
      double target = mid + dist;
      if(vBuy == 0.0) vBuy = target;
      else if(canUpdate && MathAbs(vBuy - target) >= InpStep) { vBuy = target; updated = true; }
   }
   if(allowSell)
   {
      double target = mid - dist;
      if(vSell == 0.0) vSell = target;
      else if(canUpdate && MathAbs(vSell - target) >= InpStep) { vSell = target; updated = true; }
   }
   if(updated) lastVirtualMs = (ulong)t.time_msc;

   DrawVirtual();
}

void OpenMarket(bool isBuy, const MqlTick &t, double slDist)
{
   if(InpReverseMode && InpCloseOnReverse)
      ClosePositions(isBuy ? POSITION_TYPE_SELL : POSITION_TYPE_BUY);

   double lots = CalcLots(slDist);
   if(isBuy)
   {
      lastRequested = t.ask;
      double sl = NormPrice(t.ask - slDist);
      double tp = (InpTakeProfit > 0) ? NormPrice(t.ask + InpTakeProfit) : 0.0;
      if(!trade.Buy(lots, _Symbol, 0.0, sl, tp, InpComment))
         Print("Market BUY failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   }
   else
   {
      lastRequested = t.bid;
      double sl = NormPrice(t.bid + slDist);
      double tp = (InpTakeProfit > 0) ? NormPrice(t.bid - InpTakeProfit) : 0.0;
      if(!trade.Sell(lots, _Symbol, 0.0, sl, tp, InpComment))
         Print("Market SELL failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   }
}

void ResetVirtual()
{
   vBuy  = 0.0;
   vSell = 0.0;
   DrawVirtual();
}

void CancelEntries()
{
   DeleteAllPendings();
   ResetVirtual();
}

void DrawVirtual()
{
   bool show = InpDrawVirtual && InpEntryMode == ENTRY_VIRTUAL_MID;
   DrawLine(OBJ_VBUY,  show ? vBuy  : 0.0, clrDodgerBlue);
   DrawLine(OBJ_VSELL, show ? vSell : 0.0, clrTomato);
}

void DrawLine(string name, double price, color clr)
{
   if(price <= 0.0)
   {
      if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
      return;
   }
   if(ObjectFind(0, name) < 0)
   {
      ObjectCreate(0, name, OBJ_HLINE, 0, 0, price);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
      ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
   }
   else
      ObjectMove(0, name, 0, 0, price);
}

//+------------------------------------------------------------------+
//| Positions: break-even + stepped trailing stop                     |
//+------------------------------------------------------------------+
double TrailDistanceFor(double profit)
{
   double d = 0.0;
   if(InpTrailDist > 0 && profit >= InpTrailStart)                      d = InpTrailDist;
   if(InpTrail2Start > 0 && InpTrail2Dist > 0 && profit >= InpTrail2Start) d = InpTrail2Dist;
   if(InpTrail3Start > 0 && InpTrail3Dist > 0 && profit >= InpTrail3Start) d = InpTrail3Dist;
   return d;
}

int ManagePositions(const MqlTick &t)
{
   int    count     = 0;
   double stopLevel = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;
   double freeze    = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL) * _Point;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      count++;

      long   type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl   = PositionGetDouble(POSITION_SL);
      double tp   = PositionGetDouble(POSITION_TP);

      if(type == POSITION_TYPE_BUY)
      {
         double profit = t.bid - open;
         double newSL  = sl;

         if(InpBreakEven > 0 && profit >= InpBreakEven)
            newSL = MathMax(newSL, NormPrice(open + InpBELock));

         double td = TrailDistanceFor(profit);
         if(td > 0)
         {
            double tr = NormPrice(t.bid - td);
            if(tr >= sl + InpTrailStep) newSL = MathMax(newSL, tr);
         }

         if(newSL > sl + tickSize / 2
            && newSL <= t.bid - stopLevel
            && !(freeze > 0 && sl > 0 && t.bid - sl <= freeze))
         {
            if(!trade.PositionModify(ticket, newSL, tp))
               Print("Trail BUY failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
         }
      }
      else if(type == POSITION_TYPE_SELL)
      {
         double profit = open - t.ask;
         double curSL  = (sl > 0) ? sl : DBL_MAX;
         double newSL  = curSL;

         if(InpBreakEven > 0 && profit >= InpBreakEven)
            newSL = MathMin(newSL, NormPrice(open - InpBELock));

         double td = TrailDistanceFor(profit);
         if(td > 0)
         {
            double tr = NormPrice(t.ask + td);
            if(tr <= curSL - InpTrailStep) newSL = MathMin(newSL, tr);
         }

         if(newSL < curSL - tickSize / 2
            && newSL >= t.ask + stopLevel
            && !(freeze > 0 && sl > 0 && sl - t.ask <= freeze))
         {
            if(!trade.PositionModify(ticket, newSL, tp))
               Print("Trail SELL failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
         }
      }
   }
   return count;
}

void GetPositionSides(bool &hasLong, bool &hasShort)
{
   hasLong = false; hasShort = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) hasLong = true;
      else hasShort = true;
   }
}

void ClosePositions(ENUM_POSITION_TYPE side)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      if(PositionGetInteger(POSITION_TYPE) != side) continue;
      if(!trade.PositionClose(ticket))
         Print("Close failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   }
}

void CloseAllPositions()
{
   ClosePositions(POSITION_TYPE_BUY);
   ClosePositions(POSITION_TYPE_SELL);
}

int CountPositions()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         count++;
   }
   return count;
}

double GetFloating()
{
   double sum = 0.0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0) continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol) continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      sum += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   }
   return sum;
}

//+------------------------------------------------------------------+
//| Daily risk                                                        |
//+------------------------------------------------------------------+
double SmallestPositive(double a, double b)
{
   if(a > 0 && b > 0) return MathMin(a, b);
   if(a > 0) return a;
   if(b > 0) return b;
   return 0.0;
}

void CheckDailyLimits()
{
   double dayPL = realizedToday + GetFloating();

   double lossLimit = SmallestPositive(InpDailyLossMoney,
                                       (InpDailyLossPct > 0) ? dayStartBalance * InpDailyLossPct / 100.0 : 0.0);
   double profitTarget = SmallestPositive(InpDailyProfitMoney,
                                          (InpDailyProfitPct > 0) ? dayStartBalance * InpDailyProfitPct / 100.0 : 0.0);

   if(lossLimit > 0 && dayPL <= -lossLimit)
   {
      haltedToday = true;
      haltReason  = StringFormat("Daily loss limit hit (%.2f)", dayPL);
      Print(haltReason);
   }
   else if(profitTarget > 0 && dayPL >= profitTarget)
   {
      haltedToday = true;
      haltReason  = StringFormat("Daily profit target reached (%.2f)", dayPL);
      Print(haltReason);
   }
}

void CheckNewDay()
{
   int d = DayOfYear(TimeCurrent());
   if(d == currentDay) return;

   currentDay = d;
   LoadTodayFromHistory();
   dayStartBalance = AccountInfoDouble(ACCOUNT_BALANCE) - realizedToday;
   haltedToday  = false;
   haltReason   = "";
   slipSum      = 0.0;
   slipCount    = 0;
   consecLosses = 0;
   pauseUntil   = 0;
}

void LoadTodayFromHistory()
{
   tradesToday   = 0;
   winsToday     = 0;
   lossesToday   = 0;
   realizedToday = 0.0;

   if(!HistorySelect(DayStart(TimeCurrent()), TimeCurrent() + 60)) return;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic) continue;

      double money = HistoryDealGetDouble(deal, DEAL_PROFIT)
                   + HistoryDealGetDouble(deal, DEAL_COMMISSION)
                   + HistoryDealGetDouble(deal, DEAL_SWAP);
      realizedToday += money;

      long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
      if(entry == DEAL_ENTRY_IN) tradesToday++;
      else if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
      {
         if(money >= 0) winsToday++; else lossesToday++;
      }
   }
}

//+------------------------------------------------------------------+
//| Filters                                                           |
//+------------------------------------------------------------------+
bool CanTrade(const MqlTick &t, double spread, string &reason, bool checkCooldown)
{
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
   { reason = "Algo trading is disabled (press Algo Trading button)"; return false; }

   if(spread > InpMaxSpread)
   { reason = StringFormat("Spread too wide: %.2f", spread); return false; }

   if(InpSpikeMult > 0 && avgSpread > 0 && spread > avgSpread * InpSpikeMult)
   { reason = StringFormat("Spread spike: %.2f (avg %.2f)", spread, avgSpread); return false; }

   if(InpUseSession && !InSession())
   { reason = "Outside trading hours"; return false; }

   if(InRollover())
   { reason = "Rollover time (midnight) - wide spreads"; return false; }

   if(InNewsWindow())
   { reason = "News time - paused"; return false; }

   if(TimeCurrent() < pauseUntil)
   { reason = "Paused after losing streak until " + TimeToString(pauseUntil, TIME_MINUTES); return false; }

   if(InpMaxTradesDay > 0 && tradesToday >= InpMaxTradesDay)
   { reason = "Max trades for today reached"; return false; }

   if(checkCooldown && InpCooldownSec > 0 && TimeCurrent() - lastCloseTime < InpCooldownSec)
   { reason = "Cooldown after last trade"; return false; }

   return true;
}

bool InSession()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int h = dt.hour;
   if(InpStartHour == InpEndHour) return true;
   if(InpStartHour < InpEndHour)  return (h >= InpStartHour && h < InpEndHour);
   return (h >= InpStartHour || h < InpEndHour);           // overnight session
}

bool InRollover()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int mins = dt.hour * 60 + dt.min;
   if(InpRolloverBefore > 0 && mins >= 1440 - InpRolloverBefore) return true;
   if(InpRolloverAfter > 0 && mins < InpRolloverAfter) return true;
   return false;
}

bool IsFridayClose()
{
   if(InpFridayCloseHour < 0) return false;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (dt.day_of_week == 5 && dt.hour >= InpFridayCloseHour);
}

void LoadNews()
{
   if(!InpUseNews || MQLInfoInteger(MQL_TESTER)) return;

   datetime now = TimeTradeServer();
   if(lastNewsLoad > 0 && now - lastNewsLoad < 600) return;   // refresh every 10 minutes
   lastNewsLoad = now;

   ArrayResize(newsTimes, 0);
   MqlCalendarValue values[];
   if(!CalendarValueHistory(values, now - 3600, now + 86400, NULL, InpNewsCurrency)) return;

   int n = ArraySize(values);
   for(int i = 0; i < n; i++)
   {
      MqlCalendarEvent ev;
      if(!CalendarEventById(values[i].event_id, ev)) continue;

      bool important = (ev.importance == CALENDAR_IMPORTANCE_HIGH)
                    || (!InpNewsHighOnly && ev.importance == CALENDAR_IMPORTANCE_MODERATE);
      if(!important) continue;

      int sz = ArraySize(newsTimes);
      ArrayResize(newsTimes, sz + 1);
      newsTimes[sz] = values[i].time;
   }
}

bool InNewsWindow()
{
   if(!InpUseNews || MQLInfoInteger(MQL_TESTER)) return false;
   datetime now = TimeTradeServer();
   int n = ArraySize(newsTimes);
   for(int i = 0; i < n; i++)
   {
      if(now >= newsTimes[i] - InpNewsBeforeMin * 60 && now <= newsTimes[i] + InpNewsAfterMin * 60)
         return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Spread & distances                                                |
//+------------------------------------------------------------------+
void UpdateSpreadAverage(double spread)
{
   if(spread <= 0) return;
   if(avgSpread <= 0) { avgSpread = spread; return; }

   double alpha = 2.0 / (MathMax(InpSpreadAvgTicks, 1) + 1.0);
   // spikes are clipped so they do not drag the average up too fast
   double s = (InpSpikeMult > 0) ? MathMin(spread, avgSpread * InpSpikeMult) : spread;
   avgSpread += alpha * (s - avgSpread);
}

bool GetDistances(double spread, double &dist, double &slDist)
{
   if(InpUseATR)
   {
      double buf[];
      if(CopyBuffer(atrHandle, 0, 1, 1, buf) != 1 || buf[0] <= 0) return false;
      dist   = buf[0] * InpDistATR;
      slDist = buf[0] * InpSLATR;
   }
   else
   {
      dist   = InpDistance;
      slDist = InpStopLoss;
   }

   // never closer than the spread allows
   double spreadRef = MathMax(spread, avgSpread);
   if(InpDistSpreadMult > 0) dist   = MathMax(dist,   spreadRef * InpDistSpreadMult);
   if(InpSLSpreadMult > 0)   slDist = MathMax(slDist, spreadRef * InpSLSpreadMult);

   // broker minimum distance
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point + tickSize;
   dist   = MathMax(dist, minDist);
   slDist = MathMax(slDist, minDist);
   return true;
}

//+------------------------------------------------------------------+
//| Helpers                                                           |
//+------------------------------------------------------------------+
double CalcLots(double slDist)
{
   double lots = InpLots;
   if(InpUseRisk)
   {
      double tickValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
      if(tickValue > 0 && slDist > 0)
      {
         double lossPerLot = slDist / tickSize * tickValue;
         lots = AccountInfoDouble(ACCOUNT_BALANCE) * InpRiskPercent / 100.0 / lossPerLot;
      }
   }
   if(InpMaxLots > 0) lots = MathMin(lots, InpMaxLots);

   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step > 0) lots = MathFloor(lots / step + 1e-9) * step;
   lots = MathMax(vmin, MathMin(vmax, lots));
   return NormalizeDouble(lots, 2);
}

double NormPrice(double price)
{
   return NormalizeDouble(MathRound(price / tickSize) * tickSize, digits);
}

int DayOfYear(datetime time)
{
   MqlDateTime dt;
   TimeToStruct(time, dt);
   return dt.day_of_year;
}

datetime DayStart(datetime time)
{
   MqlDateTime dt;
   TimeToStruct(time, dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   return StructToTime(dt);
}

void WriteCsv(string entry, ulong deal, string side, double volume, double price,
              double requested, double slip, double spread, double money, string reason)
{
   if(!InpWriteCsv) return;

   string fileName = "BreakoutTrail_" + _Symbol + ".csv";
   int h = FileOpen(fileName, FILE_READ | FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_SHARE_READ, ',');
   if(h == INVALID_HANDLE) return;

   if(FileSize(h) == 0)
      FileWrite(h, "time", "deal", "entry", "side", "volume", "price", "requested",
                "slippage", "spread", "profit", "reason");

   FileSeek(h, 0, SEEK_END);
   FileWrite(h,
             TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS),
             (string)deal,
             entry,
             side,
             DoubleToString(volume, 2),
             DoubleToString(price, digits),
             DoubleToString(requested, digits),
             DoubleToString(slip, digits),
             DoubleToString(spread, digits),
             DoubleToString(money, 2),
             reason);
   FileClose(h);
}

void ShowPanel(const MqlTick &t)
{
   if(!InpShowPanel) return;

   double spread   = t.ask - t.bid;
   double dayPL    = realizedToday + GetFloating();
   int    closed   = winsToday + lossesToday;
   double winRate  = (closed > 0) ? 100.0 * winsToday / closed : 0.0;
   double avgSlip  = (slipCount > 0) ? slipSum / slipCount : 0.0;
   string mode     = (InpEntryMode == ENTRY_STOP_ORDERS) ? "Stop orders" : "Virtual (mid)";
   if(InpReverseMode) mode += " + Reverse";

   Comment(StringFormat("BreakoutTrail v2.01 | %s\n%s\n"
                        "Spread %.2f (avg %.2f) | Distance %.2f | SL %.2f\n"
                        "Today P/L: %.2f | Entries %d | Wins %d / Losses %d (%.0f%%) | Avg slippage %.3f",
                        mode, gState,
                        spread, avgSpread, gDist, gSL,
                        dayPL, tradesToday, winsToday, lossesToday, winRate, avgSlip));
}
//+------------------------------------------------------------------+
