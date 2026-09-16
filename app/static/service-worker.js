self.addEventListener("install", (event) => {
  event.waitUntil(caches.open("opora-static-20260916a").then((cache) => cache.addAll([
    "/static/favicon.png", "/static/icons/opora-maskable.svg",
  ])).catch(() => undefined));
  self.skipWaiting();
});
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key.startsWith("opora-static-") && key !== "opora-static-20260916a").map((key) => caches.delete(key))
  )).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  // Ни HTML, ни API, ни данные пользователя не попадают в Cache Storage.
  if (request.method !== "GET" || url.origin !== self.location.origin || !url.pathname.startsWith("/static/")) return;
  event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then((response) => {
    if (!response.ok) return response;
    const copy = response.clone();
    caches.open("opora-static-20260916a").then((cache) => cache.put(request, copy));
    return response;
  })));
});
self.addEventListener("push", (event) => {
  const data = event.data?.json?.() || {};
  event.waitUntil(self.registration.showNotification(data.title || "Новое сообщение", {body: data.body || "", icon: data.icon || "/static/favicon.png", data: {url: data.url || "/messenger/"}}));
});
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/messenger/", self.location.origin).href;
  event.waitUntil(clients.matchAll({type: "window", includeUncontrolled: true}).then((windows) => {
    const existing = windows.find((client) => client.url.startsWith(self.location.origin));
    return existing ? existing.focus().then(() => existing.navigate(url)) : clients.openWindow(url);
  }));
});
