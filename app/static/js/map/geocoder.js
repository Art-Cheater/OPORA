/* Клиент единого геокодера. Провайдер выбирает сервер. */
window.OporaMapKit = window.OporaMapKit || {};
window.OporaMapKit.geocoder = {
  async search(query, scope) {
    const params = new URLSearchParams({ q: query });
    if (scope) params.set("scope", scope);
    const response = await fetch(`/api/geo/search?${params}`, { headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message || "Сервис адресов недоступен.");
    return body;
  },
  async reverse(lat, lon) {
    const params = new URLSearchParams({ lat: String(lat), lon: String(lon) });
    const response = await fetch(`/api/geo/reverse?${params}`, { headers: { Accept: "application/json" } });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.message || "Адрес для точки не найден.");
    return body;
  },
};
