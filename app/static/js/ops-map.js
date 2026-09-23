/* Единая карта OPORA. OporaOpsMap — совместимый alias. Слои живут в js/map. */
window.OporaMap = (() => {
  const kit = () => window.OporaMapKit;
  let map = null;
  let container = null;
  let points = [];
  let route = null;
  let selected = null;
  let hasFitted = false;
  let fetchController = null;
  let entranceController = null;
  let entranceTimer = 0;
  const nearbyIds = new Set();

  function status(text, error = false) {
    const node = document.getElementById("opsMapStatus");
    if (node) {
      node.textContent = text;
      node.classList.toggle("text-danger", error);
    }
  }

  function decorated(rows) {
    return (rows || []).map((point) => ({
      ...point,
      nearby: nearbyIds.has(String(point.entity_id || point.id)) && !(point.in_plan === true || point.in_plan === "true"),
    }));
  }

  function bindInteractions(lib) {
    map.on("click", "opora-clusters", (event) => {
      const feature = map.queryRenderedFeatures(event.point, { layers: ["opora-clusters"] })[0];
      if (!feature) return;
      map.getSource("opora-works").getClusterExpansionZoom(feature.properties.cluster_id, (error, zoom) => {
        if (!error) map.easeTo({ center: feature.geometry.coordinates, zoom });
      });
    });
    map.on("click", "opora-points", (event) => {
      const feature = event.features?.[0];
      if (!feature) return;
      const point = { ...feature.properties, lat: feature.geometry.coordinates[1], lng: feature.geometry.coordinates[0] };
      selected = point;
      map.getSource("opora-selected").setData(kit().collection([point]));
      const esc = kit().escapeHtml;
      const title = point.number ? `№ ${esc(point.number)}` : esc(point.address || "Точка");
      const quality = point.quality ? `<div>Точность: ${esc(point.quality)}</div>` : "";
      const link = point.url ? `<div class="mt-1"><a href="${esc(point.url)}">Открыть</a></div>` : "";
      new lib.Popup({ maxWidth: "280px" })
        .setLngLat(feature.geometry.coordinates)
        .setHTML(`<div><strong>${title}</strong><div>${esc(point.address || "")}</div>${quality}${link}</div>`)
        .addTo(map);
      container.dispatchEvent(new CustomEvent("opora:select-work", { bubbles: true, detail: { point } }));
    });
    map.on("click", "opora-entrances", (event) => {
      const feature = event.features?.[0];
      if (!feature) return;
      const props = feature.properties || {};
      const esc = kit().escapeHtml;
      const house = props.address_text || [props.street, props.house].filter(Boolean).join(", д. ");
      const entrance = props.ref ? esc(props.ref) : "номер не указан";
      const kind = props.entrance_type && props.entrance_type !== "yes" ? `<div>Вход: ${esc(props.entrance_type)}</div>` : "";
      const named = props.name ? `<div>${esc(props.name)}</div>` : "";
      new lib.Popup({ maxWidth: "260px" })
        .setLngLat(feature.geometry.coordinates)
        .setHTML(`<div><div>Дом: ${esc(house || "—")}</div><div>Подъезд: ${entrance}</div>${kind}${named}<div>${esc(props.lat)}, ${esc(props.lon)}</div></div>`)
        .addTo(map);
    });
    ["opora-clusters", "opora-points", "opora-entrances"].forEach((layer) => {
      map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
    });
    map.on("moveend", scheduleEntrances);
  }

  function scheduleEntrances() {
    window.clearTimeout(entranceTimer);
    entranceTimer = window.setTimeout(loadEntrances, 300);
  }

  function loadEntrances() {
    if (!map?.isStyleLoaded()) return;
    const zoom = map.getZoom();
    const minimum = kit().readConfig().entranceMinZoom;
    if (zoom < minimum) {
      map.getSource("opora-entrances")?.setData({ type: "FeatureCollection", features: [] });
      return;
    }
    const bounds = map.getBounds();
    const params = new URLSearchParams({
      min_lat: bounds.getSouth(),
      max_lat: bounds.getNorth(),
      min_lon: bounds.getWest(),
      max_lon: bounds.getEast(),
      zoom: String(zoom),
    });
    entranceController?.abort();
    entranceController = new AbortController();
    fetch(`/api/geo/entrances?${params}`, { headers: { Accept: "application/json" }, signal: entranceController.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (data?.geojson) map.getSource("opora-entrances")?.setData(data.geojson);
      })
      .catch((error) => {
        if (error.name !== "AbortError") map.getSource("opora-entrances")?.setData({ type: "FeatureCollection", features: [] });
      });
  }

  function render({ fit = false } = {}) {
    if (!map?.isStyleLoaded()) return;
    const rows = decorated(points);
    map.getSource("opora-works")?.setData(kit().collection(rows));
    map.getSource("opora-selected")?.setData(selected ? kit().collection([selected]) : kit().collection([]));
    map.getSource("opora-route")?.setData({
      type: "FeatureCollection",
      features: route?.type === "LineString" ? [{ type: "Feature", geometry: route, properties: {} }] : [],
    });
    const coords = kit().collection(rows).features.map((feature) => feature.geometry.coordinates);
    if ((fit || !hasFitted) && coords.length) {
      if (coords.length === 1) map.jumpTo({ center: coords[0], zoom: 16 });
      else {
        const bounds = coords.reduce((value, coord) => value.extend(coord), new window.maplibregl.LngLatBounds(coords[0], coords[0]));
        map.fitBounds(bounds, { padding: 36, maxZoom: 16, duration: 0 });
      }
      hasFitted = true;
    }
    const legend = container?.dataset.kind === "workbench"
      ? "Синие — заявки, красные — дефекты, зелёные — в плане, бирюзовые — рядом."
      : "";
    status(coords.length
      ? `Отметок на карте: ${coords.length}. ${legend}`.trim()
      : "Координаты не заданы.");
    map.resize();
  }

  function destroy() {
    fetchController?.abort();
    entranceController?.abort();
    window.clearTimeout(entranceTimer);
    fetchController = null;
    entranceController = null;
    kit().destroyMap?.(map);
    map = null;
    container = null;
    points = [];
    route = null;
    selected = null;
    hasFitted = false;
  }

  function init() {
    const node = document.getElementById("opsMap");
    if (!node) {
      destroy();
      return Promise.resolve(false);
    }
    if (map && container === node) {
      map.resize();
      return Promise.resolve(true);
    }
    destroy();
    container = node;
    status("Загрузка карты…");
    return kit().createMap(node, {
      onError: (message) => status(typeof message === "string" ? message : "Не удалось загрузить карту.", true),
    }).then((created) => {
      if (container !== node) {
        kit().destroyMap(created);
        return false;
      }
      map = created;
      kit().addWorkLayers(map);
      bindInteractions(window.maplibregl);
      render();
      if (node.dataset.src) reload(node.dataset.src);
      scheduleEntrances();
      return true;
    }).catch(() => {
      status("Карта недоступна: не удалось загрузить MapLibre.", true);
      return false;
    });
  }

  function reload(url, { fit = false } = {}) {
    const target = url || container?.dataset.src;
    if (!target) return Promise.resolve();
    fetchController?.abort();
    fetchController = new AbortController();
    return fetch(target, { headers: { Accept: "application/json" }, signal: fetchController.signal })
      .then((response) => {
        if (!response.ok) throw new Error("map response");
        return response.json();
      })
      .then((data) => {
        points = data.points || data.geojson?.features?.map((feature) => ({
          ...feature.properties,
          lng: feature.geometry.coordinates[0],
          lat: feature.geometry.coordinates[1],
        })) || [];
        if (selected && !points.some((point) => String(point.id || point.entity_id) === String(selected.id))) selected = null;
        render({ fit: fit || !hasFitted });
        return data;
      })
      .catch((error) => {
        if (error.name !== "AbortError") status("Не удалось загрузить данные карты.", true);
      });
  }

  function setPoints(rows) {
    points = rows || [];
    if (selected && !points.some((point) => String(point.id || point.entity_id) === String(selected.id))) selected = null;
    render();
  }

  function setNearby(ids) {
    nearbyIds.clear();
    (ids || []).forEach((id) => nearbyIds.add(String(id)));
    render();
  }

  function setRoute(routePoints, geometry) {
    route = geometry?.type === "LineString" ? geometry : null;
    render();
    return (routePoints || []).filter((point) => point.lat != null && point.lng != null).length;
  }

  function clearRoute() {
    route = null;
    render();
  }

  function fitAll() {
    hasFitted = false;
    render({ fit: true });
  }

  return {
    init,
    destroy,
    reload,
    setPoints,
    setNearby,
    setRoute,
    clearRoute,
    fitAll,
    ensureAssets: () => kit().ensureAssets(),
    getMap: () => map,
  };
})();
window.OporaOpsMap = window.OporaMap;
(() => {
  const boot = () => window.OporaMap.init();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
  window.addEventListener("opora:navigated", boot);
  window.addEventListener("opora:before-navigate", () => window.OporaMap.destroy());
})();
