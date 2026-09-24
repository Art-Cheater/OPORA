/* IRZ · Мониторинг: карта MapLibre (лампа статуса + плашка ШУНО, слой опор), список устройств и экран-дисплей. */
(function () {
  const LAMP = {ON: '#22c55e', OFF: '#9ca3af', PROBLEM: '#facc15', CRITICAL: '#dc2626'};
  const LABELS = {ON: 'Горит', OFF: 'Не горит', PROBLEM: 'Проблема', CRITICAL: 'Критическая проблема'};
  const PRIORITY = {CRITICAL: 0, PROBLEM: 1, OFF: 2, ON: 3};
  const BOX = {IP: ['#fbcfe8', '#db2777'], PP: ['#f8fafc', '#64748b'], OTHER: ['#bbf7d0', '#16a34a']};
  const KIROV = [49.668, 58.6035];
  const DEFAULT_STYLE = 'https://tiles.openfreemap.org/styles/liberty';
  const SOURCE = 'irz-devices';
  const POLES = 'irz-poles';
  const DEVICE_LAYERS = ['irz-halo', 'irz-boxes', 'irz-lamps'];
  const POLE_MIN_ZOOM = 14;

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const normalize = (v) => String(v ?? '').toLocaleLowerCase('ru-RU').replace(/ё/g, 'е').trim();
  const number = (v, digits = 1) => (v === null || v === undefined || v === '' || !Number.isFinite(Number(v)))
    ? '—' : Number(v).toLocaleString('ru-RU', {maximumFractionDigits: digits});
  const clock = (iso) => iso ? new Date(iso).toLocaleTimeString('ru-RU', {hour: '2-digit', minute: '2-digit'}) : '—';

  function ago(iso) {
    if (!iso) return 'нет данных';
    const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return 'только что';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} мин назад`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} ч назад`;
    return new Date(iso).toLocaleDateString('ru-RU');
  }
  function silence(seconds) {
    const minutes = Math.floor(seconds / 60), hours = Math.floor(minutes / 60);
    if (minutes < 1) return 'меньше минуты';
    return hours ? `${hours} ч ${minutes % 60} мин` : `${minutes} мин`;
  }
  const status = (item) => item.operational_status || 'PROBLEM';
  const noData = (item) => (item.no_data_seconds === null || item.no_data_seconds === undefined) ? '' : `Нет данных ${silence(item.no_data_seconds)}`;
  const subtitle = (item) => item.name ? `ATM21 · IMEI ${item.imei}` : 'Название не задано';
  const meterLine = (item) => item.meter ? `${item.meter.model} · № ${item.meter.serial}` : 'Счётчик: не определён';
  const lamp = (item) => `<span class="irz-lamp irz-lamp--${status(item)}" aria-hidden="true"></span>`;

  function matches(item, needle) {
    if (!needle) return true;
    return [item.title, item.imei, item.meter?.serial, item.address].some((part) => normalize(part).includes(needle));
  }

  function popupHtml(item, href, action) {
    const s = item.summary || {};
    const voltage = ['u_a', 'u_b', 'u_c'].some((key) => s[key] !== undefined)
      ? `<div class="irz-popup__row"><span>U A / B / C</span><strong>${number(s.u_a)} / ${number(s.u_b)} / ${number(s.u_c)} В</strong></div>` : '';
    const gap = noData(item);
    return `<div class="irz-popup__item">
      <div class="irz-popup__title">${lamp(item)}${esc(item.title)}</div>
      <div class="irz-popup__sub">${esc(subtitle(item))}</div>
      <div class="irz-popup__sub">${esc(meterLine(item))}</div>
      <div class="irz-popup__row"><span>Освещение</span><strong>${esc(LABELS[status(item)])}</strong></div>
      ${gap || item.problem ? `<div class="irz-popup__problem">${esc([gap, item.problem].filter(Boolean).join(' · '))}</div>` : ''}
      <div class="irz-popup__row"><span>Ответ Mercury</span><strong>${esc(ago(item.last_successful_meter_response))}</strong></div>
      <div class="irz-popup__row"><span>Связь ATM21</span><strong>${item.online ? 'online' : 'offline'} · ${esc(ago(item.last_seen_at))}</strong></div>
      ${voltage}
      ${href ? `<a class="btn btn-sm btn-primary w-100 mt-2" href="${esc(href)}">${esc(action)}</a>` : ''}
    </div>`;
  }

  function polePopupHtml(pole, href) {
    return `<div class="irz-popup__item">
      <div class="irz-popup__title"><span class="irz-pole-mark" aria-hidden="true"></span>Опора № ${esc(pole.pole_number)}</div>
      <div class="irz-popup__sub">${esc(pole.luminaire_name || 'Светильник не указан')}</div>
      <div class="irz-popup__row"><span>Количество</span><strong>${esc(pole.quantity ?? '—')}</strong></div>
      ${href ? `<a class="btn btn-sm btn-outline-primary w-100 mt-2" href="${esc(href)}">Открыть карточку</a>` : ''}
    </div>`;
  }

  function canvas(width, height) {
    const ratio = Math.max(1, Math.ceil(window.devicePixelRatio || 1));
    const node = document.createElement('canvas');
    node.width = Math.round(width * ratio); node.height = Math.round(height * ratio);
    const ctx = node.getContext('2d'); ctx.scale(ratio, ratio);
    return {ctx, ratio, done: () => ctx.getImageData(0, 0, node.width, node.height)};
  }

  function boxIcon(fill, stroke) {
    const size = 24, radius = 7, line = 1.5, {ctx, ratio, done} = canvas(size, size);
    const x = line / 2, y = line / 2, w = size - line, h = size - line;
    ctx.beginPath();
    ctx.moveTo(x + radius, y);
    ctx.arcTo(x + w, y, x + w, y + h, radius);
    ctx.arcTo(x + w, y + h, x, y + h, radius);
    ctx.arcTo(x, y + h, x, y, radius);
    ctx.arcTo(x, y, x + w, y, radius);
    ctx.closePath();
    ctx.fillStyle = fill; ctx.fill();
    ctx.lineWidth = line; ctx.strokeStyle = stroke; ctx.stroke();
    const px = (value) => Math.round(value * ratio);
    return {image: done(), options: {pixelRatio: ratio, stretchX: [[px(radius + 1), px(size - radius - 1)]],
      stretchY: [[px(radius + 1), px(size - radius - 1)]], content: [px(6), px(4), px(size - 6), px(size - 4)]}};
  }

  function triangleIcon(size) {
    const pad = 1.5, {ctx, ratio, done} = canvas(size + pad * 2, size + pad * 2);
    ctx.beginPath();
    ctx.moveTo(pad + size / 2, pad);
    ctx.lineTo(pad + size, pad + size * 0.9);
    ctx.lineTo(pad, pad + size * 0.9);
    ctx.closePath();
    ctx.fillStyle = '#475569'; ctx.fill();
    ctx.lineJoin = 'round'; ctx.lineWidth = 1.5; ctx.strokeStyle = '#ffffff'; ctx.stroke();
    return {image: done(), options: {pixelRatio: ratio}};
  }

  function styleFont(map) {
    for (const layer of map.getStyle()?.layers || []) {
      const font = layer.layout?.['text-font'];
      if (Array.isArray(font) && font.length && font.every((part) => typeof part === 'string')) return font;
    }
    return ['Noto Sans Regular'];
  }

  function createMap(node, options) {
    let map = null, lib = null, observer = null, popup = null, popupIds = [], items = [], byId = new Map();
    let loaded = false, destroyed = false, fitted = false, selectedId = null, hoverId = null;
    let labels = options.labels !== false, devices = options.devices !== false;
    const poleOptions = options.poles || null;
    let poles = Boolean(poleOptions?.enabled), poleTimer = 0, poleKey = '', poleAbort = null;
    const lampRadius = options.lampRadius, textSize = options.textSize;
    const loader = window.OporaMapKit?.ensureAssets || window.OporaMap?.ensureAssets;
    const ready = (loader ? loader() : Promise.reject(new Error('MapLibre loader unavailable'))).then((maplibre) => {
      if (destroyed) return null;
      lib = maplibre;
      const cfg = window.OporaMapKit?.readConfig?.() || {};
      const style = cfg.styleUrl || document.querySelector('meta[name="opora-maplibre-style"]')?.content || DEFAULT_STYLE;
      const center = options.center || cfg.center || KIROV;
      map = new lib.Map({container: node, style, center, zoom: options.zoom || 11, attributionControl: true, minZoom: cfg.minZoom, maxZoom: cfg.maxZoom});
      map.addControl(new lib.NavigationControl({showCompass: false}), 'top-left');
      map.on('error', (event) => { if (event?.error && !loaded) options.onError?.('Не удалось загрузить подложку карты.'); });
      if (window.ResizeObserver) { observer = new ResizeObserver(() => map?.resize()); observer.observe(node); }
      return new Promise((resolve) => map.on('load', () => {
        if (destroyed) return;
        addLayers(); bind(); loaded = true; applyVisibility(); render(); refreshPoles(); resolve(map);
      }));
    }).catch(() => { options.onError?.('Карта недоступна: не удалось загрузить MapLibre.'); return null; });

    function addLayers() {
      Object.entries(BOX).forEach(([type, [fill, stroke]]) => {
        const icon = boxIcon(fill, stroke);
        map.addImage(`irz-box-${type}`, icon.image, icon.options);
      });
      const triangle = triangleIcon(options.poleSize || 10);
      map.addImage('irz-pole', triangle.image, triangle.options);
      map.addSource(POLES, {type: 'geojson', data: {type: 'FeatureCollection', features: []}});
      map.addSource(SOURCE, {type: 'geojson', data: collection()});
      if (options.focusPoint) {
        map.addSource('irz-focus', {type: 'geojson', data: {type: 'Point', coordinates: options.focusPoint}});
        map.addLayer({id: 'irz-focus', type: 'circle', source: 'irz-focus',
          paint: {'circle-radius': 14, 'circle-color': 'rgba(37, 99, 235, 0.15)', 'circle-stroke-color': '#2563eb', 'circle-stroke-width': 2.5}});
      }
      map.addLayer({id: 'irz-poles', type: 'symbol', source: POLES, minzoom: poleOptions?.minZoom || POLE_MIN_ZOOM,
        layout: {'icon-image': 'irz-pole', 'icon-allow-overlap': true, 'icon-ignore-placement': true,
          visibility: poles ? 'visible' : 'none'}});
      map.addLayer({id: 'irz-halo', type: 'circle', source: SOURCE, filter: ['in', ['get', 'id'], ['literal', []]],
        paint: {'circle-radius': lampRadius + 5, 'circle-color': 'rgba(37, 99, 235, 0.18)',
          'circle-stroke-color': '#2563eb', 'circle-stroke-width': 2.5}});
      map.addLayer({id: 'irz-boxes', type: 'symbol', source: SOURCE, minzoom: options.boxMinZoom || 0,
        layout: {'text-field': ['get', 'title'], 'text-font': styleFont(map), 'text-size': textSize,
          'text-anchor': 'top', 'text-offset': [0, (lampRadius + 5) / textSize], 'text-max-width': 11,
          'text-line-height': 1.1, 'text-padding': 2, 'icon-image': ['concat', 'irz-box-', ['get', 'type']],
          'icon-text-fit': 'both', 'symbol-sort-key': ['get', 'priority'], visibility: labels && devices ? 'visible' : 'none'},
        paint: {'text-color': '#111827'}});
      map.addLayer({id: 'irz-lamps', type: 'circle', source: SOURCE,
        layout: {'circle-sort-key': ['-', 10, ['get', 'priority']]},
        paint: {'circle-radius': lampRadius, 'circle-color': ['match', ['get', 'status'],
          'ON', LAMP.ON, 'OFF', LAMP.OFF, 'CRITICAL', LAMP.CRITICAL, LAMP.PROBLEM],
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': Math.max(1.5, lampRadius / 3.5)}});
    }
    function hits(point, layers) {
      const pad = 4, box = [[point.x - pad, point.y - pad], [point.x + pad, point.y + pad]];
      const visible = layers.filter((id) => map.getLayer(id) && map.getLayoutProperty(id, 'visibility') !== 'none');
      return visible.length ? map.queryRenderedFeatures(box, {layers: visible}) : [];
    }
    function bind() {
      ['irz-lamps', 'irz-boxes', 'irz-poles'].forEach((id) => {
        map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
      });
      map.on('click', (event) => {
        const found = [...new Set(hits(event.point, ['irz-lamps', 'irz-boxes']).map((feature) => feature.properties.id))]
          .map((id) => byId.get(id)).filter(Boolean);
        if (found.length) {
          openPopup(found);
          setSelected(found[0].id);
          options.onSelect?.(found[0]);
          return;
        }
        const pole = hits(event.point, ['irz-poles'])[0];
        if (pole) openPolePopup(pole.properties);
      });
      map.on('moveend', () => { window.clearTimeout(poleTimer); poleTimer = window.setTimeout(refreshPoles, 300); });
    }
    async function refreshPoles() {
      if (!loaded || !poles || !poleOptions?.url || map.getZoom() < (poleOptions.minZoom || POLE_MIN_ZOOM) - 0.01) return;
      const b = map.getBounds(), key = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(5)).join(',');
      if (key === poleKey) return;
      poleAbort?.abort();
      poleAbort = new AbortController();
      try {
        const data = await fetchJson(`${poleOptions.url}?bbox=${key}`, {signal: poleAbort.signal});
        if (destroyed || !map) return;
        poleKey = key;
        map.getSource(POLES).setData(data);
      } catch (error) {
        if (error.name !== 'AbortError') options.onError?.('Опоры не загрузились — повторим при следующем перемещении карты.');
      }
    }
    function collection() {
      return {type: 'FeatureCollection', features: items.filter((item) => item.has_coordinates).map((item) => ({
        type: 'Feature', geometry: {type: 'Point', coordinates: [item.longitude, item.latitude]},
        properties: {id: item.id, status: status(item), title: item.title, type: BOX[item.cabinet_type] ? item.cabinet_type : 'OTHER',
          priority: (PRIORITY[status(item)] ?? 1) + (item.cabinet_type === 'IP' || item.cabinet_type === 'PP' ? 0 : 4)},
      }))};
    }
    function openPopup(list) {
      popup?.remove();
      popupIds = list.slice(0, 5).map((item) => item.id);
      popup = new lib.Popup({maxWidth: '320px', offset: lampRadius + 6, className: 'irz-popup'})
        .setLngLat([list[0].longitude, list[0].latitude]).setHTML(popupContent()).addTo(map);
      popup.on('close', () => { popupIds = []; });
    }
    function openPolePopup(pole) {
      popup?.remove();
      popupIds = [];
      const href = poleOptions.detailTemplate ? poleOptions.detailTemplate.replace('POLE_ID', encodeURIComponent(pole.id)) : null;
      popup = new lib.Popup({maxWidth: '300px', offset: 8, className: 'irz-popup'})
        .setLngLat([pole.lon, pole.lat]).setHTML(polePopupHtml(pole, href)).addTo(map);
    }
    function popupContent() {
      return popupIds.map((id) => byId.get(id)).filter(Boolean).map(options.popupHtml).join('<hr class="my-2">');
    }
    function updateHighlight() {
      if (!loaded) return;
      map.setFilter('irz-halo', ['in', ['get', 'id'], ['literal', [selectedId, hoverId].filter(Boolean)]]);
    }
    function setSelected(id) { selectedId = id; updateHighlight(); }
    function fitAll() {
      const coords = items.filter((item) => item.has_coordinates).map((item) => [item.longitude, item.latitude]);
      if (!coords.length) return;
      if (coords.length === 1) { map.jumpTo({center: coords[0], zoom: 15}); return; }
      const bounds = coords.reduce((value, coord) => value.extend(coord), new lib.LngLatBounds(coords[0], coords[0]));
      map.fitBounds(bounds, {padding: 48, maxZoom: 15, duration: 0});
    }
    function render({fit = false} = {}) {
      if (!loaded) return;
      map.getSource(SOURCE).setData(collection());
      updateHighlight();
      if (options.fit !== false && (fit || !fitted)) { fitAll(); fitted = items.some((item) => item.has_coordinates); }
      if (popup && popupIds.length) {
        if (popupIds.some((id) => byId.has(id))) popup.setHTML(popupContent());
        else popup.remove();
      }
    }
    function applyVisibility() {
      if (!loaded) return;
      map.setLayoutProperty('irz-lamps', 'visibility', devices ? 'visible' : 'none');
      map.setLayoutProperty('irz-halo', 'visibility', devices ? 'visible' : 'none');
      map.setLayoutProperty('irz-boxes', 'visibility', devices && labels ? 'visible' : 'none');
      map.setLayoutProperty('irz-poles', 'visibility', poles ? 'visible' : 'none');
    }
    return {
      ready,
      setItems(list, {fit = false} = {}) { items = list; byId = new Map(list.map((item) => [item.id, item])); render({fit}); },
      focus(id) {
        const item = byId.get(id);
        setSelected(id);
        if (!loaded || !item?.has_coordinates) return;
        map.flyTo({center: [item.longitude, item.latitude], zoom: Math.max(map.getZoom(), 16), duration: 600,
          offset: [0, Math.round(node.clientHeight / 4)]});
        openPopup([item]);
      },
      highlight(id) { hoverId = id; updateHighlight(); },
      select(id) { setSelected(id); },
      setLabels(visible) { labels = visible; applyVisibility(); },
      setDevices(visible) { devices = visible; applyVisibility(); },
      setPoles(visible) { poles = visible; applyVisibility(); refreshPoles(); },
      showPoint(lngLat, zoom) { if (loaded) map.jumpTo({center: lngLat, zoom}); },
      destroy() {
        destroyed = true; window.clearTimeout(poleTimer); poleAbort?.abort();
        observer?.disconnect(); popup?.remove(); map?.remove(); map = null;
      },
    };
  }

  async function fetchJson(url, init = {}) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}, ...init});
    const type = response.headers.get('content-type') || '';
    if (response.redirected || !type.includes('json')) throw new Error('SESSION_EXPIRED');
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.message || payload?.error || `HTTP ${response.status}`);
    return payload;
  }

  function stored(key, fallback) {
    try {
      const value = window.localStorage.getItem(key);
      return value === null ? fallback : value === '1';
    } catch (error) { return fallback; }
  }
  function store(key, value) {
    try { window.localStorage.setItem(key, value ? '1' : '0'); } catch (error) { /* private mode */ }
  }

  function bootDirectory() {
    const root = document.querySelector('[data-irz-directory]');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    const q = (selector) => root.querySelector(selector);
    const list = q('[data-list]'), search = q('[data-search]'), note = q('[data-message]'), empty = q('[data-map-empty]');
    const canEdit = root.dataset.canEdit === '1', refreshMs = 30000;
    const detailUrl = (id) => root.dataset.detailTemplate.replace('DEVICE_ID', encodeURIComponent(id));
    const go = (href) => (window.OporaNav ? window.OporaNav.go(href) : window.location.assign(href));
    let items = [], shown = [], filter = 'all', needle = '', selectedId = new URLSearchParams(window.location.search).get('device');
    let focusPending = Boolean(selectedId), stopped = false, timer = 0, searchTimer = 0;
    const devicesToggle = q('[data-layer-devices]'), polesToggle = q('[data-layer-poles]');
    devicesToggle.checked = stored('irz-layer-devices', true);
    polesToggle.checked = stored('irz-layer-poles', false);
    const map = createMap(q('[data-map-canvas]'), {
      lampRadius: 6, textSize: 12, boxMinZoom: 12, poleSize: 10, devices: devicesToggle.checked,
      poles: {url: root.dataset.polesUrl, detailTemplate: root.dataset.poleTemplate, enabled: polesToggle.checked},
      popupHtml: (item) => popupHtml(item, detailUrl(item.id), 'Открыть'),
      onSelect: (item) => selectRow(item.id, true),
      onError: (text) => showMessage(text, 'warning'),
    });
    devicesToggle.addEventListener('change', () => { store('irz-layer-devices', devicesToggle.checked); map.setDevices(devicesToggle.checked); });
    polesToggle.addEventListener('change', () => { store('irz-layer-poles', polesToggle.checked); map.setPoles(polesToggle.checked); });

    function showMessage(text, kind = 'secondary') {
      note.hidden = !text; note.className = `irz-note irz-note--${kind} mb-2`; note.textContent = text || '';
    }
    function passes(item) {
      const code = filter.toUpperCase();
      if (LABELS[code] && status(item) !== code) return false;
      if (filter === 'online' && !item.online) return false;
      if (filter === 'offline' && item.online) return false;
      if (filter === 'no_coordinates' && item.has_coordinates) return false;
      return matches(item, needle);
    }
    function rowHtml(item) {
      const code = status(item), href = esc(detailUrl(item.id)), gap = noData(item);
      const where = item.has_coordinates ? '' : '<span class="irz-row__nocoords">Координаты не заданы</span>';
      return `<div class="irz-row${item.id === selectedId ? ' is-selected' : ''}" role="listitem" data-id="${esc(item.id)}">
        ${lamp(item)}
        <a class="irz-row__main" href="${href}">
          <span class="irz-row__title"><span class="irz-type irz-type--${esc(item.cabinet_type || 'OTHER')}"></span>${esc(item.title)}</span>
          <span class="irz-row__sub">${esc(subtitle(item))}</span>
          <span class="irz-row__sub">${esc(meterLine(item))}${where}</span>
        </a>
        <span class="irz-row__side">
          <span class="irz-status irz-status--${code}"${item.problem ? ` title="${esc(item.problem)}"` : ''}>${esc(LABELS[code])}</span>
          <span class="irz-row__time" title="Последний успешный ответ Mercury">${esc(gap || `Mercury: ${ago(item.last_successful_meter_response)}`)}</span>
          <span class="irz-row__time" title="Транспортная связь ATM21 с сервером">ATM21 ${item.online ? 'online' : 'offline'}</span>
          ${!item.has_coordinates && canEdit ? `<a class="irz-row__locate" href="${href}">Указать расположение</a>` : ''}
        </span>
      </div>`;
    }
    function renderCounters(counters) {
      root.querySelectorAll('[data-count]').forEach((node) => { node.textContent = counters?.[node.dataset.count] ?? 0; });
    }
    function render({fit = false} = {}) {
      shown = items.filter(passes);
      list.innerHTML = shown.length ? shown.map(rowHtml).join('')
        : `<div class="irz-list__empty">${items.length ? 'Ничего не найдено' : 'Устройства ATM21 пока не подключались'}</div>`;
      q('[data-shown]').textContent = `Показано ${shown.length} из ${items.length}`;
      map.setItems(shown, {fit});
      empty.hidden = shown.some((item) => item.has_coordinates) || !items.length;
    }
    function selectRow(id, scroll) {
      selectedId = id;
      list.querySelectorAll('.irz-row.is-selected').forEach((node) => node.classList.remove('is-selected'));
      const row = list.querySelector(`.irz-row[data-id="${CSS.escape(id)}"]`);
      row?.classList.add('is-selected');
      if (scroll) row?.scrollIntoView({block: 'nearest', behavior: 'smooth'});
    }
    function focusItem(item) {
      selectRow(item.id, true);
      if (item.has_coordinates) map.focus(item.id);
      else map.select(item.id);
    }
    async function load() {
      const payload = await fetchJson(root.dataset.apiUrl);
      items = payload.items || [];
      renderCounters(payload.counters);
      render();
      if (payload.gateway !== 'online') showMessage('Шлюз связи недоступен: связь ATM21 неизвестна, показаны сохранённые данные.', 'warning');
      else showMessage('');
      if (focusPending) {
        focusPending = false;
        map.ready.then(() => {
          const item = items.find((entry) => entry.id === selectedId);
          if (item && !stopped) focusItem(item);
        });
      }
    }
    async function tick() {
      try { await load(); }
      catch (error) { showMessage(error.message === 'SESSION_EXPIRED' ? 'Сессия истекла — обновите страницу и войдите снова.' : `Список недоступен: ${error.message}`, 'danger'); }
      finally { if (!stopped) timer = window.setTimeout(tick, refreshMs); }
    }

    root.querySelectorAll('[data-filter]').forEach((button) => button.addEventListener('click', () => {
      filter = button.dataset.filter;
      root.querySelectorAll('[data-filter]').forEach((node) => node.classList.toggle('active', node === button));
      render({fit: true});
    }));
    search.addEventListener('input', () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        needle = normalize(search.value);
        render();
        if (needle && shown.length === 1) focusItem(shown[0]);
      }, 150);
    });
    search.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      window.clearTimeout(searchTimer);
      needle = normalize(search.value);
      render();
      const first = shown[0];
      if (!first) return;
      if (first.has_coordinates) focusItem(first);
      else go(detailUrl(first.id));
    });
    list.addEventListener('mouseover', (event) => { const row = event.target.closest('.irz-row'); if (row) map.highlight(row.dataset.id); });
    list.addEventListener('focusin', (event) => { const row = event.target.closest('.irz-row'); if (row) map.highlight(row.dataset.id); });
    list.addEventListener('mouseleave', () => map.highlight(null));
    list.addEventListener('click', (event) => {
      const row = event.target.closest('.irz-row');
      if (row && !event.target.closest('a')) go(detailUrl(row.dataset.id));
    });
    window.addEventListener('opora:before-navigate', () => {
      stopped = true; window.clearTimeout(timer); window.clearTimeout(searchTimer); map.destroy();
    }, {once: true});
    tick();
  }

  function bootDisplay() {
    const root = document.querySelector('[data-irz-display]');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    const q = (selector) => root.querySelector(selector);
    const refreshMs = Math.min(Math.max(Number(root.dataset.refreshSeconds) || 20, 15), 30) * 1000;
    const detailTemplate = root.dataset.detailTemplate || '';
    const labelsToggle = q('[data-labels-toggle]'), polesToggle = q('[data-poles-toggle]'), connection = q('[data-connection]');
    let lastOk = null, timer = 0;
    labelsToggle.checked = stored('irz-display-labels', true);
    polesToggle.checked = stored('irz-display-poles', false);
    const map = createMap(q('[data-map-canvas]'), {
      lampRadius: 9, textSize: 15, boxMinZoom: 11, poleSize: 13, labels: labelsToggle.checked,
      poles: {url: root.dataset.polesUrl, detailTemplate: root.dataset.poleTemplate, enabled: polesToggle.checked, minZoom: 15},
      popupHtml: (item) => popupHtml(item, detailTemplate ? detailTemplate.replace('DEVICE_ID', encodeURIComponent(item.id)) : null, 'Подробнее'),
      onError: (text) => { connection.textContent = text; connection.hidden = false; },
    });
    labelsToggle.addEventListener('change', () => { map.setLabels(labelsToggle.checked); store('irz-display-labels', labelsToggle.checked); });
    polesToggle.addEventListener('change', () => { map.setPoles(polesToggle.checked); store('irz-display-poles', polesToggle.checked); });
    async function tick() {
      try {
        const payload = await fetchJson(root.dataset.apiUrl);
        map.setItems(payload.items || []);
        root.querySelectorAll('[data-count]').forEach((node) => { node.textContent = payload.counters?.[node.dataset.count] ?? 0; });
        lastOk = payload.generated_at;
        q('[data-updated]').textContent = clock(lastOk);
        connection.hidden = payload.gateway === 'online';
        connection.textContent = payload.gateway === 'online' ? '' : 'Шлюз связи недоступен — связь ATM21 неизвестна';
      } catch (error) {
        connection.hidden = false;
        connection.textContent = error.message === 'SESSION_EXPIRED'
          ? 'Сессия истекла — требуется повторный вход'
          : `Нет связи с сервером${lastOk ? `, данные на ${clock(lastOk)}` : ''}`;
      } finally {
        timer = window.setTimeout(tick, refreshMs);
      }
    }
    window.addEventListener('pagehide', () => { window.clearTimeout(timer); map.destroy(); }, {once: true});
    tick();
  }

  function bootPole() {
    const root = document.querySelector('[data-irz-pole-map]');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    const point = [Number(root.dataset.lon), Number(root.dataset.lat)];
    const map = createMap(root, {
      lampRadius: 6, textSize: 12, poleSize: 14, devices: false, fit: false, center: point, zoom: 17, focusPoint: point,
      poles: {url: root.dataset.polesUrl, detailTemplate: root.dataset.poleTemplate, enabled: true, minZoom: 14},
      popupHtml: () => '',
      onError: (text) => { root.textContent = text; },
    });
    window.addEventListener('opora:before-navigate', () => map.destroy(), {once: true});
  }

  function boot() { bootDirectory(); bootDisplay(); bootPole(); }
  document.addEventListener('DOMContentLoaded', boot);
  window.addEventListener('opora:navigated', boot);
})();
