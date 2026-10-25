const tg = window.Telegram?.WebApp;
const initData = tg?.initData || "";
const $ = (id) => document.getElementById(id);
const fmt = (x) => x == null ? "—" : Number(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const ilTime = (iso) => new Date(iso).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jerusalem" });
const ilDate = (iso) => new Date(iso).toLocaleString("he-IL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jerusalem" });
const METHOD = { range: "🎯 טווחים", trend: "📈 מגמה", liquidity: "💧 נזילות" };
const STATUS = { tp2: "🏆 יעד 2", sl: "🛑 סטופ", be: "⚖️ יעד 1 + כניסה", expired: "⏰ פג תוקף", reversed: "🔄 התהפך", open: "⏳ פתוחה" };

let tf = "15m", chart, candles, ema = {}, priceLines = [], last = null;

if (tg) {
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.("secondary_bg_color");
}

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-Telegram-Init-Data": initData, ...(opts.headers || {}) } });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

function planCells(p, dir) {
  const r = (x) => `${((x - p.entry) * dir / Math.abs(p.entry - p.sl)).toFixed(0)}R`;
  return `
    <div><span>כניסה</span><b>${fmt(p.entry)}</b></div>
    <div class="sl"><span>סטופ (${fmt(Math.abs(p.entry - p.sl))}$)</span><b>${fmt(p.stop ?? p.sl)}</b></div>
    <div class="tp"><span>יעד 1 · ${r(p.tp1)}</span><b>${fmt(p.tp1)}</b></div>
    <div class="tp"><span>יעד 2 · ${r(p.tp2)}</span><b>${fmt(p.tp2)}</b></div>`;
}

function renderAnalysis(a) {
  last = a;
  $("symbol").textContent = a.symbol;
  $("price").textContent = fmt(a.price);
  $("mkt").className = "dot" + (a.market_open ? " open" : "");
  if (a.day_change != null) {
    const pct = (a.day_change / (a.price - a.day_change)) * 100;
    $("chg").textContent = `${a.day_change >= 0 ? "+" : ""}${fmt(a.day_change)} (${pct.toFixed(2)}%) היום`;
    $("chg").className = "chg " + (a.day_change >= 0 ? "up" : "down");
  }

  const card = $("verdictCard");
  card.className = "card verdict" + (a.direction === 1 ? " long" : a.direction === -1 ? " short" : "");
  $("verdict").textContent = (a.direction === 1 ? "▲ " : a.direction === -1 ? "▼ " : "") + a.verdict;
  $("score").textContent = (a.composite > 0 ? "+" : "") + a.composite.toFixed(0);
  const fill = $("gaugeFill"), w = Math.abs(a.composite) / 2;
  fill.style.background = a.composite >= 0 ? css("--long") : css("--short");
  fill.style.left = a.composite >= 0 ? "50%" : `${50 - w}%`;
  fill.style.width = `${w}%`;
  const badges = [`ביטחון ${a.confidence}`];
  if (!a.market_open) badges.push("😴 השוק סגור");
  if (a.killzone) badges.push(`💧 סשן ${a.killzone}`);
  $("badges").innerHTML = badges.map((b) => `<span class="badge">${b}</span>`).join("") +
    (a.entry_ready && a.market_open ? `<span class="badge go">✓ תנאי כניסה מתקיימים</span>` : "");

  const trades = a.open_trades || [];
  const pend = a.pending;
  $("tradeCard").hidden = !trades.length && !pend;
  const blocks = trades.map((t) => `
    <h2>${METHOD[t.method] || ""}${(a.alert_methods || []).includes(t.method) ? "" : " (מעקב בלבד, בלי התראות)"} · עסקה #${t.id} · ${t.direction === 1 ? "לונג" : "שורט"} מ-${ilTime(t.opened_at)}${t.tp1_hit ? " · יעד 1 הושג ✓" : ""}</h2>
    <div class="plan">${planCells(t, t.direction)}</div>`);
  if (pend) blocks.push(`
    <h2>💧 הזמנת ${pend.direction === 1 ? "Buy" : "Sell"} Limit ממתינה #${pend.id} · בתוקף עד ${ilTime(pend.expires)}</h2>
    <p class="muted" style="margin-bottom:8px">סוויפ של ${pend.note} (${fmt(pend.level)})</p>
    <div class="plan">${planCells(pend, pend.direction)}</div>`);
  $("tradePlan").innerHTML = blocks.join('<div style="height:12px"></div>');

  const dir = a.direction || a.lean;
  $("planCard").hidden = !a.plan;
  if (a.plan) {
    $("planTitle").textContent = "📈 שיטת מגמה - לניתוח בלבד (הפסידה בבדיקה ההיסטורית)";
    $("plan").innerHTML = planCells(a.plan, dir);
    $("reasons").innerHTML = a.reasons.map((r) => `<li>${r}</li>`).join("");
  }

  $("tfs").innerHTML = a.timeframes.map((x) => {
    const w = Math.min(Math.abs(x.score), 100) / 2;
    const color = x.score >= 20 ? css("--long") : x.score <= -20 ? css("--short") : css("--neutral");
    const pos = x.score >= 0 ? `left:50%` : `left:${50 - w}%`;
    return `<div class="tf">
      <span class="name">${x.tf}</span>
      <div class="bar"><i style="${pos};width:${w}%;background:${color}"></i></div>
      <span class="meta num">${x.score > 0 ? "+" : ""}${x.score.toFixed(0)} · RSI ${x.rsi.toFixed(0)}</span>
      <span class="trend">${x.trend} · ADX ${x.adx.toFixed(0)} · ${x.above_ema200 == null ? "" : x.above_ema200 ? "מעל EMA200" : "מתחת EMA200"} · משקל ${Math.round(x.weight * 100)}%</span>
    </div>`;
  }).join("");

  const names = { R2: "התנגדות 2", R1: "התנגדות 1", PP: "פיבוט", S1: "תמיכה 1", S2: "תמיכה 2", PDH: "שיא אתמול", PDL: "שפל אתמול", HOD: "שיא היום", LOD: "שפל היום", ASH: "שיא אסיה", ASL: "שפל אסיה", LDH: "שיא לונדון", LDL: "שפל לונדון" };
  const lv = Object.entries(a.levels).map(([k, v]) => ({ k, v })).concat([{ k: "NOW", v: a.price }]).sort((x, y) => y.v - x.v);
  $("levels").innerHTML = lv.map(({ k, v }) => k === "NOW"
    ? `<div class="lv now"><span>◀ מחיר נוכחי</span><b class="num">${fmt(v)}</b></div>`
    : `<div class="lv ${v > a.price ? "res" : "sup"}"><span>${names[k] || k} · ${k}</span><b class="num">${fmt(v)}</b></div>`).join("");

  $("updated").textContent = `עודכן ${ilTime(a.updated_at)} · מקור: ${a.source}` + (a.error ? " · ⚠️ " + a.error : "");
  drawPriceLines();
}

function renderTrades({ trades, stats, by_method }) {
  $("stats").innerHTML = stats.count
    ? `<div><b>${stats.count}</b><span>עסקאות</span></div><div><b>${stats.win_rate}%</b><span>הצלחה</span></div><div><b class="${stats.total_r >= 0 ? "up" : "down"}">${stats.total_r > 0 ? "+" : ""}${stats.total_r}R</b><span>סה"כ</span></div>`
    : `<p class="muted" style="grid-column:1/-1">עוד אין עסקאות סגורות. כל סיגנל נרשם כאן עם התוצאה שלו.</p>`;
  const per = Object.entries(by_method || {}).filter(([, s]) => s.count)
    .map(([m, s]) => `${METHOD[m]}: ${s.count} עסקאות · ${s.win_rate}% · <span class="num">${s.total_r > 0 ? "+" : ""}${s.total_r}R</span>`).join("<br>");
  $("byMethod").innerHTML = per;
  $("history").innerHTML = trades.slice(0, 15).map((t) => `
    <div class="tr">
      <span class="side ${t.direction === 1 ? "l" : "s"}">${(METHOD[t.method] || "").split(" ")[0]} ${t.direction === 1 ? "לונג" : "שורט"}</span>
      <span>${ilDate(t.opened_at)} · <span class="num">${fmt(t.entry)}</span> · ${STATUS[t.status] || t.status}</span>
      <b class="num ${t.result_r > 0 ? "up" : t.result_r < 0 ? "down" : ""}">${t.result_r == null ? "" : (t.result_r > 0 ? "+" : "") + t.result_r + "R"}</b>
    </div>`).join("");
}

function initChart() {
  const el = $("chart");
  const text = css("--muted"), grid = "rgba(128,128,128,0.12)";
  chart = LightweightCharts.createChart(el, {
    height: 300, layout: { background: { color: "transparent" }, textColor: text, fontSize: 11 },
    grid: { vertLines: { color: grid }, horzLines: { color: grid } },
    rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false, timeVisible: true },
    localization: { timeFormatter: (t) => new Date(t * 1000).toLocaleString("he-IL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Asia/Jerusalem" }) },
    crosshair: { mode: 0 },
  });
  candles = chart.addCandlestickSeries({ upColor: css("--long"), downColor: css("--short"), borderVisible: false, wickUpColor: css("--long"), wickDownColor: css("--short") });
  for (const [k, c] of [["ema21", "#4ea1ff"], ["ema50", "#d4a537"], ["ema200", "#b07cff"]]) {
    ema[k] = chart.addLineSeries({ color: c, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
  }
  new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth })).observe(el);
}

function drawPriceLines() {
  if (!candles || !last) return;
  priceLines.forEach((l) => candles.removePriceLine(l));
  priceLines = [];
  const p = (last.open_trades || [])[0] || last.pending || (last.direction ? last.plan : null);
  if (!p) return;
  const add = (price, color, title) => priceLines.push(candles.createPriceLine({ price, color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title }));
  add(p.entry, css("--accent"), "כניסה");
  add(p.stop ?? p.sl, css("--short"), "סטופ");
  add(p.tp1, css("--long"), "TP1");
  add(p.tp2, css("--long"), "TP2");
}

async function loadCandles() {
  const data = await api(`/api/candles?tf=${tf}&limit=300`);
  candles.setData(data.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
  for (const k of Object.keys(ema)) ema[k].setData(data.filter((d) => d[k] != null).map((d) => ({ time: d.time, value: d[k] })));
  chart.timeScale().fitContent();
}

async function loadAll() {
  $("refresh").classList.add("spin");
  try {
    const [a, tr] = await Promise.all([api("/api/analysis"), api("/api/trades")]);
    renderAnalysis(a);
    renderTrades(tr);
    await loadCandles();
  } catch (e) {
    $("verdict").innerHTML = `<span class="err">${e.message}</span>`;
  } finally {
    $("refresh").classList.remove("spin");
  }
}

async function initAlerts() {
  const box = $("alerts");
  if (!initData) { box.closest(".card").querySelector(".muted").textContent = "פתח מתוך טלגרם כדי לנהל התראות"; return; }
  try {
    const me = await api("/api/me");
    box.checked = me.alerts;
    box.disabled = false;
    box.addEventListener("change", async () => {
      box.disabled = true;
      try {
        await api("/api/alerts", { method: "POST", body: JSON.stringify({ enabled: box.checked }) });
        tg?.HapticFeedback?.notificationOccurred("success");
      } catch (e) {
        box.checked = !box.checked;
        tg?.showAlert?.(e.message);
      } finally { box.disabled = false; }
    });
  } catch (e) {
    box.closest(".card").querySelector(".muted").textContent = e.message;
  }
}

$("tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("on", x === b));
  tf = b.dataset.tf;
  tg?.HapticFeedback?.selectionChanged();
  loadCandles().catch(() => {});
});
$("refresh").addEventListener("click", loadAll);

initChart();
loadAll();
initAlerts();
setInterval(loadAll, 60_000);
