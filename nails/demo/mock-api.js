/* Nails preview: a stand-in for the server that runs inside the browser.
 * Loaded before app.js in the preview build only (demo/build.py).
 * Data lives in this browser's localStorage; sample businesses are generated on load.
 */
"use strict";

(function () {
  const KEY = "nails.preview.db.v6";
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
  const PALETTES = [   // nude / cocoa / stone tones, like the hero photo
    ["#efe4df", "#b9988a", ["#e6cdc8", "#5a3426", "#f6eeea", "#fff", "#8f5d4b"]],
    ["#e9e4dc", "#a39587", ["#d9b8ad", "#3b1f15", "#efe2dc", "#fff", "#b88b7d"]],
    ["#f1e7e1", "#c4a397", ["#f2dcd5", "#7a4636", "#e8cfc6", "#fff", "#4a2c25"]],
    ["#e6dfd8", "#9c8576", ["#cfa79a", "#5a3426", "#f5e9e4", "#fff", "#a77565"]],
    ["#f3ebe6", "#b9a093", ["#ead3cb", "#6d4230", "#dcbcb0", "#fff", "#895d48"]],
    ["#ece6e0", "#ab968a", ["#e1c2b8", "#3f2219", "#f3e4de", "#fff", "#b07c6a"]],
    ["#efe8e2", "#b59c8e", ["#d7b2a6", "#5c2f22", "#efdcd5", "#fff", "#9b6b58"]],
  ];  function rand(seed) { let x = seed * 9301 + 49297; return () => ((x = (x * 9301 + 49297) % 233280) / 233280); }

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
      db = { nextId: 1, nextPhoto: 1, nextVer: 1, users: {}, businesses: [], verifications: [], favorites: [] };
      SAMPLES.forEach((s, n) => {
        const [name, phone, city, address, lat, lng, services, pmin, pmax, description, hours] = s;
        db.businesses.push({
          id: db.nextId++, owner: `sample-${n}`, name, phone, city, address, lat, lng,
          services: services.split(","), price_min: pmin, price_max: pmax, description, hours,
          photos: [0, 1, 2, 3, 4].map((i) => ({ id: db.nextPhoto++, sample: [n, i] })),
          views: 0, clicks: 0, created: Date.now() - n * 1000, sampleVerified: n % 3 === 0,
          instagram: ["pink.studio.tlv", "", "lia.nails", "", "glow.studio", "", ""][n],
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
      street: b.street || "", house_number: b.house_number || "", apartment: b.apartment || "", entrance: b.entrance || "",
      instagram: b.instagram || "",
      services: b.services, price_min: b.price_min, price_max: b.price_max, hours: b.hours, open_now: openNow(b.hours),
      lat: b.lat, lng: b.lng, photos: b.photos.map((p) => ({ id: p.id, url: photoUrl(p) })),
      distance_km: dist == null ? null : Math.round(dist * 10) / 10,
      verified: !!(db.users[b.owner]?.verified ?? b.sampleVerified),
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
  function insta(raw) {
    let v = String(raw).trim();
    const m = /^(?:https?:\/\/)?(?:www\.)?instagram\.com\/([^/?#]+)/i.exec(v);
    if (m) v = m[1];
    v = v.replace(/^@+/, "").trim();
    if (v && !/^[A-Za-z0-9._]{1,30}$/.test(v)) fail(422, "שם המשתמש באינסטגרם לא תקין");
    return v;
  }
  // Preview stand-in for the map lookup: the city's center, nudged by the street name.
  function locate(city, street, number) {
    if (!street || !number) fail(422, "צריך למלא רחוב ומספר בית, או ללחוץ 'אני בעסק עכשיו'");
    const c = (typeof CITIES !== "undefined" ? CITIES : []).find(([n]) => n === city);
    if (!c) fail(422, "לא מצאנו את הכתובת במפה. בדקי את שם העיר והרחוב");
    let h = 0;
    for (const ch of street + number) h = (h * 31 + ch.charCodeAt(0)) % 1000;
    return [c[1] + (h - 500) / 50000, c[2] + ((h * 7) % 1000 - 500) / 50000];
  }
  const addressLine = (st, no, apt, ent) => [`${st} ${no}`.trim(), ent && `כניסה ${ent}`, apt && `דירה ${apt}`].filter(Boolean).join(", ");
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
  // What /api/me returns: the stored user plus admin flag and latest verification request.
  function me(u) {
    const v = [...db.verifications].reverse().find((x) => x.uid === u.uid);
    return { ...u, verified: !!u.verified, is_admin: true,
      verification: v ? { status: v.status, note: v.note, created_at: v.created_at } : null };
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

    if (path === "/api/config") return { firebase: null, dev_auth: true, methods: ["google", "email"], preview: true, support_email: "", support_phone: "0528326523", operator: { name: "", id: "", address: "" } };
    if (path === "/api/services") return Object.entries(SERVICES).map(([key, label]) => ({ key, label }));

    if (path === "/api/me/verification") {
      const u = registered(headers);
      if (u.verified) fail(409, "החשבון כבר מאומת");
      if (db.verifications.some((v) => v.uid === u.uid && v.status === "pending")) fail(409, "כבר שלחת בקשה, והיא בבדיקה");
      if (!db.businesses.some((b) => b.owner === u.uid)) fail(422, "אימות מיועד לבעלות עסקים. קודם צריך להוסיף עסק");
      db.verifications.push({ id: db.nextVer++, uid: u.uid, selfie: await blobToDataUrl(body.get("selfie")),
        status: "pending", note: "", created_at: new Date().toISOString() });
      saveOrFail();
      return me(u);
    }
    if (path.startsWith("/api/admin/")) {
      registered(headers);  // in the preview every account is an admin
      let m2;
      if (path === "/api/admin/summary") {
        const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
        return { pending_verifications: db.verifications.filter((v) => v.status === "pending").length,
          backup: { ok: true, at: midnight.toISOString(), size: 4.2 * 1048576, photos: db.businesses.reduce((n, b) => n + b.photos.length, 0), offsite: true } };
      }
      if (path === "/api/admin/verifications") {
        const st = q.get("status") || "pending";
        return db.verifications.filter((v) => v.status === st).reverse().map((v) => {
          const u = db.users[v.uid] || {};
          return { id: v.id, uid: v.uid, status: v.status, note: v.note, created_at: v.created_at, decided_at: v.decided_at || null,
            user: { name: u.name, email: u.email, phone: u.phone, city: u.city, verified: !!u.verified, avatar_url: u.avatar_url || null },
            businesses: db.businesses.filter((b) => b.owner === v.uid).map((b) => ({ id: b.id, name: b.name, city: b.city })),
            has_selfie: !!v.selfie };
        });
      }
      if ((m2 = /^\/api\/admin\/verifications\/(\d+)\/selfie$/.exec(path))) {
        const v = db.verifications.find((x) => x.id === Number(m2[1]));
        if (!v?.selfie) fail(404, "התמונה לא נמצאה");
        const [meta, b64] = v.selfie.split(",");
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        return { __blob: new Blob([bytes], { type: meta.slice(5).split(";")[0] }) };
      }
      if ((m2 = /^\/api\/admin\/verifications\/(\d+)$/.exec(path))) {
        const v = db.verifications.find((x) => x.id === Number(m2[1])) || fail(404, "הבקשה לא נמצאה");
        if (v.status !== "pending") fail(409, "כבר טיפלת בבקשה הזאת");
        const d = JSON.parse(body);
        Object.assign(v, { status: d.approve ? "approved" : "rejected", note: (d.note || "").trim(), selfie: "", decided_at: new Date().toISOString() });
        if (d.approve && db.users[v.uid]) db.users[v.uid].verified = true;
        save();
        return { id: v.id, status: v.status };
      }
      if ((m2 = /^\/api\/admin\/users\/([^/]+)\/unverify$/.exec(path))) {
        const u = db.users[decodeURIComponent(m2[1])];
        if (u) u.verified = false;
        save();
        return { verified: false };
      }
      fail(404, "לא נמצא");
    }
    if (path === "/api/me/avatar") {
      const u = registered(headers);
      u.avatar_url = method === "POST" ? await blobToDataUrl(body.get("photo")) : null;
      saveOrFail();
      return me(u);
    }
    if (path === "/api/me") {
      const ident = who(headers);
      if (method === "GET") return me(db.users[ident.uid] || fail(404, "not_registered"));
      if (method === "DELETE") {
        db.businesses = db.businesses.filter((b) => b.owner !== ident.uid);
        db.verifications = db.verifications.filter((v) => v.uid !== ident.uid);
        db.favorites = db.favorites.filter((f) => f.uid !== ident.uid);
        delete db.users[ident.uid];
        save();
        return null;
      }
      const data = JSON.parse(body);
      const name = String(data.name || "").trim();
      if (name.length < 2) fail(422, "צריך לכתוב שם");
      if (!db.users[ident.uid] && !data.accepted_terms) fail(422, "כדי להירשם צריך לאשר את תנאי השימוש ומדיניות הפרטיות");
      const isEmail = ident.contact.includes("@");
      db.users[ident.uid] = {
        avatar_url: null, ...db.users[ident.uid],
        uid: ident.uid, name, city: String(data.city || "").trim(),
        email: isEmail ? ident.contact : null, phone: isEmail ? null : ident.contact,
        provider: ident.uid.startsWith("google") ? "google" : ident.uid.startsWith("email") ? "email" : "dev",
      };
      saveOrFail();
      return me(db.users[ident.uid]);
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
      if (f.get("photos_rights") !== "true") fail(422, "צריך לאשר שהתמונות הן של עבודות שלך ושמותר לך לפרסם אותן");
      const g = (k) => String(f.get(k) || "").trim();
      const pos = f.get("lat") ? [Number(f.get("lat")), Number(f.get("lng"))] : locate(g("city"), g("street"), g("house_number"));
      const b = {
        id: db.nextId++, owner: user.uid, name: f.get("name").trim(), phone, city: f.get("city").trim(),
        street: g("street"), house_number: g("house_number"), apartment: g("apartment"), entrance: g("entrance"),
        address: addressLine(g("street"), g("house_number"), g("apartment"), g("entrance")),
        description: (f.get("description") || "").trim(),
        instagram: insta(f.get("instagram") || ""),
        services: (f.get("services") || "").split(",").filter(Boolean), price_min: pmin, price_max: pmax, hours,
        lat: pos[0], lng: pos[1], photos: await storePhotos(files),
        views: 0, clicks: 0, created: Date.now(), photos_updated_at: Date.now(),
      };
      db.businesses.push(b);
      try { saveOrFail(); } catch (e) { db.businesses.pop(); throw e; }
      return { id: b.id };
    }
    if (path === "/api/favorites/ids") {
      return db.favorites.filter((f) => f.uid === user.uid).sort((a, b) => b.created - a.created).map((f) => f.business_id);
    }
    if (path === "/api/favorites") {
      const lat = q.get("lat"), lng = q.get("lng");
      return db.favorites.filter((f) => f.uid === user.uid).sort((a, b) => b.created - a.created)
        .map((f) => [f, db.businesses.find((x) => x.id === f.business_id)]).filter(([, b]) => b)
        .map(([f, b]) => ({ ...pub(b, lat ? distanceKm(Number(lat), Number(lng), b.lat, b.lng) : null),
          new_photos: (b.photos_updated_at || 0) > f.seen_at }));
    }
    if ((m = /^\/api\/favorites\/(\d+)$/.exec(path))) {
      const id = Number(m[1]);
      db.businesses.find((x) => x.id === id) || fail(404, "העסק לא נמצא");
      db.favorites = db.favorites.filter((f) => !(f.uid === user.uid && f.business_id === id));
      if (method === "PUT") db.favorites.push({ uid: user.uid, business_id: id, created: Date.now(), seen_at: Date.now() });
      save();
      return null;
    }
    if (path === "/api/my/businesses") {
      return db.businesses.filter((b) => b.owner === user.uid)
        .map((b) => ({ ...pub(b), stats: { views: b.views, whatsapp_clicks: b.clicks,
          saves: db.favorites.filter((f) => f.business_id === b.id).length } }));
    }
    if ((m = /^\/api\/businesses\/(\d+)\/lead$/.exec(path))) {
      const b = db.businesses.find((x) => x.id === Number(m[1])) || fail(404, "העסק לא נמצא");
      if (b.owner !== user.uid) { b.clicks++; save(); }
      return null;
    }
    if ((m = /^\/api\/businesses\/(\d+)\/photos\/(\d+)\/main$/.exec(path))) {
      const b = owned(Number(m[1]), user);
      const p = b.photos.find((x) => x.id === Number(m[2])) || fail(404, "התמונה לא נמצאה");
      b.photos = [p, ...b.photos.filter((x) => x !== p)];
      save();
      return pub(b).photos;
    }
    if ((m = /^\/api\/businesses\/(\d+)\/photos(?:\/(\d+))?$/.exec(path))) {
      const b = owned(Number(m[1]), user);
      if (method === "POST") {
        const files = body.getAll("photos");
        if (b.photos.length + files.length > 12) fail(422, "אפשר עד 12 תמונות לעסק");
        b.photos.push(...(await storePhotos(files)));
        b.photos_updated_at = Date.now();
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
        if (b.owner !== user.uid) b.views++;
        const fav = db.favorites.find((f) => f.uid === user.uid && f.business_id === id);
        if (fav) fav.seen_at = Date.now();
        save();
        const lat = q.get("lat"), lng = q.get("lng");
        return pub(b, lat ? distanceKm(Number(lat), Number(lng), b.lat, b.lng) : null);
      }
      const b = owned(id, user);
      if (method === "DELETE") {
        db.businesses = db.businesses.filter((x) => x !== b);
        db.favorites = db.favorites.filter((f) => f.business_id !== b.id);
        save();
        return null;
      }
      const u = JSON.parse(body);
      if (u.phone != null) u.phone = normPhone(u.phone) || fail(422, "מספר טלפון לא תקין");
      if (u.price_min != null) checkPrices(u.price_min, u.price_max);
      if (u.hours != null) u.hours = checkHours(u.hours);
      if (u.instagram != null) u.instagram = insta(u.instagram);
      const moved = ["city", "street", "house_number"].some((k) => u[k] != null && u[k] !== (b[k] || ""));
      if (moved && u.lat == null) [u.lat, u.lng] = locate(u.city ?? b.city, u.street ?? b.street, u.house_number ?? b.house_number);
      for (const k of ["street", "house_number", "apartment", "entrance"]) if (u[k] != null) b[k] = u[k];
      if (["street", "house_number", "apartment", "entrance"].some((k) => u[k] != null)) {
        u.address = addressLine(b.street || "", b.house_number || "", b.apartment || "", b.entrance || "");
      }
      for (const k of ["name", "phone", "city", "address", "description", "services", "price_min", "price_max", "hours", "lat", "lng", "instagram"]) {
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
      if (data && data.__blob) return new Response(data.__blob, { status: 200 });
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

})();
