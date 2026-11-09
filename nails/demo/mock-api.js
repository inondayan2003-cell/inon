/* Nails preview: a stand-in for the server that runs inside the browser.
 * Loaded before app.js in the preview build only (demo/build.py).
 * Data lives in this browser's localStorage; sample businesses are generated on load.
 */
"use strict";

(function () {
  const KEY = "nails.preview.db.v2";
  const TZ = "Asia/Jerusalem";

  const SERVICES = {
    gel: "לק ג'ל", build: "בניית ציפורניים", fill: "מילוי", regular: "לק רגיל",
    art: "ציור ועיצובים", pedicure: "פדיקור", russian: "מניקור רוסי",
  };
  const WA_TEXT = "היי! הגעתי אלייך דרך אפליקציית Nails 💅 אשמח לשמוע פרטים ולקבוע תור";
  const WEEK = { 0: ["09:00", "19:00"], 1: ["09:00", "19:00"], 2: ["09:00", "19:00"], 3: ["09:00", "19:00"], 4: ["09:00", "19:00"], 5: ["09:00", "14:00"] };

  const SAMPLES = [
    ["סטודיו ורוד", "0501234567", "תל אביב", "דיזנגוף 120", 32.0790, 34.7806, "gel,art", 80, 250, "בניית ציפורניים ועיצובים בהתאמה אישית ✨", WEEK],
    ["נייל בר רמת גן", "0521234567", "רמת גן", "ביאליק 30", 32.0684, 34.8248, "gel,build,fill", 100, 290, "מניקור ג'ל ובנייה, אווירה רגועה וקפה טוב", WEEK],
    ["ליה ציפורניים", "0531234567", "גבעתיים", "כצנלסון 55", 32.0722, 34.8125, "russian,gel", 120, 330, "מניקור רוסי מדויק, 6 שנות ניסיון", { ...WEEK, 6: ["20:00", "23:00"] }],
    ["ציפורני זהב", "0541234567", "חולון", "סוקולוב 12", 32.0158, 34.7874, "build,art,pedicure", 140, 370, "סטודיו פרטי, חניה בשפע", { 0: ["10:00", "20:00"], 2: ["10:00", "20:00"], 4: ["10:00", "20:00"] }],
    ["סטודיו זוהר", "0551234567", "הרצליה", "סוקולוב 40", 32.1624, 34.8447, "gel,pedicure,regular", 160, 410, "לק ג'ל, פדיקור רפואי וטיפוח", WEEK],
    ["נוי ציפורניים", "0561234567", "ירושלים", "יפו 90", 31.7683, 35.2137, "gel,build", 90, 260, "בנייה באקריל וג'ל, מחירים הוגנים", WEEK],
    ["המעבדה הוורודה", "0571234567", "בת ים", "בלפור 8", 32.0171, 34.7454, "gel,art,regular", 70, 200, "עיצובים צבעוניים וטרנדים מהאינסטגרם", WEEK],
  ];

  /* ---------- generated sample photos (canvas) ---------- */
  const PALETTES = [
    ["#f6c1d1", "#b03a64", ["#e94b7b", "#ffd1dc", "#c9a46a", "#fff", "#8e2a50"]],
    ["#fbe2c9", "#c9a46a", ["#d4a373", "#faedcd", "#e76f51", "#fff", "#9c6644"]],
    ["#d9dcf5", "#5a64b4", ["#7b8cde", "#c8b6ff", "#ffd6ff", "#fff", "#3d348b"]],
    ["#f3d1ea", "#963c8c", ["#c86bfa", "#ffc8dd", "#ffafcc", "#fff", "#6a2c70"]],
    ["#ffe1e1", "#dc505a", ["#ef476f", "#ffd166", "#f78c6b", "#fff", "#b5179e"]],
    ["#d7efe5", "#3c8c6e", ["#52b788", "#b7e4c7", "#e9c46a", "#fff", "#2d6a4f"]],
    ["#f1e4d8", "#7a5c48", ["#a98467", "#e6ccb2", "#d62828", "#fff", "#432818"]],
  ];
  function rand(seed) { let x = seed * 9301 + 49297; return () => ((x = (x * 9301 + 49297) % 233280) / 233280); }

  function samplePhoto(n, i) {
    const r = rand(n * 31 + i * 7 + 3);
    const [top, bottom, polish] = PALETTES[(n + i) % PALETTES.length];
    const c = document.createElement("canvas");
    c.width = 480; c.height = 640;
    const g = c.getContext("2d");
    const grad = g.createLinearGradient(0, 0, 0, 640);
    grad.addColorStop(0, top); grad.addColorStop(1, bottom);
    g.fillStyle = grad; g.fillRect(0, 0, 480, 640);
    // a hand of five nails
    const base = 360 + r() * 60;
    for (let k = 0; k < 5; k++) {
      const x = 48 + k * 82, h = 150 + r() * 90 + (k === 2 ? 30 : 0), y = base - h * 0.55 - (k === 2 ? 20 : 0);
      g.fillStyle = "rgba(255,226,206,.95)";
      roundRect(g, x - 6, y + 30, 74, h + 140, 36); g.fill();
      g.fillStyle = polish[(k + i) % polish.length];
      roundRect(g, x, y, 62, h * 0.62, 31); g.fill();
      // design details
      g.fillStyle = "rgba(255,255,255,.55)";
      roundRect(g, x + 10, y + 10, 10, h * 0.32, 5); g.fill();
      if ((k + n + i) % 3 === 0) { g.fillStyle = polish[(k + 2) % polish.length]; dots(g, x + 31, y + h * 0.3, r); }
      if ((k + i) % 4 === 1) { g.fillStyle = "#fff"; g.fillRect(x, y + h * 0.5, 62, 10); }
    }
    return c.toDataURL("image/jpeg", 0.8);
  }
  function roundRect(g, x, y, w, h, rad) {
    g.beginPath(); g.moveTo(x + rad, y); g.arcTo(x + w, y, x + w, y + h, rad); g.arcTo(x + w, y + h, x, y + h, rad);
    g.arcTo(x, y + h, x, y, rad); g.arcTo(x, y, x + w, y, rad); g.closePath();
  }
  function dots(g, cx, cy, r) {
    for (let d = 0; d < 5; d++) { g.beginPath(); g.arc(cx + (r() - 0.5) * 30, cy + (r() - 0.5) * 40, 3 + r() * 3, 0, 7); g.fill(); }
  }

  /* ---------- storage ---------- */
  let db;
  function load() {
    try { db = JSON.parse(localStorage.getItem(KEY)); } catch { db = null; }
    if (!db) {
      db = { nextId: 1, nextPhoto: 1, users: {}, businesses: [] };
      SAMPLES.forEach((s, n) => {
        const [name, phone, city, address, lat, lng, services, pmin, pmax, description, hours] = s;
        db.businesses.push({
          id: db.nextId++, owner: `sample-${n}`, name, phone, city, address, lat, lng,
          services: services.split(","), price_min: pmin, price_max: pmax, description, hours,
          photos: [0, 1, 2, 3, 4].map((i) => ({ id: db.nextPhoto++, sample: [n, i] })),
          views: 0, clicks: 0, created: Date.now() - n * 1000,
        });
      });
      save();
    }
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(db)); return true; } catch { return false; }
  }
  const sampleCache = {};
  const photoUrl = (p) => p.url || (sampleCache[p.sample.join("-")] ||= samplePhoto(...p.sample));

  /* ---------- helpers mirroring the server ---------- */
  function distanceKm(lat1, lng1, lat2, lng2) {
    const rad = (d) => (d * Math.PI) / 180;
    const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lng2 - lng1) / 2) ** 2;
    return 2 * 6371 * Math.asin(Math.sqrt(a));
  }
  function israelNow() {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(new Date()).map((x) => [x.type, x.value]));
    return { day: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(p.weekday), time: `${p.hour}:${p.minute}` };
  }
  function openNow(hours) {
    const { day, time } = israelNow();
    const span = hours[day];
    return !!span && span[0] <= time && time < span[1];
  }
  function normPhone(raw) {
    let d = String(raw).replace(/[^\d+]/g, "");
    if (d.startsWith("+972")) d = "0" + d.slice(4); else if (d.startsWith("972")) d = "0" + d.slice(3);
    return /^0\d{8,9}$/.test(d) ? d : null;
  }
  function pub(b, dist = null) {
    return {
      id: b.id, name: b.name, phone: b.phone, city: b.city, address: b.address, description: b.description,
      services: b.services, price_min: b.price_min, price_max: b.price_max, hours: b.hours, open_now: openNow(b.hours),
      lat: b.lat, lng: b.lng, photos: b.photos.map((p) => ({ id: p.id, url: photoUrl(p) })),
      distance_km: dist == null ? null : Math.round(dist * 10) / 10,
      whatsapp_url: `https://wa.me/972${b.phone.slice(1)}?text=${encodeURIComponent(WA_TEXT)}`,
    };
  }
  class HttpError extends Error { constructor(status, detail) { super(detail); this.status = status; this.detail = detail; } }
  const fail = (status, detail) => { throw new HttpError(status, detail); };
  function checkHours(h) {
    const out = {};
    for (const [d, span] of Object.entries(h || {})) {
      if (!span) continue;
      if (!/^[0-6]$/.test(d) || span.length !== 2 || span[0] >= span[1]) fail(422, "שעות פעילות לא תקינות");
      out[d] = span;
    }
    if (!Object.keys(out).length) fail(422, "צריך לבחור לפחות יום פעילות אחד");
    return out;
  }
  function checkPrices(min, max) {
    if (!(min > 0 && max > 0 && min <= 5000 && max <= 5000)) fail(422, "המחירים צריכים להיות בין 1 ל-5000 ₪");
    if (min > max) fail(422, "המחיר ההתחלתי גבוה מהמחיר המקסימלי");
  }
  const blobToDataUrl = (blob) => new Promise((res, rej) => {
    const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(blob);
  });
  async function storePhotos(files) {
    const out = [];
    for (const f of files) out.push({ id: db.nextPhoto++, url: await blobToDataUrl(f) });
    return out;
  }
  function saveOrFail() {
    if (!save()) fail(507, "אין מספיק מקום בדפדפן לתצוגה המקדימה. נסי פחות תמונות.");
  }

  /* ---------- routes ---------- */
  function who(headers) {
    const h = headers.Authorization || headers.authorization || "";
    const m = /^Bearer dev:([^:]+):(.*)$/.exec(h);
    if (!m) fail(401, "צריך להתחבר מחדש");
    return { uid: m[1], contact: m[2] };
  }
  function registered(headers) {
    const ident = who(headers);
    const u = db.users[ident.uid];
    if (!u) fail(403, "not_registered");
    return u;
  }
  const owned = (id, user) => {
    const b = db.businesses.find((x) => x.id === id) || fail(404, "העסק לא נמצא");
    if (b.owner !== user.uid) fail(403, "אין הרשאה לערוך את העסק הזה");
    return b;
  };

  async function handle(method, url, headers, body) {
    const path = url.pathname;
    const q = url.searchParams;
    let m;

    if (path === "/api/config") return { firebase: null, dev_auth: true, methods: ["google", "email"], preview: true };
    if (path === "/api/services") return Object.entries(SERVICES).map(([key, label]) => ({ key, label }));

    if (path === "/api/me") {
      const ident = who(headers);
      if (method === "GET") return db.users[ident.uid] || fail(404, "not_registered");
      const name = String(JSON.parse(body).name || "").trim();
      if (name.length < 2) fail(422, "צריך לכתוב שם");
      const isEmail = ident.contact.includes("@");
      db.users[ident.uid] = {
        uid: ident.uid, name, email: isEmail ? ident.contact : null, phone: isEmail ? null : ident.contact,
        provider: ident.uid.startsWith("google") ? "google" : ident.uid.startsWith("email") ? "email" : "dev",
      };
      saveOrFail();
      return db.users[ident.uid];
    }

    const user = registered(headers);

    if (path === "/api/businesses" && method === "GET") {
      const lat = q.has("lat") ? Number(q.get("lat")) : null, lng = q.has("lng") ? Number(q.get("lng")) : null;
      const radius = Number(q.get("radius_km") || 10), service = q.get("service"), maxPrice = q.get("max_price");
      const text = (q.get("q") || "").trim(), onlyOpen = q.get("open_now") === "true";
      let list = db.businesses.map((b) => [lat == null ? null : distanceKm(lat, lng, b.lat, b.lng), b])
        .filter(([d, b]) => (d == null || d <= radius)
          && (!service || b.services.includes(service))
          && (!maxPrice || b.price_min <= Number(maxPrice))
          && (!text || [b.name, b.city, b.description].some((v) => v.includes(text)))
          && (!onlyOpen || openNow(b.hours)));
      list = lat == null ? list.sort((a, b) => b[1].created - a[1].created) : list.sort((a, b) => a[0] - b[0]);
      return list.slice(0, 100).map(([d, b]) => pub(b, d));
    }
    if (path === "/api/businesses" && method === "POST") {
      const f = body;
      const phone = normPhone(f.get("phone")) || fail(422, "מספר טלפון לא תקין");
      const pmin = Number(f.get("price_min")), pmax = Number(f.get("price_max"));
      checkPrices(pmin, pmax);
      const hours = checkHours(JSON.parse(f.get("hours")));
      const files = f.getAll("photos");
      if (files.length < 5 || files.length > 12) fail(422, "צריך להעלות בין 5 ל-12 תמונות");
      const b = {
        id: db.nextId++, owner: user.uid, name: f.get("name").trim(), phone, city: f.get("city").trim(),
        address: (f.get("address") || "").trim(), description: (f.get("description") || "").trim(),
        services: (f.get("services") || "").split(",").filter(Boolean), price_min: pmin, price_max: pmax, hours,
        lat: Number(f.get("lat")), lng: Number(f.get("lng")), photos: await storePhotos(files),
        views: 0, clicks: 0, created: Date.now(),
      };
      db.businesses.push(b);
      try { saveOrFail(); } catch (e) { db.businesses.pop(); throw e; }
      return { id: b.id };
    }
    if (path === "/api/my/businesses") {
      return db.businesses.filter((b) => b.owner === user.uid)
        .map((b) => ({ ...pub(b), stats: { views: b.views, whatsapp_clicks: b.clicks } }));
    }
    if ((m = /^\/api\/businesses\/(\d+)\/lead$/.exec(path))) {
      const b = db.businesses.find((x) => x.id === Number(m[1])) || fail(404, "העסק לא נמצא");
      if (b.owner !== user.uid) { b.clicks++; save(); }
      return null;
    }
    if ((m = /^\/api\/businesses\/(\d+)\/photos(?:\/(\d+))?$/.exec(path))) {
      const b = owned(Number(m[1]), user);
      if (method === "POST") {
        const files = body.getAll("photos");
        if (b.photos.length + files.length > 12) fail(422, "אפשר עד 12 תמונות לעסק");
        b.photos.push(...(await storePhotos(files)));
      } else {
        if (b.photos.length <= 5) fail(422, "חייבות להישאר לפחות 5 תמונות");
        b.photos = b.photos.filter((p) => p.id !== Number(m[2]));
      }
      saveOrFail();
      return pub(b).photos;
    }
    if ((m = /^\/api\/businesses\/(\d+)$/.exec(path))) {
      const id = Number(m[1]);
      if (method === "GET") {
        const b = db.businesses.find((x) => x.id === id) || fail(404, "העסק לא נמצא");
        if (b.owner !== user.uid) { b.views++; save(); }
        const lat = q.get("lat"), lng = q.get("lng");
        return pub(b, lat ? distanceKm(Number(lat), Number(lng), b.lat, b.lng) : null);
      }
      const b = owned(id, user);
      if (method === "DELETE") { db.businesses = db.businesses.filter((x) => x !== b); save(); return null; }
      const u = JSON.parse(body);
      if (u.phone != null) u.phone = normPhone(u.phone) || fail(422, "מספר טלפון לא תקין");
      if (u.price_min != null) checkPrices(u.price_min, u.price_max);
      if (u.hours != null) u.hours = checkHours(u.hours);
      for (const k of ["name", "phone", "city", "address", "description", "services", "price_min", "price_max", "hours", "lat", "lng"]) {
        if (u[k] != null) b[k] = u[k];
      }
      saveOrFail();
      return pub(b);
    }
    fail(404, "לא נמצא");
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async function (input, opts = {}) {
    const url = new URL(typeof input === "string" ? input : input.url, location.href);
    if (!url.pathname.startsWith("/api/")) return realFetch(input, opts);
    load();
    const json = (status, data) => new Response(status === 204 ? null : JSON.stringify(data), {
      status, headers: { "Content-Type": "application/json" },
    });
    try {
      const data = await handle((opts.method || "GET").toUpperCase(), url, opts.headers || {}, opts.body);
      return data === null ? json(204) : json(200, data);
    } catch (e) {
      if (e instanceof HttpError) return json(e.status, { detail: e.detail });
      console.error(e);
      return json(500, { detail: "משהו השתבש בתצוגה המקדימה" });
    }
  };

  /* ---------- in-page router (artifact frames only pass plain #names) ---------- */
  let current = "#/";
  const listeners = [];
  const fire = () => listeners.forEach((fn) => fn());
  window.NAILS_NAV = {
    get hash() { return current; },
    go(h) { current = h; fire(); },
    replace(h) { current = h; fire(); },
    silent(h) { current = h; },
    listen(fn) { listeners.push(fn); },
  };
  document.addEventListener("click", (e) => {
    const a = e.target.closest('a[href^="#/"]');
    if (!a) return;
    e.preventDefault();
    window.NAILS_NAV.go(a.getAttribute("href"));
  });

  // Preview starts near Tel Aviv so sample businesses show up right away.
  try {
    if (!localStorage.getItem("nails.loc")) {
      localStorage.setItem("nails.loc", JSON.stringify({ lat: 32.0853, lng: 34.7818, label: "תל אביב" }));
    }
  } catch { /* storage blocked */ }
})();
