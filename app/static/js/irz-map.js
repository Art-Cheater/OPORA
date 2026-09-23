/* IRZ · Мониторинг: карта MapLibre с квадратными маркерами, список устройств и экран-дисплей. */
(function () {
  const COLORS = {OK: '#16a34a', WARNING: '#eab308', OFFLINE: '#dc2626', UNKNOWN: '#9ca3af'};
  const LABELS = {OK: 'Online', WARNING: 'Проблема', OFFLINE: 'Offline', UNKNOWN: 'Нет связи со шлюзом'};
  const DRAW_ORDER = {UNKNOWN: 0, OK: 1, WARNING: 2, OFFLINE: 3};
  const KIROV = [49.668, 58.6035];
  const DEFAULT_STYLE = 'https://tiles.openfreemap.org/styles/liberty';
  const SOURCE = 'irz-devices';

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
  const subtitle = (item) => item.name ? `ATM21 · IMEI ${item.imei}` : 'Название не задано';
  const meterLine = (item) => item.meter ? `${item.meter.model} · № ${item.meter.serial}` : 'Счётчик: не определён';

  function matches(item, needle) {
    if (!needle) return true;
    return [item.title, item.imei, item.meter?.serial, item.address].some((part) => normalize(part).includes(needle));
  }

  function popupHtml(item, href, action) {
    const s = item.summary || {};
    const voltage = ['u_a', 'u_b', 'u_c'].some((key) => s[key] !== undefined)
      ? `<div class="irz-popup__row"><span>U A / B / C</span><strong>${number(s.u_a)} / ${number(s.u_b)} / ${number(s.u_c)} В</strong></div>` : '';
    return `<div class="irz-popup__item">
      <div class="irz-popup__title"><span class="irz-square irz-square--${item.status.toLowerCase()}"></span>${esc(item.title)}</div>
      <div class="irz-popup__sub">${esc(subtitle(item))}</div>
      <div class="irz-popup__sub">${esc(meterLine(item))}</div>
      <div class="irz-popup__row"><span>Статус</span><strong>${esc(LABELS[item.status] || item.status)}</strong></div>
      ${item.problem ? `<div class="irz-popup__problem">${esc(item.problem)}</div>` : ''}
      <div class="irz-popup__row"><span>Связь</span><strong>${esc(ago(item.last_seen_at))}</strong></div>
      <div class="irz-popup__row"><span>Показания</span><strong>${esc(ago(item.updated_at))}</strong></div>
      ${voltage}
      ${href ? `<a class="btn btn-sm btn-primary w-100 mt-2" href="${esc(href)}">${esc(action)}</a>` : ''}
    </div>`;
  }

  function squareIcon(size, fill, border, hollow = false) {
    const ratio = Math.max(1, Math.ceil(window.devicePixelRatio || 1)), px = size * ratio;
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = px;
    const ctx = canvas.getContext('2d'), line = Math.max(ratio, Math.round(ratio * size / 9));
    ctx.fillStyle = border; ctx.fillRect(0, 0, px, px);
    if (hollow) ctx.clearRect(line, line, px - 2 * line, px - 2 * line);
    else { ctx.fillStyle = fill; ctx.fillRect(line, line, px - 2 * line, px - 2 * line); }
    return {image: ctx.getImageData(0, 0, px, px), ratio};
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
    let loaded = false, destroyed = false, fitted = false, selectedId = null, hoverId = null, labels = options.labels !== false;
    const loader = window.OporaMapKit?.ensureAssets || window.OporaMap?.ensureAssets;
    const ready = (loader ? loader() : Promise.reject(new Error('MapLibre loader unavailable'))).then((maplibre) => {
      if (destroyed) return null;
      lib = maplibre;
      const cfg = window.OporaMapKit?.readConfig?.() || {};
      const style = cfg.styleUrl || document.querySelector('meta[name="opora-maplibre-style"]')?.content || DEFAULT_STYLE;
      const center = cfg.center || KIROV;
      map = new lib.Map({container: node, style, center, zoom: options.zoom || 11, attributionControl: true, minZoom: cfg.minZoom, maxZoom: cfg.maxZoom});
      map.addControl(new lib.NavigationControl({showCompass: false}), 'top-left');
      map.on('error', (event) => { if (event?.error && !loaded) options.onError?.('Не удалось загрузить подложку карты.'); });
      if (window.ResizeObserver) { observer = new ResizeObserver(() => map?.resize()); observer.observe(node); }
      return new Promise((resolve) => map.on('load', () => {
        if (destroyed) return;
        addLayers(); bind(); loaded = true; render(); resolve(map);
      }));
    }).catch(() => { options.onError?.('Карта недоступна: не удалось загрузить MapLibre.'); return null; });

    function addLayers() {
      const size = options.markerSize;
      Object.entries(COLORS).forEach(([status, color]) => {
        const icon = squareIcon(size, color, 'rgba(17, 24, 39, 0.85)');
        map.addImage(`irz-${status.toLowerCase()}`, icon.image, {pixelRatio: icon.ratio});
      });
      const halo = squareIcon(size + 10, null, '#2563eb', true);
      map.addImage('irz-selected', halo.image, {pixelRatio: halo.ratio});
      map.addSource(SOURCE, {type: 'geojson', data: collection()});
      map.addLayer({id: 'irz-selected', type: 'symbol', source: SOURCE, filter: ['in', ['get', 'id'], ['literal', []]],
        layout: {'icon-image': 'irz-selected', 'icon-allow-overlap': true, 'icon-ignore-placement': true}});
      map.addLayer({id: 'irz-markers', type: 'symbol', source: SOURCE,
        layout: {'icon-image': ['concat', 'irz-', ['downcase', ['get', 'status']]], 'icon-allow-overlap': true,
          'icon-ignore-placement': true, 'symbol-sort-key': ['get', 'order']}});
      map.addLayer({id: 'irz-labels', type: 'symbol', source: SOURCE, minzoom: options.labelMinZoom,
        layout: {'text-field': ['get', 'title'], 'text-font': styleFont(map), 'text-size': options.labelSize,
          'text-anchor': 'top', 'text-offset': [0, (size / 2 + 3) / options.labelSize], 'text-max-width': 12,
          visibility: labels ? 'visible' : 'none'},
        paint: {'text-color': '#111827', 'text-halo-color': '#ffffff', 'text-halo-width': 1.6}});
    }
    function bind() {
      map.on('mouseenter', 'irz-markers', () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', 'irz-markers', () => { map.getCanvas().style.cursor = ''; });
      map.on('click', 'irz-markers', (event) => {
        const found = [...new Set(event.features.map((feature) => feature.properties.id))].map((id) => byId.get(id)).filter(Boolean);
        if (!found.length) return;
        openPopup(found);
        setSelected(found[0].id);
        options.onSelect?.(found[0]);
      });
    }
    function collection() {
      return {type: 'FeatureCollection', features: items.filter((item) => item.has_coordinates).map((item) => ({
        type: 'Feature', geometry: {type: 'Point', coordinates: [item.longitude, item.latitude]},
        properties: {id: item.id, status: item.status, title: item.title, order: DRAW_ORDER[item.status] ?? 0},
      }))};
    }
    function openPopup(list) {
      popup?.remove();
      popupIds = list.slice(0, 5).map((item) => item.id);
      popup = new lib.Popup({maxWidth: '320px', offset: options.markerSize / 2 + 6, className: 'irz-popup'})
        .setLngLat([list[0].longitude, list[0].latitude]).setHTML(popupContent()).addTo(map);
      popup.on('close', () => { popupIds = []; });
    }
    function popupContent() {
      return popupIds.map((id) => byId.get(id)).filter(Boolean).map(options.popupHtml).join('<hr class="my-2">');
    }
    function updateHighlight() {
      if (!loaded) return;
      map.setFilter('irz-selected', ['in', ['get', 'id'], ['literal', [selectedId, hoverId].filter(Boolean)]]);
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
      if (fit || !fitted) { fitAll(); fitted = items.some((item) => item.has_coordinates); }
      if (popup && popupIds.length) {
        if (popupIds.some((id) => byId.has(id))) popup.setHTML(popupContent());
        else popup.remove();
      }
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
      setLabels(visible) { labels = visible; if (loaded) map.setLayoutProperty('irz-labels', 'visibility', visible ? 'visible' : 'none'); },
      destroy() { destroyed = true; observer?.disconnect(); popup?.remove(); map?.remove(); map = null; },
    };
  }

  async function fetchJson(url) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}});
    const type = response.headers.get('content-type') || '';
    if (response.redirected || !type.includes('application/json')) throw new Error('SESSION_EXPIRED');
    const payload = await response.json();
    if (!response.ok) throw new Error(payload?.message || payload?.error || `HTTP ${response.status}`);
    return payload;
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
    const map = createMap(q('[data-map-canvas]'), {
      markerSize: 14, labelMinZoom: 14, labelSize: 12,
      popupHtml: (item) => popupHtml(item, detailUrl(item.id), 'Открыть'),
      onSelect: (item) => selectRow(item.id, true),
      onError: (text) => showMessage(text, 'warning'),
    });

    function showMessage(text, kind = 'secondary') {
      note.hidden = !text; note.className = `irz-note irz-note--${kind} mb-2`; note.textContent = text || '';
    }
    function passes(item) {
      if (filter === 'online' && !item.online) return false;
      if (filter === 'offline' && item.status !== 'OFFLINE') return false;
      if (filter === 'problem' && item.status !== 'WARNING') return false;
      if (filter === 'no_coordinates' && item.has_coordinates) return false;
      return matches(item, needle);
    }
    function rowHtml(item) {
      const status = item.status.toLowerCase(), href = esc(detailUrl(item.id));
      const where = item.has_coordinates ? '' : '<span class="irz-row__nocoords">Координаты не заданы</span>';
      return `<div class="irz-row${item.id === selectedId ? ' is-selected' : ''}" role="listitem" data-id="${esc(item.id)}">
        <span class="irz-square irz-square--${status}" aria-hidden="true"></span>
        <a class="irz-row__main" href="${href}">
          <span class="irz-row__title">${esc(item.title)}</span>
          <span class="irz-row__sub">${esc(subtitle(item))}</span>
          <span class="irz-row__sub">${esc(meterLine(item))}${where}</span>
        </a>
        <span class="irz-row__side">
          <span class="irz-status irz-status--${status}"${item.problem ? ` title="${esc(item.problem)}"` : ''}>${esc(LABELS[item.status] || item.status)}</span>
          <span class="irz-row__time" title="Последний пакет ATM21">${esc(ago(item.last_seen_at))}</span>
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
      if (payload.gateway !== 'online') showMessage('Шлюз связи недоступен: онлайн-статус ATM21 неизвестен, показаны сохранённые данные.', 'warning');
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
    const toggle = q('[data-labels-toggle]'), status = q('[data-connection]');
    let lastOk = null, timer = 0;
    let labels = true;
    try { labels = window.localStorage.getItem('irz-display-labels') !== '0'; } catch (error) { labels = true; }
    toggle.checked = labels;
    const map = createMap(q('[data-map-canvas]'), {
      markerSize: 22, labelMinZoom: 13, labelSize: 15, labels,
      popupHtml: (item) => popupHtml(item, detailTemplate ? detailTemplate.replace('DEVICE_ID', encodeURIComponent(item.id)) : null, 'Подробнее'),
      onError: (text) => { status.textContent = text; status.hidden = false; },
    });
    toggle.addEventListener('change', () => {
      map.setLabels(toggle.checked);
      try { window.localStorage.setItem('irz-display-labels', toggle.checked ? '1' : '0'); } catch (error) { /* private mode */ }
    });
    async function tick() {
      try {
        const payload = await fetchJson(root.dataset.apiUrl);
        map.setItems(payload.items || []);
        root.querySelectorAll('[data-count]').forEach((node) => { node.textContent = payload.counters?.[node.dataset.count] ?? 0; });
        lastOk = payload.generated_at;
        q('[data-updated]').textContent = clock(lastOk);
        status.hidden = payload.gateway === 'online';
        status.textContent = payload.gateway === 'online' ? '' : 'Шлюз связи недоступен — статус устройств неизвестен';
      } catch (error) {
        status.hidden = false;
        status.textContent = error.message === 'SESSION_EXPIRED'
          ? 'Сессия истекла — требуется повторный вход'
          : `Нет связи с сервером${lastOk ? `, данные на ${clock(lastOk)}` : ''}`;
      } finally {
        timer = window.setTimeout(tick, refreshMs);
      }
    }
    window.addEventListener('pagehide', () => { window.clearTimeout(timer); map.destroy(); }, {once: true});
    tick();
  }

  function boot() { bootDirectory(); bootDisplay(); }
  document.addEventListener('DOMContentLoaded', boot);
  window.addEventListener('opora:navigated', boot);
})();
