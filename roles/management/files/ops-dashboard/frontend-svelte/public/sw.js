// Ops phone app service worker. It exists so iOS/Android treat the app as
// installable and the shell opens instantly; it never caches /api or /auth, so
// every number on screen is live and a signed-out phone is sent to sign-in.
const SHELL = 'ops-shell-v1';

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.add('/m/')).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin || !url.pathname.startsWith('/m/')) return;
  if (url.pathname.startsWith('/m/assets/')) {
    // Content-hashed: cache forever once seen.
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(SHELL).then((c) => c.put(e.request, copy)); }
      return res;
    })));
    return;
  }
  // The shell: network first (picks up redeploys and the sign-in redirect),
  // cached copy only when offline.
  e.respondWith(fetch(e.request).then((res) => {
    if (res.ok && res.type === 'basic') { const copy = res.clone(); caches.open(SHELL).then((c) => c.put('/m/', copy)); }
    return res;
  }).catch(() => caches.match('/m/')));
});
