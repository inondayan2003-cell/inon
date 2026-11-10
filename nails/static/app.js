"use strict";

/* ================= helpers ================= */

const $ = (sel, root = document) => root.querySelector(sel);

// Images shipped with the app (the preview build swaps in embedded copies).
const asset = (name) => (window.NAILS_ASSETS || {})[name] || name;
const LOGO = () => `<img src="${asset("icon-192.png")}" alt="">`;

// Screen navigation lives in the URL hash ("#/b/12"). The preview build provides its own router.
const nav = window.NAILS_NAV || {
  get hash() { return location.hash; },
  go(h) { location.hash = h; },          // new history entry
  replace(h) { location.replace(h); },    // no history entry, triggers routing
  silent(h) { history.replaceState(null, "", h); },  // change address only
  listen(fn) { window.addEventListener("hashchange", fn); },
};
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
  chevron: '<svg viewBox="0 0 24 24"><path d="m15 6-6 6 6 6"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  camera: '<svg viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>',
  store: '<svg viewBox="0 0 24 24"><path d="M4 9h16l-1-5H5zM5 9v11h14V9M9 20v-6h6v6"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  user: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
  logout: '<svg viewBox="0 0 24 24"><path d="M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10"/></svg>',
  gear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/></svg>',
  mail: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
  doc: '<svg viewBox="0 0 24 24"><path d="M14 3H6v18h12V7z"/><path d="M14 3v4h4M9 12h6M9 16h6"/></svg>',
  lock: '<svg viewBox="0 0 24 24"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
  access: '<svg viewBox="0 0 24 24"><circle cx="12" cy="4.5" r="1.8"/><path d="M5 8.5 12 10l7-1.5M12 10v4.5l-3.5 6.5M12 14.5l3.5 6.5"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6"/></svg>',
  alert: '<svg viewBox="0 0 24 24"><path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17v.5"/></svg>',
  flag: '<svg viewBox="0 0 24 24"><path d="M5 21V4M5 4h11l-2 4 2 4H5"/></svg>',
  shield: '<svg viewBox="0 0 24 24"><path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
  share: '<svg viewBox="0 0 24 24"><circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="m8.2 10.8 7.6-4.5M8.2 13.2l7.6 4.5"/></svg>',
  link: '<svg viewBox="0 0 24 24"><path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1 1"/><path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1-1"/></svg>',
  instagram: '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.2" cy="6.8" r=".6" fill="currentColor"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/></svg>',
  download: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
  eye: '<svg viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  whatsapp: '<svg viewBox="0 0 24 24"><path d="M4 20l1.3-4A8 8 0 1 1 8 18.7z"/><path d="M9 9.5c0 3 2.5 5.5 5.5 5.5l1-1.5-2-1-1 .8a4 4 0 0 1-1.8-1.8l.8-1-1-2z"/></svg>',
  google: '<svg viewBox="0 0 24 24" class="brand"><path fill="#4285F4" stroke="none" d="M22.6 12.2c0-.8-.1-1.5-.2-2.2H12v4.2h6a5 5 0 0 1-2.2 3.3v2.7h3.5c2-1.9 3.3-4.7 3.3-8z"/><path fill="#34A853" stroke="none" d="M12 23c3 0 5.5-1 7.3-2.7l-3.5-2.7c-1 .7-2.3 1.1-3.8 1.1-2.9 0-5.4-2-6.3-4.7H2.1v2.8A11 11 0 0 0 12 23z"/><path fill="#FBBC05" stroke="none" d="M5.7 14a6.6 6.6 0 0 1 0-4.2V7H2.1a11 11 0 0 0 0 9.8z"/><path fill="#EA4335" stroke="none" d="M12 5.4c1.6 0 3.1.6 4.2 1.7l3.1-3.1A11 11 0 0 0 2.1 7l3.6 2.8C6.6 7.3 9.1 5.4 12 5.4z"/></svg>',
  apple: '<svg viewBox="0 0 24 24" class="brand"><path fill="currentColor" stroke="none" d="M16.4 12.6c0-2.6 2.1-3.8 2.2-3.9a4.8 4.8 0 0 0-3.8-2c-1.6-.2-3.1.9-3.9.9-.8 0-2-.9-3.4-.9a5 5 0 0 0-4.2 2.6c-1.8 3.1-.5 7.7 1.3 10.2.8 1.2 1.8 2.6 3.1 2.6 1.3-.1 1.7-.8 3.3-.8 1.5 0 1.9.8 3.3.8 1.4 0 2.2-1.2 3-2.5a10 10 0 0 0 1.4-2.8 4.3 4.3 0 0 1-2.3-4.2zM13.9 5c.7-.8 1.2-2 1-3.1-1 0-2.2.7-2.9 1.5-.6.7-1.2 1.9-1 3 1.1.1 2.2-.6 2.9-1.4z"/></svg>',
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
const DAYS = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"];  // 0 = Sunday
const DEFAULT_HOURS = {
  0: ["09:00", "19:00"], 1: ["09:00", "19:00"], 2: ["09:00", "19:00"],
  3: ["09:00", "19:00"], 4: ["09:00", "19:00"], 5: ["09:00", "14:00"],
};

const priceText = (b) => (b.price_min ? (b.price_min === b.price_max
  ? `${b.price_min} ₪` : `<span dir="ltr">${b.price_min}–${b.price_max}</span> ₪`) : "");

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
  toastTimer = setTimeout(() => el.classList.remove("show"), 2800);
}

/* ================= sign-in (Firebase, or fake accounts in local dev) ================= */

const FIREBASE_SDK = "https://www.gstatic.com/firebasejs/10.12.2";

class AuthError extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

const AUTH_MESSAGES = {
  "auth/email-already-in-use": ["exists", "כבר יש חשבון עם המייל הזה"],
  "auth/invalid-email": ["bad", "כתובת המייל לא תקינה"],
  "auth/weak-password": ["bad", "הסיסמה חלשה מדי (לפחות 6 תווים)"],
  "auth/invalid-credential": ["bad", "המייל או הסיסמה לא נכונים"],
  "auth/wrong-password": ["bad", "המייל או הסיסמה לא נכונים"],
  "auth/user-not-found": ["bad", "לא מצאנו חשבון עם המייל הזה"],
  "auth/invalid-phone-number": ["bad", "מספר הטלפון לא תקין"],
  "auth/invalid-verification-code": ["bad", "הקוד לא נכון"],
  "auth/code-expired": ["bad", "הקוד פג תוקף, שלחי קוד חדש"],
  "auth/too-many-requests": ["bad", "יותר מדי ניסיונות. נסי שוב בעוד כמה דקות"],
  "auth/popup-closed-by-user": ["cancel", ""],
  "auth/cancelled-popup-request": ["cancel", ""],
  "auth/network-request-failed": ["bad", "אין חיבור לאינטרנט"],
  "auth/operation-not-allowed": ["bad", "שיטת ההתחברות הזאת עוד לא הופעלה"],
  "auth/requires-recent-login": ["relogin", "מטעמי אבטחה צריך להתחבר מחדש, ואז לנסות שוב"],
};

function authError(e) {
  if (e instanceof AuthError) return e;
  const [code, msg] = AUTH_MESSAGES[e?.code] || ["bad", "ההתחברות נכשלה, נסי שוב"];
  return new AuthError(code, msg);
}

const toE164 = (phone) => {
  const d = phone.replace(/[^\d+]/g, "");
  if (d.startsWith("+")) return d;
  if (d.startsWith("972")) return "+" + d;
  if (d.startsWith("0")) return "+972" + d.slice(1);
  return d;
};

function firebaseAuth(cfg) {
  let F, auth, listener;
  const ready = (async () => {
    const appMod = await import(`${FIREBASE_SDK}/firebase-app.js`);
    F = await import(`${FIREBASE_SDK}/firebase-auth.js`);
    auth = F.getAuth(appMod.initializeApp(cfg));
    auth.languageCode = "he";
    await F.getRedirectResult(auth).catch(() => null);
    F.onAuthStateChanged(auth, (u) => listener?.(u && {
      uid: u.uid, name: u.displayName, email: u.email, phone: u.phoneNumber,
    }));
  })();

  const popup = async (provider) => {
    try {
      await F.signInWithPopup(auth, provider);
    } catch (e) {
      if (e?.code === "auth/popup-blocked" || e?.code === "auth/operation-not-supported-in-this-environment") {
        return F.signInWithRedirect(auth, provider);
      }
      throw authError(e);
    }
  };
  const wrap = (fn) => async (...a) => { await ready; try { return await fn(...a); } catch (e) { throw authError(e); } };

  let recaptcha;
  return {
    ready,
    onChange(cb) { listener = cb; },
    async token() { await ready; return auth.currentUser ? auth.currentUser.getIdToken() : null; },
    google: async () => { await ready; return popup(new F.GoogleAuthProvider()); },
    apple: async () => {
      await ready;
      const p = new F.OAuthProvider("apple.com");
      p.addScope("email"); p.addScope("name"); p.setCustomParameters({ locale: "he" });
      return popup(p);
    },
    emailSignUp: wrap((email, pw) => F.createUserWithEmailAndPassword(auth, email, pw)),
    emailSignIn: wrap((email, pw) => F.signInWithEmailAndPassword(auth, email, pw)),
    resetPassword: wrap((email) => F.sendPasswordResetEmail(auth, email)),
    phoneStart: wrap(async (phone, buttonId) => {
      recaptcha?.clear?.();
      recaptcha = new F.RecaptchaVerifier(auth, buttonId, { size: "invisible" });
      const confirmation = await F.signInWithPhoneNumber(auth, toE164(phone), recaptcha);
      return { confirm: wrap((code) => confirmation.confirm(code)) };
    }),
    signOut: wrap(() => F.signOut(auth)),
    changePassword: wrap((pw) => F.updatePassword(auth.currentUser, pw)),
    deleteAccount: wrap(() => auth.currentUser.delete()),
  };
}

// Local development without Firebase: fake accounts kept in this browser only.
function devAuth() {
  let listener;
  const accounts = () => store.get("nails.dev.accounts", {});
  const emit = () => listener?.(store.get("nails.dev.session", null));
  const login = (uid, contact, name = null) => {
    const isEmail = contact.includes("@");
    store.set("nails.dev.session", { uid, contact, name, email: isEmail ? contact : null, phone: isEmail ? null : contact });
    emit();
  };
  const emailUid = (email) => `email-${email.toLowerCase().replace(/[^a-z0-9]/g, "")}`;
  return {
    ready: Promise.resolve(),
    onChange(cb) { listener = cb; setTimeout(emit); },
    async token() {
      const s = store.get("nails.dev.session", null);
      return s && `dev:${s.uid}:${s.contact}`;
    },
    async google() { login("google-demo", "demo@gmail.com", "Demo Google"); },
    async apple() { login("apple-demo", "demo@icloud.com"); },
    async emailSignUp(email, pw) {
      if (!/^\S+@\S+\.\S+$/.test(email)) throw new AuthError("bad", "כתובת המייל לא תקינה");
      if (pw.length < 6) throw new AuthError("bad", "הסיסמה חלשה מדי (לפחות 6 תווים)");
      const a = accounts();
      if (a[email]) throw new AuthError("exists", "כבר יש חשבון עם המייל הזה");
      store.set("nails.dev.accounts", { ...a, [email]: pw });
      login(emailUid(email), email);
    },
    async emailSignIn(email, pw) {
      if (accounts()[email] !== pw) throw new AuthError("bad", "המייל או הסיסמה לא נכונים");
      login(emailUid(email), email);
    },
    async resetPassword() {},
    async phoneStart(phone) {
      const e164 = toE164(phone);
      if (!/^\+\d{10,13}$/.test(e164)) throw new AuthError("bad", "מספר הטלפון לא תקין");
      return {
        async confirm(code) {
          if (code !== "123456") throw new AuthError("bad", "הקוד לא נכון (בפיתוח: 123456)");
          login(`phone-${e164.slice(1)}`, e164);
        },
      };
    },
    async signOut() { store.set("nails.dev.session", null); emit(); },
    async changePassword(pw) {
      if (pw.length < 6) throw new AuthError("bad", "הסיסמה חלשה מדי (לפחות 6 תווים)");
      const s = store.get("nails.dev.session", null);
      store.set("nails.dev.accounts", { ...accounts(), [s.contact]: pw });
    },
    async deleteAccount() {
      const s = store.get("nails.dev.session", null);
      const a = accounts();
      delete a[s?.contact];
      store.set("nails.dev.accounts", a);
      store.set("nails.dev.session", null);
      emit();
    },
  };
}

let Auth = null;
const session = { user: null, profile: null, mode: "firebase", methods: ["google", "email"], preview: false, config: {} };  // user = signed in, profile = registered

/* ================= API ================= */

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const token = Auth && (await Auth.token());
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && Auth) {
    await Auth.signOut().catch(() => {});
  }
  if (res.status === 403 && data.detail === "not_registered") {
    session.profile = null;
    nav.go("#/welcome");
  }
  if (!res.ok) {
    const d = data.detail;
    const msg = res.status === 401 ? "צריך להתחבר מחדש"
      : typeof d === "string" ? d : Array.isArray(d) ? "יש שדה שלא מולא נכון" : "משהו השתבש, נסי שוב";
    const err = new Error(msg);
    err.status = res.status;
    throw err;
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

/* ================= opening hours ================= */

function israelNow() {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Jerusalem", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date()).map((p) => [p.type, p.value]));
  const day = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].indexOf(parts.weekday);
  return { day, time: `${parts.hour}:${parts.minute}` };
}

function openStatus(b) {
  const { day, time } = israelNow();
  const today = b.hours[day];
  if (b.open_now && today) return { open: true, text: `פתוח עכשיו · עד ${today[1]}` };
  if (today && time < today[0]) return { open: false, text: `סגור · נפתח היום ב-${today[0]}` };
  for (let i = 1; i <= 7; i++) {
    const d = (day + i) % 7;
    if (b.hours[d]) return { open: false, text: `סגור · נפתח ${i === 1 ? "מחר" : `ביום ${DAYS[d]}`} ב-${b.hours[d][0]}` };
  }
  return { open: false, text: "סגור" };
}

// Half-hour steps, 24h clock: "00:00" ... "23:30" (+ any saved value that isn't on the grid).
const TIMES = Array.from({ length: 48 }, (_, i) => `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`);
function timeOptions(selected) {
  const list = TIMES.includes(selected) ? TIMES : [...TIMES, selected].sort();
  return list.map((t) => `<option value="${t}" ${t === selected ? "selected" : ""}>${t}</option>`).join("");
}

function hoursEditor(hours = DEFAULT_HOURS) {
  return `<div class="hours">${DAYS.map((name, d) => {
    const span = hours[d];
    return `<div class="hours-row ${span ? "" : "closed"}" data-day="${d}">
      <label class="day-toggle"><input type="checkbox" ${span ? "checked" : ""}><span class="switch"></span><b>${name}</b></label>
      <div class="times">
        <select class="t-open" aria-label="שעת פתיחה ביום ${name}">${timeOptions(span ? span[0] : "09:00")}</select>
        <span>–</span>
        <select class="t-close" aria-label="שעת סגירה ביום ${name}">${timeOptions(span ? span[1] : "19:00")}</select>
      </div>
      <span class="closed-label">סגור</span>
    </div>`;
  }).join("")}</div>`;
}

function bindHoursEditor(root) {
  root.querySelectorAll(".hours-row").forEach((row) => {
    row.querySelector(".day-toggle input").addEventListener("change", (e) => {
      row.classList.toggle("closed", !e.target.checked);
    });
  });
}

function readHours(root) {
  const out = {};
  for (const row of root.querySelectorAll(".hours-row")) {
    if (!row.querySelector(".day-toggle input").checked) continue;
    const open = row.querySelector(".t-open").value;
    const close = row.querySelector(".t-close").value;
    const day = DAYS[Number(row.dataset.day)];
    if (!open || !close) return { error: `צריך למלא שעות ליום ${day}` };
    if (open >= close) return { error: `ביום ${day} שעת הסגירה צריכה להיות אחרי הפתיחה` };
    out[row.dataset.day] = [open, close];
  }
  if (!Object.keys(out).length) return { error: "צריך לבחור לפחות יום פעילות אחד" };
  return { hours: out };
}

function hoursTable(hours) {
  const { day } = israelNow();
  return `<table class="hours-table">${DAYS.map((name, d) => `
    <tr class="${d === day ? "today" : ""}"><td>${name}</td>
    <td>${hours[d] ? `<span dir="ltr">${hours[d][0]}–${hours[d][1]}</span>` : '<span class="muted">סגור</span>'}</td></tr>`).join("")}
  </table>`;
}

/* ================= state ================= */

const state = {
  loc: store.get("nails.loc", null),          // {lat, lng, label}
  radius: store.get("nails.radius", 10),
  q: "",
};
// Saved businesses live in the account (server); this is the local copy for the hearts.
const savedIds = new Set();
const isFav = (id) => savedIds.has(id);
function toggleFav(id) {
  const on = !savedIds.has(id);
  if (on) savedIds.add(id); else savedIds.delete(id);
  api(`/api/favorites/${id}`, { method: on ? "PUT" : "DELETE" }).catch((err) => {
    if (on) savedIds.delete(id); else savedIds.add(id);   // undo
    document.querySelectorAll(`[data-fav="${id}"]`).forEach((b) => b.classList.toggle("on", !on));
    toast(err.message);
  });
  return on;
}

function setFavoritesDot(on) {
  document.querySelector('.tabbar [data-tab="favorites"]')?.classList.toggle("has-new", on);
}

async function loadFavorites() {
  savedIds.clear();
  try {
    (await api("/api/favorites/ids")).forEach((id) => savedIds.add(id));
    // Hearts saved on this phone before favorites moved to the account.
    const local = store.get("nails.favs", []).filter((id) => !savedIds.has(id));
    for (const id of local) {
      try { await api(`/api/favorites/${id}`, { method: "PUT" }); savedIds.add(id); } catch { /* deleted business */ }
    }
    store.set("nails.favs", []);
    if (savedIds.size) setFavoritesDot((await api("/api/favorites")).some((b) => b.new_photos));
  } catch { /* offline: hearts start empty */ }
}

/* ================= shared UI ================= */

function card(b, i = 0) {
  const cover = b.photos[0]?.url;
  const dist = b.distance_km != null ? `${b.distance_km} ק"מ` : "";
  return `
    <a class="card" href="#/b/${b.id}" style="--i:${i}">
      <div class="media">
        ${cover ? `<img src="${esc(cover)}" alt="עבודת ציפורניים של ${esc(b.name)}" loading="lazy">` : ""}
        ${dist ? `<span class="badge">${ICON.pin}${dist}</span>` : ""}
        <button class="heart ${isFav(b.id) ? "on" : ""}" data-fav="${b.id}" aria-label="מועדפים">${ICON.heart}</button>
        ${b.new_photos ? '<span class="new-badge">תמונות חדשות</span>' : ""}
        <span class="count-badge">${b.photos.length} תמונות</span>
      </div>
      <div class="body">
        <h4>${esc(b.name)}${verifiedBadge(b.verified)}</h4>
        ${priceText(b) ? `<div class="price">${priceText(b)}</div>` : ""}
        <div class="meta">${ICON.pin}<span>${esc(b.city)}</span></div>
        <div class="open-dot ${b.open_now ? "on" : ""}">${b.open_now ? "פתוח עכשיו" : "סגור עכשיו"}</div>
        <div class="tags">${b.services.slice(0, 2).map((s) => `<span class="tag">${esc(serviceLabel(s))}</span>`).join("")}</div>
      </div>
    </a>`;
}

function pop(el, on) {
  el.classList.remove("pop");
  if (!on) return;
  void el.offsetWidth;
  el.classList.add("pop");
}

function bindFavButtons(root) {
  root.querySelectorAll("[data-fav]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const on = toggleFav(Number(btn.dataset.fav));
      btn.classList.toggle("on", on);
      pop(btn, on);
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

const initials = (name) => (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
const verifiedBadge = (on, big = false) => (on
  ? `<span class="verified ${big ? "big" : ""}" role="img" title="בעלת עסק מאומתת" aria-label="עסק מאומת">${ICON.check}</span>` : "");
const avatarInner = (p) => (p?.avatar_url ? `<img src="${esc(p.avatar_url)}" alt="">` : esc(initials(p?.name)));
// Terms & privacy consent, shown when the account is created.
const consentBox = (id, checked = false) => `<label class="consent">
  <input type="checkbox" id="${id}" ${checked ? "checked" : ""}>
  <span>קראתי ואני מסכימה ל<a href="#/terms">תנאי השימוש</a> ול<a href="#/privacy">מדיניות הפרטיות</a></span>
</label>`;
const cityOptions = () => `<datalist id="cities">${CITIES.map(([c]) => `<option value="${esc(c)}">`).join("")}</datalist>`;

/* ================= sign-up / sign-in screens ================= */

function renderAuth(mode, prefill = {}) {
  const signup = mode === "signup";
  const has = (m) => session.methods.includes(m);
  const verb = signup ? "הרשמה" : "התחברות";
  view.innerHTML = `
    <div class="auth">
      <div class="auth-hero">
        <div class="logo big">${LOGO()}</div>
        <h1>${signup ? "ברוכה הבאה ל-Nails" : "שמחים לראות אותך שוב"}</h1>
        <p>${signup ? "הרשמי כדי למצוא מניקוריסטיות קרובות אלייך" : "התחברי לחשבון שלך"}</p>
      </div>
      ${session.preview
        ? '<p class="dev-note">תצוגה מקדימה: הכניסה כאן לדוגמה בלבד, והכל נשמר רק בטלפון שלך</p>'
        : session.mode === "dev" ? `<p class="dev-note">מצב פיתוח: חשבונות לדוגמה בלבד${has("phone") ? ". קוד לדוגמה בהודעה: 123456" : ""}</p>` : ""}
      ${prefill.notice ? `<div class="notice">${esc(prefill.notice)}</div>` : ""}

      ${signup ? consentBox("consent", session.termsAccepted) : ""}

      <div class="auth-buttons">
        ${has("google") ? `<button class="btn social" id="google">${ICON.google}<span>${verb} עם גוגל</span></button>` : ""}
        ${has("apple") ? `<button class="btn social apple" id="apple">${ICON.apple}<span>${verb} עם אפל</span></button>` : ""}
        ${has("phone") ? `<button class="btn social" id="phone-btn">${ICON.phone}<span>${verb} עם מספר טלפון</span></button>` : ""}
      </div>

      ${has("email") ? `${session.methods.length > 1 ? '<div class="divider"><span>או עם אימייל</span></div>' : ""}

      <form id="email-form" novalidate>
        <label class="field"><span>אימייל</span>
          <input type="email" name="email" required autocomplete="email" inputmode="email" dir="ltr" value="${esc(prefill.email)}"></label>
        <label class="field"><span>סיסמה${signup ? " (לפחות 6 תווים)" : ""}</span>
          <input type="password" name="password" required minlength="6" autocomplete="${signup ? "new-password" : "current-password"}" dir="ltr"></label>
        ${signup ? "" : '<button type="button" class="link" id="forgot">שכחתי סיסמה</button>'}
        <p class="error hidden" id="auth-err"></p>
        <button class="btn block" id="email-submit">${verb}</button>
      </form>` : '<p class="error hidden" id="auth-err"></p>'}

      <p class="switch-mode">${signup
        ? 'כבר יש לך חשבון? <a href="#/login">להתחברות</a>'
        : 'עוד אין לך חשבון? <a href="#/signup">להרשמה</a>'}</p>
      <p class="legal-links"><a href="#/terms">תנאי שימוש</a> · <a href="#/privacy">פרטיות</a> · <a href="#/cookies">עוגיות</a> · <a href="#/accessibility">נגישות</a></p>
    </div>`;

  const err = $("#auth-err");
  const showErr = (m) => { err.textContent = m; err.classList.remove("hidden"); };
  const busy = async (btn, fn) => {
    btn.disabled = true;
    err.classList.add("hidden");
    try { await fn(); } catch (e) {
      const ae = authError(e);
      if (ae.code !== "cancel") showErr(ae.message);
    } finally { btn.disabled = false; }
  };

  // Sign-up needs the terms checkbox first (sign-in doesn't).
  const consentOk = () => {
    if (!signup) return true;
    session.termsAccepted = $("#consent").checked;
    if (session.termsAccepted) return true;
    showErr("כדי להירשם צריך לסמן שקראת ואת מסכימה לתנאי השימוש ולמדיניות הפרטיות");
    $("#consent").closest(".consent").classList.add("shake");
    setTimeout(() => $(".consent")?.classList.remove("shake"), 500);
    return false;
  };
  $("#consent")?.addEventListener("change", (e) => { session.termsAccepted = e.target.checked; err.classList.add("hidden"); });
  $("#google")?.addEventListener("click", (e) => { if (consentOk()) busy(e.currentTarget, () => Auth.google()); });
  $("#apple")?.addEventListener("click", (e) => { if (consentOk()) busy(e.currentTarget, () => Auth.apple()); });
  $("#phone-btn")?.addEventListener("click", () => { if (consentOk()) nav.go(`#/phone?from=${mode}`); });

  $("#email-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const email = String(fd.get("email")).trim();
    const pw = String(fd.get("password"));
    if (!email || !pw) return showErr("צריך למלא אימייל וסיסמה");
    if (!consentOk()) return;
    busy($("#email-submit"), async () => {
      if (!signup) return Auth.emailSignIn(email, pw);
      try {
        await Auth.emailSignUp(email, pw);
      } catch (ex) {
        const ae = authError(ex);
        if (ae.code === "exists") {
          // Already registered -> send her to the sign-in page with the email filled in.
          nav.silent("#/login");
          renderAuth("login", { email, notice: "כבר יש לך חשבון עם המייל הזה. התחברי עם הסיסמה שלך." });
          return;
        }
        throw ae;
      }
    });
  });

  $("#forgot")?.addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const email = String($("#email-form").email.value).trim();
    if (!email) throw new AuthError("bad", "כתבי את המייל שלך ואז לחצי שוב");
    await Auth.resetPassword(email);
    toast("שלחנו לך מייל לאיפוס סיסמה");
  }));
}

function renderPhone(from) {
  view.innerHTML = `
    <div class="auth">
      ${pageTitle("כניסה עם מספר טלפון", `#/${from === "login" ? "login" : "signup"}`)}
      <form id="phone-form" novalidate>
        <label class="field"><span>מספר טלפון</span>
          <input type="tel" name="phone" required inputmode="tel" autocomplete="tel" placeholder="050-0000000" dir="ltr"></label>
        <p class="note" style="text-align:start">נשלח אלייך קוד בהודעה</p>
        <button class="btn block" id="send-code">שליחת קוד</button>
      </form>
      <form id="code-form" class="hidden" novalidate>
        <label class="field"><span>הקוד שקיבלת בהודעה</span>
          <input type="text" name="code" required inputmode="numeric" autocomplete="one-time-code" maxlength="6" dir="ltr" class="code-input"></label>
        <button class="btn block">אישור</button>
        <button type="button" class="link" id="resend">לא קיבלתי קוד, שלחי שוב</button>
      </form>
      <p class="error hidden" id="auth-err"></p>
    </div>`;
  const err = $("#auth-err");
  const showErr = (m) => { err.textContent = m; err.classList.remove("hidden"); };
  let pending = null;

  $("#phone-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const phone = String(e.target.phone.value).trim();
    if (!phone) return showErr("צריך למלא מספר טלפון");
    err.classList.add("hidden");
    $("#send-code").disabled = true;
    try {
      pending = await Auth.phoneStart(phone, "send-code");
      $("#phone-form").classList.add("hidden");
      $("#code-form").classList.remove("hidden");
      $("#code-form").code.focus();
      toast("הקוד נשלח");
    } catch (ex) { showErr(authError(ex).message); }
    $("#send-code").disabled = false;
  });
  $("#resend").addEventListener("click", () => {
    $("#code-form").classList.add("hidden");
    $("#phone-form").classList.remove("hidden");
  });
  $("#code-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const code = String(e.target.code.value).trim();
    if (code.length < 6) return showErr("הקוד הוא 6 ספרות");
    try { await pending.confirm(code); } catch (ex) { showErr(authError(ex).message); }
  });
}

function renderWelcome() {
  view.innerHTML = `
    <div class="auth">
      <div class="auth-hero">
        <div class="logo big">${LOGO()}</div>
        <h1>עוד רגע מסיימים</h1>
        <p>איך קוראים לך?</p>
      </div>
      <form id="name-form" novalidate>
        <label class="field"><span>שם מלא</span>
          <input type="text" name="name" required minlength="2" maxlength="60" autocomplete="name" value="${esc(session.user?.name)}"></label>
        <label class="field"><span>עיר מגורים (לא חובה)</span>
          <input type="text" name="city" maxlength="40" list="cities" autocomplete="address-level2"></label>
        ${cityOptions()}
        ${consentBox("w-consent", session.termsAccepted)}
        <p class="error hidden" id="auth-err"></p>
        <button class="btn block">סיום הרשמה</button>
      </form>
      <button class="link" id="other-account" style="margin-top:16px">התחברות עם חשבון אחר</button>
    </div>`;
  $("#name-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = String(e.target.name.value).trim();
    const city = String(e.target.city.value).trim();
    const err = $("#auth-err");
    if (name.length < 2) { err.textContent = "צריך לכתוב שם"; err.classList.remove("hidden"); return; }
    if (!$("#w-consent").checked) {
      err.textContent = "צריך לסמן שקראת ואת מסכימה לתנאי השימוש ולמדיניות הפרטיות";
      err.classList.remove("hidden");
      return;
    }
    try {
      session.profile = await api("/api/me", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, city, accepted_terms: true }),
      });
      loadFavorites();
      toast(`ברוכה הבאה, ${name.split(" ")[0]}! 💅`);
      nav.go(takeReturn() || "#/");
    } catch (ex) { err.textContent = ex.message; err.classList.remove("hidden"); }
  });
  $("#other-account").addEventListener("click", () => Auth.signOut());
}

/* ================= home ================= */

/* ================= install as an app ================= */

let installEvent = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();            // show our own banner instead
  installEvent = e;
  if (nav.hash === "" || nav.hash === "#/") showInstallBanner();
});

const isStandalone = () => window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) && !/crios|fxios/i.test(navigator.userAgent);

function showInstallBanner() {
  const slot = $("#install-slot");
  if (!slot || session.preview || isStandalone()) return;
  if (Date.now() - store.get("nails.install.dismissed", 0) < 14 * 864e5) return;
  const ios = isIOS();
  if (!installEvent && !ios) return;   // this browser can't install
  slot.innerHTML = `<div class="install-banner">
      <div class="logo">${LOGO()}</div>
      <div class="grow"><b>הוסיפי את Nails למסך הבית</b>
        <small>${ios ? 'בספארי: לחצי על כפתור השיתוף <span class="ios-share">⬆︎</span> ואז "הוספה למסך הבית"'
          : "נפתחת כמו אפליקציה, בלחיצה אחת"}</small></div>
      ${ios ? "" : `<button class="btn small" id="install-btn">${ICON.download} התקנה</button>`}
      <button class="install-x" id="install-x" aria-label="לא עכשיו">${ICON.close}</button>
    </div>`;
  $("#install-x").addEventListener("click", () => { store.set("nails.install.dismissed", Date.now()); slot.innerHTML = ""; });
  $("#install-btn")?.addEventListener("click", async () => {
    installEvent.prompt();
    const { outcome } = await installEvent.userChoice;
    installEvent = null;
    slot.innerHTML = "";
    if (outcome === "accepted") toast("Nails נוספה למסך הבית 💅");
  });
}

function renderHome() {
  // No location yet: start from the city in her profile.
  const home = CITIES.find(([c]) => c === session.profile?.city);
  if (!state.loc && home) {
    state.loc = { lat: home[1], lng: home[2], label: home[0] };
    store.set("nails.loc", state.loc);
  }
  const loc = state.loc;
  const first = (session.profile?.name || "").split(" ")[0];
  view.innerHTML = `
    <div class="top">
      <a class="avatar" href="#/profile" aria-label="פרופיל">${avatarInner(session.profile)}</a>
      <div><h1>שלום, ${esc(first)}</h1><p>איפה עושים ציפורניים היום?</p></div>
      <div class="spacer"></div>
      <a class="icon-btn" href="#/favorites" aria-label="מועדפים">${ICON.heart}</a>
    </div>

    <div id="install-slot"></div>

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

    <div class="hero" role="img" aria-label="ציפורניים בגוון ניוד עם פרחים חומים"
      ${window.NAILS_ASSETS ? `style="--hero-img:url('${asset("hero.jpg")}')"` : ""}>
      <small>Nails</small>
      <h2>הציפורניים שחיפשת, ממש קרוב</h2>
      <p>רואים עבודות אמיתיות וקובעים בוואטסאפ</p>
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
  if (!state.loc) tryAutoLocate();
  loadResults();
  showInstallBanner();
}

async function tryAutoLocate() {
  try {
    const p = await getPosition();
    state.loc = { ...p, label: "המיקום שלי" };
    store.set("nails.loc", state.loc);
    if (nav.hash === "" || nav.hash === "#/") renderHome();
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
  if (state.q.trim()) params.set("q", state.q.trim());
  const box = $("#results");
  try {
    const list = await api(`/api/businesses?${params}`);
    if (seq !== loadSeq || !box.isConnected) return;
    $("#results-title").textContent = state.loc ? `עד ${state.radius} ק"מ ממך` : "עסקים חדשים";
    $("#results-count").textContent = list.length ? `${list.length} עסקים` : "";
    if (!list.length) {
      box.className = "";
      box.innerHTML = empty(ICON.search, "לא מצאנו עסקים באזור",
        "נסי להגדיל את הרדיוס או לחפש בעיר אחרת.");
      return;
    }
    box.className = "grid";
    box.innerHTML = list.map(card).join("");
    bindFavButtons(box);
  } catch (err) {
    if (box.isConnected) { box.className = ""; box.innerHTML = `<p class="error">${esc(err.message)}</p>`; }
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
      renderHome();
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
    renderHome();
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
  const status = openStatus(b);
  view.innerHTML = `
    <div class="page-title" style="justify-content:space-between">
      <a class="back" href="#/" aria-label="חזרה">${ICON.back}</a>
      <div class="top-actions">
        <button class="icon-btn" id="share" aria-label="שיתוף העסק">${ICON.share}</button>
        <button class="icon-btn" id="fav" aria-label="מועדפים">${ICON.heart}</button>
      </div>
    </div>
    <div class="gallery" id="gallery" tabindex="0" role="region" aria-label="תמונות של העבודות, אפשר לגלול לצדדים">${b.photos.map((p) => `<img src="${esc(p.url)}" alt="עבודה של ${esc(b.name)}" loading="lazy">`).join("")}</div>
    ${b.photos.length > 1 ? `<div class="gallery-dots" aria-hidden="true">${b.photos.map((_, i) => `<i class="${i ? "" : "on"}"></i>`).join("")}</div>` : ""}
    <div class="biz-head">
      <h1>${esc(b.name)}${verifiedBadge(b.verified, true)}</h1>
      ${b.verified ? '<p class="verified-note">' + ICON.shield + ' בעלת העסק אומתה על ידי Nails</p>' : ""}
      <div class="meta">
        <span>${ICON.pin}${esc(b.city)}${b.address ? ` · ${esc(b.address)}` : ""}</span>
        ${b.distance_km != null ? `<span>${ICON.target}${b.distance_km} ק"מ ממך</span>` : ""}
      </div>
    </div>
    ${priceText(b) ? `<div class="price-box"><span>טווח מחירים</span><b>${priceText(b)}</b></div>` : ""}

    <details class="hours-box">
      <summary><span class="status ${status.open ? "open" : ""}">${ICON.clock}${status.text}</span><span class="muted">שעות פעילות ▾</span></summary>
      ${hoursTable(b.hours)}
    </details>

    <div class="tags" style="margin-top:12px">${b.services.map((s) => `<span class="tag">${esc(serviceLabel(s))}</span>`).join("")}</div>
    ${b.description ? `<p class="desc">${esc(b.description)}</p>` : ""}

    <div class="actions">
      <a class="btn whatsapp block" id="wa" href="${esc(b.whatsapp_url)}" target="_blank" rel="noopener">${ICON.whatsapp} שליחת הודעה בוואטסאפ</a>
      <div class="row ${b.instagram ? "three" : ""}">
        <a class="btn outline" href="tel:${esc(b.phone)}">${ICON.phone} התקשרות</a>
        <a class="btn outline" href="${waze}" target="_blank" rel="noopener">${ICON.nav} ניווט</a>
        ${b.instagram ? `<a class="btn outline" href="https://instagram.com/${esc(b.instagram)}" target="_blank" rel="noopener">${ICON.instagram} אינסטגרם</a>` : ""}
      </div>
      <p class="note">ההודעה תיפתח עם הטקסט: "היי! הגעתי אלייך דרך אפליקציית Nails 💅"</p>
    </div>`;
  const favBtn = $("#fav");
  const paintFav = (on) => { favBtn.querySelector("svg").style.fill = on ? "currentColor" : "none"; };
  paintFav(isFav(b.id));
  favBtn.addEventListener("click", () => {
    const on = toggleFav(b.id);
    paintFav(on);
    pop(favBtn, on);
    toast(on ? "נשמר במועדפים 💖" : "הוסר מהמועדפים");
  });
  $("#share").addEventListener("click", () => openShare(b));
  const gallery = $("#gallery");
  const dots = [...document.querySelectorAll(".gallery-dots i")];
  if (dots.length) {
    gallery.addEventListener("scroll", () => {
      const imgs = [...gallery.children];
      const mid = gallery.getBoundingClientRect().left + gallery.clientWidth / 2;
      let best = 0, dist = Infinity;
      imgs.forEach((img, i) => {
        const r = img.getBoundingClientRect();
        const d = Math.abs(r.left + r.width / 2 - mid);
        if (d < dist) { dist = d; best = i; }
      });
      dots.forEach((d, i) => d.classList.toggle("on", i === best));
    }, { passive: true });
  }
  $("#wa").addEventListener("click", () => {
    // Count the enquiry; don't block opening WhatsApp.
    api(`/api/businesses/${b.id}/lead`, { method: "POST", keepalive: true }).catch(() => {});
  });
}

/* ================= share ================= */

const businessLink = (id) => `${location.origin}${location.pathname}#/b/${id}`;

function openShare(b) {
  const url = businessLink(b.id);
  const text = `מצאתי את ${b.name} ב-Nails 💅 ${b.city}${priceText(b) ? ` · ${priceText(b).replace(/<[^>]+>/g, "")}` : ""}`;
  const sheet = document.createElement("div");
  sheet.className = "sheet-backdrop";
  sheet.innerHTML = `
    <div class="sheet" role="dialog" aria-label="שיתוף העסק">
      <div class="sheet-grip"></div>
      <h3>שיתוף ${esc(b.name)}</h3>
      <a class="btn whatsapp block" target="_blank" rel="noopener"
        href="https://wa.me/?text=${encodeURIComponent(`${text}\n${url}`)}">${ICON.whatsapp} שליחה בוואטסאפ</a>
      ${navigator.share ? `<button class="btn outline block" data-native>${ICON.share} שיתוף באפליקציה אחרת</button>` : ""}
      <button class="btn outline block" data-copy>${ICON.link} העתקת קישור</button>
      <input class="share-url" value="${esc(url)}" readonly dir="ltr" aria-label="קישור לעסק">
      <button class="link" data-close>סגירה</button>
    </div>`;
  const close = () => sheet.remove();
  sheet.addEventListener("click", async (e) => {
    if (e.target === sheet || e.target.closest("[data-close]")) return close();
    if (e.target.closest("[data-native]")) {
      try { await navigator.share({ title: b.name, text, url }); close(); } catch { /* cancelled */ }
    }
    if (e.target.closest("[data-copy]")) {
      try { await navigator.clipboard.writeText(url); toast("הקישור הועתק ✓"); close(); } catch {
        const input = sheet.querySelector(".share-url");
        input.focus(); input.select();
        toast("סמני את הקישור והעתיקי");
      }
    }
    if (e.target.closest("a.whatsapp")) setTimeout(close, 300);
  });
  document.body.appendChild(sheet);
}

/* ================= favorites ================= */

async function renderFavorites() {
  view.innerHTML = `${pageTitle("המועדפים שלי", "#/")}<div id="fav-list" class="grid">${'<div class="skeleton"></div>'.repeat(2)}</div>`;
  const box = $("#fav-list");
  const none = () => empty(ICON.heart, "אין עדיין עסקים במועדפים",
    "לחצי על הלב כדי לשמור עסקים שאהבת. כשעסק ששמרת יעלה עבודות חדשות, נסמן לך את זה כאן.",
    '<a class="btn" href="#/">חיפוש עסקים</a>');
  const params = state.loc ? `?lat=${state.loc.lat}&lng=${state.loc.lng}` : "";
  let list;
  try { list = await api(`/api/favorites${params}`); } catch (err) {
    box.className = ""; box.innerHTML = `<p class="error">${esc(err.message)}</p>`; return;
  }
  if (!box.isConnected) return;
  savedIds.clear();
  list.forEach((b) => savedIds.add(b.id));
  setFavoritesDot(list.some((b) => b.new_photos));
  if (!list.length) { box.className = ""; box.innerHTML = none(); return; }
  const fresh = list.filter((b) => b.new_photos).length;
  box.insertAdjacentHTML("beforebegin", fresh
    ? `<p class="fav-note">✨ ${fresh === 1 ? "עסק אחד העלה" : `${fresh} עסקים העלו`} תמונות חדשות מאז שביקרת</p>` : "");
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

/* ================= business form (add / edit) ================= */

const MIN_PHOTOS = 5;
const MAX_PHOTOS = 12;


function locationFields(b = {}) {
  return `
    <label class="field"><span>עיר *</span>
      <input type="text" name="city" required minlength="2" maxlength="40" value="${esc(b.city)}" list="cities" autocomplete="address-level2"></label>
    <datalist id="cities">${CITIES.map(([c]) => `<option value="${esc(c)}">`).join("")}</datalist>
    <div class="addr-row">
      <label class="field grow2"><span>רחוב *</span>
        <input type="text" name="street" maxlength="60" value="${esc(b.street)}" placeholder="למשל: הרצל" autocomplete="address-line1"></label>
      <label class="field"><span>מספר *</span>
        <input type="text" name="house_number" maxlength="10" value="${esc(b.house_number)}" inputmode="numeric" placeholder="12"></label>
    </div>
    <div class="addr-row">
      <label class="field"><span>כניסה</span>
        <input type="text" name="entrance" maxlength="10" value="${esc(b.entrance)}" placeholder="לא חובה"></label>
      <label class="field"><span>דירה</span>
        <input type="text" name="apartment" maxlength="10" value="${esc(b.apartment)}" inputmode="numeric" placeholder="לא חובה"></label>
    </div>
    <div class="divider"><span>או</span></div>
    <button type="button" class="btn outline block" id="here">${ICON.target} אני בעסק עכשיו, קחי את המיקום</button>
    <p class="progress" id="loc-status">ניקח את המיקום מהכתובת. אם את בעסק עכשיו, אפשר לקחת אותו מהטלפון ולקבל מיקום מדויק יותר.</p>`;
}

// "I'm at the business now": the phone's location replaces the address lookup.
function bindHere(onPick) {
  const status = $("#loc-status");
  $("#here").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const p = await getPosition();
      onPick(p);
      status.innerHTML = `✓ המיקום נלקח מהטלפון <button type="button" class="link" id="here-undo">ביטול</button>`;
      status.classList.add("ok");
      $("#here-undo").addEventListener("click", () => {
        onPick(null);
        status.textContent = "ניקח את המיקום מהכתובת.";
        status.classList.remove("ok");
      });
    } catch (err) { toast(err.message); }
    btn.disabled = false;
  });
}

function readAddress(fd, picked) {
  const a = {
    city: String(fd.get("city") || "").trim(),
    street: String(fd.get("street") || "").trim(),
    house_number: String(fd.get("house_number") || "").trim(),
    entrance: String(fd.get("entrance") || "").trim(),
    apartment: String(fd.get("apartment") || "").trim(),
  };
  if (a.city.length < 2) return { error: "צריך למלא עיר" };
  if (!picked && (!a.street || !a.house_number)) return { error: "צריך למלא רחוב ומספר בית, או ללחוץ 'אני בעסק עכשיו'" };
  return { address: a };
}

function businessFields(b = {}) {
  const sel = new Set(b.services || []);
  return `
    <label class="field"><span>שם העסק *</span>
      <input type="text" name="name" required minlength="2" maxlength="60" value="${esc(b.name)}" placeholder="למשל: סטודיו ורוד"></label>
    <label class="field"><span>טלפון (וואטסאפ) *</span>
      <input type="tel" name="phone" required inputmode="tel" value="${esc(b.phone)}" placeholder="050-0000000"></label>
    <div class="field"><span class="label-sm">אילו טיפולים את עושה?</span>
      <div class="check-grid">
        ${SERVICES.map((s) => `<label class="chip ${sel.has(s.key) ? "on" : ""}">
          <input type="checkbox" name="services" value="${s.key}" ${sel.has(s.key) ? "checked" : ""}>${esc(s.label)}</label>`).join("")}
      </div>
    </div>
    <div class="field" style="margin-top:12px"><span class="label-sm">טווח מחירים *</span>
      <div class="price-row">
        <label><span>החל מ-</span><input type="number" name="price_min" min="1" max="5000" inputmode="numeric" value="${b.price_min || ""}" placeholder="80"><em>₪</em></label>
        <label><span>עד</span><input type="number" name="price_max" min="1" max="5000" inputmode="numeric" value="${b.price_max || ""}" placeholder="350"><em>₪</em></label>
      </div>
      <p class="note" style="text-align:start;margin:4px 0 0">מהטיפול הכי זול שלך ועד הכי יקר</p>
    </div>
    <label class="field" style="margin-top:12px"><span>אינסטגרם (לא חובה)</span>
      <span class="insta-wrap"><b>@</b><input type="text" name="instagram" maxlength="100" dir="ltr" value="${esc(b.instagram)}"
        placeholder="your.studio" autocapitalize="off" autocorrect="off" spellcheck="false"></span></label>
    <label class="field" style="margin-top:12px"><span>כמה מילים על העסק (לא חובה)</span>
      <textarea name="description" rows="3" maxlength="600" placeholder="ניסיון, סגנון, אווירה...">${esc(b.description)}</textarea></label>`;
}

function readPrices(fd) {
  const min = Number(fd.get("price_min"));
  const max = Number(fd.get("price_max"));
  if (!Number.isInteger(min) || !Number.isInteger(max) || min < 1 || max < 1) return { error: "צריך למלא טווח מחירים (מספרים שלמים)" };
  if (min > max) return { error: "המחיר ההתחלתי גבוה מהמחיר המקסימלי" };
  if (max > 5000) return { error: "המחיר המקסימלי גבוה מדי" };
  return { min, max };
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
        <div class="panel-head"><div class="step">${ICON.clock}<b>2</b></div>
          <div><h2>שעות פעילות</h2><p>בחרי באילו ימים את עובדת ובאילו שעות</p></div></div>
        ${hoursEditor()}
      </section>

      <section class="panel">
        <div class="panel-head"><div class="step">${ICON.pin}<b>3</b></div>
          <div><h2>איפה העסק נמצא?</h2><p>הכתובת המלאה תופיע ללקוחות, כדי שיגיעו בדיוק אלייך</p></div></div>
        ${locationFields()}
      </section>

      <section class="panel">
        <div class="panel-head"><div class="step">${ICON.camera}<b>4</b></div>
          <div><h2>תמונות של עבודות</h2><p>לפחות ${MIN_PHOTOS} תמונות של ציפורניים שעשית. ⭐ קובע איזו תמונה תופיע ראשונה</p></div></div>
        <div class="photo-grid" id="photos"></div>
        <input type="file" id="file" accept="image/*" multiple hidden>
        <p class="progress" id="photo-status"></p>
        <label class="consent">
          <input type="checkbox" id="rights">
          <span>אני מאשרת שהתמונות הן של עבודות שעשיתי, ושמותר לי לפרסם אותן. אם מופיע בהן אדם, יש לי את הסכמתו.</span>
        </label>
      </section>

      <p class="error hidden" id="form-err"></p>
      <div class="sticky-submit"><button class="btn block" id="submit">פרסום העסק</button></div>
    </form>`;

  bindServiceChips(view);
  bindHoursEditor(view);
  bindHere((p) => { picked = p; });

  const drawPhotos = () => {
    $("#photos").innerHTML = photos.map((p, i) => `
      <div class="ph"><img src="${p.preview}" alt=""><button type="button" class="rm" data-rm="${i}" aria-label="הסרה">${ICON.close}</button>
        ${i === 0 ? '<span class="main-tag">ראשית</span>'
          : `<button type="button" class="make-main" data-main="${i}" aria-label="קביעה כתמונה ראשית">${ICON.star}</button>`}</div>`).join("")
      + (photos.length < MAX_PHOTOS ? `<div class="ph add-ph" id="add-ph" role="button" tabindex="0">${ICON.plus}<span>הוספת תמונות</span></div>` : "");
    const st = $("#photo-status");
    const missing = MIN_PHOTOS - photos.length;
    st.textContent = missing > 0 ? `${photos.length} מתוך ${MIN_PHOTOS} (חסרות עוד ${missing})` : `✓ ${photos.length} תמונות`;
    st.classList.toggle("ok", missing <= 0);
    $("#add-ph")?.addEventListener("click", () => $("#file").click());
  };
  $("#photos").addEventListener("click", (e) => {
    const main = e.target.closest("[data-main]");
    if (main) {
      const [p] = photos.splice(Number(main.dataset.main), 1);
      photos.unshift(p);
      drawPhotos();
      return;
    }
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
    const prices = readPrices(fd);
    if (prices.error) return fail(prices.error);
    const hours = readHours(form);
    if (hours.error) return fail(hours.error);
    const addr = readAddress(fd, picked);
    if (addr.error) return fail(addr.error);
    if (photos.length < MIN_PHOTOS) return fail(`צריך לפחות ${MIN_PHOTOS} תמונות`);
    if (!$("#rights").checked) return fail("צריך לאשר שהתמונות הן של עבודות שלך ושמותר לך לפרסם אותן");

    const body = new FormData();
    for (const k of ["name", "phone", "description", "instagram"]) body.set(k, fd.get(k) || "");
    for (const [k, v] of Object.entries(addr.address)) body.set(k, v);
    body.set("services", fd.getAll("services").join(","));
    body.set("price_min", prices.min);
    body.set("price_max", prices.max);
    body.set("hours", JSON.stringify(hours.hours));
    if (picked) { body.set("lat", picked.lat); body.set("lng", picked.lng); }
    photos.forEach((p, i) => body.append("photos", p.blob, `photo${i}.jpg`));
    body.set("photos_rights", "true");

    const btn = $("#submit");
    btn.disabled = true;
    btn.textContent = "מעלה...";
    try {
      const res = await api("/api/businesses", { method: "POST", body });
      nav.go(`#/manage/${res.id}?new=1`);
    } catch (ex) {
      fail(ex.message);
      btn.disabled = false;
      btn.textContent = "פרסום העסק";
    }
  });
}

/* ================= profile & my businesses ================= */

async function renderProfile() {
  const p = session.profile;
  const via = { google: "גוגל", apple: "אפל", email: "אימייל", phone: "מספר טלפון", dev: "חשבון לדוגמה" }[p.provider] || "";
  view.innerHTML = `
    <div class="profile-head">
      <div class="avatar-wrap">
        <div class="avatar big" id="avatar">${avatarInner(p)}</div>
        <button class="avatar-cam" id="avatar-btn" aria-label="החלפת תמונת פרופיל">${ICON.camera}</button>
        <input type="file" id="avatar-file" accept="image/*" hidden>
      </div>
      <div class="grow">
        <h1>${esc(p.name)}${verifiedBadge(p.verified, true)}</h1>
        ${p.city ? `<p>${ICON.pin}${esc(p.city)}</p>` : '<p><a class="link" href="#/edit-profile">+ הוספת עיר</a></p>'}
        <small>מחוברת דרך ${via}</small>
      </div>
    </div>

    <div id="my-stats"></div>
    <div id="verify-slot"></div>

    <div class="section-head"><h3>העסקים שלי</h3></div>
    <div id="my-list" class="panel" style="padding:0"><div class="skeleton" style="aspect-ratio:5/1"></div></div>
    <a class="btn outline block" href="#/add">${ICON.plus} הוספת עסק</a>

    <div class="section-head" style="margin-top:26px"><h3>החשבון שלי</h3></div>
    ${menu([
      ["#/edit-profile", ICON.user, "עריכת פרופיל"],
      ["#/favorites", ICON.heart, "מועדפים"],
      ["#/settings", ICON.gear, "הגדרות"],
      ...(p.is_admin ? [["#/admin", ICON.shield, 'ניהול <span class="count-pill hidden" id="admin-count"></span>']] : []),
    ])}

    <div class="section-head" style="margin-top:26px"><h3>מידע ותמיכה</h3></div>
    ${menu([
      ["#/about", ICON.info, "אודות"],
      ["#/contact", ICON.mail, "יצירת קשר"],
      ["#/terms", ICON.doc, "תנאי שימוש"],
      ["#/privacy", ICON.lock, "מדיניות פרטיות"],
    ])}
    <button class="btn logout block" id="logout">${ICON.logout} התנתקות</button>
    <a class="delete-link" href="#/delete-account">מחיקת חשבון</a>`;

  $("#avatar-btn").addEventListener("click", () => $("#avatar-file").click());
  $("#avatar-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const { blob } = await resizeImage(file, 512, 0.85);
      const body = new FormData();
      body.append("photo", blob, "avatar.jpg");
      session.profile = await api("/api/me/avatar", { method: "POST", body });
      $("#avatar").innerHTML = avatarInner(session.profile);
      toast("תמונת הפרופיל עודכנה ✓");
    } catch (ex) { toast(ex.message); }
  });

  $("#logout").addEventListener("click", async () => {
    await Auth.signOut();
    toast("התנתקת");
  });

  if (p.is_admin) {
    api("/api/admin/summary").then((sum) => {
      const el = $("#admin-count");
      if (el && sum.pending_verifications) { el.textContent = sum.pending_verifications; el.classList.remove("hidden"); }
    }).catch(() => {});
  }

  try {
    const [list, fresh] = await Promise.all([api("/api/my/businesses"), api("/api/me")]);
    session.profile = fresh;
    const box = $("#my-list");
    if (!box) return;
    if (list.length) $("#verify-slot").innerHTML = verifyBanner(fresh);
    $(".profile-head h1").innerHTML = esc(fresh.name) + verifiedBadge(fresh.verified, true);
    if (list.length) {
      const sum = (k) => list.reduce((n, b) => n + b.stats[k], 0);
      $("#my-stats").innerHTML = `<div class="panel stats four">
        <div><b>${list.length}</b><span>${list.length === 1 ? "עסק" : "עסקים"}</span></div>
        <div><b>${sum("views")}</b><span>צפיות</span></div>
        <div><b>${sum("whatsapp_clicks")}</b><span>פניות</span></div>
        <div><b>${sum("saves")}</b><span>שמרו</span></div></div>`;
    }
    box.innerHTML = list.length ? list.map((b) => `
      <a class="list-item" href="#/manage/${b.id}">
        ${b.photos[0] ? `<img src="${esc(b.photos[0].url)}" alt="">` : `<div class="step">${ICON.store}</div>`}
        <div class="grow"><b>${esc(b.name)}</b><br>
          <small>${b.stats.views} צפיות · ${b.stats.whatsapp_clicks} פניות בוואטסאפ</small></div>
        ${ICON.chevron}</a>`).join("")
      : '<p class="note" style="padding:18px">בעלת עסק לציפורניים? העלי את העסק שלך ולקוחות מהאזור ימצאו אותך.</p>';
  } catch (err) {
    const box = $("#my-list");
    if (box) box.innerHTML = `<p class="error" style="padding:14px">${esc(err.message)}</p>`;
  }
}

function renderEditProfile() {
  const p = session.profile;
  view.innerHTML = `
    ${pageTitle("עריכת פרופיל", "#/profile")}
    <form id="profile-form" class="panel" novalidate>
      <div class="avatar-edit">
        <div class="avatar big" id="avatar">${avatarInner(p)}</div>
        <div class="avatar-actions">
          <button type="button" class="btn outline" id="avatar-btn">${ICON.camera} ${p.avatar_url ? "החלפת תמונה" : "הוספת תמונה"}</button>
          ${p.avatar_url ? '<button type="button" class="link" id="avatar-remove">הסרת התמונה</button>' : ""}
        </div>
        <input type="file" id="avatar-file" accept="image/*" hidden>
      </div>
      <label class="field"><span>שם מלא</span>
        <input type="text" name="name" required minlength="2" maxlength="60" value="${esc(p.name)}"></label>
      ${p.email || p.phone ? `<label class="field"><span>${p.email ? "אימייל" : "טלפון"}</span>
        <input type="text" value="${esc(p.email || p.phone)}" dir="ltr" readonly class="readonly"></label>
        <p class="note" style="text-align:start;margin-top:-6px">לא ניתן לשנות את ${p.email ? "כתובת האימייל" : "מספר הטלפון"} מהאפליקציה. לשינוי יש לפנות לתמיכה.</p>` : ""}
      <label class="field"><span>עיר מגורים</span>
        <input type="text" name="city" maxlength="40" list="cities" value="${esc(p.city)}"></label>
      ${cityOptions()}
      <p class="note" style="text-align:start;margin-top:-4px">כשלא משתפים מיקום, החיפוש יתחיל מהעיר הזאת</p>
      <p class="error hidden" id="err"></p>
      <button class="btn block">שמירת פרטים</button>
    </form>
    ${usesPassword() ? `
    <form id="pw-form" class="panel" novalidate>
      <div class="panel-head"><div class="step">${ICON.lock}</div><div><h2>שינוי סיסמה</h2></div></div>
      <label class="field"><span>סיסמה חדשה</span>
        <span class="pw-wrap"><input type="password" name="pw" minlength="6" autocomplete="new-password" placeholder="לפחות 6 תווים" dir="ltr">
        <button type="button" class="pw-eye" aria-label="הצגת הסיסמה">${ICON.eye}</button></span></label>
      <label class="field"><span>אימות סיסמה</span>
        <input type="password" name="pw2" minlength="6" autocomplete="new-password" placeholder="הקלידי שוב את הסיסמה" dir="ltr"></label>
      <p class="error hidden" id="pw-err"></p>
      <button class="btn outline block">עדכון סיסמה</button>
    </form>` : ""}`;
  const err = $("#err");
  const showErr = (m) => { err.textContent = m; err.classList.remove("hidden"); };

  $("#pw-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const pwErr = $("#pw-err");
    const fail = (m) => { pwErr.textContent = m; pwErr.classList.remove("hidden"); };
    pwErr.classList.add("hidden");
    const pw = e.target.pw.value, pw2 = e.target.pw2.value;
    if (pw.length < 6) return fail("הסיסמה צריכה להיות לפחות 6 תווים");
    if (pw !== pw2) return fail("שתי הסיסמאות לא זהות");
    try {
      await Auth.changePassword(pw);
      e.target.reset();
      toast("הסיסמה עודכנה ✓");
    } catch (ex) { fail(authError(ex).message); }
  });
  $(".pw-eye")?.addEventListener("click", () => {
    const f = $("#pw-form");
    const show = f.pw.type === "password";
    f.pw.type = f.pw2.type = show ? "text" : "password";
  });

  $("#avatar-btn").addEventListener("click", () => $("#avatar-file").click());
  $("#avatar-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const { blob } = await resizeImage(file, 512, 0.85);
      const body = new FormData();
      body.append("photo", blob, "avatar.jpg");
      session.profile = await api("/api/me/avatar", { method: "POST", body });
      toast("תמונת הפרופיל עודכנה ✓");
      renderEditProfile();
    } catch (ex) { showErr(ex.message); }
  });
  $("#avatar-remove")?.addEventListener("click", async () => {
    try {
      session.profile = await api("/api/me/avatar", { method: "DELETE" });
      toast("התמונה הוסרה");
      renderEditProfile();
    } catch (ex) { showErr(ex.message); }
  });

  $("#profile-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = String(e.target.name.value).trim();
    const city = String(e.target.city.value).trim();
    if (name.length < 2) return showErr("צריך לכתוב שם");
    try {
      const before = session.profile.city;
      session.profile = await api("/api/me", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, city }),
      });
      // A new home city becomes the search location, unless she is using GPS.
      const home = CITIES.find(([c]) => c === city);
      if (home && city !== before && state.loc?.label !== "המיקום שלי") {
        state.loc = { lat: home[1], lng: home[2], label: home[0] };
        store.set("nails.loc", state.loc);
      }
      toast("הפרופיל נשמר ✓");
      nav.go("#/profile");
    } catch (ex) { showErr(ex.message); }
  });
}

/* ================= settings & information pages ================= */

const menu = (items) => `<div class="panel menu">${items.map(([href, icon, label, cls = ""]) =>
  `<a class="list-item ${cls}" href="${href}"><div class="step">${icon}</div><div class="grow"><b>${label}</b></div>${ICON.chevron}</a>`).join("")}</div>`;

const usesPassword = () => session.profile?.provider === "email"
  || (session.mode === "dev" && String(session.profile?.uid || "").startsWith("email-"));

const supportEmail = () => session.config.support_email || "";
const supportPhone = () => session.config.support_phone || "";
const prettyPhone = (p) => p.replace(/^(\d{3})(\d{3})(\d{4})$/, "$1-$2-$3");
const waLink = (phone, text) => `https://wa.me/972${phone.slice(1)}?text=${encodeURIComponent(text)}`;
// How to reach support, inside running text.
const contactText = () => {
  const parts = [];
  if (supportPhone()) parts.push(`טלפון או וואטסאפ <a href="tel:${esc(supportPhone())}" dir="ltr">${prettyPhone(esc(supportPhone()))}</a>`);
  if (supportEmail()) parts.push(`<a href="mailto:${esc(supportEmail())}" dir="ltr">${esc(supportEmail())}</a>`);
  return parts.join(" או ") || "דרך עמוד יצירת הקשר";
};

// **bold** inside page texts
const operatorText = () => {
  const o = session.config.operator || {};
  if (!o.name) return "מפעילי Nails";
  return [esc(o.name), o.id && `מספר עוסק / ח.פ. ${esc(o.id)}`, o.address && esc(o.address)].filter(Boolean).join(", ");
};
const rich = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
  .replace("{CONTACT}", contactText()).replace("{OPERATOR}", operatorText());

function renderSettings() {
  view.innerHTML = `
    ${pageTitle("הגדרות", "#/profile")}
    <div class="label-sm settings-label">החשבון</div>
    ${menu([
      ["#/edit-profile", ICON.user, "עריכת פרופיל"],
      ["#/privacy", ICON.lock, "מדיניות פרטיות"],
      ["#/terms", ICON.doc, "תנאי שימוש"],
      ["#/accessibility", ICON.access, "הצהרת נגישות"],
      ["#/cookies", ICON.doc, "עוגיות ואחסון במכשיר"],
    ])}
    <div class="label-sm settings-label">תמיכה</div>
    ${menu([["#/contact", ICON.mail, "יצירת קשר עם התמיכה"]])}
    <a class="btn logout block" href="#/delete-account">${ICON.trash} מחיקת חשבון</a>`;
}

function renderInfoPage(key) {
  const page = PAGES[key];
  const back = !session.profile ? (session.user ? "#/welcome" : "#/signup")
    : ["accessibility", "cookies"].includes(key) ? "#/settings" : "#/profile";
  const head = page.hero
    ? `<div class="info-hero"><div class="logo">${LOGO()}</div><h2>${esc(page.hero.title)}</h2>
        <p class="lead">${esc(page.hero.lead)}</p><p>${esc(page.hero.sub)}</p></div>`
    : `<div class="doc-head"><div class="step">${key === "accessibility" ? ICON.access : key === "privacy" ? ICON.lock : ICON.doc}</div>
        <div><b>${esc(page.title)} של Nails</b><small>עודכן לאחרונה: ${UPDATED}</small></div></div>
        ${page.intro ? `<p>${rich(page.intro)}</p>` : ""}`;
  const numbered = !page.hero;
  view.innerHTML = `
    ${pageTitle(esc(page.title), back)}
    <article class="doc">
      ${head}
      ${page.sections.map(([title, paras], i) => `
        <section>
          <h3>${numbered ? `${i + 1}. ` : ""}${esc(title)}</h3>
          ${paras.map((t) => `<p>${rich(t)}</p>`).join("")}
        </section>`).join("")}
      ${key === "accessibility" ? '<a class="btn block" href="#/contact">פנייה בנושא נגישות</a>' : ""}
    </article>`;
}

function renderContact() {
  const email = supportEmail();
  const phone = supportPhone();
  const report = "היי, אני רוצה לדווח על עסק באפליקציית Nails.\nשם העסק:\nמה הבעיה:";
  view.innerHTML = `
    ${pageTitle("יצירת קשר", "#/profile")}
    <div class="doc-head contact-hero"><div class="step">${ICON.mail}</div>
      <div><b>אנחנו כאן בשבילך</b><small>יש לך שאלה, נתקלת בבעיה או רוצה להציע משהו? נשמח לעזור.</small></div></div>

    <div class="panel menu">
      ${phone ? `<div class="list-item contact-row"><div class="step">${ICON.phone}</div><div class="grow"><b>שירות לקוחות</b><br>
        <small dir="ltr" class="select">${prettyPhone(esc(phone))}</small></div>
        <div class="contact-actions">
          <a class="btn whatsapp small" href="${esc(waLink(phone, "היי, יש לי שאלה לגבי אפליקציית Nails"))}" target="_blank" rel="noopener">${ICON.whatsapp} וואטסאפ</a>
          <a class="btn outline small" href="tel:${esc(phone)}">${ICON.phone} שיחה</a>
        </div></div>` : ""}
      ${email ? `<div class="list-item"><div class="step">${ICON.mail}</div><div class="grow"><b>אימייל תמיכה</b><br>
        <small dir="ltr" class="select">${esc(email)}</small></div>
        <a class="btn outline small" href="mailto:${esc(email)}">שליחת מייל</a></div>` : ""}
      <div class="list-item"><div class="step">${ICON.clock}</div><div class="grow"><b>זמן מענה</b><br>
        <small>בדרך כלל עד 48 שעות בימי עבודה</small></div></div>
    </div>

    ${session.config.operator?.name ? `<p class="operator-line">השירות מופעל על ידי ${operatorText()}</p>` : ""}

    ${phone || email ? `<section class="panel">
      <div class="panel-head"><div class="step">${ICON.flag}</div><div><h2>דיווח על עסק</h2>
        <p>עסק עם פרטים לא נכונים, תמונות שאינן שלו או התנהגות פוגענית? ספרי לנו ונבדוק.</p></div></div>
      ${phone
        ? `<a class="btn outline block" href="${esc(waLink(phone, report))}" target="_blank" rel="noopener">${ICON.whatsapp} דיווח בוואטסאפ</a>`
        : `<a class="btn outline block" href="mailto:${esc(email)}?subject=${encodeURIComponent("דיווח על עסק ב-Nails")}">דיווח במייל</a>`}
    </section>` : ""}`;
}

function renderDeleteAccount() {
  view.innerHTML = `
    ${pageTitle("מחיקת חשבון", "#/settings")}
    <div class="warn-box">${ICON.alert}<div><b>לפני שמוחקים את החשבון</b>
      <p>מחיקת החשבון היא פעולה סופית. אחרי שהיא מסתיימת אי אפשר לשחזר את החשבון.</p></div></div>
    <article class="doc">
      <section><h3>מה נמחק</h3>
        <p>החשבון ופרטי הפרופיל שלך, תמונת הפרופיל, וכל העסקים שפרסמת עם כל התמונות שלהם. העסקים יפסיקו להופיע בחיפוש מיד.</p></section>
      <section><h3>לפני שממשיכים</h3>
        <p>אם יש לך עסק פעיל ואת רק רוצה להפסיק לקבל פניות, אפשר לערוך אותו או למחוק רק אותו מתוך "העסקים שלי".</p></section>
      <section><h3>איך מוחקים</h3>
        <p>לוחצים על הכפתור למטה, ואז מאשרים פעם נוספת.</p>
        <p>זקוקה לעזרה? ${contactText()}</p></section>
    </article>
    <p class="error hidden" id="del-err"></p>
    <button class="btn danger-solid block" id="del-btn">${ICON.trash} מחיקת החשבון</button>`;

  let armed = false;
  $("#del-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const err = $("#del-err");
    if (!armed) {
      armed = true;
      btn.innerHTML = `${ICON.trash} בטוחה? לחצי שוב כדי למחוק לצמיתות`;
      btn.classList.add("armed");
      return;
    }
    btn.disabled = true;
    err.classList.add("hidden");
    try {
      await api("/api/me", { method: "DELETE" });
      try { await Auth.deleteAccount(); } catch { await Auth.signOut().catch(() => {}); }
      savedIds.clear();
      toast("החשבון נמחק");
    } catch (ex) {
      err.textContent = ex.message;
      err.classList.remove("hidden");
      btn.disabled = false;
    }
  });
}


/* ================= business owner verification ================= */

function verifyBanner(p) {
  if (p.verified) {
    return `<div class="verify-banner ok">${ICON.shield}<div><b>בעלת עסק מאומתת</b>
      <small>הסימן ✓ מופיע ליד העסקים שלך</small></div></div>`;
  }
  const v = p.verification;
  if (v?.status === "pending") {
    return `<div class="verify-banner">${ICON.clock}<div><b>בקשת האימות בבדיקה</b>
      <small>נעדכן כאן ברגע שהבקשה תאושר</small></div></div>`;
  }
  const rejected = v?.status === "rejected";
  return `<a class="verify-banner" href="#/verify">${ICON.shield}<div>
      <b>${rejected ? "בקשת האימות נדחתה" : "בקשי אימות בעלת עסק"}</b>
      <small>${rejected ? esc(v.note || "אפשר לשלוח בקשה חדשה עם תמונה ברורה") : "צלמי סלפי ושלחי לאישור. עסק מאומת מקבל סימן ✓"}</small>
    </div>${ICON.chevron}</a>`;
}

function renderVerify() {
  const p = session.profile;
  if (p.verified) { nav.replace("#/profile"); return; }
  let blob = null;
  view.innerHTML = `
    ${pageTitle("אימות בעלת עסק", "#/profile")}
    <div class="doc-head"><div class="step">${ICON.shield}</div>
      <div><b>למה לאמת?</b><small>ליד עסק מאומת מופיע הסימן ✓. זה עוזר ללקוחות לסמוך עלייך ולבחור בך.</small></div></div>

    <section class="panel">
      <h2 class="panel-title">צילום סלפי עדכני</h2>
      <p class="note" style="text-align:start">צלמי תמונה ברורה של הפנים, באור טוב, בלי משקפי שמש. התמונה משמשת רק לבדיקת האימות.</p>
      <input type="file" id="selfie-file" accept="image/*" capture="user" hidden>
      <label class="selfie-box" id="selfie-box" for="selfie-file">
        <span class="selfie-empty"><span class="cam">${ICON.camera}</span><b>צילום סלפי</b><small>נפתחת המצלמה הקדמית</small></span>
      </label>
      <p class="note" style="text-align:start">התמונה נשמרת במקום מאובטח ונגיש רק לצוות Nails לצורך האימות, ונמחקת מיד אחרי ההחלטה.</p>
      <p class="error hidden" id="v-err"></p>
      <button class="btn block" id="v-send" disabled>שליחה לאימות</button>
    </section>`;

  const box = $("#selfie-box");
  $("#selfie-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const r = await resizeImage(file, 1024, 0.85);
      blob = r.blob;
      box.innerHTML = `<img src="${r.preview}" alt="הסלפי שצילמת"><span class="retake">${ICON.camera} צילום מחדש</span>`;
      $("#v-send").disabled = false;
    } catch (ex) { toast(ex.message); }
  });
  $("#v-send").addEventListener("click", async (e) => {
    const err = $("#v-err");
    err.classList.add("hidden");
    e.currentTarget.disabled = true;
    try {
      const body = new FormData();
      body.append("selfie", blob, "selfie.jpg");
      session.profile = await api("/api/me/verification", { method: "POST", body });
      toast("הבקשה נשלחה ✓");
      nav.go("#/profile");
    } catch (ex) {
      err.textContent = ex.message;
      err.classList.remove("hidden");
      e.currentTarget.disabled = false;
    }
  });
}

/* ================= admin ================= */

async function selfieUrl(id) {
  const token = await Auth.token();
  const res = await fetch(`/api/admin/verifications/${id}/selfie`, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) return null;
  return URL.createObjectURL(await res.blob());
}

async function renderAdmin(tab = "pending") {
  if (!session.profile.is_admin) { nav.replace("#/profile"); return; }
  view.innerHTML = `
    ${pageTitle("ניהול", "#/profile")}
    ${session.preview ? '<p class="dev-note">בתצוגה המקדימה כל חשבון הוא מנהל, כדי שאפשר יהיה לנסות. באפליקציה האמיתית רק המנהל רואה את המסך הזה.</p>' : ""}
    <div class="tabs" role="tablist">
      ${[["pending", "ממתינות"], ["approved", "אושרו"], ["rejected", "נדחו"]].map(([k, l]) =>
        `<button class="tab ${k === tab ? "on" : ""}" data-tab="${k}" role="tab" aria-selected="${k === tab}">${l}</button>`).join("")}
    </div>
    <div id="admin-list"><div class="skeleton" style="aspect-ratio:3/1"></div></div>`;
  view.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => renderAdmin(b.dataset.tab)));

  let list;
  try { list = await api(`/api/admin/verifications?status=${tab}`); } catch (ex) {
    $("#admin-list").innerHTML = `<p class="error">${esc(ex.message)}</p>`;
    return;
  }
  const box = $("#admin-list");
  if (!list.length) {
    box.innerHTML = empty(ICON.shield, tab === "pending" ? "אין בקשות שמחכות" : "אין בקשות ברשימה הזאת",
      tab === "pending" ? "כשבעלת עסק תשלח בקשת אימות, היא תופיע כאן." : "");
    return;
  }
  box.innerHTML = list.map((v) => `
    <article class="panel req" data-id="${v.id}">
      <div class="req-head">
        <div class="avatar">${avatarInner(v.user)}</div>
        <div class="grow"><b>${esc(v.user.name)}</b>
          <small dir="ltr">${esc(v.user.email || v.user.phone || "")}</small>
          <small>${esc(v.user.city || "")} · נשלח ${esc(v.created_at.slice(0, 16).replace("T", " "))}</small></div>
      </div>
      ${v.has_selfie ? '<div class="req-selfie"><div class="skeleton" style="aspect-ratio:3/4"></div></div>' : ""}
      <div class="req-biz"><span class="label-sm">העסקים שלה:</span>
        ${v.businesses.map((b) => `<a class="tag" href="#/b/${b.id}">${esc(b.name)} · ${esc(b.city)}</a>`).join(" ") || '<span class="muted">אין עסקים</span>'}</div>
      ${tab === "pending" ? `
        <label class="field"><span>סיבת דחייה (נשלחת לבעלת העסק, לא חובה)</span>
          <input type="text" class="req-note" maxlength="300" placeholder="למשל: התמונה מטושטשת"></label>
        <div class="row2">
          <button class="btn approve" data-act="approve">${ICON.check} אישור</button>
          <button class="btn outline reject" data-act="reject">דחייה</button>
        </div>` : `
        <p class="req-status ${v.status}">${v.status === "approved" ? "אושרה" : "נדחתה"}${v.note ? `: ${esc(v.note)}` : ""}</p>
        ${v.status === "approved" && v.user.verified ? `<button class="link" data-act="unverify" data-uid="${esc(v.uid)}">ביטול האימות</button>` : ""}`}
    </article>`).join("");

  // selfies are private: fetched with the admin's sign-in
  list.filter((v) => v.has_selfie).forEach(async (v) => {
    const url = await selfieUrl(v.id);
    const slot = box.querySelector(`.req[data-id="${v.id}"] .req-selfie`);
    if (slot) slot.innerHTML = url ? `<img src="${url}" alt="סלפי של ${esc(v.user.name)}">` : '<p class="note">התמונה לא נמצאה</p>';
  });

  box.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-act]");
    if (!btn) return;
    const card = btn.closest(".req");
    btn.disabled = true;
    try {
      if (btn.dataset.act === "unverify") {
        await api(`/api/admin/users/${encodeURIComponent(btn.dataset.uid)}/unverify`, { method: "POST" });
        toast("האימות בוטל");
      } else {
        const approve = btn.dataset.act === "approve";
        await api(`/api/admin/verifications/${card.dataset.id}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approve, note: card.querySelector(".req-note")?.value || "" }),
        });
        toast(approve ? "אושר ✓ הסימן נוסף לעסקים שלה" : "הבקשה נדחתה");
      }
      renderAdmin(tab);
    } catch (ex) { toast(ex.message); btn.disabled = false; }
  });
}


async function renderManage(id, isNew) {
  view.innerHTML = `${pageTitle("ניהול עסק", "#/profile")}<div class="skeleton" style="aspect-ratio:2/1"></div>`;
  let b;
  try {
    b = (await api("/api/my/businesses")).find((x) => x.id === id);
  } catch (err) {
    view.innerHTML = `${pageTitle("ניהול עסק", "#/profile")}<p class="error">${esc(err.message)}</p>`;
    return;
  }
  if (!b) {
    view.innerHTML = `${pageTitle("ניהול עסק", "#/profile")}${empty(ICON.store, "העסק לא נמצא",
      "אפשר לנהל רק עסקים שהעלית מהחשבון שלך.")}`;
    return;
  }

  view.innerHTML = `
    ${pageTitle(esc(b.name), "#/profile")}
    ${isNew ? `<div class="loc-bar" style="display:block"><b>🎉 העסק שלך באוויר!</b><br>
      לקוחות באזור כבר יכולות למצוא אותך.</div>` : ""}

    <div class="panel stats three">
      <div><b>${b.stats.views}</b><span>צפיות בעמוד</span></div>
      <div><b>${b.stats.whatsapp_clicks}</b><span>פניות בוואטסאפ</span></div>
      <div><b>${b.stats.saves}</b><span>שמרו במועדפים</span></div>
    </div>

    <a class="btn outline block" href="#/b/${id}" style="margin-bottom:14px">צפייה בעמוד כמו שלקוחה רואה</a>

    <form id="edit-form" novalidate>
      <section class="panel">
        <div class="panel-head"><div class="step">${ICON.store}</div><div><h2>פרטי העסק</h2></div></div>
        ${businessFields(b)}
      </section>
      <section class="panel">
        <div class="panel-head"><div class="step">${ICON.clock}</div><div><h2>שעות פעילות</h2></div></div>
        ${hoursEditor(b.hours)}
      </section>
      <section class="panel">
        <div class="panel-head"><div class="step">${ICON.pin}</div><div><h2>כתובת העסק</h2><p>אם משנים כתובת, המיקום מתעדכן לבד</p></div></div>
        ${locationFields(b)}
      </section>
      <p class="error hidden" id="edit-err"></p>
      <button class="btn block" style="margin-bottom:14px">שמירת שינויים</button>
    </form>

    <section class="panel">
      <div class="panel-head"><div class="step">${ICON.camera}</div><div><h2>תמונות</h2>
        <p>לפחות ${MIN_PHOTOS}, עד ${MAX_PHOTOS}. ⭐ קובע איזו תמונה תופיע בכרטיס</p></div></div>
      <div class="photo-grid" id="photos"></div>
      <input type="file" id="file" accept="image/*" multiple hidden>
    </section>

    <button class="btn danger block" id="delete">מחיקת העסק</button>`;

  bindServiceChips(view);
  bindHoursEditor(view);

  let newLoc = null;
  bindHere((p) => { newLoc = p; });

  $("#edit-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const err = $("#edit-err");
    const fail = (m) => { err.textContent = m; err.classList.remove("hidden"); };
    err.classList.add("hidden");
    const prices = readPrices(fd);
    if (prices.error) return fail(prices.error);
    const hours = readHours(e.target);
    if (hours.error) return fail(hours.error);
    // The business already has a position; the server only looks up an address that changed.
    const addr = readAddress(fd, newLoc || b);
    if (addr.error) return fail(addr.error);
    const payload = {
      name: String(fd.get("name")).trim(),
      phone: String(fd.get("phone")).trim(),
      description: String(fd.get("description") || "").trim(),
      instagram: String(fd.get("instagram") || "").trim(),
      services: fd.getAll("services"),
      price_min: prices.min,
      price_max: prices.max,
      hours: hours.hours,
      ...addr.address,
      ...(newLoc || {}),
    };
    try {
      await api(`/api/businesses/${id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      toast("השינויים נשמרו ✓");
    } catch (ex) { fail(ex.message); }
  });

  let photos = b.photos;
  const drawPhotos = () => {
    $("#photos").innerHTML = photos.map((p, i) => `
      <div class="ph"><img src="${esc(p.url)}" alt="">${photos.length > MIN_PHOTOS
        ? `<button type="button" class="rm" data-rm="${p.id}" aria-label="מחיקה">${ICON.close}</button>` : ""}
        ${i === 0 ? '<span class="main-tag">ראשית</span>'
          : `<button type="button" class="make-main" data-main="${p.id}" aria-label="קביעה כתמונה ראשית">${ICON.star}</button>`}</div>`).join("")
      + (photos.length < MAX_PHOTOS ? `<div class="ph add-ph" id="add-ph" role="button" tabindex="0">${ICON.plus}<span>הוספה</span></div>` : "");
    $("#add-ph")?.addEventListener("click", () => $("#file").click());
  };
  $("#photos").addEventListener("click", async (e) => {
    const main = e.target.closest("[data-main]");
    if (main) {
      try {
        photos = await api(`/api/businesses/${id}/photos/${main.dataset.main}/main`, { method: "POST" });
        drawPhotos();
        toast("התמונה הראשית עודכנה ✓");
      } catch (ex) { toast(ex.message); }
      return;
    }
    const rm = e.target.closest("[data-rm]");
    if (!rm) return;
    try {
      photos = await api(`/api/businesses/${id}/photos/${rm.dataset.rm}`, { method: "DELETE" });
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
      photos = await api(`/api/businesses/${id}/photos`, { method: "POST", body });
      drawPhotos();
      toast("התמונות נוספו ✓");
    } catch (ex) { toast(ex.message); }
  });
  drawPhotos();

  let armed = false;
  $("#delete").addEventListener("click", async (e) => {
    if (!armed) {
      armed = true;
      e.currentTarget.textContent = "בטוחה? לחצי שוב כדי למחוק לצמיתות";
      e.currentTarget.classList.add("armed");
      return;
    }
    try {
      await api(`/api/businesses/${id}`, { method: "DELETE" });
      toast("העסק נמחק");
      nav.go("#/profile");
    } catch (ex) { toast(ex.message); }
  });
}

function renderNotFound() {
  view.innerHTML = `${pageTitle("", "#/")}${empty(ICON.search, "הדף הזה לא נמצא",
    "אולי הקישור ישן, או שהעסק כבר לא באפליקציה.", '<a class="btn" href="#/">חזרה לדף הבית</a>')}`;
}

/* ================= router ================= */

const AUTH_PAGES = new Set(["signup", "login", "phone"]);
const PUBLIC_PAGES = new Set(["terms", "privacy", "cookies", "accessibility", "about"]);  // readable without an account

// A page opened before signing in (a shared link) is shown right after.
function rememberReturn(hash) { try { sessionStorage.setItem("nails.return", hash); } catch { /* blocked */ } }
function takeReturn() {
  try {
    const h = sessionStorage.getItem("nails.return");
    sessionStorage.removeItem("nails.return");
    return h;
  } catch { return null; }
}
const isAuthPageEnabled = (page) => page !== "phone" || session.methods.includes("phone");

function route() {
  const hash = nav.hash || "#/";
  const [path, query] = hash.slice(1).split("?");
  const parts = path.split("/").filter(Boolean);
  const page = parts[0];
  const params = new URLSearchParams(query);

  // Guards: not signed in -> sign-up; signed in but no name yet -> welcome.
  if (PUBLIC_PAGES.has(page) && !session.profile) {
    document.body.classList.add("signed-out");
    window.scrollTo(0, 0);
    return renderInfoPage(page);
  }
  if (!session.user) {
    if (!AUTH_PAGES.has(page) || !isAuthPageEnabled(page)) {
      if (page && page !== "welcome") rememberReturn(hash);   // e.g. a shared business link
      nav.replace("#/signup");
      return;
    }
  } else if (!session.profile) {
    if (page !== "welcome") { nav.replace("#/welcome"); return; }
  } else if (AUTH_PAGES.has(page) || page === "welcome") {
    nav.replace(takeReturn() || "#/"); return;
  }

  document.body.classList.toggle("signed-out", !session.profile);
  const tab = { "": "home", b: "home", favorites: "favorites", add: "add", profile: "profile", manage: "profile", "edit-profile": "profile",
    settings: "profile", about: "profile", contact: "profile", terms: "profile", privacy: "profile",
    accessibility: "profile", cookies: "profile", "delete-account": "profile", verify: "profile", admin: "profile" }[page || ""];
  document.querySelectorAll(".tabbar a").forEach((a) => {
    a.classList.toggle("on", a.dataset.tab === tab);
    if (a.dataset.tab === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  window.scrollTo(0, 0);
  view.classList.remove("enter");
  void view.offsetWidth;            // restart the entrance animation
  view.classList.add("enter");

  switch (page) {
    case "signup": return renderAuth("signup");
    case "login": return renderAuth("login");
    case "phone": return renderPhone(params.get("from"));
    case "welcome": return renderWelcome();
    case undefined: return renderHome();
    case "b": return renderBusiness(Number(parts[1]));
    case "favorites": return renderFavorites();
    case "add": return renderAdd();
    case "profile": return renderProfile();
    case "edit-profile": return renderEditProfile();
    case "settings": return renderSettings();
    case "about": case "terms": case "privacy": case "accessibility": case "cookies": return renderInfoPage(page);
    case "contact": return renderContact();
    case "delete-account": return renderDeleteAccount();
    case "verify": return renderVerify();
    case "admin": return renderAdmin();
    case "manage": return renderManage(Number(parts[1]), params.has("new"));
    default: return renderNotFound();
  }
}

async function onAuthChange(user) {
  const wasSignedIn = !!session.user;
  const fromSignup = /^#\/(signup|phone\?from=signup)/.test(nav.hash);
  session.user = user;
  session.profile = null;
  if (user) {
    try {
      session.profile = await api("/api/me");
      loadFavorites();
      // Used "sign up" with an account that already exists -> she is simply signed in.
      if (fromSignup) toast("כבר יש לך חשבון, התחברת 👋");
    } catch (err) {
      if (err.status !== 404) toast(err.message);
    }
  } else if (wasSignedIn) {
    nav.silent("#/login");
  }
  route();
}

if ("serviceWorker" in navigator && !window.NAILS_NAV) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

(async function start() {
  try { SERVICES = await api("/api/services"); } catch { SERVICES = []; }
  let cfg = { firebase: null, dev_auth: false };
  try { cfg = await api("/api/config"); } catch { /* offline */ }

  if (Array.isArray(cfg.methods) && cfg.methods.length) session.methods = cfg.methods;
  session.preview = !!cfg.preview;
  session.config = cfg;
  if (cfg.dev_auth) {           // local development: fake accounts
    session.mode = "dev";
    Auth = devAuth();
  } else if (cfg.firebase) {
    Auth = firebaseAuth(cfg.firebase);
  } else {
    document.body.classList.add("signed-out");
    view.innerHTML = empty(ICON.close, "ההתחברות עוד לא הוגדרה", "צריך להשלים את הגדרת ההתחברות בשרת.");
    return;
  }
  nav.listen(route);
  Auth.onChange(onAuthChange);
  try { await Auth.ready; } catch {
    document.body.classList.add("signed-out");
    view.innerHTML = empty(ICON.close, "לא הצלחנו לטעון את ההתחברות", "בדקי את החיבור לאינטרנט ונסי שוב.");
  }
})();
