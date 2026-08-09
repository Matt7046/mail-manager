const CACHE = "mail-manager-v10";
const PRECACHE = [
  "/",
  "/manifest.webmanifest",
  "/favicon.png",
  "/pwa/icon-192.png",
  "/pwa/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((c) => c.addAll(PRECACHE).catch(() => undefined))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.pathname.startsWith("/api/")) return;
  // Never cache the service worker itself
  if (url.pathname === "/sw.js") return;
  event.respondWith(
    caches.match(request).then((cached) => cached || fetch(request).catch(() => cached)),
  );
});

function absUrl(path) {
  try {
    return new URL(path || "/", self.location.origin).href;
  } catch (_) {
    return path || "/";
  }
}

self.addEventListener("push", (event) => {
  // Chrome/Android richiedono sempre una notifica visibile nel push handler
  // (userVisibleOnly). Deve funzionare anche a app/PWA chiusa.
  const fallback = {
    title: "Mail Manager",
    body: "Nuova email",
    // `/` → Index ripristina la sessione vault e reindirizza a /home o /login
    url: "/",
    tag: "new-mail",
  };
  let data = { ...fallback };
  try {
    if (event.data) {
      const parsed = event.data.json();
      if (parsed && typeof parsed === "object") data = { ...fallback, ...parsed };
    }
  } catch (_) {
    try {
      const text = event.data ? event.data.text() : "";
      if (text) data.body = text;
    } catch (_) {}
  }

  const title = data.title || fallback.title;
  // Preferisci `/` rispetto a `/home` a freddo: evita inbox vuota senza vault unlock
  let path = data.url || fallback.url;
  if (path === "/home" || path === "/home/") path = "/";
  const options = {
    body: data.body || fallback.body,
    icon: absUrl("/pwa/icon-192.png"),
    badge: absUrl("/favicon.png"),
    tag: data.tag || fallback.tag,
    renotify: true,
    vibrate: [120, 60, 120],
    data: { url: path },
  };

  event.waitUntil(
    self.registration.showNotification(title, options).catch((err) => {
      console.error("[sw] showNotification failed", err);
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // Non fare client.navigate(): remounta la SPA e azzerava il vault in memoria
  // (inbox vuota / "account non collegati"). Focus client esistente + postMessage;
  // altrimenti openWindow("/") — AuthContext ripristina la sessione da storage.
  const target = absUrl("/");

  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        try {
          const origin = new URL(client.url).origin;
          if (origin === self.location.origin && "focus" in client) {
            return client.focus().then((focused) => {
              try {
                (focused || client).postMessage({
                  type: "NOTIFICATION_CLICK",
                  url: "/home",
                });
              } catch (_) {}
              return focused || client;
            });
          }
        } catch (_) {}
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    }),
  );
});
