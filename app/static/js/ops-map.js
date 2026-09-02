window.OporaOpsMap = {
  _map: null,
  init() {
    const mapNode = document.getElementById("opsMap");
    if (!mapNode || typeof L === "undefined") return;

    if (this._map) {
      this._map.remove();
      this._map = null;
    }

    const src = mapNode.getAttribute("data-src");
    if (!src) return;
    const kind = mapNode.getAttribute("data-kind") || "point";
    const statusNode = document.getElementById("opsMapStatus");
    const KIROV = [58.6035, 49.668];
    const COLORS = { request: "#DC3545", defect: "#E6A700", route: "#c45c26" };

    const map = L.map(mapNode, { zoomControl: true });
    this._map = map;
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
      attribution: "&copy; OpenStreetMap &copy; CARTO",
    }).addTo(map);
    map.setView(KIROV, 12);
    const refreshSize = () => map.invalidateSize();
    map.whenReady(refreshSize);
    window.addEventListener("resize", refreshSize);
    setTimeout(refreshSize, 250);

    const layer = L.layerGroup().addTo(map);

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function setStatus(text) {
      if (statusNode) statusNode.textContent = text;
    }

    function typeLabel(type) {
      if (type === "defect") return "Дефект";
      if (type === "request") return "Заявка";
      return type || "";
    }

    function popupHtml(point) {
      const number = point.number ? escapeHtml(point.number) : "";
      const address = escapeHtml(point.address || "");
      const type = escapeHtml(typeLabel(point.type));
      const title = point.url
        ? `<a href="${escapeHtml(point.url)}">${number || type}</a>`
        : `<span class="fw-semibold">${number || type}</span>`;
      return `<div><div>${title}</div><div class="small text-muted mt-1">${type}</div><div class="mt-1">${address}</div></div>`;
    }

    function paint(data) {
      layer.clearLayers();
      const bounds = [];
      const line = [];
      (data.points || []).forEach((point) => {
        const lat = Number(point.lat);
        const lng = Number(point.lng);
        if (Number.isNaN(lat) || Number.isNaN(lng)) return;
        const pos = [lat, lng];
        bounds.push(pos);
        if (kind === "route") {
          line.push(pos);
          const order = point.order || bounds.length;
          L.marker(pos, {
            icon: L.divIcon({
              className: "ops-map-num",
              html: `<span style="display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:#c45c26;color:#fff;font-size:12px;font-weight:700;border:2px solid #fff;">${order}</span>`,
              iconSize: [26, 26],
              iconAnchor: [13, 13],
            }),
          })
            .addTo(layer)
            .bindPopup(popupHtml(point), { maxWidth: 280 });
        } else {
          L.circleMarker(pos, {
            radius: 8,
            color: "#fff",
            weight: 1,
            fillColor: COLORS[point.type] || COLORS.request,
            fillOpacity: 0.92,
          })
            .addTo(layer)
            .bindPopup(popupHtml(point), { maxWidth: 280 });
        }
      });
      if (kind === "route" && line.length > 1) {
        L.polyline(line, { color: "#c45c26", weight: 3, opacity: 0.85 }).addTo(layer);
      }
      if (bounds.length === 1) {
        map.setView(bounds[0], 16);
      } else if (bounds.length > 1) {
        map.fitBounds(bounds, { padding: [28, 28], maxZoom: 16 });
      } else {
        map.setView(KIROV, 12);
      }
      map.invalidateSize();
      const count = bounds.length;
      if (kind === "route") {
        setStatus(count ? `Точек маршрута: ${count}.` : "Добавьте точки с координатами — появится линия маршрута.");
      } else {
        setStatus(count ? `Отметок: ${count}. Нажмите точку — номер и адрес.` : "Пока нет точек с координатами.");
      }
    }

    fetch(src, { headers: { Accept: "application/json" } })
      .then((response) => {
        if (!response.ok) throw new Error("map");
        return response.json();
      })
      .then(paint)
      .catch(() => setStatus("Не удалось загрузить карту."));
  },
};

document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("opsMap")) {
    window.OporaOpsMap.init();
  }
});
