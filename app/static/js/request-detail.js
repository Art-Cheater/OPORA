window.OporaRequestDetail = (() => {
  let inflight = null;
  let leafletMap = null;

  function showStatus(text, isError) {
    const el = document.getElementById("requestMapStatus");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("text-danger", Boolean(isError));
    el.classList.toggle("text-muted", !isError);
  }

  function setExternalLink(lat, lng) {
    const link = document.getElementById("requestMapExternal");
    if (!link) return;
    link.href = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=17/${lat}/${lng}`;
    link.classList.remove("d-none");
  }

  function paintLeaflet(lat, lng, address) {
    const mapNode = document.getElementById("requestMap");
    if (!mapNode) return;
    if (typeof L === "undefined") {
      showStatus("Карта недоступна: не загружен Leaflet.", true);
      return;
    }
    if (leafletMap) {
      leafletMap.remove();
      leafletMap = null;
    }
    mapNode.innerHTML = "";
    const map = L.map(mapNode, { zoomControl: true });
    leafletMap = map;
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
      attribution: "&copy; OpenStreetMap &copy; CARTO",
    }).addTo(map);
    const pos = [lat, lng];
    map.setView(pos, 16);
    L.circleMarker(pos, {
      radius: 9,
      color: "#fff",
      weight: 1,
      fillColor: "#DC3545",
      fillOpacity: 0.95,
    })
      .addTo(map)
      .bindPopup(address || "Точка")
      .openPopup();
    setTimeout(() => map.invalidateSize(), 200);
    setExternalLink(lat, lng);
    showStatus(address ? `Точка: ${address}` : "");
  }

  function readCoords(mapNode) {
    const latRaw = mapNode?.dataset.lat || "";
    const lngRaw = mapNode?.dataset.lng || "";
    const lat = latRaw !== "" ? Number(latRaw) : null;
    const lng = lngRaw !== "" ? Number(lngRaw) : null;
    if (lat === null || lng === null || Number.isNaN(lat) || Number.isNaN(lng)) {
      return null;
    }
    return { lat, lng };
  }

  async function fetchCoords(url) {
    const response = await fetch(url, {
      headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
      throw new Error(data.message || "Не удалось определить координаты");
    }
    return {
      lat: Number(data.latitude),
      lng: Number(data.longitude),
      address: data.address || "",
    };
  }

  async function init() {
    const mapNode = document.getElementById("requestMap");
    if (!mapNode) return;
    if (inflight) return;

    const address = mapNode.dataset.address || "";
    const existing = readCoords(mapNode);
    if (existing) {
      paintLeaflet(existing.lat, existing.lng, address);
      return;
    }

    const url = mapNode.dataset.coordsUrl;
    if (!url) {
      showStatus("Координаты для этой заявки не сохранены.", true);
      return;
    }

    showStatus("Определяем координаты по адресу…");
    inflight = fetchCoords(url)
      .then((coords) => {
        if (Number.isNaN(coords.lat) || Number.isNaN(coords.lng)) {
          throw new Error("Пустой ответ геокодера");
        }
        mapNode.dataset.lat = String(coords.lat);
        mapNode.dataset.lng = String(coords.lng);
        paintLeaflet(coords.lat, coords.lng, coords.address || address);
      })
      .catch((err) => {
        showStatus(err.message || "Не удалось показать карту по адресу.", true);
      })
      .finally(() => {
        inflight = null;
      });
    await inflight;
  }

  function destroy() {
    if (leafletMap) {
      leafletMap.remove();
      leafletMap = null;
    }
    const mapNode = document.getElementById("requestMap");
    if (mapNode) mapNode.innerHTML = "";
  }

  document.addEventListener("DOMContentLoaded", () => {
    init();
  });

  return { init, destroy };
})();
