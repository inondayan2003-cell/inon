"use strict";

/* ================= helpers ================= */

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

const ICON = {
  search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  heart: '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
  pin: '<svg viewBox="0 0 24 24"><path d="M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11z"/><circle cx="12" cy="10" r="2.5"/></svg>',
  target: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>',
  phone: '<svg viewBox="0 0 24 24"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
  nav: '<svg viewBox="0 0 24 24"><path d="m3 11 18-8-8 18-2-8z"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  camera: '<svg viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  store: '<svg viewBox="0 0 24 24"><path d="M4 9h16l-1-5H5zM5 9v11h14V9M9 20v-6h6v6"/></svg>',
  info: '<svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h10"/></svg>',
  whatsapp: '<svg viewBox="0 0 24 24"><path d="M4 20l1.3-4A8 8 0 1 1 8 18.7z"/><path d="M9 9.5c0 3 2.5 5.5 5.5 5.5l1-1.5-2-1-1 .8a4 4 0 0 1-1.8-1.8l.8-1-1-2z"/></svg>',
};

// Fallback when the customer doesn't share GPS.
const CITIES = [
  ["תל אביב", 32.0853, 34.7818], ["ירושלים", 31.7683, 35.2137], ["חיפה", 32.794, 34.9896],
  ["ראשון לציון", 31.973, 34.7925], ["פתח תקווה", 32.0871, 34.8875], ["אשדוד", 31.8044, 34.6553],
  ["נתניה", 32.3215, 34.8532], ["באר שבע", 31.2518, 34.7913], ["חולון", 32.0158, 34.7874],
  ["בני ברק", 32.0807, 34.8338], ["רמת גן", 32.0684, 34.8248], ["רחובות", 31.8928, 34.8113],
  ["אשקלון", 31.6688, 34.5743], ["בת ים", 32.0171, 34.7454], ["בית שמש", 31.7497, 34.9886],
  ["כפר סבא", 32.1782, 34.9076], ["הרצליה", 32.1624, 34.8447], ["חדרה", 32.4340, 34.9196],
  ["מודיעין", 31.8980, 35.0104], ["רעננה", 32.1848, 34.8713], ["לוד", 31.9510, 34.8881],
  ["רמלה", 31.9293, 34.8664], ["נצרת", 32.6996, 35.3035], ["עפולה", 32.6091, 35.2892],
  ["קריית גת", 31.6100, 34.7642], ["אילת", 29.5577, 34.9519], ["טבריה", 32.7922, 35.5312],
  ["אור עקיבא", 32.5076, 34.9188], ["נס ציונה", 31.9293, 34.7987], ["גדרה", 31.8119, 34.7778],
];

const RADII = [2, 5, 10, 25, 50];

const store = {
  get(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ }
  },
};

let toastTimer;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? "יש שדה שלא מולא נכון" : "משהו השתבש, נסי שוב";
    throw new Error(msg);
  }
  return data;
}

let SERVICES = [];
const serviceLabel = (k) => (SERVICES.find((s) => s.key === k) || {}).label || k;

function getPosition() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("הדפדפן לא תומך במיקום"));
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => reject(new Error("לא הצלחנו לקבל את המיקום. אפשר לבחור עיר במקום.")),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  });
}

/* ================= state ================= */

const state = {
  loc: store.get("nails.loc", null),          // {lat, lng, label}
  radius: store.get("nails.radius", 10),
  service: null,
  q: "",
};
const favs = () => store.get("nails.favs", []);
const isFav = (id) => favs().includes(id);
function toggleFav(id) {
  const f = favs();
  const next = f.includes(id) ? f.filter((x) => x !== id) : [...f, id];
  store.set("nails.favs", next);
  return next.includes(id);
}
const mine = () => store.get("nails.mine", []);  // [{id, token, name}]
function saveMine(entry) {
  store.set("nails.mine", [...mine().filter((m) => m.id !== entry.id), entry]);
}

/* ================= shared UI ================= */

function card(b) {
  const cover = b.photos[0]?.url;
  const dist = b.distance_km != null ? `${b.distance_km} ק"מ` : "";
  return `
    <a class="card" href="#/b/${b.id}">
      <div class="media">
        ${cover ? `<img src="${esc(cover)}" alt="" loading="lazy">` : ""}
        ${dist ? `<span class="badge">${ICON.pin}${dist}</span>` : ""}
        <button class="heart ${isFav(b.id) ? "on" : ""}" data-fav="${b.id}" aria-label="מועדפים">${ICON.heart}</button>
        <span class="count-badge">${b.photos.length} תמונות</span>
      </div>
      <div class="body">
        <h4>${esc(b.name)}</h4>
        <div class="meta">${ICON.pin}<span>${esc(b.city)}</span></div>
        <div class="tags">${b.services.slice(0, 2).map((s) => `<span class="tag">${esc(serviceLabel(s))}</span>`).join("")}</div>
      </div>
    </a>`;
}

function bindFavButtons(root) {
  root.querySelectorAll("[data-fav]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const on = toggleFav(Number(btn.dataset.fav));
      btn.classList.toggle("on", on);
      toast(on ? "נשמר במועדפים 💖" : "הוסר מהמועדפים");
    });
  });
}

function empty(icon, title, text, btnHtml = "") {
  return `<div class="empty"><div class="circle">${icon}</div><h3>${title}</h3><p>${text}</p>${btnHtml}</div>`;
}

function pageTitle(title, backHref) {
  return `<div class="page-title">
    ${backHref ? `<a class="back" href="${backHref}" aria-label="חזרה">${ICON.back}</a>` : ""}
    <h1>${title}</h1></div>`;
}

/* ================= home ================= */

function renderHome() {
  const loc = state.loc;
  view.innerHTML = `
    <div class="top">
      <div class="logo">💅</div>
      <div><h1>Nails</h1><p>איפה עושים ציפורניים היום?</p></div>
      <div class="spacer"></div>
      <a class="icon-btn" href="#/favorites" aria-label="מועדפים">${ICON.heart}</a>
    </div>

    <label class="search">${ICON.search}
      <input id="q" type="search" placeholder="חפשי לפי שם, עיר או סגנון..." value="${esc(state.q)}">
    </label>

    <div class="loc-bar">
      <span>${ICON.pin} ${loc ? `מחפשות ליד: <b>${esc(loc.label)}</b>` : "בחרי מיקום כדי לראות מה קרוב אלייך"}</span>
      <button id="change-loc">${loc ? "שינוי" : "בחירה"}</button>
    </div>

    <div class="label-sm">רדיוס חיפוש</div>
    <div class="chips" id="radius">
      ${RADII.map((r) => `<button class="chip ${state.radius === r ? "on" : ""}" data-r="${r}">עד ${r} ק"מ</button>`).join("")}
    </div>

    <div class="chips" id="services">
      <button class="chip ${!state.service ? "on" : ""}" data-s="">הכל</button>
      ${SERVICES.map((s) => `<button class="chip ${state.service === s.key ? "on" : ""}" data-s="${s.key}">${esc(s.label)}</button>`).join("")}
    </div>

    <div class="hero">
      <small>NAILS</small>
      <h2>הציפורניים שחיפשת, ממש קרוב.</h2>
      <p>מוצאים מניקוריסטית באזור, רואים עבודות, וקובעים בוואטסאפ.</p>
      <div class="nail-art" aria-hidden="true">💅</div>
    </div>

    <div class="section-head"><h3 id="results-title">קרוב אלייך</h3><span id="results-count"></span></div>
    <div id="results" class="grid">${'<div class="skeleton"></div>'.repeat(4)}</div>
  `;

  let qTimer;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(qTimer);
    qTimer = setTimeout(() => { state.q = e.target.value; loadResults(); }, 300);
  });
  $("#change-loc").addEventListener("click", openLocationPicker);
  $("#radius").addEventListener("click", (e) => {
    const b = e.target.closest("[data-r]");
    if (!b) return;
    state.radius = Number(b.dataset.r);
    store.set("nails.radius", state.radius);
    $("#radius").querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b));
    loadResults();
  });
  $("#services").addEventListener("click", (e) => {
    const b = e.target.closest("[data-s]");
    if (!b) return;
    state.service = b.dataset.s || null;
    $("#services").querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", c === b));
    loadResults();
  });

  if (!state.loc) tryAutoLocate();
  loadResults();
}

async function tryAutoLocate() {
  try {
    const p = await getPosition();
    state.loc = { ...p, label: "המיקום שלי" };
    store.set("nails.loc", state.loc);
    if (location.hash === "" || location.hash === "#/") renderHome();
  } catch { /* user can pick a city */ }
}

let loadSeq = 0;
async function loadResults() {
  const seq = ++loadSeq;
  const params = new URLSearchParams();
  if (state.loc) {
    params.set("lat", state.loc.lat);
    params.set("lng", state.loc.lng);
    params.set("radius_km", state.radius);
  }
  if (state.service) params.set("service", state.service);
  if (state.q.trim()) params.set("q", state.q.trim());
  const box = $("#results");
  try {
    const list = await api(`/api/businesses?${params}`);
    if (seq !== loadSeq || !box.isConnected) return;
    $("#results-title").textContent = state.loc ? `עד ${state.radius} ק"מ ממך` : "עסקים חדשים";
    $("#results-count").textContent = list.length ? `${list.length} עסקים` : "";
    if (!list.length) {
      box.outerHTML = `<div id="results">${empty(ICON.search, "לא מצאנו עסקים באזור",
        "נסי להגדיל את הרדיוס או לבחור סוג טיפול אחר.")}</div>`;
      return;
    }
    box.className = "grid";
    box.innerHTML = list.map(card).join("");
    bindFavButtons(box);
  } catch (err) {
    if (box.isConnected) box.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

function openLocationPicker() {
  view.innerHTML = `
    ${pageTitle("בחירת מיקום", "#/")}
    <button class="btn block" id="gps">${ICON.target} השתמשי במיקום הנוכחי שלי</button>
    <p class="error hidden" id="gps-err"></p>
    <div class="section-head" style="margin-top:22px"><h3>או בחרי עיר</h3></div>
    <div class="chips" style="flex-wrap:wrap;margin:0">
      ${CITIES.map(([name], i) => `<button class="chip" data-city="${i}">${esc(name)}</button>`).join("")}
    </div>`;
  $("#gps").addEventListener("click", async () => {
    try {
      const p = await getPosition();
      state.loc = { ...p, label: "המיקום שלי" };
      store.set("nails.loc", state.loc);
      location.hash = "#/";
    } catch (err) {
      const el = $("#gps-err");
      el.textContent = err.message;
      el.classList.remove("hidden");
    }
  });
  view.querySelectorAll("[data-city]").forEach((b) => b.addEventListener("click", () => {
    const [label, lat, lng] = CITIES[Number(b.dataset.city)];
    state.loc = { lat, lng, label };
    store.set("nails.loc", state.loc);
    location.hash = "#/";
  }));
}

/* ================= business page ================= */

async function renderBusiness(id) {
  view.innerHTML = `${pageTitle("", "#/")}<div class="skeleton" style="aspect-ratio:4/3"></div>`;
  const params = state.loc ? `?lat=${state.loc.lat}&lng=${state.loc.lng}` : "";
  let b;
  try {
    b = await api(`/api/businesses/${id}${params}`);
  } catch (err) {
    view.innerHTML = `${pageTitle("", "#/")}${empty(ICON.store, "העסק לא נמצא", esc(err.message))}`;
    return;
  }
  const waze = `https://waze.com/ul?ll=${b.lat},${b.lng}&navigate=yes`;
  view.innerHTML = `
    <div class="page-title" style="justify-content:space-between">
      <a class="back" href="#/" aria-label="חזרה">${ICON.back}</a>
      <button class="icon-btn heart-top ${isFav(b.id) ? "on" : ""}" id="fav" aria-label="מועדפים">${ICON.heart}</button>
    </div>
    <div class="gallery">${b.photos.map((p) => `<img src="${esc(p.url)}" alt="עבודה של ${esc(b.name)}" loading="lazy">`).join("")}</div>
    <div class="biz-head">
      <h1>${esc(b.name)}</h1>
      <div class="meta">
        <span>${ICON.pin}${esc(b.city)}${b.address ? ` · ${esc(b.address)}` : ""}</span>
        ${b.distance_km != null ? `<span>${ICON.target}${b.distance_km} ק"מ ממך</span>` : ""}
      </div>
    </div>
    <div class="tags" style="margin-top:12px">${b.services.map((s) => `<span class="tag">${esc(serviceLabel(s))}</span>`).join("")}</div>
    ${b.description ? `<p class="desc">${esc(b.description)}</p>` : ""}
    <div class="actions">
      <a class="btn whatsapp block" href="${esc(b.whatsapp_url)}" target="_blank" rel="noopener">${ICON.whatsapp} שליחת הודעה בוואטסאפ</a>
      <div class="row">
        <a class="btn outline" href="tel:${esc(b.phone)}">${ICON.phone} התקשרות</a>
        <a class="btn outline" href="${waze}" target="_blank" rel="noopener">${ICON.nav} ניווט</a>
      </div>
      <p class="note">ההודעה תיפתח עם הטקסט: "היי! הגעתי אלייך דרך אפליקציית Nails 💅"</p>
    </div>`;
  const favBtn = $("#fav");
  if (isFav(b.id)) favBtn.querySelector("svg").style.fill = "currentColor";
  favBtn.addEventListener("click", () => {
    const on = toggleFav(b.id);
    favBtn.querySelector("svg").style.fill = on ? "currentColor" : "none";
    toast(on ? "נשמר במועדפים 💖" : "הוסר מהמועדפים");
  });
}

/* ================= favorites ================= */

async function renderFavorites() {
  const ids = favs();
  view.innerHTML = `${pageTitle("המועדפים שלי", "#/")}<div id="fav-list"></div>`;
  const box = $("#fav-list");
  if (!ids.length) {
    box.innerHTML = empty(ICON.heart, "אין עדיין עסקים במועדפים",
      "לחצי על הלב כדי לשמור עסקים שאהבת.", '<a class="btn" href="#/">חיפוש עסקים</a>');
    return;
  }
  const params = state.loc ? `?lat=${state.loc.lat}&lng=${state.loc.lng}` : "";
  const results = await Promise.all(ids.map((id) => api(`/api/businesses/${id}${params}`).catch(() => null)));
  const list = results.filter(Boolean);
  store.set("nails.favs", list.map((b) => b.id));  // drop deleted businesses
  if (!list.length) {
    box.innerHTML = empty(ICON.heart, "אין עדיין עסקים במועדפים", "לחצי על הלב כדי לשמור עסקים שאהבת.");
    return;
  }
  box.className = "grid";
  box.innerHTML = list.map(card).join("");
  bindFavButtons(box);
}

/* ================= photos (client-side resize) ================= */

async function resizeImage(file, maxSide = 1600, quality = 0.85) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("לא הצלחנו לקרוא את התמונה"));
      i.src = url;
    });
    const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(img.width * scale);
    canvas.height = Math.round(img.height * scale);
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", quality));
    return { blob, preview: URL.createObjectURL(blob) };
  } finally {
    URL.revokeObjectURL(url);
  }
}

/* ================= add business ================= */

const MIN_PHOTOS = 5;
const MAX_PHOTOS = 12;

function locationMap(el, initial, onPick) {
  if (!window.L) {
    el.innerHTML = '<p class="note" style="padding:16px">המפה לא נטענה. השתמשי בכפתור "אני בעסק עכשיו".</p>';
    return { set() {} };
  }
  const start = initial || state.loc || { lat: 32.0853, lng: 34.7818 };
  const map = L.map(el, { zoomControl: true }).setView([start.lat, start.lng], initial ? 16 : 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: "© OpenStreetMap",
  }).addTo(map);
  let marker = initial ? L.marker([initial.lat, initial.lng]).addTo(map) : null;
  const set = (lat, lng, zoom) => {
    if (marker) marker.setLatLng([lat, lng]); else marker = L.marker([lat, lng]).addTo(map);
    if (zoom) map.setView([lat, lng], zoom);
    onPick({ lat, lng });
  };
  map.on("click", (e) => set(e.latlng.lat, e.latlng.lng));
  setTimeout(() => map.invalidateSize(), 50);
  return { set };
}

function businessFields(b = {}) {
  const sel = new Set(b.services || []);
  return `
    <label class="field"><span>שם העסק *</span>
      <input type="text" name="name" required minlength="2" maxlength="60" value="${esc(b.name)}" placeholder="למשל: סטודיו ורוד"></label>
    <label class="field"><span>טלפון (וואטסאפ) *</span>
      <input type="tel" name="phone" required inputmode="tel" value="${esc(b.phone)}" placeholder="050-0000000"></label>
    <label class="field"><span>עיר *</span>
      <input type="text" name="city" required minlength="2" maxlength="40" value="${esc(b.city)}" list="cities"></label>
    <datalist id="cities">${CITIES.map(([c]) => `<option value="${esc(c)}">`).join("")}</datalist>
    <label class="field"><span>כתובת (לא חובה)</span>
      <input type="text" name="address" maxlength="100" value="${esc(b.address)}" placeholder="רחוב ומספר"></label>
    <div class="field"><span class="label-sm">אילו טיפולים את עושה?</span>
      <div class="check-grid">
        ${SERVICES.map((s) => `<label class="chip ${sel.has(s.key) ? "on" : ""}">
          <input type="checkbox" name="services" value="${s.key}" ${sel.has(s.key) ? "checked" : ""}>${esc(s.label)}</label>`).join("")}
      </div>
    </div>
    <label class="field" style="margin-top:12px"><span>כמה מילים על העסק (לא חובה)</span>
      <textarea name="description" rows="3" maxlength="600" placeholder="ניסיון, סגנון, שעות פעילות...">${esc(b.description)}</textarea></label>`;
}

function bindServiceChips(root) {
  root.querySelectorAll(".check-grid input").forEach((cb) =>
    cb.addEventListener("change", () => cb.parentElement.classList.toggle("on", cb.checked)));
}

function renderAdd() {
  const photos = [];   // {blob, preview}
  let picked = null;   // {lat, lng}

  view.innerHTML = `
    <div class="page-title" style="justify-content:space-between">
      <h1>הוספת העסק שלך</h1>
      <a class="back" href="#/" aria-label="סגירה">${ICON.close}</a>
    </div>
    <form id="add-form" novalidate>
      <section class="panel">
        <div class="panel-head"><div class="step">${ICON.store}<b>1</b></div>
          <div><h2>פרטי העסק</h2><p>ככה הלקוחות יראו אותך</p></div></div>
        ${businessFields()}
      </section>

      <section class="panel">
        <div class="panel-head"><div class="step">${ICON.pin}<b>2</b></div>
          <div><h2>איפה העסק נמצא?</h2><p>כדי שלקוחות באזור ימצאו אותך</p></div></div>
        <button type="button" class="btn outline block" id="here">${ICON.target} אני בעסק עכשיו, קחי את המיקום</button>
        <div class="map" id="map"></div>
        <p class="progress" id="loc-status">או לחצי על המפה במקום של העסק</p>
      </section>

      <section class="panel">
        <div class="panel-head"><div class="step">${ICON.camera}<b>3</b></div>
          <div><h2>תמונות של עבודות</h2><p>לפחות ${MIN_PHOTOS} תמונות של ציפורניים שעשית</p></div></div>
        <div class="photo-grid" id="photos"></div>
        <input type="file" id="file" accept="image/*" multiple hidden>
        <p class="progress" id="photo-status"></p>
      </section>

      <p class="error hidden" id="form-err"></p>
      <div class="sticky-submit"><button class="btn block" id="submit">פרסום העסק</button></div>
    </form>`;

  bindServiceChips(view);
  const mapCtl = locationMap($("#map"), null, (p) => {
    picked = p;
    const s = $("#loc-status");
    s.textContent = "✓ המיקום נשמר";
    s.classList.add("ok");
  });
  $("#here").addEventListener("click", async () => {
    try {
      const p = await getPosition();
      mapCtl.set(p.lat, p.lng, 17);
    } catch (err) { toast(err.message); }
  });

  const drawPhotos = () => {
    $("#photos").innerHTML = photos.map((p, i) => `
      <div class="ph"><img src="${p.preview}" alt=""><button type="button" class="rm" data-rm="${i}" aria-label="הסרה">${ICON.close}</button></div>`).join("")
      + (photos.length < MAX_PHOTOS ? `<div class="ph add-ph" id="add-ph" role="button" tabindex="0">${ICON.plus}<span>הוספת תמונות</span></div>` : "");
    const st = $("#photo-status");
    const missing = MIN_PHOTOS - photos.length;
    st.textContent = missing > 0 ? `${photos.length} מתוך ${MIN_PHOTOS} (חסרות עוד ${missing})` : `✓ ${photos.length} תמונות`;
    st.classList.toggle("ok", missing <= 0);
    $("#add-ph")?.addEventListener("click", () => $("#file").click());
  };
  $("#photos").addEventListener("click", (e) => {
    const rm = e.target.closest("[data-rm]");
    if (!rm) return;
    const [p] = photos.splice(Number(rm.dataset.rm), 1);
    URL.revokeObjectURL(p.preview);
    drawPhotos();
  });
  $("#file").addEventListener("change", async (e) => {
    const files = [...e.target.files].slice(0, MAX_PHOTOS - photos.length);
    e.target.value = "";
    for (const f of files) {
      try { photos.push(await resizeImage(f)); } catch (err) { toast(err.message); }
      drawPhotos();
    }
  });
  drawPhotos();

  $("#add-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const err = $("#form-err");
    const fail = (m) => { err.textContent = m; err.classList.remove("hidden"); };
    err.classList.add("hidden");

    const fd = new FormData(form);
    if (String(fd.get("name")).trim().length < 2) return fail("צריך למלא את שם העסק");
    if (!String(fd.get("phone")).trim()) return fail("צריך למלא מספר טלפון");
    if (String(fd.get("city")).trim().length < 2) return fail("צריך למלא עיר");
    if (!picked) return fail("צריך לסמן את מיקום העסק על המפה");
    if (photos.length < MIN_PHOTOS) return fail(`צריך לפחות ${MIN_PHOTOS} תמונות`);

    const body = new FormData();
    for (const k of ["name", "phone", "city", "address", "description"]) body.set(k, fd.get(k) || "");
    body.set("services", fd.getAll("services").join(","));
    body.set("lat", picked.lat);
    body.set("lng", picked.lng);
    photos.forEach((p, i) => body.append("photos", p.blob, `photo${i}.jpg`));

    const btn = $("#submit");
    btn.disabled = true;
    btn.textContent = "מעלה...";
    try {
      const res = await api("/api/businesses", { method: "POST", body });
      saveMine({ id: res.id, token: res.token, name: String(fd.get("name")).trim() });
      location.hash = `#/manage/${res.id}?new=1`;
    } catch (ex) {
      fail(ex.message);
      btn.disabled = false;
      btn.textContent = "פרסום העסק";
    }
  });
}

/* ================= my business ================= */

function renderMine() {
  const list = mine();
  view.innerHTML = `${pageTitle("העסק שלי")}${list.length ? `
    <div class="panel" style="padding:0">
      ${list.map((m) => `<a class="list-item" href="#/manage/${m.id}">
        <div class="step">${ICON.store}</div>
        <div class="grow"><b>${esc(m.name)}</b><br><small>ניהול, סטטיסטיקות ועריכה</small></div>
        <span style="transform:scaleX(-1)">${ICON.back}</span></a>`).join("")}
    </div>
    <a class="btn outline block" href="#/add">${ICON.plus} הוספת עסק נוסף</a>`
    : empty(ICON.store, "עוד לא העלית עסק", "בעלת עסק לציפורניים? העלי את העסק שלך ולקוחות מהאזור ימצאו אותך.",
      '<a class="btn" href="#/add">הוספת העסק שלי</a>')}`;
}

async function renderManage(id, isNew) {
  const entry = mine().find((m) => m.id === id);
  if (!entry) {
    view.innerHTML = `${pageTitle("ניהול עסק", "#/mine")}${empty(ICON.store, "אין הרשאה",
      "אפשר לנהל עסק רק מהמכשיר שבו הוא נוצר, או דרך הקישור הפרטי שקיבלת.")}`;
    return;
  }
  const headers = { "X-Edit-Token": entry.token };
  let b;
  try {
    b = await api(`/api/businesses/${id}/manage`, { headers });
  } catch (err) {
    view.innerHTML = `${pageTitle("ניהול עסק", "#/mine")}<p class="error">${esc(err.message)}</p>`;
    return;
  }
  saveMine({ ...entry, name: b.name });
  const privateLink = `${location.origin}/#/claim/${id}/${entry.token}`;

  view.innerHTML = `
    ${pageTitle(esc(b.name), "#/mine")}
    ${isNew ? `<div class="loc-bar" style="display:block"><b>🎉 העסק שלך באוויר!</b><br>
      לקוחות באזור כבר יכולות למצוא אותך.</div>` : ""}

    <div class="panel stats">
      <div><b>${b.stats.views}</b><span>צפיות בעמוד</span></div>
      <div><b>${b.stats.whatsapp_clicks}</b><span>פניות בוואטסאפ</span></div>
    </div>

    <a class="btn outline block" href="#/b/${id}" style="margin-bottom:14px">צפייה בעמוד כמו שלקוחה רואה</a>

    <section class="panel">
      <div class="panel-head"><div class="step">${ICON.info}</div><div><h2>קישור פרטי לניהול</h2>
        <p>שמרי אותו! איתו אפשר לנהל את העסק מכל טלפון.</p></div></div>
      <div class="secret" id="secret">${esc(privateLink)}</div>
      <button class="btn outline block" id="copy" style="margin-top:10px">העתקת הקישור</button>
    </section>

    <form class="panel" id="edit-form" novalidate>
      <div class="panel-head"><div class="step">${ICON.store}</div><div><h2>עריכת פרטים</h2></div></div>
      ${businessFields(b)}
      <div class="label-sm">מיקום העסק (לחצי על המפה כדי לשנות)</div>
      <div class="map" id="map"></div>
      <p class="error hidden" id="edit-err"></p>
      <button class="btn block" style="margin-top:14px">שמירת שינויים</button>
    </form>

    <section class="panel">
      <div class="panel-head"><div class="step">${ICON.camera}</div><div><h2>תמונות</h2>
        <p>לפחות ${MIN_PHOTOS}, עד ${MAX_PHOTOS}</p></div></div>
      <div class="photo-grid" id="photos"></div>
      <input type="file" id="file" accept="image/*" multiple hidden>
    </section>

    <button class="btn danger block" id="delete">מחיקת העסק</button>`;

  bindServiceChips(view);
  $("#copy").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(privateLink); toast("הקישור הועתק"); }
    catch { toast("לא הצלחנו להעתיק, סמני את הקישור והעתיקי ידנית"); }
  });

  let newLoc = null;
  locationMap($("#map"), { lat: b.lat, lng: b.lng }, (p) => { newLoc = p; });

  $("#edit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = {
      name: String(fd.get("name")).trim(),
      phone: String(fd.get("phone")).trim(),
      city: String(fd.get("city")).trim(),
      address: String(fd.get("address") || "").trim(),
      description: String(fd.get("description") || "").trim(),
      services: fd.getAll("services"),
      ...(newLoc || {}),
    };
    const err = $("#edit-err");
    err.classList.add("hidden");
    try {
      await api(`/api/businesses/${id}`, {
        method: "PATCH", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      saveMine({ ...entry, name: payload.name });
      toast("השינויים נשמרו ✓");
    } catch (ex) {
      err.textContent = ex.message;
      err.classList.remove("hidden");
    }
  });

  let photos = b.photos;
  const drawPhotos = () => {
    $("#photos").innerHTML = photos.map((p) => `
      <div class="ph"><img src="${esc(p.url)}" alt="">${photos.length > MIN_PHOTOS
        ? `<button type="button" class="rm" data-rm="${p.id}" aria-label="מחיקה">${ICON.close}</button>` : ""}</div>`).join("")
      + (photos.length < MAX_PHOTOS ? `<div class="ph add-ph" id="add-ph" role="button" tabindex="0">${ICON.plus}<span>הוספה</span></div>` : "");
    $("#add-ph")?.addEventListener("click", () => $("#file").click());
  };
  $("#photos").addEventListener("click", async (e) => {
    const rm = e.target.closest("[data-rm]");
    if (!rm) return;
    try {
      photos = await api(`/api/businesses/${id}/photos/${rm.dataset.rm}`, { method: "DELETE", headers });
      drawPhotos();
    } catch (ex) { toast(ex.message); }
  });
  $("#file").addEventListener("change", async (e) => {
    const files = [...e.target.files].slice(0, MAX_PHOTOS - photos.length);
    e.target.value = "";
    if (!files.length) return;
    const body = new FormData();
    for (const [i, f] of files.entries()) {
      try { body.append("photos", (await resizeImage(f)).blob, `photo${i}.jpg`); } catch (ex) { toast(ex.message); }
    }
    try {
      photos = await api(`/api/businesses/${id}/photos`, { method: "POST", headers, body });
      drawPhotos();
      toast("התמונות נוספו ✓");
    } catch (ex) { toast(ex.message); }
  });
  drawPhotos();

  $("#delete").addEventListener("click", async () => {
    if (!confirm("למחוק את העסק לצמיתות? אי אפשר לבטל את זה.")) return;
    try {
      await api(`/api/businesses/${id}`, { method: "DELETE", headers });
      store.set("nails.mine", mine().filter((m) => m.id !== id));
      toast("העסק נמחק");
      location.hash = "#/mine";
    } catch (ex) { toast(ex.message); }
  });
}

function claim(id, token) {
  saveMine({ id, token, name: mine().find((m) => m.id === id)?.name || "העסק שלי" });
  location.replace(`#/manage/${id}`);
}

/* ================= router ================= */

function route() {
  const hash = location.hash || "#/";
  const [path, query] = hash.slice(1).split("?");
  const parts = path.split("/").filter(Boolean);
  const tab = { "": "home", b: "home", favorites: "favorites", add: "add", mine: "mine", manage: "mine" }[parts[0] || ""];
  document.querySelectorAll(".tabbar a").forEach((a) => a.classList.toggle("on", a.dataset.tab === tab));
  window.scrollTo(0, 0);

  switch (parts[0]) {
    case undefined: return renderHome();
    case "b": return renderBusiness(Number(parts[1]));
    case "favorites": return renderFavorites();
    case "add": return renderAdd();
    case "mine": return renderMine();
    case "manage": return renderManage(Number(parts[1]), new URLSearchParams(query).has("new"));
    case "claim": return claim(Number(parts[1]), parts[2]);
    default: location.hash = "#/";
  }
}

(async function start() {
  try { SERVICES = await api("/api/services"); } catch { SERVICES = []; }
  window.addEventListener("hashchange", route);
  route();
})();
