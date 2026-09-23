(function () {
  function boot() {
    const root = document.querySelector('[data-irz-monitor]');
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    const q = (s) => root.querySelector(s), csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
    let devices = [], selected = null, stopped = false, busy = false, timer;
    const url = (template) => template.replace('IMEI', encodeURIComponent(selected?.imei || ''));
    const fmt = (v) => v === null || v === undefined || v === '' ? '—' : String(v);
    const time = (v) => v ? new Date(v).toLocaleString('ru-RU') : '—';
    const esc = (v) => fmt(v).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    async function api(path, options = {}) {
      const response = await fetch(path, {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json','Content-Type':'application/json','X-CSRFToken':csrf}, ...options});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload?.message || payload?.error || `HTTP ${response.status}`);
      return payload;
    }
    function message(value, kind='secondary') { const node=q('[data-message]'); node.className=`alert alert-${kind} py-2`; node.textContent=value; }
    function details(values) { return `<dl class="irz-detail-grid mb-0">${values.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`; }
    function nested(obj, names) { for (const name of names) { const parts=name.split('.'); let value=obj; for (const part of parts) value=value?.[part]; if (value !== undefined && value !== null) return value; } return null; }
    function phaseValues(values, prefix) { return ['a','b','c','total'].map((phase) => values?.[`${prefix}_${phase}`] ?? null); }
    function renderTelemetry() {
      const latest=selected?.latest, values=latest?.values || selected?.meter?.latest_snapshot || {};
      const specs=[['Напряжение, В','u'],['Ток, А','i'],['Активная мощность, Вт','p'],['Реактивная мощность, вар','q'],['Полная мощность, ВА','s'],['cos φ','cos_phi']];
      q('[data-phase-values]').innerHTML=specs.map(([label,prefix])=>`<tr><th>${label}</th>${phaseValues(values,prefix).map(v=>`<td>${esc(v)}</td>`).join('')}</tr>`).join('');
      const summary=[['Частота, Гц',nested(values,['frequency'])],['Серийный №',nested(values,['serial_number'])],['Дата выпуска',nested(values,['manufacture_date'])],['Версия ПО',nested(values,['firmware_version'])],['Коэф. напряжения',nested(values,['transformation_voltage'])],['Коэф. тока',nested(values,['transformation_current'])]];
      q('[data-summary-values]').innerHTML=summary.map(([label,value])=>`<div class="col-6"><div class="irz-metric"><small class="text-muted">${label}</small><strong>${esc(typeof value==='object'?JSON.stringify(value):value)}</strong></div></div>`).join('');
      const state=selected?.data_state || 'NO_DATA'; const badge=q('[data-quality]'); badge.textContent=state==='STALE'?'ДАННЫЕ УСТАРЕЛИ':state; badge.className=`badge text-bg-${state==='SUCCESS'?'success':state==='PARTIAL'||state==='STALE'?'warning':'secondary'}`;
    }
    function render() {
      if (!selected) return;
      const status=q('[data-device-status]'); status.textContent=selected.online?'ONLINE':'OFFLINE'; status.className=`badge text-bg-${selected.online?'success':'secondary'}`;
      q('[data-last-update]').textContent=`Последний опрос: ${time(selected.latest?.captured_at || selected.last_polled_at)}`;
      q('[data-poll]').disabled=busy || !selected.online;
      q('[data-name]').value=selected.name || ''; q('[data-address]').value=selected.location?.address_text || ''; q('[data-lat]').value=selected.location?.latitude ?? ''; q('[data-lon]').value=selected.location?.longitude ?? '';
      q('[data-map]').innerHTML=selected.location?.latitude!=null&&selected.location?.longitude!=null?`<i class="bi bi-geo-alt-fill"></i><span>${esc(selected.location.latitude)}, ${esc(selected.location.longitude)}</span>`:'<i class="bi bi-geo-alt"></i><span>Координаты не заданы</span>';
      const meter=selected.meter; q('[data-meter-details]').innerHTML=meter?details([['Название',meter.display_name],['Модель',meter.model],['Серийный №',meter.serial_number],['Дата выпуска',meter.manufacture_date],['Версия ПО',meter.firmware_version],['Последний ответ',selected.last_mercury_seen_at]]):'Счётчик ещё не обнаружен';
      q('[data-atm-details]').innerHTML=details([['IMEI',selected.imei],['IP / порт',`${fmt(selected.ip)}:${fmt(selected.port)}`],['CSQ',selected.csq],['Интерфейсы',selected.interfaces],['Версия',`${fmt(selected.firmware_version)} / ${fmt(selected.firmware_revision)} / ${fmt(selected.firmware_build)}`],['Последний пакет',selected.last_seen_at]]);
      renderTelemetry();
    }
    async function history() { const rows=await api(url(root.dataset.historyTemplate)+'?limit=30'); q('[data-history]').innerHTML=rows.length?rows.map(x=>`<tr><td>${esc(time(x.captured_at))}</td><td>${esc(x.source)}</td><td>${esc(x.status)}</td><td>${esc(x.quality)}</td><td>${esc(x.poll_duration_ms==null?null:`${x.poll_duration_ms} мс`)}</td></tr>`).join(''):'<tr><td colspan="5" class="text-center text-muted py-4">История пока пуста</td></tr>'; }
    async function select(imei) { selected=devices.find(x=>x.imei===imei)||null; if(!selected)return; render(); await history(); }
    async function reload() {
      const previous=selected?.imei; devices=await api(root.dataset.listUrl); devices.sort((a,b)=>(Number(b.online)-Number(a.online))||(Number(a.stale)-Number(b.stale))||a.name.localeCompare(b.name,'ru'));
      const selector=q('[data-device-select]'); selector.innerHTML=devices.length?devices.map(x=>`<option value="${esc(x.imei)}">${x.online?'●':'○'} ${esc(x.name)} · ${esc(x.imei)}</option>`).join(''):'<option>Устройств нет</option>';
      const imei=devices.some(x=>x.imei===previous)?previous:devices[0]?.imei; if(imei){selector.value=imei; await select(imei); message(selected.online?'Устройство подключено.':'ATM21 не подключён; показаны последние сохранённые данные.',selected.online?'success':'warning');} else message('Устройства ATM21 пока не обнаружены.','secondary');
    }
    q('[data-device-select]').addEventListener('change',(e)=>select(e.target.value).catch(err=>message(err.message,'danger')));
    q('[data-poll]').addEventListener('click',async()=>{busy=true;render();message('Выполняется опрос…','info');try{await api(url(root.dataset.pollTemplate),{method:'POST',body:'{}'});await reload();message('Показания обновлены.','success');}catch(err){message(`Опрос не выполнен: ${err.message}. Последние данные сохранены.`,'danger');}finally{busy=false;render();}});
    q('[data-profile-form]').addEventListener('submit',async(e)=>{e.preventDefault();if(root.dataset.canAdmin!=='1')return;try{await api(url(root.dataset.detailTemplate),{method:'PATCH',body:JSON.stringify({name:q('[data-name]').value,address_text:q('[data-address]').value,latitude:q('[data-lat]').value,longitude:q('[data-lon]').value})});await reload();message('Карточка объекта сохранена.','success');}catch(err){message(err.message,'danger');}});
    async function tick(){try{await reload();}catch(err){message(`Мониторинг недоступен: ${err.message}`,'danger');}finally{if(!stopped)timer=setTimeout(tick,10000);}}
    window.addEventListener('opora:before-navigate',()=>{stopped=true;clearTimeout(timer);},{once:true}); tick();
  }
  document.addEventListener('DOMContentLoaded',boot); window.addEventListener('opora:navigated',boot);
})();
