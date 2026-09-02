window.OporaOpsMap = {
  _map: null,
  _layer: null,
  _routeLayer: null,
  _kind: "point",
  _points: [],

  init() {
    const mapNode = document.getElementById("opsMap");
    if (!mapNode || typeof L === "undefined") return;

    if (this._map) {
      this._map.remove();
      this._map = null;
    }

    const src = mapNode.getAttribute("data-src");
    if (!src) return;
    this._kind = mapNode.getAttribute("data-kind") || "point";
    const statusNode = document.getElementById("opsMapStatus");
    const KIROV = [58.6035, 49.668];
    const COLORS = { request: "#2563EB", defect: "#DC3545", route: "#c45c26" };
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    const tiles = dark
      ? "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
      : "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png";

    const map = L.map(mapNode, { zoomControl: true });
    this._map = map;
    L.tileLayer(tiles, {
      maxZoom: 19,
      subdomains: "abcd",
      attribution: "&copy; OpenStreetMap &copy; CARTO",
    }).addTo(map);
    map.setView(KIROV, 12);
    const refreshSize = () => map.invalidateSize();
    map.whenReady(refreshSize);
    window.addEventListener("resize", refreshSize);
    setTimeout(refreshSize, 250);

    this._layer = L.layerGroup().addTo(map);
    this._routeLayer = L.layerGroup().addTo(map);

    const self = this;

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

    function workbenchPopup(point) {
      const canAdd = mapNode.closest("#workOrderRoot")?.dataset.canEdit === "true";
      const inPlan = Boolean(point.in_plan);
      const addBtn = canAdd && !inPlan
        ? `<button type="button" class="btn btn-sm btn-primary mt-2 js-add-to-plan" data-type="${escapeHtml(point.type)}" data-id="${escapeHtml(point.id)}">Добавить в план работ</button>`
        : inPlan
          ? `<div class="small text-muted mt-2">Уже в плане работ</div>`
          : "";
      const journal = point.journal ? `<div class="small text-muted">${escapeHtml(point.journal)}</div>` : "";
      const status = point.status ? `<div class="small">${escapeHtml(point.status)}</div>` : "";
      const desc = point.description ? `<div class="mt-1">${escapeHtml(point.description)}</div>` : "";
      return `<div class="ops-map-popup">
        <div class="fw-semibold">${escapeHtml(typeLabel(point.type))} ${escapeHtml(point.number || "")}</div>
        ${journal}${status}
        <div class="mt-1">${escapeHtml(point.address || "")}</div>
        ${desc}
        ${addBtn}
      </div>`;
    }

    function popupHtml(point) {
      if (self._kind === "workbench") return workbenchPopup(point);
      const number = point.number ? escapeHtml(point.number) : "";
      const address = escapeHtml(point.address || "");
      const type = escapeHtml(typeLabel(point.type));
      const title = point.url
        ? `<a href="${escapeHtml(point.url)}">${number || type}</a>`
        : `<span class="fw-semibold">${number || type}</span>`;
      return `<div><div>${title}</div><div class="small text-muted mt-1">${type}</div><div class="mt-1">${address}</div></div>`;
    }

    function markerColor(point) {
      return COLORS[point.type] || COLORS.request;
    }

    this._paint = function paint(data) {
      self._layer.clearLayers();
      self._points = data.points || [];
      const bounds = [];
      const line = [];
      self._points.forEach((point) => {
        const lat = Number(point.lat);
        const lng = Number(point.lng);
        if (Number.isNaN(lat) || Number.isNaN(lng)) return;
        const pos = [lat, lng];
        bounds.push(pos);
        if (self._kind === "route") {
          line.push(pos);
          const order = point.order || bounds.length;
          L.marker(pos, {
            icon: L.divIcon({
              className: "ops-map-num",
              html: `<span class="ops-map-num__badge">${order}</span>`,
              iconSize: [26, 26],
              iconAnchor: [13, 13],
            }),
          })
            .addTo(self._layer)
            .bindPopup(popupHtml(point), { maxWidth: 280 });
        } else {
          L.circleMarker(pos, {
            radius: point.in_plan ? 10 : 8,
            color: "#fff",
            weight: point.in_plan ? 2 : 1,
            fillColor: markerColor(point),
            fillOpacity: 0.92,
          })
            .addTo(self._layer)
            .bindPopup(popupHtml(point), { maxWidth: 300 });
        }
      });
      if (self._kind === "route" && line.length > 1) {
        L.polyline(line, { color: COLORS.route, weight: 3, opacity: 0.85 }).addTo(self._layer);
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
      if (self._kind === "route") {
        setStatus(count ? `Точек маршрута: ${count}.` : "Добавьте точки с координатами — появится линия маршрута.");
      } else if (self._kind === "workbench") {
        setStatus(count ? `На карте: ${count}. Красные — дефекты, синие — заявки.` : "Нет точек с координатами.");
      } else {
        setStatus(count ? `Отметок: ${count}. Нажмите точку — номер и адрес.` : "Пока нет точек с координатами.");
      }
    };

    this.reload = function reload(nextSrc) {
      const url = nextSrc || mapNode.getAttribute("data-src");
      if (!url) return Promise.resolve();
      mapNode.setAttribute("data-src", url);
      return fetch(url, { headers: { Accept: "application/json" } })
        .then((response) => {
          if (!response.ok) throw new Error("map");
          return response.json();
        })
        .then((data) => self._paint(data))
        .catch(() => setStatus("Не удалось загрузить карту."));
    };

    this.setRoute = function setRoute(points) {
      self._routeLayer.clearLayers();
      const line = [];
      (points || []).forEach((point) => {
        const lat = Number(point.lat);
        const lng = Number(point.lng);
        if (Number.isNaN(lat) || Number.isNaN(lng)) return;
        const pos = [lat, lng];
        line.push(pos);
        L.marker(pos, {
          icon: L.divIcon({
            className: "ops-map-num",
            html: `<span class="ops-map-num__badge">${point.order || line.length}</span>`,
            iconSize: [26, 26],
            iconAnchor: [13, 13],
          }),
        }).addTo(self._routeLayer);
      });
      if (line.length > 1) {
        L.polyline(line, { color: COLORS.route, weight: 4, opacity: 0.9 }).addTo(self._routeLayer);
        map.fitBounds(line, { padding: [36, 36], maxZoom: 16 });
      }
      map.invalidateSize();
    };

    this.clearRoute = function clearRoute() {
      self._routeLayer.clearLayers();
    };

    mapNode.addEventListener("click", (event) => {
      const btn = event.target.closest(".js-add-to-plan");
      if (!btn) return;
      mapNode.dispatchEvent(
        new CustomEvent("opora:add-to-plan", {
          bubbles: true,
          detail: { type: btn.getAttribute("data-type"), id: btn.getAttribute("data-id") },
        })
      );
    });

    this.reload(src);
  },
};

document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById("opsMap")) {
    window.OporaOpsMap.init();
  }
});
