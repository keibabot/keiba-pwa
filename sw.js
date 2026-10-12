const BUILD_VERSION = '__BUILD_VERSION__';
const CACHE = `keiba-pwa-${BUILD_VERSION}`;
const CORE = [
  `./styles.css?v=${BUILD_VERSION}`,
  `./app.js?v=${BUILD_VERSION}`,
  './manifest.webmanifest',
  './icon.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(CORE)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key.startsWith('keiba-pwa-') && key !== CACHE).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const response = await fetch(request, { cache: 'no-store' });
    if (response && response.ok) await cache.put(request, response.clone());
    return response;
  } catch (error) {
    const cached = await cache.match(request, { ignoreSearch: false });
    if (cached) return cached;
    throw error;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(request, { ignoreSearch: false });
  if (cached) return cached;
  const response = await fetch(request);
  if (response && response.ok) await cache.put(request, response.clone());
  return response;
}

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  const path = url.pathname;
  const isHtml = event.request.mode === 'navigate' || path.endsWith('/index.html') || path.endsWith('/');
  const isLatest = path.endsWith('/data/latest.json') || path.endsWith('data/latest.json');
  const isVersionedAsset = path.endsWith('/app.js') || path.endsWith('/styles.css');

  if (isHtml || isLatest) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  if (isVersionedAsset) {
    event.respondWith(cacheFirst(event.request));
    return;
  }

  event.respondWith(cacheFirst(event.request));
});
