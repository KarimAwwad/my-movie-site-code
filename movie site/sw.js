// RUIN.TO service worker.
// Deliberately tiny: it does NOT cache the site. Every page, script and style always comes fresh from the network,
// so after you update the site nobody is ever stuck on an old copy (the classic service-worker trap).
// Its only jobs: make the site installable, and show a friendly page when someone opens it with no internet.
const OFFLINE_CACHE = 'ruin-offline-v1';   // change the number if you ever edit offline.html
const OFFLINE_URL = 'offline.html';
const NAV_TIMEOUT_MS = 6000;               // a navigation that has not answered by now is treated as down
const PREFIX = 'ruin-';                    // only our own caches are ever purged

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(OFFLINE_CACHE)
      // reload bypasses the HTTP cache so a version bump really does re-fetch the page;
      // a missing offline.html must not stop the worker from installing
      .then(cache => cache.add(new Request(OFFLINE_URL, {cache: 'reload'})).catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k.startsWith(PREFIX) && k !== OFFLINE_CACHE).map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

async function offline() {
  const cached = await caches.match(OFFLINE_URL);
  return cached || new Response('Offline', {status: 503, headers: {'Content-Type': 'text/plain'}});
}

self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return;   // scripts, images, API calls: untouched, straight to the network

  // A dead socket is as bad as no network. Abort it and show the offline page rather than
  // leaving the tab hanging on a blank document forever.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), NAV_TIMEOUT_MS);

  event.respondWith(
    fetch(event.request, {signal: controller.signal})
      .then(response => { clearTimeout(timer); return response; })
      .catch(async () => { clearTimeout(timer); return offline(); })
  );
});