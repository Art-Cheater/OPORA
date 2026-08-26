window.OporaRequestDetail = (() => {
  let mapInstance = null;
  let resizeHandler = null;

  function iconBase() {
    const link = document.querySelector('link[href*="leaflet.css"]');
    if (link?.href) {
      return link.href.replace(/leaflet\.css.*$/i, "images/");
    }
    return "/static/vendor/leaflet/images/";
  }

  function destroy() {
    if (resizeHandler) {
      window.removeEventListener("resize", resizeHandler);
      resizeHandler = null;
    }
    if (mapInstance) {
      try {
        mapInstance.remove();
      } catch (_) {
        /* ignore */
      }
      mapInstance = null;
    }
    const mapNode = document.getElementById("requestMap");
    if (mapNode) {
      mapNode._leaflet_id = null;
      mapNode.innerHTML = "";
    }
  }

  function showStatus(text, isError) {
    const el = document.getElementById("requestMapStatus");
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("text-danger", Boolean(isError));
    el.classList.toggle("text-muted", !isError);
  }

  function showOsmFallback(lat, lng, address) {
    const mapNode = document.getElementById("requestMap");
    if (!mapNode) return;
    destroy();
    const delta = 0.012;
    const bbox = `${lng - delta}%2C${lat - delta}%2C${lng + delta}%2C${lat + delta}`;
    const src =
      `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik` +
      `&marker=${lat}%2C${lng}`;
    mapNode.innerHTML =
      `<iframe title="Карта заявки" src="${src}" ` +
      `style="width:100%;height:360px;border:0;border-radius:12px;" loading="lazy"></iframe>`;
    showStatus(address ? `Точка: ${address}` : "Карта OpenStreetMap");
  }

  function readCoords() {
    const mapNode = document.getElementById("requestMap");
    const latRaw =
      mapNode?.dataset.lat || document.getElementById("requestLat")?.value || "";
    const lngRaw =
      mapNode?.dataset.lng || document.getElementById("requestLng")?.value || "";
    const lat = latRaw !== "" ? Number(latRaw) : null;
    const lng = lngRaw !== "" ? Number(lngRaw) : null;
    if (lat === null || lng === null || Number.isNaN(lat) || Number.isNaN(lng)) {
      return null;
    }
    return { lat, lng };
  }

  function buildMap(lat, lng, address) {
    const mapNode = document.getElementById("requestMap");
    if (!mapNode || typeof L === "undefined") return false;

    destroy();

    try {
      const base = iconBase();
      if (typeof L.Icon?.Default?.mergeOptions === "function") {
        L.Icon.Default.mergeOptions({
          iconUrl: `${base}marker-icon.png`,
          iconRetinaUrl: `${base}marker-icon-2x.png`,
          shadowUrl: `${base}marker-shadow.png`,
        });
      }

      mapInstance = L.map(mapNode, { zoomControl: true });
      // OSM напрямую — cartocdn часто недоступен из РФ/корпсети
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap",
      }).addTo(mapInstance);

      mapInstance.setView([lat, lng], 16);
      L.marker([lat, lng]).addTo(mapInstance).bindPopup(address || "Адрес заявки").openPopup();

      resizeHandler = () => mapInstance?.invalidateSize();
      mapInstance.whenReady(resizeHandler);
      window.addEventListener("resize", resizeHandler);
      setTimeout(resizeHandler, 100);
      setTimeout(resizeHandler, 400);
      showStatus("");
      return true;
    } catch (err) {
      console.error("request map:", err);
      showOsmFallback(lat, lng, address);
      return true;
    }
  }

  function init(attempt) {
    const mapNode = document.getElementById("requestMap");
    if (!mapNode) return;

    const coords = readCoords();
    if (!coords) {
      showStatus("Координаты для этой заявки не сохранены.", true);
      return;
    }

    const address =
      mapNode.dataset.address ||
      document.getElementById("requestAddress")?.value ||
      "";

    if (typeof L === "undefined") {
      const n = attempt || 0;
      if (n < 50) {
        window.setTimeout(() => init(n + 1), 80);
        return;
      }
      showOsmFallback(coords.lat, coords.lng, address);
      return;
    }

    if (!buildMap(coords.lat, coords.lng, address)) {
      showOsmFallback(coords.lat, coords.lng, address);
    }
  }

  document.addEventListener("DOMContentLoaded", () => init(0));

  return { init: () => init(0), destroy };
})();
