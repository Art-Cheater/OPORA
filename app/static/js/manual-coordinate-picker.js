/* Ручная точка Request/Defect: MapLibre, адрес меняется только по явному выбору. */
window.OporaManualCoordinatePicker = (() => {
  const KIROV = [49.668, 58.6035];
  const styleUrl = () => document.querySelector('meta[name="opora-maplibre-style"]')?.content || "https://tiles.openfreemap.org/styles/liberty";
  function fields(form) { return { lat: form.querySelector("[data-coordinate-lat]"), lng: form.querySelector("[data-coordinate-lng]"), source: form.querySelector("[name='coordinates_source']"), warning: form.querySelector("[data-coordinate-warning]") }; }
  function setWarning(fieldSet, message, isError = false) {
    if (!fieldSet.warning) return;
    fieldSet.warning.textContent = message;
    fieldSet.warning.classList.toggle("text-danger", isError);
  }
  async function pick(form) {
    const f = fields(form); if (!f.lat || !f.lng) return;
    try {
      if (!window.OporaMap?.ensureAssets) throw new Error("Модуль карты недоступен");
      await window.OporaMap.ensureAssets();
      if (!window.maplibregl?.Map || !window.bootstrap?.Modal) throw new Error("Карта не загрузилась");
    } catch (error) {
      console.error("Не удалось открыть карту выбора точки", error);
      setWarning(f, "Карта выбора точки пока недоступна. Проверьте подключение и повторите попытку.", true);
      return;
    }
    const modal = document.createElement("div"); modal.className = "modal fade"; modal.tabIndex = -1;
    modal.innerHTML = `<div class="modal-dialog modal-lg modal-dialog-centered"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">Укажите точку на карте</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Закрыть"></button></div><div class="modal-body"><div class="opora-coordinate-map" data-point-map></div><p class="small text-muted mt-2 mb-0">Нажмите на карту, чтобы поставить точку.</p></div><div class="modal-footer"><button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Отмена</button><button type="button" class="btn btn-primary" data-save-point disabled>Сохранить точку</button></div></div></div>`;
    document.body.append(modal); const instance = new window.bootstrap.Modal(modal); let map, marker, selected;
    modal.addEventListener("shown.bs.modal", () => {
      try {
        const lat = Number(f.lat.value), lng = Number(f.lng.value), initial = Number.isFinite(lat) && Number.isFinite(lng) ? [lng, lat] : KIROV;
        map = new window.maplibregl.Map({ container: modal.querySelector("[data-point-map]"), style: styleUrl(), center: initial, zoom: Number.isFinite(lat) ? 16 : 12 });
        map.addControl(new window.maplibregl.NavigationControl(), "top-left");
        const place = (coords) => { selected = coords; if (marker) marker.setLngLat(coords); else marker = new window.maplibregl.Marker({ color: "#198754" }).setLngLat(coords).addTo(map); modal.querySelector("[data-save-point]").disabled = false; };
        map.on("click", (event) => place([event.lngLat.lng, event.lngLat.lat])); if (Number.isFinite(lat) && Number.isFinite(lng)) place(initial);
        map.once("load", () => map?.resize());
      } catch (error) {
        console.error("Не удалось инициализировать карту выбора точки", error);
        instance.hide();
        setWarning(f, "Не удалось открыть карту выбора точки. Попробуйте ещё раз.", true);
      }
    }, { once: true });
    modal.querySelector("[data-save-point]").addEventListener("click", () => { if (!selected) return; f.lat.value = selected[1].toFixed(7); f.lng.value = selected[0].toFixed(7); if (f.source) f.source.value = "manual"; setWarning(f, "Точка указана вручную и не будет заменена геокодером."); instance.hide(); });
    modal.addEventListener("hidden.bs.modal", () => { map?.remove(); modal.remove(); }, { once: true }); instance.show();
  }
  function init(form) {
    if (!form || form.dataset.coordinatePickerBound === "1") return; const f = fields(form); if (!f.lat || !f.lng) return; form.dataset.coordinatePickerBound = "1";
    [f.lat, f.lng].forEach((input) => input.addEventListener("input", () => { if (f.source) f.source.value = f.lat.value && f.lng.value ? "manual" : ""; }));
    form.querySelector("[data-coordinate-picker]")?.addEventListener("click", () => pick(form));
    form.querySelector("[data-coordinate-clear]")?.addEventListener("click", () => { f.lat.value = ""; f.lng.value = ""; if (f.source) f.source.value = "cleared"; setWarning(f, "Точка очищена. Сохраните форму, чтобы применить изменение."); });
    form.querySelector("[name='address']")?.addEventListener("input", () => { if (f.source?.value === "manual") setWarning(f, "Адрес изменён. Проверьте точку на карте."); });
  }
  const boot = () => document.querySelectorAll("[data-requests-form]").forEach(init);
  document.addEventListener("DOMContentLoaded", boot); window.addEventListener("opora:navigated", boot);
  return { init, boot };
})();
