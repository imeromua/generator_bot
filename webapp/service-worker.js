/**
 * Service Worker для Telegram Mini App генератора.
 *
 * Стратегії кешування:
 *   - Static assets (HTML/CSS/JS): cache-first
 *   - API data: network-first з fallback до кешу
 *   - Термін кешу API: 24 години
 */

const CACHE_VERSION = 'v1.1.0'; // Update this value manually on every deploy to bust old caches
const STATIC_CACHE = `generator-bot-cache-${CACHE_VERSION}-static`;
const API_CACHE    = `generator-bot-cache-${CACHE_VERSION}-api`;

const STATIC_ASSETS = [
    '/',
    '/css/style.css',
    '/js/app.js',
    '/js/api.js',
];

const API_CACHE_URLS = [
    '/api/status',
    '/api/schedule',
    '/api/schedule/week',
    '/api/events',
    '/api/maintenance',
    '/api/generators',
    '/api/drivers',
];

const API_CACHE_TTL_MS = 24 * 60 * 60 * 1000; // 24 hours


// ---------------------------------------------------------------------------
// Install: pre-cache static assets
// ---------------------------------------------------------------------------
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(STATIC_CACHE).then(cache => {
            return cache.addAll(STATIC_ASSETS).catch(err => {
                console.warn('[SW] Static pre-cache partial failure:', err);
            });
        }).then(() => self.skipWaiting())
    );
});


// ---------------------------------------------------------------------------
// Activate: clean up old caches
// ---------------------------------------------------------------------------
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys
                    .filter(k => k !== STATIC_CACHE && k !== API_CACHE)
                    .map(k => {
                        console.log('Deleting old cache:', k);
                        return caches.delete(k);
                    })
            )
        ).then(() => self.clients.claim())
    );
});


// ---------------------------------------------------------------------------
// Fetch: routing strategy
// ---------------------------------------------------------------------------
self.addEventListener('fetch', event => {
    const { request } = event;
    const url = new URL(request.url);

    // Only handle same-origin requests
    if (url.origin !== self.location.origin) return;

    // API endpoints: network-first with cache fallback
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(networkFirstApi(request));
        return;
    }

    // Static assets: cache-first
    event.respondWith(cacheFirst(request));
});


// ---------------------------------------------------------------------------
// Strategies
// ---------------------------------------------------------------------------

async function cacheFirst(request) {
    const cached = await caches.match(request);
    if (cached) return cached;

    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(STATIC_CACHE);
            cache.put(request, response.clone());
        }
        return response;
    } catch (_) {
        // Offline and nothing in cache
        return new Response('Офлайн: ресурс недоступний', { status: 503 });
    }
}


async function networkFirstApi(request) {
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(API_CACHE);
            // Store with timestamp header for TTL check
            const cloned = response.clone();
            const body = await cloned.text();
            const headers = new Headers(cloned.headers);
            headers.set('sw-cached-at', Date.now().toString());
            const cachedResponse = new Response(body, {
                status: cloned.status,
                headers,
            });
            cache.put(request, cachedResponse);
        }
        return response;
    } catch (_) {
        // Network failed — try cache
        const cached = await caches.match(request);
        if (cached) {
            const cachedAt = parseInt(cached.headers.get('sw-cached-at') || '0', 10);
            if (Date.now() - cachedAt < API_CACHE_TTL_MS) {
                return cached;
            }
        }
        return new Response(
            JSON.stringify({ error: 'Офлайн: дані недоступні', offline: true }),
            { status: 503, headers: { 'Content-Type': 'application/json' } }
        );
    }
}
