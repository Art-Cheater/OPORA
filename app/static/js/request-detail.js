/* Read-only карта Request/Defect на MapLibre. */
window.OporaRequestDetail = (() => {
  let inflight, detailMap;
  function status(text, error = false) { const el = document.getElementById("requestMapStatus"); if (el) { el.textContent = text || ""; el.classList.toggle("text-danger", error); } }
  function external(lat, lng) { const link = document.getElementById("requestMapExternal"); if (link) { link.href = `https://www.openstreetmap.org/?mlat=${lat}&mlon=${lng}#map=17/${lat}/${lng}`; link.classList.remove("d-none"); } }
  async function paint(lat, lng, address) {
    const node = document.getElementById("requestMap"); if (!node) return;
    try { await window.OporaMap.ensureAssets(); } catch { status("Карта недоступна: не удалось загрузить MapLibre.", true); return; }
    detailMap?.remove(); node.replaceChildren();
    const style = document.querySelector('meta[name="opora-maplibre-style"]')?.content || "https://tiles.openfreemap.org/styles/liberty";
    detailMap = new window.maplibregl.Map({ container: node, style, center: [lng, lat], zoom: 16 });
    detailMap.addControl(new window.maplibregl.NavigationControl(), "top-left");
    new window.maplibregl.Marker({ color: "#dc3545" }).setLngLat([lng, lat]).setPopup(new window.maplibregl.Popup().setText(address || "Точка")).addTo(detailMap);
    external(lat, lng); status(address ? `Точка: ${address}` : "");
  }
  function coords(node) { const lat = Number(node?.dataset.lat), lng = Number(node?.dataset.lng); return Number.isFinite(lat) && Number.isFinite(lng) ? { lat, lng } : null; }
  async function init() {
    const node = document.getElementById("requestMap"); if (!node || inflight) return;
    const current = coords(node), address = node.dataset.address || "";
    if (current) return paint(current.lat, current.lng, address);
    if (!node.dataset.coordsUrl) return status("Координаты для этой работы не сохранены.", true);
    status("Определяем координаты по адресу…");
    inflight = fetch(node.dataset.coordsUrl, { headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" } })
      .then((response) => response.json().then((body) => ({ response, body })))
      .then(({ response, body }) => { if (!response.ok || !body.success) throw new Error(body.message || "Не удалось определить координаты"); node.dataset.lat = body.latitude; node.dataset.lng = body.longitude; return paint(Number(body.latitude), Number(body.longitude), body.address || address); })
      .catch((error) => status(error.message || "Не удалось показать карту по адресу.", true)).finally(() => inflight = null);
    return inflight;
  }
  function destroy() { detailMap?.remove(); detailMap = null; inflight = null; }
  document.addEventListener("DOMContentLoaded", init); window.addEventListener("opora:navigated", init); window.addEventListener("opora:before-navigate", destroy);
  return { init, destroy };
})();
