// Keeps the app shell available on weak mountain networks. API calls are never cached:
// a stale fare or ride status would be worse than a clear "you are offline" message.
const CACHE = "raahi-v14";
const SHELL = [
  "/", "/ride", "/driver",
  "/static/app.css?v=14", "/static/common.js?v=14", "/static/home.js?v=14", "/static/chat.js?v=14", "/static/rider.js?v=14", "/static/driver.js?v=14",
  "/static/photos/photos.json",
  "/static/manifest.webmanifest", "/static/icons/icon-192.png",
];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  if (url.origin !== location.origin) return;

  // Network first, so a deployed update is seen as soon as there is signal.
  event.respondWith(
    // no-cache: always ask the server (a cheap 304 when unchanged), never a stale HTTP copy.
    fetch(event.request, { cache: "no-cache" })
      .then(response => {
        const copy = response.clone();
        caches.open(CACHE).then(cache => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request)));
});
