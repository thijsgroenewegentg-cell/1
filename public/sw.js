/* ULTRON service worker — caches the shell so he installs as an app.
   API calls are never cached (he must think fresh). */
'use strict';

const CACHE = 'ultron-v3';
const SHELL = [
  '/',
  '/index.html',
  '/styles.css',
  '/app.js',
  '/favicon.svg',
  '/manifest.webmanifest',
  '/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL).catch(() => null))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.pathname.startsWith('/api/')) return; // network only
  if (url.origin !== location.origin) return;

  e.respondWith(
    caches.match(e.request).then((cached) => {
      const fresh = fetch(e.request)
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((cache) => cache.put(e.request, copy)).catch(() => null);
          }
          return res;
        })
        .catch(() => cached);
      return cached || fresh;
    })
  );
});
