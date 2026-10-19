const CACHE = 'best-or-first-pwa-v2';
const ASSETS = ['./','./index.html','./online.html','./supabase-config.js','./manifest.webmanifest','./icons/app-icon-192.png','./icons/app-icon-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('best-or-first-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  event.respondWith(caches.match(request).then(cached => cached || fetch(request).catch(error => {
    if (request.mode === 'navigate') return caches.match('./online.html');
    throw error;
  })));
});
