/* Клиент маршрута. Движок на сервере, прямая линия здесь не рисуется. */
window.OporaMapKit = window.OporaMapKit || {};
window.OporaMapKit.routing = {
  async build(points, { mode = "driving", optimize = false } = {}) {
    const response = await fetch("/api/routes", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ points, mode, optimize }),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.ok === false) throw new Error(body.message || "Не удалось построить маршрут.");
    return body;
  },
};
