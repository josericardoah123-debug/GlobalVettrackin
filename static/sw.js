const CACHE = 'labtrack-v2';
const ASSETS = ['/', '/manifest.json'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) return; // Never cache API calls
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
