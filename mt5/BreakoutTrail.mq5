//+------------------------------------------------------------------+
//|                                              BreakoutTrail.mq5   |
//|  Gold breakout EA:                                               |
//|  - Buy Stop above price and Sell Stop below price, both always   |
//|    following the price at a fixed distance.                      |
//|  - A fast move (breakout) hits one of them.                      |
//|  - Reverse mode (default): the opposite order keeps following    |
//|    the price; if it fills, the old trade is closed (flip).       |
//|    Without reverse mode the opposite order is cancelled (OCO).   |
//|  - Initial SL, optional break-even, then trailing stop.          |
//|                                                                  |
//|  All distances are in PRICE units. For XAUUSD 1.0 = $1 move      |
//|  (e.g. 2350.00 -> 2351.00). Defaults are an AGGRESSIVE M1 scalp. |
//+------------------------------------------------------------------+
#property copyright "inon"
#property version   "1.10"
#property description "Trailing Buy Stop / Sell Stop breakout with trailing stop (XAUUSD)"

#include <Trade\Trade.mqh>

//--- Volume
input group "=== Volume ==="
input double InpLots           = 0.01;   // Fixed lot size
input bool   InpUseRisk        = false;  // Use risk % instead of fixed lot
input double InpRiskPercent    = 1.0;    // Risk % of balance per trade (if enabled)

//--- Distances
input group "=== Breakout distance & stops (price units, gold: 1.0 = $1) ==="
input bool            InpUseATR      = false;     // Use ATR for distance & SL
input ENUM_TIMEFRAMES InpATRTf       = PERIOD_M5; // ATR timeframe
input int             InpATRPeriod   = 14;        // ATR period
input double          InpDistATR     = 0.5;       // Distance = ATR x this
input double          InpSLATR       = 1.0;       // Stop loss = ATR x this
input double          InpDistance    = 0.30;      // Fixed distance of pending orders from price
input double          InpStopLoss    = 0.60;      // Fixed initial stop loss
input double          InpTakeProfit  = 0.0;       // Take profit (0 = none, trailing only)

//--- Reverse mode (like the video)
input group "=== Reverse mode ==="
input bool   InpReverseMode    = true;   // Keep the opposite stop order while in a trade
input bool   InpCloseOnReverse = true;   // When the opposite order fills, close the old trade (flip)

//--- Order following
input group "=== Pending orders following the price ==="
input double InpStep           = 0.05;   // Move orders only if target changed by at least this
input int    InpModifyMs       = 200;    // Minimum time between modifications (ms)

//--- Trailing
input group "=== Break-even & trailing stop ==="
input double InpBreakEven      = 0.15;   // Move SL to entry after this profit (0 = off)
input double InpBELock         = 0.05;   // Profit locked at break-even
input double InpTrailStart     = 0.20;   // Start trailing after this profit
input double InpTrailDist      = 0.15;   // Trailing distance from price (0 = off)
input double InpTrailStep      = 0.05;   // Move SL only in steps of at least this

//--- Filters
input group "=== Filters ==="
input double InpMaxSpread      = 0.35;   // Max spread allowed (price units)
input bool   InpUseSession     = false;  // Trade only between hours (server time)
input int    InpStartHour      = 1;      // Session start hour (server time)
input int    InpEndHour        = 23;     // Session end hour (server time)
input int    InpCooldownSec    = 0;      // Seconds to wait after a trade closes
input int    InpMaxTradesDay   = 200;    // Max entries per day (0 = unlimited)

//--- General
input group "=== General ==="
input long   InpMagic          = 20261104;        // Magic number
input int    InpDeviation      = 50;              // Max deviation (points)
input string InpComment        = "BreakoutTrail"; // Order comment

//--- Globals
CTrade   trade;
int      atrHandle     = INVALID_HANDLE;
ulong    lastModifyMs  = 0;
datetime lastCloseTime = 0;
int      tradesToday   = 0;
int      currentDay    = -1;
int      prevPositions = 0;
double   tickSize      = 0.0;
int      digits        = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0.0) tickSize = _Point;
   digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);

   if(InpDistance <= 0 || InpStopLoss <= 0 || InpStep < 0)
   {
      Print("Invalid inputs: distance and stop loss must be > 0");
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

   currentDay    = DayOfYear(TimeCurrent());
   tradesToday   = CountTodayEntries();
   prevPositions = CountPositions();
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // If the EA is removed, do not leave orders that no longer follow the price
   if(reason == REASON_REMOVE || reason == REASON_CHARTCLOSE)
      DeleteAllPendings();
   if(atrHandle != INVALID_HANDLE) IndicatorRelease(atrHandle);
   Comment("");
}

//+------------------------------------------------------------------+
void OnTick()
{
   MqlTick t;
   if(!SymbolInfoTick(_Symbol, t)) return;

   ResetDailyCounter();

   //--- 1. Manage open position(s): break-even + trailing
   int positions = ManagePositions(t);

   if(prevPositions > 0 && positions == 0)
      lastCloseTime = TimeCurrent();       // trade closed -> start cooldown
   prevPositions = positions;

   bool hasLong = false, hasShort = false;
   if(positions > 0) GetPositionSides(hasLong, hasShort);

   if(positions > 0 && !InpReverseMode)
   {
      DeleteAllPendings();                 // OCO: no pending orders while in a trade
      ShowStatus(t, "In trade - trailing");
      return;
   }

   //--- 2. Filters (cooldown only matters when flat)
   string reason = "";
   if(!CanTrade(t, reason, positions == 0))
   {
      DeleteAllPendings();
      ShowStatus(t, (positions > 0) ? "In trade - " + reason : reason);
      return;
   }

   //--- 3. Distances
   double dist = 0, slDist = 0;
   if(!GetDistances(dist, slDist))
   {
      ShowStatus(t, "Waiting for ATR data");
      return;
   }

   //--- 4. Place / move pending orders around the price
   if(positions == 0)
   {
      TrackPendings(t, dist, slDist, true, true);
      ShowStatus(t, StringFormat("Waiting for breakout (distance %.2f, SL %.2f)", dist, slDist));
   }
   else
   {
      // Reverse mode: keep only the order in the opposite direction
      bool allowBuy  = hasShort && !hasLong;
      bool allowSell = hasLong && !hasShort;
      TrackPendings(t, dist, slDist, allowBuy, allowSell);
      ShowStatus(t, hasLong ? "In BUY - trailing, Sell Stop ready to flip"
                            : "In SELL - trailing, Buy Stop ready to flip");
   }
}

//+------------------------------------------------------------------+
//| Cancel the opposite order as soon as one fills                    |
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetString(trans.deal, DEAL_SYMBOL) != _Symbol) return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic) return;

   long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entry == DEAL_ENTRY_IN)
   {
      tradesToday++;
      if(!InpReverseMode)
      {
         DeleteAllPendings();
      }
      else if(InpCloseOnReverse)
      {
         // Flip: the new trade replaces the old one in the other direction
         long dealType = HistoryDealGetInteger(trans.deal, DEAL_TYPE);
         if(dealType == DEAL_TYPE_BUY)  ClosePositions(POSITION_TYPE_SELL);
         if(dealType == DEAL_TYPE_SELL) ClosePositions(POSITION_TYPE_BUY);
      }
   }
   else if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
   {
      lastCloseTime = TimeCurrent();
   }
}

//+------------------------------------------------------------------+
//| Pending orders                                                    |
//+------------------------------------------------------------------+
void TrackPendings(const MqlTick &t, double dist, double slDist, bool allowBuy, bool allowSell)
{
   ulong buyT = 0, sellT = 0;
   FindPendings(buyT, sellT);

   // Remove orders for a side that is not allowed right now
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
   bool   canModify = (GetTickCount64() - lastModifyMs) >= (ulong)InpModifyMs;

   //--- Buy Stop
   if(!allowBuy)
   {
      // nothing
   }
   else if(buyT == 0)
   {
      if(!trade.BuyStop(lots, buyPrice, _Symbol, buySL, buyTP, ORDER_TIME_GTC, 0, InpComment))
         Print("BuyStop failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   }
   else if(canModify && OrderSelect(buyT))
   {
      double cur = OrderGetDouble(ORDER_PRICE_OPEN);
      bool frozen = (freeze > 0 && cur - t.ask <= freeze);
      if(MathAbs(cur - buyPrice) >= InpStep && !frozen)
      {
         if(trade.OrderModify(buyT, buyPrice, buySL, buyTP, ORDER_TIME_GTC, 0))
            lastModifyMs = GetTickCount64();
      }
   }

   //--- Sell Stop
   if(!allowSell)
   {
      // nothing
   }
   else if(sellT == 0)
   {
      if(!trade.SellStop(lots, sellPrice, _Symbol, sellSL, sellTP, ORDER_TIME_GTC, 0, InpComment))
         Print("SellStop failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   }
   else if(canModify && OrderSelect(sellT))
   {
      double cur = OrderGetDouble(ORDER_PRICE_OPEN);
      bool frozen = (freeze > 0 && t.bid - cur <= freeze);
      if(MathAbs(cur - sellPrice) >= InpStep && !frozen)
      {
         if(trade.OrderModify(sellT, sellPrice, sellSL, sellTP, ORDER_TIME_GTC, 0))
            lastModifyMs = GetTickCount64();
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
//| Positions: break-even + trailing stop                             |
//+------------------------------------------------------------------+
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

         if(InpTrailDist > 0 && profit >= InpTrailStart)
         {
            double tr = NormPrice(t.bid - InpTrailDist);
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

         if(InpTrailDist > 0 && profit >= InpTrailStart)
         {
            double tr = NormPrice(t.ask + InpTrailDist);
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
         Print("Flip close failed: ", trade.ResultRetcode(), " ", trade.ResultRetcodeDescription());
   }
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

//+------------------------------------------------------------------+
//| Filters                                                           |
//+------------------------------------------------------------------+
bool CanTrade(const MqlTick &t, string &reason, bool checkCooldown)
{
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
   { reason = "Algo trading is disabled (press Algo Trading button)"; return false; }

   if(t.ask - t.bid > InpMaxSpread)
   { reason = StringFormat("Spread too wide: %.2f", t.ask - t.bid); return false; }

   if(InpUseSession && !InSession())
   { reason = "Outside trading hours"; return false; }

   if(checkCooldown && InpCooldownSec > 0 && TimeCurrent() - lastCloseTime < InpCooldownSec)
   { reason = "Cooldown after last trade"; return false; }

   if(InpMaxTradesDay > 0 && tradesToday >= InpMaxTradesDay)
   { reason = "Max trades for today reached"; return false; }

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

//+------------------------------------------------------------------+
//| Helpers                                                           |
//+------------------------------------------------------------------+
bool GetDistances(double &dist, double &slDist)
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

   // Respect broker minimum distance for stops/pending orders
   double minDist = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point + tickSize;
   dist   = MathMax(dist, minDist);
   slDist = MathMax(slDist, minDist);
   return true;
}

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
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step > 0) lots = MathFloor(lots / step) * step;
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

void ResetDailyCounter()
{
   int d = DayOfYear(TimeCurrent());
   if(d != currentDay)
   {
      currentDay  = d;
      tradesToday = CountTodayEntries();
   }
}

int CountTodayEntries()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   dt.hour = 0; dt.min = 0; dt.sec = 0;
   datetime dayStart = StructToTime(dt);

   if(!HistorySelect(dayStart, TimeCurrent() + 60)) return 0;
   int count = 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong deal = HistoryDealGetTicket(i);
      if(deal == 0) continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(deal, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetInteger(deal, DEAL_ENTRY) == DEAL_ENTRY_IN) count++;
   }
   return count;
}

void ShowStatus(const MqlTick &t, string state)
{
   Comment(StringFormat("BreakoutTrail  |  %s\nSpread: %.2f   Trades today: %d / %d",
                        state, t.ask - t.bid, tradesToday, InpMaxTradesDay));
}
//+------------------------------------------------------------------+
