/* Ручная точка для Request/Defect. Leaflet загружается только после явного клика. */
(() => {
  const KIROV = [58.6035, 49.668];
  const leafletCss = "/static/vendor/leaflet/leaflet.css";
  const leafletJs = "/static/vendor/leaflet/leaflet.js";

  function loadLeaflet() {
    if (window.L) return Promise.resolve(window.L);
    let css = document.querySelector(`link[href="${leafletCss}"]`);
    if (!css) { css = document.createElement("link"); css.rel = "stylesheet"; css.href = leafletCss; document.head.append(css); }
    return new Promise((resolve, reject) => {
      let script = document.querySelector(`script[src="${leafletJs}"]`);
      if (!script) { script = document.createElement("script"); script.src = leafletJs; document.head.append(script); }
      script.addEventListener("load", () => resolve(window.L), { once: true });
      script.addEventListener("error", () => reject(new Error("leaflet")), { once: true });
    });
  }

  function fields(form) {
    return { lat: form.querySelector("[data-coordinate-lat]"), lng: form.querySelector("[data-coordinate-lng]"), source: form.querySelector("[name='coordinates_source']"), warning: form.querySelector("[data-coordinate-warning]") };
  }

  async function pick(form) {
    const f = fields(form);
    if (!f.lat || !f.lng) return;
    let L;
    try { L = await loadLeaflet(); } catch { alert("Не удалось загрузить карту выбора точки."); return; }
    const modal = document.createElement("div");
    modal.className = "modal fade";
    modal.tabIndex = -1;
    modal.innerHTML = `<div class="modal-dialog modal-lg modal-dialog-centered"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">Укажите точку на карте</h5><button type="button" class="btn-close" data-bs-dismiss="modal"></button></div><div class="modal-body"><div style="height:420px" data-point-map></div><p class="small text-muted mt-2 mb-0">Кликните по нужному месту, затем подтвердите выбор.</p></div><div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Отмена</button><button type="button" class="btn btn-primary" data-save-point disabled>Использовать точку</button></div></div></div>`;
    document.body.append(modal);
    const instance = new bootstrap.Modal(modal);
    let map, marker, selected;
    modal.addEventListener("shown.bs.modal", () => {
      const initialLat = Number(f.lat.value), initialLng = Number(f.lng.value);
      const center = Number.isFinite(initialLat) && Number.isFinite(initialLng) ? [initialLat, initialLng] : KIROV;
      map = L.map(modal.querySelector("[data-point-map]")).setView(center, Number.isFinite(initialLat) ? 16 : 12);
      L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", { maxZoom: 19, subdomains: "abcd", attribution: "&copy; OpenStreetMap &copy; CARTO" }).addTo(map);
      if (Number.isFinite(initialLat) && Number.isFinite(initialLng)) { selected = center; marker = L.marker(center).addTo(map); modal.querySelector("[data-save-point]").disabled = false; }
      map.on("click", event => { selected = [event.latlng.lat, event.latlng.lng]; if (marker) marker.setLatLng(selected); else marker = L.marker(selected).addTo(map); modal.querySelector("[data-save-point]").disabled = false; });
    }, { once: true });
    modal.querySelector("[data-save-point]").addEventListener("click", () => {
      if (!selected) return;
      f.lat.value = selected[0].toFixed(7); f.lng.value = selected[1].toFixed(7);
      if (f.source) f.source.value = "manual";
      if (f.warning) f.warning.textContent = "Точка указана вручную и не будет заменена геокодером.";
      instance.hide();
    });
    modal.addEventListener("hidden.bs.modal", () => { map?.remove(); modal.remove(); }, { once: true });
    instance.show();
  }

  function init(form) {
    if (!form || form.dataset.coordinatePickerBound === "1") return;
    const f = fields(form); if (!f.lat || !f.lng) return;
    form.dataset.coordinatePickerBound = "1";
    [f.lat, f.lng].forEach(input => input.addEventListener("input", () => {
      if (!f.source) return;
      f.source.value = f.lat.value && f.lng.value ? "manual" : "";
    }));
    form.querySelector("[data-coordinate-picker]")?.addEventListener("click", () => pick(form));
    const address = form.querySelector("[name='address']");
    address?.addEventListener("input", () => { if (f.source?.value === "manual" && f.warning) f.warning.textContent = "Адрес изменён. Проверьте точку на карте."; });
  }

  const boot = () => document.querySelectorAll("[data-requests-form]").forEach(init);
  document.addEventListener("DOMContentLoaded", boot);
  window.addEventListener("opora:navigated", boot);
})();
