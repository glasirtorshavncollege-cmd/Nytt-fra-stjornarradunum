
const CACHE = 'ministry-check-v9';
const BADGE_CACHE = 'ministry-check-badge-v1';

const CORE = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon.svg',
  './apple-touch-icon.png'
];

// Install
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE).then(cache => cache.addAll(CORE))
  );
  self.skipWaiting();
});

// Activate
self.addEventListener('activate', event => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();

      await Promise.all(
        keys
          .filter(key => key !== CACHE && key !== BADGE_CACHE)
          .map(key => caches.delete(key))
      );

      await self.clients.claim();
    })()
  );
});

// Fetch
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  if (url.origin !== self.location.origin) return;

  if (url.pathname.endsWith('/feed.json')) {
    event.respondWith(
      fetch(event.request, { cache: 'no-store' })
    );
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() =>
        caches.match('./index.html')
      )
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached =>
      cached || fetch(event.request)
    )
  );
});

// Badge storage
function badgeRequest() {
  return new Request(
    new URL('./__badge_count__', self.registration.scope).href
  );
}

async function getBadgeCount() {
  const cache = await caches.open(BADGE_CACHE);
  const response = await cache.match(badgeRequest());

  if (!response) return 0;

  const data = await response.json();
  const count = Number(data.count);

  return Number.isSafeInteger(count) && count >= 0
    ? count
    : 0;
}

async function saveBadgeCount(count) {
  const cache = await caches.open(BADGE_CACHE);

  await cache.put(
    badgeRequest(),
    new Response(
      JSON.stringify({ count }),
      {
        headers: {
          'Content-Type': 'application/json'
        }
      }
    )
  );
}

// Increase badge for each push event
async function incrementBadge() {
  const previous = await getBadgeCount();
  const next = Math.min(previous + 1, 999);

  await saveBadgeCount(next);

  if ('setAppBadge' in self.navigator) {
    await self.navigator.setAppBadge(next);
  }
}

// Clear badge
async function clearBadge() {
  await saveBadgeCount(0);

  if ('clearAppBadge' in self.navigator) {
    await self.navigator.clearAppBadge();
  } else if ('setAppBadge' in self.navigator) {
    await self.navigator.setAppBadge(0);
  }
}

// Push notification
self.addEventListener('push', event => {
  let payload = {
    title: 'Nýtt frá ráðunum',
    body: 'Nýggj tíðindi eru komin.'
  };

  try {
    if (event.data) {
      payload = {
        ...payload,
        ...event.data.json()
      };
    }
  } catch (error) {
    console.warn('Could not read push payload', error);
  }

  const link = payload.articleId
    ? './?article=' + encodeURIComponent(payload.articleId)
    : './';

  event.waitUntil(
    (async () => {
      // Always display the notification.
      const notificationPromise = self.registration.showNotification(
        payload.title,
        {
          body: payload.body,
          icon: './apple-touch-icon.png',
          badge: './icon.svg',
          tag: 'ministry-news-' + (payload.articleId || 'latest'),
          data: {
            url: new URL(link, self.registration.scope).href
          }
        }
      );

      // Badge errors must not prevent notifications.
      const badgePromise = incrementBadge().catch(error => {
        console.warn('Could not update app badge', error);
      });

      await Promise.all([
        notificationPromise,
        badgePromise
      ]);
    })()
  );
});

// Notification click
self.addEventListener('notificationclick', event => {
  event.notification.close();

  const target =
    event.notification.data?.url ||
    self.registration.scope;

  event.waitUntil(
    (async () => {
      try {
        await clearBadge();
      } catch (error) {
        console.warn('Could not clear app badge', error);
      }

      const windows = await clients.matchAll({
        type: 'window',
        includeUncontrolled: true
      });

      const found = windows.find(client =>
        new URL(client.url).origin === new URL(target).origin
      );

      if (found) {
        const navigated = await found.navigate(target);
        if (navigated) return navigated.focus();
      }

      return clients.openWindow(target);
    })()
  );
});

// Allow the app to clear its badge when opened.
self.addEventListener('message', event => {
  if (event.data?.type === 'CLEAR_BADGE') {
    event.waitUntil(
      clearBadge().catch(error => {
        console.warn('Could not clear app badge', error);
      })
    );
  }
});
