/* Ручная точка Request/Defect: MapLibre, адрес меняется только по явному выбору. */
(() => {
  const KIROV = [49.668, 58.6035];
  const styleUrl = () => document.querySelector('meta[name="opora-maplibre-style"]')?.content || "https://tiles.openfreemap.org/styles/liberty";
  function fields(form) { return { lat: form.querySelector("[data-coordinate-lat]"), lng: form.querySelector("[data-coordinate-lng]"), source: form.querySelector("[name='coordinates_source']"), warning: form.querySelector("[data-coordinate-warning]") }; }
  async function pick(form) {
    const f = fields(form); if (!f.lat || !f.lng) return;
    try { await window.OporaMap?.ensureAssets?.(); } catch { alert("Не удалось загрузить карту выбора точки."); return; }
    const modal = document.createElement("div"); modal.className = "modal fade"; modal.tabIndex = -1;
    modal.innerHTML = `<div class="modal-dialog modal-lg modal-dialog-centered"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">Укажите точку на карте</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button></div><div class="modal-body"><div class="opora-coordinate-map" data-point-map></div><p class="small text-muted mt-2 mb-0">Кликните по нужному месту, затем подтвердите выбор.</p><p class="small text-muted mb-0" data-reverse-address hidden></p></div><div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Отмена</button><button type="button" class="btn btn-primary" data-save-point disabled>Использовать точку</button></div></div></div>`;
    document.body.append(modal); const instance = new bootstrap.Modal(modal); let map, marker, selected;
    modal.addEventListener("shown.bs.modal", () => {
      const lat = Number(f.lat.value), lng = Number(f.lng.value), initial = Number.isFinite(lat) && Number.isFinite(lng) ? [lng, lat] : KIROV;
      map = new window.maplibregl.Map({ container: modal.querySelector("[data-point-map]"), style: styleUrl(), center: initial, zoom: Number.isFinite(lat) ? 16 : 12 });
      map.addControl(new window.maplibregl.NavigationControl(), "top-left");
      const place = (coords) => { selected = coords; if (marker) marker.setLngLat(coords); else marker = new window.maplibregl.Marker({ color: "#198754" }).setLngLat(coords).addTo(map); modal.querySelector("[data-save-point]").disabled = false; };
      map.on("click", (event) => place([event.lngLat.lng, event.lngLat.lat])); if (Number.isFinite(lat) && Number.isFinite(lng)) place(initial);
    }, { once: true });
    modal.querySelector("[data-save-point]").addEventListener("click", () => { if (!selected) return; f.lat.value = selected[1].toFixed(7); f.lng.value = selected[0].toFixed(7); if (f.source) f.source.value = "manual"; if (f.warning) f.warning.textContent = "Точка указана вручную и не будет заменена геокодером."; instance.hide(); });
    modal.addEventListener("hidden.bs.modal", () => { map?.remove(); modal.remove(); }, { once: true }); instance.show();
  }
  function init(form) {
    if (!form || form.dataset.coordinatePickerBound === "1") return; const f = fields(form); if (!f.lat || !f.lng) return; form.dataset.coordinatePickerBound = "1";
    [f.lat, f.lng].forEach((input) => input.addEventListener("input", () => { if (f.source) f.source.value = f.lat.value && f.lng.value ? "manual" : ""; }));
    form.querySelector("[data-coordinate-picker]")?.addEventListener("click", () => pick(form));
    form.querySelector("[name='address']")?.addEventListener("input", () => { if (f.source?.value === "manual" && f.warning) f.warning.textContent = "Адрес изменён. Проверьте точку на карте."; });
  }
  const boot = () => document.querySelectorAll("[data-requests-form]").forEach(init);
  document.addEventListener("DOMContentLoaded", boot); window.addEventListener("opora:navigated", boot);
})();
