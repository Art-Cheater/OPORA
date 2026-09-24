(function () {
  const PHASES = [['a', 'A'], ['b', 'B'], ['c', 'C'], ['total', 'Σ']];
  const COLUMNS = [['u', 'U, В', 1, 2, false], ['i', 'I, А', 1, 3, false], ['p', 'P, кВт', 1000, 3, true],
    ['q', 'Q, квар', 1000, 3, true], ['s', 'S, кВА', 1000, 3, true], ['cos_phi', 'cos φ', 1, 3, true]];
  const ENERGY = [['a_plus', 'A+'], ['a_minus', 'A−'], ['r_plus', 'R+'], ['r_minus', 'R−']];
  const TARIFFS = [['total', 'Σ'], ['t1', 'T1'], ['t2', 'T2'], ['t3', 'T3'], ['t4', 'T4']];
  const STATES = {GOOD: ['success', 'ДАННЫЕ АКТУАЛЬНЫ'], PARTIAL: ['warning', 'ЧАСТИЧНО'], STALE: ['warning', 'ДАННЫЕ УСТАРЕЛИ'],
    INVALID: ['danger', 'ОШИБКА ДАННЫХ'], CRC_ERROR: ['danger', 'ОШИБКА CRC'], UNSUPPORTED: ['secondary', 'НЕ ПОДДЕРЖИВАЕТСЯ'],
    NO_DATA: ['secondary', 'НЕТ ДАННЫХ']};

  function boot() {
    const root = document.querySelector('[data-irz-monitor]');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    const q = (s) => root.querySelector(s), csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const canEdit = root.dataset.canEdit === '1', defaultName = `ATM21 ${root.dataset.imei}`;
    let selected = null, stopped = false, busy = false, timer, events = null, formDirty = false;
    const missing = (v) => v === null || v === undefined || v === '' || (typeof v === 'number' && Number.isNaN(v));
    const fmt = (v) => missing(v) ? '—' : String(v);
    const num = (v, divisor = 1, digits = 3) => {
      if (missing(v)) return '—';
      const value = Number(v) / divisor;
      return Number.isFinite(value) ? value.toLocaleString('ru-RU', {maximumFractionDigits: digits}) : '—';
    };
    const time = (v) => v ? new Date(v).toLocaleString('ru-RU') : '—';
    const esc = (v) => fmt(v).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function api(path, options = {}) {
      const response = await fetch(path, {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json','Content-Type':'application/json','X-CSRFToken':csrf}, ...options});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.message || payload?.error || `HTTP ${response.status}`);
      return payload;
    }
    let heldUntil = 0;
    function message(value, kind='secondary', hold=false) {
      if (!hold && Date.now() < heldUntil) return;
      if (hold) heldUntil = Date.now() + 15000;
      const node=q('[data-message]'); node.className=`irz-note irz-note--${kind}`; node.textContent=value;
    }
    const notice = (value, kind) => message(value, kind, true);
    function details(values) { return `<dl class="irz-detail-grid mb-0">${values.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`; }
    function current() { return {values: selected?.current?.values || selected?.latest?.values || {}, quality: selected?.current?.quality || {}, captured: selected?.current?.captured_at || {}}; }
    function cell(data, key, text) {
      const quality = data.quality[key], stale = quality && quality !== 'GOOD' && !missing(data.values[key]);
      const title = stale ? ` title="${esc(quality === 'STALE' ? `Устарело: ${time(data.captured[key])}` : quality)}"` : '';
      return `<td class="${stale ? 'irz-stale' : ''}"${title}>${esc(text)}</td>`;
    }
    function renderTelemetry() {
      const data = current(), values = data.values;
      q('[data-phase-values]').innerHTML = PHASES.map(([phase, label]) => `<tr><th>${label}</th>${COLUMNS.map(([prefix, , divisor, digits, hasTotal]) => {
        const key = `${prefix}_${phase}`, value = phase === 'total' && !hasTotal ? null : values?.[key] ?? null;
        return cell(data, key, num(value, divisor, digits));
      }).join('')}</tr>`).join('');
      q('[data-energy-values]').innerHTML = TARIFFS.map(([tariff, label]) => `<tr><th>${label}</th>${ENERGY.map(([key]) => {
        const name = `energy_${key}_${tariff}`;
        return cell(data, name, num(values?.[name] ?? null, 1000, 3));
      }).join('')}</tr>`).join('');
      const drift = values?.drift_seconds ?? null;
      const diagnostics = Array.isArray(values?.diagnostics) ? values.diagnostics : null;
      const summary = [
        ['Частота, Гц', num(values?.frequency ?? null, 1, 2), 'frequency'],
        ['Угол AB / AC / BC, °', ['ab','ac','bc'].map((k) => num(values?.[`phase_angle_${k}`] ?? null, 1, 2)).join(' / '), 'phase_angle_ab'],
        ['Время счётчика', values?.meter_time ? time(values.meter_time) : '—', 'meter_time'],
        ['Расхождение часов, с', missing(drift) ? '—' : `${drift > 0 ? '+' : ''}${drift}`, 'drift_seconds'],
      ];
      q('[data-summary-values]').innerHTML = summary.map(([label, value, key]) => {
        const stale = data.quality[key] && data.quality[key] !== 'GOOD' && value !== '—';
        return `<div class="col-6 col-lg-3"><div class="irz-metric${stale ? ' irz-stale' : ''}"><small class="text-muted">${label}</small><strong>${esc(value)}</strong></div></div>`;
      }).join('');
      q('[data-diagnostics]').innerHTML = diagnostics === null ? '<span class="text-muted">Нет данных самодиагностики</span>'
        : diagnostics.length ? `<ul class="mb-0 ps-3">${diagnostics.map((item) => `<li><strong>${esc(item.code)}</strong> ${esc(item.text)}</li>`).join('')}</ul>`
        : '<span class="text-success"><i class="bi bi-check-circle"></i> Ошибок самодиагностики нет</span>';
      const state = selected?.data_state || 'NO_DATA', [kind, label] = STATES[state] || ['secondary', state];
      const badge = q('[data-quality]'); badge.textContent = label; badge.className = `badge text-bg-${kind}`;
      q('[data-values-time]').textContent = selected?.current?.updated_at ? `Данные на ${time(selected.current.updated_at)}` : '';
    }
    function renderEvents() {
      const node = q('[data-events]');
      if (!events) { node.innerHTML = '<span class="text-muted">Журналы читаются по запросу</span>'; return; }
      node.innerHTML = `<ul class="list-unstyled mb-0 irz-events">${events.map((item) => {
        const at = item.start || item.at, end = item.end;
        const info = item.status === 'GOOD' ? (at ? `${time(at)}${end ? ` → ${time(end)}` : ''}` : 'Записей нет') : fmt(item.error_code || item.status);
        return `<li><span class="badge text-bg-${item.status === 'GOOD' ? 'light' : 'secondary'} me-1">${esc(item.number)}</span>${esc(item.title)}<div class="small text-muted">${esc(info)}</div></li>`;
      }).join('')}</ul>`;
    }
    function customName() { return selected?.name && selected.name !== defaultName ? selected.name : ''; }
    function renderProfile() {
      const location = selected.location || {}, hasPoint = location.latitude != null && location.longitude != null;
      q('[data-map]').innerHTML = hasPoint
        ? `<i class="bi bi-geo-alt-fill"></i><span>${esc(location.latitude)}, ${esc(location.longitude)}</span><a class="small" href="${esc(root.dataset.mapUrl)}">Показать на карте</a>`
        : `<i class="bi bi-geo-alt"></i><span>Координаты не заданы</span>${canEdit ? '<span class="small">Укажите широту и долготу в карточке</span>' : ''}`;
      if (canEdit) {
        if (formDirty) return;
        q('[data-name]').value = customName(); q('[data-address]').value = location.address_text || '';
        q('[data-lat]').value = location.latitude ?? ''; q('[data-lon]').value = location.longitude ?? '';
      } else {
        q('[data-profile-view]').innerHTML = details([['Название', customName() || 'Название не задано'], ['Адрес', location.address_text || '—'],
          ['Координаты', hasPoint ? `${location.latitude}, ${location.longitude}` : 'Не заданы']]);
      }
    }
    function renderDirectory() {
      const state = selected.directory || {}, entry = state.entry, node = q('[data-directory]');
      let html = '';
      if (entry) {
        html = details([['ШУНО', entry.cabinet_name || 'не указано в справочнике'], ['ID ШУНО', entry.cabinet_external_id], ['Модель по справочнику', entry.meter_model]])
          + `<div class="text-muted mt-1">Сопоставлено по серийному № ${esc(entry.meter_serial)}</div>`;
        if (state.serial_changed) html += `<div class="irz-note irz-note--warning mt-2 mb-0">Сейчас прочитан другой серийный № ${esc(state.current_serial)}. Карточка не менялась автоматически${canEdit ? ' — при необходимости примените справочник повторно' : ''}.</div>`;
      } else if (state.status === 'NOT_FOUND') {
        html = `<div class="irz-note irz-note--warning mb-0">Серийный номер ${esc(state.matched_serial)} не найден в справочнике ШУНО</div>`;
      } else if (state.status === 'METER_SERIAL_CONFLICT') {
        html = `<div class="irz-note irz-note--danger mb-0">Серийный № ${esc(state.matched_serial)} уже сопоставлен с другим IRZ, автоматическая привязка не выполнена${canEdit ? '. Проверьте и примените справочник вручную' : ''}.</div>`;
      }
      node.innerHTML = html; node.hidden = !html;
      const button = q('[data-directory-reapply]');
      if (button) button.disabled = busy || !state.current_serial;
    }
    function render() {
      if (!selected) return;
      const status=q('[data-device-status]'); status.textContent=selected.online?'ONLINE':'OFFLINE'; status.className=`badge text-bg-${selected.online?'success':'danger'}`;
      q('[data-last-update]').textContent=`Последний опрос: ${time(selected.latest?.captured_at || selected.last_polled_at)}`;
      if (q('[data-poll]')) q('[data-poll]').disabled=busy || !selected.online;
      if (q('[data-read-events]')) q('[data-read-events]').disabled=busy || !selected.online;
      renderProfile(); renderDirectory();
      const meter=selected.meter, values=current().values;
      q('[data-meter-details]').innerHTML=meter?details([['Название',meter.display_name],['Модель',meter.catalog_model || meter.model || 'Mercury 230'],['Серийный №',meter.serial_number],['Дата выпуска',meter.manufacture_date],['Версия ПО',meter.firmware_version],['Кн / Кт',`${fmt(values?.transformation_voltage ?? null)} / ${fmt(values?.transformation_current ?? null)}`],['Последний ответ',time(selected.last_mercury_seen_at)]]):'Счётчик: не определён';
      q('[data-atm-details]').innerHTML=details([['IMEI',selected.imei],['IP / порт',`${fmt(selected.ip)}:${fmt(selected.port)}`],['CSQ',selected.csq],['Интерфейсы',selected.interfaces],['Версия',`${fmt(selected.firmware_version)} / ${fmt(selected.firmware_revision)} / ${fmt(selected.firmware_build)}`],['Последний пакет',time(selected.last_seen_at)]]);
      renderTelemetry(); renderEvents();
    }
    async function history() { const rows=await api(root.dataset.historyUrl+'?limit=30'); q('[data-history]').innerHTML=rows.length?rows.map(x=>`<tr><td>${esc(time(x.captured_at))}</td><td>${esc(x.source)}</td><td>${esc(x.status)}</td><td>${esc(x.quality)}</td><td>${esc(x.poll_duration_ms==null?null:`${x.poll_duration_ms} мс`)}</td></tr>`).join(''):'<tr><td colspan="5" class="text-center text-muted py-4">История пока пуста</td></tr>'; }
    async function reload() {
      selected = await api(root.dataset.detailUrl); render(); await history();
      if (!busy) message(selected.online ? 'Устройство подключено.' : 'ATM21 не подключён; показаны последние сохранённые данные.', selected.online ? 'success' : 'warning');
    }
    q('[data-poll]')?.addEventListener('click',async()=>{
      busy=true; render(); notice('Выполняется опрос счётчика…','info');
      try {
        const result=await api(root.dataset.pollUrl,{method:'POST',body:'{}'});
        busy=false; await reload();
        const failed=(result.errors||[]).filter((item)=>item.error_code!=='SKIPPED'&&item.error_code!=='UNSUPPORTED').length;
        if (result.quality==='GOOD') notice('Показания обновлены.','success');
        else if (result.quality==='PARTIAL') notice(`Показания обновлены частично: без ответа ${failed} ${failed===1?'команда':'команд'}. Остальные значения отмечены как устаревшие.`,'warning');
        else notice('Счётчик не ответил. Показаны последние сохранённые значения.','danger');
      } catch(err) { notice(`Опрос не выполнен: ${err.message}. Последние данные сохранены.`,'danger'); }
      finally { busy=false; render(); }
    });
    q('[data-read-events]')?.addEventListener('click',async()=>{
      busy=true; render(); notice('Чтение журналов событий…','info');
      try { const result=await api(root.dataset.eventsUrl,{method:'POST',body:'{}'}); events=result.data?.journals||[]; notice('Журналы событий прочитаны.','success'); }
      catch(err) { notice(`Журналы не прочитаны: ${err.message}`,'danger'); }
      finally { busy=false; render(); }
    });
    const PROFILE_ERRORS = {INVALID_LATITUDE: 'Широта должна быть числом от −90 до 90.', INVALID_LONGITUDE: 'Долгота должна быть числом от −180 до 180.',
      INCOMPLETE_COORDINATES: 'Укажите обе координаты или оставьте обе пустыми.', INVALID_NAME: 'Название не длиннее 160 символов.',
      INVALID_ADDRESS_TEXT: 'Адрес не длиннее 500 символов.'};
    const form = q('[data-profile-form]');
    form?.addEventListener('input', () => { formDirty = true; });
    form?.addEventListener('submit',async(e)=>{
      e.preventDefault();
      try {
        await api(root.dataset.detailUrl,{method:'PATCH',body:JSON.stringify({name:q('[data-name]').value,address_text:q('[data-address]').value,latitude:q('[data-lat]').value,longitude:q('[data-lon]').value})});
        formDirty = false; await reload(); notice('Карточка объекта сохранена.','success');
      } catch(err) { notice(PROFILE_ERRORS[err.message] || err.message,'danger'); }
    });
    const DIRECTORY_ERRORS = {METER_SERIAL_UNKNOWN: 'Серийный номер счётчика ещё не прочитан.',
      DIRECTORY_ENTRY_NOT_FOUND: 'Серийного номера счётчика нет в справочнике ШУНО.',
      DIRECTORY_PREVIEW_OUTDATED: 'Справочник изменился, откройте предпросмотр заново.'};
    const preview = q('[data-directory-preview]');
    const closePreview = () => { preview.hidden = true; preview.innerHTML = ''; };
    q('[data-directory-reapply]')?.addEventListener('click', async () => {
      try {
        const plan = await api(root.dataset.directoryUrl), entry = plan.entry;
        const changes = plan.changes.length
          ? `<ul class="mb-2 ps-3">${plan.changes.map((item) => `<li><strong>${esc(item.label)}:</strong> ${esc(item.current)} → ${esc(item.new)}</li>`).join('')}</ul>`
          : '<div class="mb-2">Карточка уже совпадает со справочником.</div>';
        const conflict = plan.conflict ? `<div class="irz-note irz-note--danger mb-2">Запись сейчас сопоставлена с IRZ «${esc(plan.conflict.name)}» (IMEI ${esc(plan.conflict.imei)}). После применения связь перейдёт на это устройство.</div>` : '';
        preview.innerHTML = `<div class="mb-1">По серийному № ${esc(plan.serial)} · ШУНО ${esc(entry.cabinet_name)}</div>${conflict}${changes}`
          + '<div class="d-flex gap-2"><button type="button" class="btn btn-sm btn-primary" data-directory-confirm>Применить</button><button type="button" class="btn btn-sm btn-outline-secondary" data-directory-cancel>Отмена</button></div>';
        preview.hidden = false;
        preview.querySelector('[data-directory-cancel]').addEventListener('click', closePreview);
        const confirm = preview.querySelector('[data-directory-confirm]');
        confirm.addEventListener('click', async () => {
          confirm.disabled = true;
          try {
            await api(root.dataset.directoryApplyUrl, {method: 'POST', body: JSON.stringify({entry_id: entry.id})});
            closePreview(); formDirty = false; await reload(); notice('Данные справочника применены.', 'success');
          } catch (err) { confirm.disabled = false; notice(DIRECTORY_ERRORS[err.message] || err.message, 'danger'); }
        });
      } catch (err) { notice(DIRECTORY_ERRORS[err.message] || err.message, 'danger'); }
    });
    async function tick(){try{if(!busy)await reload();}catch(err){message(`Мониторинг недоступен: ${err.message}`,'danger');}finally{if(!stopped)timer=setTimeout(tick,10000);}}
    window.addEventListener('opora:before-navigate',()=>{stopped=true;clearTimeout(timer);},{once:true}); tick();
  }
  document.addEventListener('DOMContentLoaded',boot); window.addEventListener('opora:navigated',boot);
})();
