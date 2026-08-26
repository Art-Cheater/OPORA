window.OporaRequestDetail = (() => {
  let inflight = null;

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

  function paintIframe(lat, lng, address) {
    const mapNode = document.getElementById("requestMap");
    if (!mapNode) return;
    const delta = 0.012;
    const bbox = `${lng - delta}%2C${lat - delta}%2C${lng + delta}%2C${lat + delta}`;
    const src =
      `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik` +
      `&marker=${lat}%2C${lng}`;
    mapNode.innerHTML =
      `<iframe title="Карта заявки" src="${src}" ` +
      `style="width:100%;height:360px;border:0;border-radius:12px;" loading="lazy" ` +
      `referrerpolicy="no-referrer-when-downgrade"></iframe>`;
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
      paintIframe(existing.lat, existing.lng, address);
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
        paintIframe(coords.lat, coords.lng, coords.address || address);
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
    const mapNode = document.getElementById("requestMap");
    if (mapNode) mapNode.innerHTML = "";
  }

  document.addEventListener("DOMContentLoaded", () => {
    init();
  });

  return { init, destroy };
})();
