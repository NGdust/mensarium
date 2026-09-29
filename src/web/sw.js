// Push notifications from Core: shown unless the owner is already looking at that chat; a click opens it.

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

const windows = () => self.clients.matchAll({ type: 'window', includeUncontrolled: true });

self.addEventListener('push', (e) => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch { /* not JSON: show the default text */ }
  e.waitUntil((async () => {
    const watching = (await windows()).some((w) => w.focused && w.visibilityState === 'visible' && data.task_id && new URL(w.url).hash === `#/chat/${data.task_id}`);
    if (watching) return;
    await self.registration.showNotification(data.title || 'Mensarium', {
      body: data.body || '',
      tag: data.tag,
      icon: '/static/apple-touch-icon.png',
      data: { url: data.task_id ? `/#/chat/${data.task_id}` : '/' },
    });
  })());
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || '/', self.location.origin).href;
  e.waitUntil((async () => {
    const win = (await windows())[0];
    if (!win) return self.clients.openWindow(url);
    await win.focus();
    return win.navigate(url).catch(() => self.clients.openWindow(url));
  })());
});
