/* Единая карта OPORA на MapLibre GL JS. OporaOpsMap — совместимый alias. */
window.OporaMap = (() => {
  const DEFAULT_STYLE = "https://tiles.openfreemap.org/styles/liberty";
  // Библиотека поставляется вместе с приложением: карта не зависит от CDN.
  const ASSET_BASE = "/static/vendor/maplibre";
  const KIROV = [49.668, 58.6035];
  let assetPromise, map, container, resizeObserver, onResize, points = [], route = null, selected = null, hasFitted = false, fetchController;

  function status(text, error = false) {
    const node = document.getElementById("opsMapStatus");
    if (node) { node.textContent = text; node.classList.toggle("text-danger", error); }
  }
  function ensureAssets() {
    if (window.maplibregl) return Promise.resolve(window.maplibregl);
    if (assetPromise) return assetPromise;
    assetPromise = new Promise((resolve, reject) => {
      let css = document.querySelector("link[data-opora-maplibre]");
      if (!css) { css = document.createElement("link"); css.rel = "stylesheet"; css.href = `${ASSET_BASE}/maplibre-gl.css`; css.dataset.oporaMaplibre = "1"; document.head.append(css); }
      let script = document.querySelector("script[data-opora-maplibre]");
      if (!script) { script = document.createElement("script"); script.src = `${ASSET_BASE}/maplibre-gl.js`; script.dataset.oporaMaplibre = "1"; document.head.append(script); }
      const ready = () => window.maplibregl ? resolve(window.maplibregl) : reject(new Error("MapLibre unavailable"));
      script.addEventListener("load", ready, { once: true });
      script.addEventListener("error", () => reject(new Error("MapLibre load failed")), { once: true });
    }).catch((error) => { assetPromise = null; throw error; });
    return assetPromise;
  }
  function pointFeature(point) {
    const lat = Number(point.lat), lng = Number(point.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    const type = point.type || point.entity_type || "request", inPlan = Boolean(point.in_plan);
    return { type: "Feature", geometry: { type: "Point", coordinates: [lng, lat] }, properties: { ...point, type, id: String(point.id || point.entity_id || ""), in_plan: inPlan, color: inPlan ? "#198754" : (type === "defect" ? "#dc3545" : "#2563eb") } };
  }
  function collection(rows) { return { type: "FeatureCollection", features: (rows || []).map(pointFeature).filter(Boolean) }; }
  function addLayers() {
    map.addSource("opora-works", { type: "geojson", data: collection(points), cluster: true, clusterMaxZoom: 14, clusterRadius: 48 });
    map.addLayer({ id: "opora-clusters", type: "circle", source: "opora-works", filter: ["has", "point_count"], paint: { "circle-color": "#344054", "circle-radius": ["step", ["get", "point_count"], 18, 20, 23, 100, 29], "circle-stroke-width": 2, "circle-stroke-color": "#ffffff" } });
    map.addLayer({ id: "opora-cluster-count", type: "symbol", source: "opora-works", filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"], "text-size": 12 }, paint: { "text-color": "#ffffff" } });
    map.addLayer({ id: "opora-points", type: "circle", source: "opora-works", filter: ["!", ["has", "point_count"]], paint: { "circle-radius": ["case", ["get", "in_plan"], 10, 8], "circle-color": ["get", "color"], "circle-stroke-width": 2, "circle-stroke-color": "#ffffff", "circle-opacity": 0.96 } });
    map.addSource("opora-selected", { type: "geojson", data: collection([]) });
    map.addLayer({ id: "opora-selected-point", type: "circle", source: "opora-selected", paint: { "circle-radius": 14, "circle-color": "transparent", "circle-stroke-width": 3, "circle-stroke-color": "#111827" } });
    map.addSource("opora-route", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    map.addLayer({ id: "opora-route-line", type: "line", source: "opora-route", paint: { "line-color": "#c45c26", "line-width": 5, "line-opacity": 0.9 } });
  }
  function bindInteractions() {
    map.on("click", "opora-clusters", (event) => {
      const feature = map.queryRenderedFeatures(event.point, { layers: ["opora-clusters"] })[0];
      if (feature) map.getSource("opora-works").getClusterExpansionZoom(feature.properties.cluster_id, (error, zoom) => { if (!error) map.easeTo({ center: feature.geometry.coordinates, zoom }); });
    });
    map.on("click", "opora-points", (event) => {
      const feature = event.features?.[0]; if (!feature) return;
      const point = { ...feature.properties, lat: feature.geometry.coordinates[1], lng: feature.geometry.coordinates[0] };
      selected = point; map.getSource("opora-selected").setData(collection([point]));
      container.dispatchEvent(new CustomEvent("opora:select-work", { bubbles: true, detail: { point } }));
    });
    ["opora-clusters", "opora-points"].forEach((layer) => { map.on("mouseenter", layer, () => map.getCanvas().style.cursor = "pointer"); map.on("mouseleave", layer, () => map.getCanvas().style.cursor = ""); });
  }
  function resize() { map?.resize(); }
  function render({ fit = false } = {}) {
    if (!map?.isStyleLoaded()) return;
    map.getSource("opora-works")?.setData(collection(points));
    map.getSource("opora-selected")?.setData(selected ? collection([selected]) : collection([]));
    map.getSource("opora-route")?.setData({ type: "FeatureCollection", features: route?.type === "LineString" ? [{ type: "Feature", geometry: route, properties: {} }] : [] });
    const coords = collection(points).features.map((feature) => feature.geometry.coordinates);
    if ((fit || !hasFitted) && coords.length) {
      if (coords.length === 1) map.jumpTo({ center: coords[0], zoom: 16 });
      else { const bounds = coords.reduce((value, coord) => value.extend(coord), new window.maplibregl.LngLatBounds(coords[0], coords[0])); map.fitBounds(bounds, { padding: 36, maxZoom: 16, duration: 0 }); }
      hasFitted = true;
    }
    status(container?.dataset.kind === "workbench" ? (coords.length ? `На карте: ${coords.length}. Синие — заявки, красные — дефекты, зелёные — в плане.` : "Нет точек с координатами.") : (coords.length ? `Отметок на карте: ${coords.length}.` : "Нет точек с координатами."));
    resize();
  }
  function destroy() {
    fetchController?.abort(); fetchController = null; resizeObserver?.disconnect(); resizeObserver = null;
    if (onResize) window.removeEventListener("resize", onResize); onResize = null;
    map?.remove(); map = null; container = null; points = []; route = null; selected = null; hasFitted = false;
  }
  function init() {
    const node = document.getElementById("opsMap");
    if (!node) { destroy(); return Promise.resolve(false); }
    if (map && container === node) { resize(); return Promise.resolve(true); }
    destroy(); container = node; status("Загрузка карты…");
    return ensureAssets().then((lib) => {
      if (container !== node) return false;
      const style = node.dataset.mapStyle || document.querySelector('meta[name="opora-maplibre-style"]')?.content || DEFAULT_STYLE;
      map = new lib.Map({ container: node, style: style || DEFAULT_STYLE, center: KIROV, zoom: 12, attributionControl: true });
      map.addControl(new lib.NavigationControl(), "top-left");
      map.on("load", () => { addLayers(); bindInteractions(); render(); });
      map.on("error", (event) => { if (event?.error) status("Не удалось загрузить карту. Проверьте style URL и подключение.", true); });
      onResize = resize; window.addEventListener("resize", onResize);
      if (window.ResizeObserver) { resizeObserver = new ResizeObserver(resize); resizeObserver.observe(node); }
      requestAnimationFrame(() => requestAnimationFrame(resize));
      if (node.dataset.src) reload(node.dataset.src);
      return true;
    }).catch(() => { status("Карта недоступна: не удалось загрузить MapLibre.", true); return false; });
  }
  function reload(url, { fit = false } = {}) {
    const target = url || container?.dataset.src; if (!target) return Promise.resolve();
    fetchController?.abort(); fetchController = new AbortController();
    return fetch(target, { headers: { Accept: "application/json" }, signal: fetchController.signal })
      .then((response) => { if (!response.ok) throw new Error("map response"); return response.json(); })
      .then((data) => {
        points = data.points || [];
        if (selected && !points.some((point) => String(point.id || point.entity_id) === String(selected.id))) selected = null;
        render({ fit: fit || !hasFitted }); return data;
      })
      .catch((error) => { if (error.name !== "AbortError") status("Не удалось загрузить данные карты.", true); });
  }
  function setPoints(rows) { points = rows || []; if (selected && !points.some((point) => String(point.id || point.entity_id) === String(selected.id))) selected = null; render(); }
  function setRoute(routePoints, geometry) { route = geometry?.type === "LineString" ? geometry : null; render(); return (routePoints || []).filter((point) => point.lat != null && point.lng != null).length; }
  function clearRoute() { route = null; render(); }
  function fitAll() { render({ fit: true }); }
  return { init, destroy, reload, setPoints, setRoute, clearRoute, fitAll, ensureAssets, getMap: () => map };
})();
window.OporaOpsMap = window.OporaMap;
(() => { const boot = () => window.OporaMap.init(); if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot(); window.addEventListener("opora:navigated", boot); window.addEventListener("opora:before-navigate", () => window.OporaMap.destroy()); })();
