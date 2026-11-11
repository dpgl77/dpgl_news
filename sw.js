const CACHE_NAME = 'dpgl-news-v3';
const SHELL = [
  './index.html',
  './style.css',
  './script.js',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(activate());
});

async function activate() {
  const keys = await caches.keys();
  const hadPrevious = keys.some(key => key !== CACHE_NAME);
  await Promise.all(
    keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
  );
  await self.clients.claim();
  if (!hadPrevious) return;

  const windows = await self.clients.matchAll({
    type: 'window',
    includeUncontrolled: true
  });
  await Promise.all(windows.map(reloadClient));
}

async function reloadClient(client) {
  if (typeof client.navigate === 'function') {
    try {
      await client.navigate(client.url);
      return;
    } catch (e) {}
  }
  client.postMessage({ type: 'dpgl-reload' });
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch (e) {
    return;
  }
  if (url.origin !== self.location.origin) return;
  if (url.pathname.endsWith('/sw.js')) return;

  if (!isAppShell(url)) {
    if (request.mode === 'navigate') {
      event.respondWith(fetch(request).catch(() => offlineResponse()));
    }
    return;
  }

  event.respondWith(networkFirst(request));
});

function isAppShell(url) {
  const scopePath = new URL('./', self.location).pathname;
  if (!url.pathname.startsWith(scopePath)) return false;
  const relative = url.pathname.slice(scopePath.length);
  return SHELL.some(item => item.replace('./', '') === relative) || relative === '';
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response && response.ok && response.type === 'basic') {
      try {
        await cache.put(request, response.clone());
      } catch (e) {}
    }
    return response;
  } catch (e) {
    const cached = await cache.match(request);
    if (cached) return cached;
    if (request.mode === 'navigate') {
      const shell = await cache.match('./index.html');
      if (shell) return shell;
      return offlineResponse();
    }
    throw e;
  }
}

function offlineResponse() {
  const html = '<!DOCTYPE html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DPGL NEWS</title><body style="font-family:Segoe UI,sans-serif;padding:24px"><p>Нет подключения к сети. Откройте приложение снова, когда связь появится.</p></body></html>';
  return new Response(html, {
    headers: { 'Content-Type': 'text/html; charset=utf-8' }
  });
}
