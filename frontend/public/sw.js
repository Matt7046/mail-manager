const CACHE = "mail-manager-v4";
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

self.addEventListener("push", (event) => {
  let data = { title: "Mail Manager", body: "Nuova email", url: "/home", tag: "new-mail" };
  try {
    if (event.data) data = { ...data, ...event.data.json() };
  } catch (_) {
    try {
      data.body = event.data ? event.data.text() : data.body;
    } catch (_) {}
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Mail Manager", {
      body: data.body || "Nuova email",
      icon: "/pwa/icon-192.png",
      badge: "/favicon.png",
      tag: data.tag || "new-mail",
      renotify: true,
      data: { url: data.url || "/home" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/home";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const c of clients) {
        if ("focus" in c) {
          try {
            if (typeof c.navigate === "function") c.navigate(target);
          } catch (_) {}
          return c.focus();
        }
      }
      if (self.clients.openWindow) return self.clients.openWindow(target);
    }),
  );
});
