// Nails service worker: makes the app installable and shows a friendly page when offline.
// Everything else goes straight to the network (no caching of data).
const OFFLINE = "nails-offline-v3";

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(OFFLINE).then((c) => c.addAll(["/offline.html", "/theme.js", "/icon-192.png"])));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== OFFLINE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate") return;           // only page loads
  e.respondWith(fetch(e.request).catch(() => caches.match("/offline.html")));
});
