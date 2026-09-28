/* Обследование объекта: свои опоры + серая подложка городских (IRZ), без записи в мониторинг. */
window.OporaObjectSurvey = (() => {
  const KIND_COLOR = { existing: "#6c757d", planned: "#198754" };
  const TYPE_LABEL = { concrete: "ЖБ", metal: "Металлическая", other: "Другое" };
  const KIND_LABEL = { existing: "Существующая", planned: "Новая" };
  let map, markers = new Map(), geoWatch, cityTimer, root;

  function csrf() {
    return document.querySelector('meta[name="csrf-token"]')?.content || "";
  }
  function headers(json = true) {
    const out = { "X-Requested-With": "XMLHttpRequest", Accept: "application/json", "X-CSRFToken": csrf() };
    if (json) out["Content-Type"] = "application/json";
    return out;
  }
  function canEdit() { return root?.dataset.canEdit === "1"; }
  function status(text, error = false) {
    const el = root?.querySelector("[data-survey-status]");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("text-danger", error);
  }
  function selectedKind() {
    return root?.querySelector('input[name="surveyKind"]:checked')?.value || "existing";
  }
  function selectedType() {
    return root?.querySelector('input[name="surveyType"]:checked')?.value || "metal";
  }
  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }
  function fmtCoord(lat, lng) {
    return `${Number(lat).toFixed(6)}, ${Number(lng).toFixed(6)}`;
  }

  async function api(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", ...options });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.success === false) throw new Error(body.message || "Не удалось сохранить.");
    return body;
  }

  function paintSummary(summary) {
    const el = root?.querySelector("[data-survey-summary]");
    if (!el || !summary) return;
    el.textContent = `Существующих: ${summary.existing} · Новых: ${summary.planned} · Всего: ${summary.total}`;
  }

  function paintList(poles) {
    const body = root?.querySelector("[data-survey-list]");
    if (!body) return;
    const cols = canEdit() ? 5 : 4;
    if (!poles.length) {
      body.innerHTML = `<tr><td colspan="${cols}" class="text-muted">Опор пока нет. Поставьте точку по GPS или кликом по карте.</td></tr>`;
      return;
    }
    body.innerHTML = poles.map((pole) => {
      const kindOpts = Object.entries(KIND_LABEL).map(([value, label]) =>
        `<option value="${value}"${value === pole.kind ? " selected" : ""}>${label}</option>`).join("");
      const typeOpts = Object.entries(TYPE_LABEL).map(([value, label]) =>
        `<option value="${value}"${value === pole.pole_type ? " selected" : ""}>${label}</option>`).join("");
      const kindCell = canEdit()
        ? `<select class="form-select form-select-sm" data-survey-field="kind" data-id="${esc(pole.id)}">${kindOpts}</select>`
        : esc(KIND_LABEL[pole.kind] || pole.kind);
      const typeCell = canEdit()
        ? `<select class="form-select form-select-sm" data-survey-field="pole_type" data-id="${esc(pole.id)}">${typeOpts}</select>`
        : esc(TYPE_LABEL[pole.pole_type] || pole.pole_type);
      const del = canEdit()
        ? `<button type="button" class="btn btn-sm btn-outline-danger" data-survey-del="${esc(pole.id)}" aria-label="Удалить">×</button>`
        : "";
      const acc = pole.accuracy_m != null ? ` · ±${Math.round(pole.accuracy_m)} м` : "";
      return `<tr>
        <td>${pole.sequence}</td>
        <td>${kindCell}</td>
        <td>${typeCell}</td>
        <td class="small">${esc(fmtCoord(pole.lat, pole.lng))}${acc}</td>
        ${canEdit() ? `<td class="text-end">${del}</td>` : ""}
      </tr>`;
    }).join("");
  }

  function markerColor(kind) {
    return KIND_COLOR[kind] || KIND_COLOR.existing;
  }

  function upsertMarker(pole) {
    if (!map || !window.maplibregl) return;
    const prev = markers.get(pole.id);
    prev?.remove();
    const marker = new window.maplibregl.Marker({ color: markerColor(pole.kind), draggable: canEdit() })
      .setLngLat([pole.lng, pole.lat])
      .setPopup(new window.maplibregl.Popup({ offset: 12 }).setText(`№${pole.sequence} · ${KIND_LABEL[pole.kind] || pole.kind} · ${TYPE_LABEL[pole.pole_type] || pole.pole_type}`))
      .addTo(map);
    marker._surveyId = pole.id;
    if (canEdit()) {
      marker.on("dragend", () => {
        const pos = marker.getLngLat();
        patchPole(pole.id, { lat: pos.lat, lng: pos.lng, source: "manual" });
      });
    }
    markers.set(pole.id, marker);
  }

  function clearMarkers() {
    markers.forEach((marker) => marker.remove());
    markers.clear();
  }

  async function reload() {
    const body = await api(root.dataset.polesUrl);
    paintSummary(body.summary);
    paintList(body.poles || []);
    clearMarkers();
    (body.poles || []).forEach(upsertMarker);
    return body;
  }

  async function createAt(lat, lng, extra = {}) {
    if (!canEdit()) return;
    status("Сохраняем опору…");
    try {
      const body = await api(root.dataset.polesUrl, {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({
          kind: selectedKind(),
          pole_type: selectedType(),
          lat,
          lng,
          source: extra.source || "manual",
          accuracy_m: extra.accuracy_m,
        }),
      });
      paintSummary(body.summary);
      if (body.pole) upsertMarker(body.pole);
      await reload();
      const acc = extra.accuracy_m != null ? ` Точность GPS ±${Math.round(extra.accuracy_m)} м.` : "";
      status(`Опора №${body.pole?.sequence || ""} поставлена.${acc}`.trim());
    } catch (error) {
      status(error.message || "Не удалось поставить опору.", true);
    }
  }

  async function patchPole(id, payload) {
    try {
      const body = await api(`${root.dataset.polesUrl.replace(/\.json$/, "")}/${id}.json`, {
        method: "PATCH",
        headers: headers(),
        body: JSON.stringify(payload),
      });
      paintSummary(body.summary);
      if (body.pole) upsertMarker(body.pole);
      await reload();
    } catch (error) {
      status(error.message || "Не удалось изменить опору.", true);
      reload().catch(() => undefined);
    }
  }

  async function deletePole(id) {
    if (!window.confirm("Удалить эту опору с карты обследования?")) return;
    try {
      await api(`${root.dataset.polesUrl.replace(/\.json$/, "")}/${id}/delete`, {
        method: "POST",
        headers: headers(false),
      });
      markers.get(id)?.remove();
      markers.delete(id);
      await reload();
      status("Опора удалена.");
    } catch (error) {
      status(error.message || "Не удалось удалить опору.", true);
    }
  }

  function citySource() {
    if (!map?.getSource("survey-city-poles")) {
      map.addSource("survey-city-poles", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "survey-city-poles",
        type: "circle",
        source: "survey-city-poles",
        minzoom: 14,
        paint: {
          "circle-radius": 4,
          "circle-color": "#94a3b8",
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffffff",
          "circle-opacity": 0.85,
        },
      });
    }
  }

  async function refreshCity() {
    if (!map || map.getZoom() < 13.9 || !root?.dataset.cityUrl) return;
    const b = map.getBounds();
    const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(",");
    try {
      const response = await fetch(`${root.dataset.cityUrl}?bbox=${bbox}`, {
        credentials: "same-origin",
        headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      });
      const data = await response.json().catch(() => ({ features: [] }));
      if (!map?.getSource("survey-city-poles")) return;
      map.getSource("survey-city-poles").setData({
        type: "FeatureCollection",
        features: data.features || [],
      });
    } catch {
      /* подложка необязательна */
    }
  }

  function placeByGps() {
    if (!navigator.geolocation) {
      status("Геолокация в этом браузере недоступна.", true);
      return;
    }
    status("Определяем координаты…");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude, accuracy } = pos.coords;
        map?.easeTo({ center: [longitude, latitude], zoom: Math.max(map.getZoom(), 18) });
        if (accuracy > 20) status(`Точность GPS ±${Math.round(accuracy)} м — точку можно поправить руками.`);
        createAt(latitude, longitude, { source: "gps", accuracy_m: accuracy });
      },
      (error) => {
        const messages = {
          1: "Нет разрешения на геолокацию. Разрешите доступ к местоположению для этого сайта.",
          2: "Координаты недоступны. Выйдите на улицу или проверьте GPS.",
          3: "Не дождались ответа GPS. Повторите попытку.",
        };
        status(messages[error.code] || "Не удалось определить позицию.", true);
      },
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 5000 },
    );
  }

  async function setupMap() {
    const node = document.getElementById("objectSurveyMap");
    const kit = window.OporaMapKit;
    if (!node || !kit?.createMap) {
      status("Карта недоступна.", true);
      return;
    }
    kit.destroyMap(map);
    map = null;
    node.replaceChildren();
    const lat = Number(root.dataset.lat), lng = Number(root.dataset.lng);
    const center = Number.isFinite(lat) && Number.isFinite(lng) ? [lng, lat] : undefined;
    map = await kit.createMap(node, { center, zoom: center ? 17 : undefined, onError: () => status("Не удалось загрузить карту.", true) });
    if (window.maplibregl?.GeolocateControl) {
      map.addControl(new window.maplibregl.GeolocateControl({
        positionOptions: { enableHighAccuracy: true },
        trackUserLocation: true,
        showUserHeading: true,
      }), "top-right");
    }
    citySource();
    map.on("load", () => { citySource(); refreshCity(); });
    map.on("moveend", () => {
      window.clearTimeout(cityTimer);
      cityTimer = window.setTimeout(refreshCity, 280);
    });
    if (canEdit()) {
      map.on("click", (event) => {
        if (event.originalEvent?.target?.closest?.(".maplibregl-marker")) return;
        createAt(event.lngLat.lat, event.lngLat.lng, { source: "manual" });
      });
    }
    await reload();
    const coords = [...markers.values()].map((marker) => marker.getLngLat());
    if (coords.length > 1) {
      const bounds = coords.reduce((value, coord) => value.extend(coord), new window.maplibregl.LngLatBounds(coords[0], coords[0]));
      map.fitBounds(bounds, { padding: 48, maxZoom: 18 });
    }
    status(canEdit() ? "Клик по карте или кнопка GPS — поставить опору." : "Просмотр обследования.");
  }

  function bindList() {
    root?.querySelector("[data-survey-list]")?.addEventListener("change", (event) => {
      const field = event.target.closest("[data-survey-field]");
      if (!field) return;
      const payload = { [field.dataset.surveyField]: field.value };
      patchPole(field.dataset.id, payload);
    });
    root?.querySelector("[data-survey-list]")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-survey-del]");
      if (btn) deletePole(btn.getAttribute("data-survey-del"));
    });
    root?.querySelector("[data-survey-gps]")?.addEventListener("click", placeByGps);
  }

  async function init() {
    const next = document.querySelector("[data-object-survey]");
    if (!next || next.dataset.bound === "1") return;
    root = next;
    root.dataset.bound = "1";
    bindList();
    try {
      await setupMap();
    } catch (error) {
      status(error.message || "Не удалось открыть карту обследования.", true);
    }
  }

  function destroy() {
    window.clearTimeout(cityTimer);
    if (geoWatch != null && navigator.geolocation) navigator.geolocation.clearWatch(geoWatch);
    geoWatch = null;
    cityTimer = null;
    clearMarkers();
    window.OporaMapKit?.destroyMap?.(map);
    map = null;
    if (root) delete root.dataset.bound;
    root = null;
  }

  document.addEventListener("DOMContentLoaded", init);
  window.addEventListener("opora:navigated", init);
  window.addEventListener("opora:before-navigate", destroy);
  return { init, destroy };
})();
