(() => {
  const mapNode = document.getElementById("agreementMap");
  if (!mapNode || typeof L === "undefined") return;

  const src = mapNode.getAttribute("data-src");
  if (!src) return;

  const statusNode = document.getElementById("agreementMapStatus");
  const KIROV = [58.6035, 49.668];
  const COLORS = ["#c45c26", "#1d4ed8", "#0f766e", "#7c3aed", "#b45309", "#be123c", "#0369a1"];

  const map = L.map(mapNode, { zoomControl: true });
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  map.setView(KIROV, 12);

  const layer = L.layerGroup().addTo(map);
  const placed = new Map();
  const colorByCustomer = new Map();
  let rounds = 0;

  function colorFor(customer) {
    const key = customer || "—";
    if (colorByCustomer.has(key)) return colorByCustomer.get(key);
    const color = COLORS[colorByCustomer.size % COLORS.length];
    colorByCustomer.set(key, color);
    return color;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function offsetPoint(lat, lng) {
    const key = `${lat.toFixed(5)},${lng.toFixed(5)}`;
    const n = placed.get(key) || 0;
    placed.set(key, n + 1);
    if (n === 0) return [lat, lng];
    const angle = n * 0.9;
    const dist = 0.0002 * n;
    return [lat + Math.cos(angle) * dist, lng + Math.sin(angle) * dist];
  }

  function popupHtml(point) {
    const number = point.number ? `№ ${escapeHtml(point.number)}` : escapeHtml(point.title);
    const fileLink = point.file_url
      ? `<div class="mt-2"><a href="${escapeHtml(point.file_url)}">Скачать договор</a></div>`
      : "";
    return `
      <div class="agreement-map-popup">
        <div class="fw-semibold">${escapeHtml(point.customer)}</div>
        <div class="mt-1"><a href="${escapeHtml(point.url)}">${number}</a></div>
        ${point.subject ? `<div class="text-muted small mt-1">${escapeHtml(point.subject)}</div>` : ""}
        <div class="small mt-2"><span class="text-muted">Срок:</span> ${escapeHtml(point.period)}</div>
        <div class="mt-2">${escapeHtml(point.address)}</div>
        <div class="small mt-2">
          Крепления: ${point.mounts ?? "—"}
          · Опоры: ${point.poles ?? "—"}
        </div>
        ${point.note ? `<div class="small mt-1">${escapeHtml(point.note)}</div>` : ""}
        ${fileLink}
      </div>
    `;
  }

  function setStatus(text) {
    if (statusNode) statusNode.textContent = text;
  }

  function paint(data) {
    layer.clearLayers();
    placed.clear();
    const bounds = [];
    (data.points || []).forEach((point) => {
      const lat = Number(point.lat);
      const lng = Number(point.lng);
      if (Number.isNaN(lat) || Number.isNaN(lng)) return;
      const pos = offsetPoint(lat, lng);
      bounds.push(pos);
      L.circleMarker(pos, {
        radius: 8,
        color: "#fff",
        weight: 1,
        fillColor: colorFor(point.customer),
        fillOpacity: 0.92,
      })
        .addTo(layer)
        .bindPopup(popupHtml(point), { maxWidth: 320 });
    });
    if (bounds.length === 1) {
      map.setView(bounds[0], 15);
    } else if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [28, 28], maxZoom: 15 });
    } else {
      map.setView(KIROV, 12);
    }
  }

  async function load(backfill) {
    const url = new URL(src, window.location.origin);
    if (backfill) url.searchParams.set("backfill", "1");
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      setStatus("Не удалось загрузить карту.");
      return;
    }
    const data = await response.json();
    paint(data);
    const count = (data.points || []).length;
    const remaining = Number(data.remaining || 0);
    if (remaining > 0) {
      setStatus(`На карте ${count}. Ищем координаты ещё для ${remaining}…`);
      if (rounds < 12) {
        rounds += 1;
        load(true);
      } else {
        setStatus(`На карте ${count}. Без точки: ${remaining} (адрес не нашёлся).`);
      }
    } else if (count) {
      setStatus(`Отметок: ${count}. Нажмите точку — откроется договор.`);
    } else {
      setStatus("Пока нет точек — загрузите договор с адресной программой.");
    }
  }

  load(false);
})();
