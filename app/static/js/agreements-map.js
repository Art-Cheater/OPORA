/* Карта договоров на общем MapLibre. Leaflet больше не используется. */
window.OporaAgreementMap = {
  _map: null,
  _abort: null,
  _timer: 0,
  init() {
    const mapNode = document.getElementById("agreementMap");
    if (!mapNode || mapNode.dataset.bound === "1") return;
    const src = mapNode.getAttribute("data-src");
    if (!src || !window.OporaMapKit?.createMap) return;
    mapNode.dataset.bound = "1";
    const token = {};
    this._token = token;
    const statusNode = document.getElementById("agreementMapStatus");
    const setStatus = (text) => { if (statusNode) statusNode.textContent = text; };
    const colors = ["#c45c26", "#1d4ed8", "#0f766e", "#7c3aed", "#b45309", "#be123c", "#0369a1"];
    const colorByCustomer = new Map();
    let lastRemaining = null;
    let stalled = 0;
    const colorFor = (customer) => {
      const key = customer || "—";
      if (!colorByCustomer.has(key)) colorByCustomer.set(key, colors[colorByCustomer.size % colors.length]);
      return colorByCustomer.get(key);
    };
    const esc = window.OporaMapKit.escapeHtml;
    const popupHtml = (point) => {
      const number = point.number ? `№ ${esc(point.number)}` : esc(point.title);
      const fileLink = point.file_url ? `<div class="mt-2"><a href="${esc(point.file_url)}">Скачать договор</a></div>` : "";
      return `<div class="agreement-map-popup"><div class="fw-semibold">${esc(point.customer)}</div><div class="mt-1"><a href="${esc(point.url)}">${number}</a></div>${point.subject ? `<div class="text-muted small mt-1">${esc(point.subject)}</div>` : ""}<div class="small mt-2"><span class="text-muted">Срок:</span> ${esc(point.period)}</div><div class="mt-2">${esc(point.address)}</div><div class="small mt-2">Крепления: ${esc(point.mounts ?? "—")} · Опоры: ${esc(point.poles ?? "—")}</div>${point.note ? `<div class="small mt-1">${esc(point.note)}</div>` : ""}${fileLink}</div>`;
    };
    const paint = (data) => {
      if (!this._map?.getSource("agreements")) return;
      const placed = new Map();
      const features = [];
      (data.points || []).forEach((point) => {
        const lat = Number(point.lat);
        const lng = Number(point.lng);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
        const key = `${lat.toFixed(5)},${lng.toFixed(5)}`;
        const n = placed.get(key) || 0;
        placed.set(key, n + 1);
        const angle = n * 0.9;
        const dist = 0.0002 * n;
        features.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: [lng + Math.sin(angle) * dist, lat + Math.cos(angle) * dist] },
          properties: { ...point, color: colorFor(point.customer) },
        });
      });
      this._map.getSource("agreements").setData({ type: "FeatureCollection", features });
      if (features.length === 1) this._map.jumpTo({ center: features[0].geometry.coordinates, zoom: 15 });
      else if (features.length > 1) {
        const bounds = features.reduce((value, feature) => value.extend(feature.geometry.coordinates), new window.maplibregl.LngLatBounds(features[0].geometry.coordinates, features[0].geometry.coordinates));
        this._map.fitBounds(bounds, { padding: 28, maxZoom: 15, duration: 0 });
      }
      this._map.resize();
    };
    const load = async () => {
      this._abort?.abort();
      this._abort = new AbortController();
      try {
        const response = await fetch(src, { headers: { Accept: "application/json" }, signal: this._abort.signal });
        if (!response.ok) {
          setStatus("Не удалось загрузить карту.");
          return;
        }
        const data = await response.json();
        paint(data);
        const count = (data.points || []).length;
        const remaining = Number(data.remaining || 0);
        if (remaining > 0) {
          stalled = remaining === lastRemaining ? stalled + 1 : 0;
          lastRemaining = remaining;
          setStatus(`На карте ${count}. Координаты догружаются: ещё ${remaining}.`);
          if (stalled >= 8) {
            setStatus(`На карте ${count}. Без точки: ${remaining}.`);
            return;
          }
          this._timer = window.setTimeout(load, 8000);
        } else if (count) setStatus(`Отметок: ${count}. Нажмите точку — откроется договор.`);
        else setStatus("Пока нет точек — загрузите договор с адресной программой.");
      } catch (error) {
        if (error?.name !== "AbortError") setStatus("Не удалось загрузить карту.");
      }
    };
    window.OporaMapKit.createMap(mapNode, { onError: () => setStatus("Не удалось загрузить карту.") }).then((map) => {
      if (this._token !== token) {
        window.OporaMapKit.destroyMap(map);
        return;
      }
      this._map = map;
      map.addSource("agreements", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "agreements-points",
        type: "circle",
        source: "agreements",
        paint: {
          "circle-radius": 8,
          "circle-color": ["get", "color"],
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffffff",
        },
      });
      map.on("click", "agreements-points", (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        new window.maplibregl.Popup({ maxWidth: "320px" }).setLngLat(feature.geometry.coordinates).setHTML(popupHtml(feature.properties)).addTo(map);
      });
      map.on("mouseenter", "agreements-points", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "agreements-points", () => { map.getCanvas().style.cursor = ""; });
      load();
    }).catch(() => setStatus("Карта недоступна: не удалось загрузить MapLibre."));
  },
  destroy() {
    this._abort?.abort();
    window.clearTimeout(this._timer);
    this._token = null;
    window.OporaMapKit?.destroyMap?.(this._map);
    this._map = null;
    const mapNode = document.getElementById("agreementMap");
    if (mapNode) delete mapNode.dataset.bound;
  },
};
(() => {
  const boot = () => window.OporaAgreementMap.init();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  window.addEventListener("opora:navigated", boot);
  window.addEventListener("opora:before-navigate", () => window.OporaAgreementMap.destroy());
})();
