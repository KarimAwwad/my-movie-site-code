// RUIN.TO service worker.
// Deliberately tiny: it does NOT cache the site. Every page, script and style always comes fresh from the network,
// so after you update the site nobody is ever stuck on an old copy (the classic service-worker trap).
// Its only jobs: make the site installable, and show a friendly page when someone opens it with no internet.
const OFFLINE_CACHE = 'ruin-offline-v1';   // change the number if you ever edit offline.html

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(OFFLINE_CACHE)
      // a missing offline.html must not stop the worker from installing
      .then(cache => cache.add('offline.html').catch(() => {}))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== OFFLINE_CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.mode !== 'navigate') return;   // scripts, images, API calls: untouched, straight to the network
  event.respondWith(
    fetch(event.request).catch(async () => (await caches.match('offline.html')) || new Response('Offline', {status: 503, headers: {'Content-Type': 'text/plain'}}))
  );
});