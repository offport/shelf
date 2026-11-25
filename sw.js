/* Shelf offline support. The shelf page saves every book into the cache below when "Save offline" is pressed;
   this worker answers from that cache when there is no connection. Online, the network copy wins (and replaces
   the saved one), so a book that was rebuilt shows up without anything to clear. */
const CACHE = "shelf-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const saved = await cache.match(req, { ignoreSearch: true });
    const fresh = fetch(req).then(res => {
      if (res.ok) e.waitUntil(cache.put(req, res.clone()));
      return res;
    });
    if (!saved) return fresh;
    // A saved copy exists: use the network if it answers within 3 seconds, the saved copy otherwise.
    return Promise.race([fresh.catch(() => saved), new Promise(done => setTimeout(() => done(saved), 3000))]);
  })());
});
