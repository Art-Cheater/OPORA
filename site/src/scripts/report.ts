// Форма «Сообщить о неисправности»: 4 шага, по одному вопросу на шаг.
import type { Map as LMap, Marker } from 'leaflet';
import { createMap, addMarker, KIROV_CENTER } from '../lib/map';
import { FAULTS, type FaultId } from '../data/site';
import {
  createTicket, findNearbyOpen, addAlsoSeen, termFor, isEmergency, insideCity, draft, ticketUrl, faultTitle,
  statusTitle, sentToday, DAILY_LIMIT, escapeHtml, type TicketDraft,
} from '../lib/tickets';
import { iconSvg } from '../lib/icons';

type Street = { name: string; lat: number; lon: number };

const form = document.getElementById('report') as HTMLFormElement | null;
if (form) init(form);

function init(form: HTMLFormElement) {
  const $ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) => root.querySelector<T>(sel);
  const $$ = <T extends Element = HTMLElement>(sel: string, root: ParentNode = document) => [...root.querySelectorAll<T>(sel)];
  const steps = $$<HTMLFieldSetElement>('[data-step]', form);
  const total = steps.length;
  const state: { lat?: number; lon?: number; photos: string[]; joined?: string } = { photos: [] };
  let current = 1;
  let map: LMap | null = null;
  let marker: Marker | null = null;
  let L: typeof import('leaflet') | null = null;

  const val = (name: string) => {
    const el = form.elements.namedItem(name);
    if (el instanceof RadioNodeList) return el.value;
    return (el as HTMLInputElement | null)?.value?.trim() ?? '';
  };
  const setVal = (name: string, v: string) => {
    const el = form.elements.namedItem(name);
    if (el instanceof RadioNodeList) el.value = v;
    else if (el) (el as HTMLInputElement).value = v;
  };

  // ---------- Шаги ----------
  function show(n: number, focus = true) {
    current = n;
    steps.forEach((s) => (s.hidden = Number(s.dataset.step) !== n));
    $$('[data-progress-step]').forEach((li) => {
      const i = Number(li.dataset.progressStep);
      li.dataset.state = i < n ? 'done' : '';
      if (i === n) li.setAttribute('aria-current', 'step');
      else li.removeAttribute('aria-current');
    });
    const text = $('[data-step-text]');
    if (text) text.textContent = `Шаг ${n} из ${total}`;
    if (n === 2) void initMap();
    if (n === 4) renderSummary();
    if (focus) {
      $<HTMLElement>('.step__title', steps[n - 1])?.focus({ preventScroll: true });
      const top = form.getBoundingClientRect().top + window.scrollY - 140;
      if (window.scrollY > top) window.scrollTo({ top, behavior: 'smooth' });
    }
    saveDraft();
  }

  // ---------- Ошибки у полей (ui-ux-pro-max: error-placement, aria-live-errors, focus-management) ----------
  type Field = 'type' | 'poleFalling' | 'where' | 'phone' | 'email' | 'consent' | 'general';
  type FieldError = { field: Field; msg: string };
  const STEP_FIELDS: Record<number, Field[]> = { 1: ['type', 'poleFalling'], 2: ['where'], 3: [], 4: ['phone', 'email', 'consent'] };
  const ERROR_ID: Partial<Record<Field, string>> = {
    type: 'type-error', poleFalling: 'pole-error', where: 'where-error', phone: 'phone-error', email: 'email-error', consent: 'consent-error',
  };
  const control = (f: Field) => form.querySelector<HTMLElement>(`[data-field="${f}"]`);

  function setFieldError(f: Field, msg: string) {
    const el = f === 'general' ? $('[data-error]', steps[current - 1]) : document.getElementById(ERROR_ID[f]!);
    if (el) { el.textContent = msg; el.hidden = !msg; }
    const ctl = f === 'general' ? null : control(f);
    if (ctl) msg ? ctl.setAttribute('aria-invalid', 'true') : ctl.removeAttribute('aria-invalid');
  }

  function checkField(f: Field): string {
    switch (f) {
      case 'type': return val('type') ? '' : 'Выберите, что случилось: нажмите на одну из плиток.';
      case 'poleFalling': return val('type') === 'pole' && !val('poleFalling') ? 'Ответьте, может ли опора упасть, — от этого зависит срок выезда.' : '';
      case 'where':
        if (state.lat == null && val('address').length < 3) return 'Поставьте метку на карте или напишите адрес — хотя бы улицу.';
        if (state.lat != null && !insideCity(state.lat, state.lon!)) return 'Метка за пределами Кирова. Перетащите её на улицу города.';
        return '';
      case 'phone': {
        const digits = val('phone').replace(/\D/g, '');
        return val('phone') && (digits.length < 10 || digits.length > 11) ? 'Проверьте номер: нужно 10–11 цифр, например +7 912 345-67-89.' : '';
      }
      case 'email': return val('email') && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(val('email')) ? 'Проверьте email: должен быть вида name@mail.ru.' : '';
      case 'consent': return hasContact() && !(form.elements.namedItem('consent') as HTMLInputElement).checked ? 'Отметьте согласие или сотрите контакты — без них заявку тоже примем.' : '';
      default: return '';
    }
  }

  function validate(n: number): FieldError[] {
    const errs = (STEP_FIELDS[n] ?? []).map((field) => ({ field, msg: checkField(field) })).filter((e) => e.msg);
    if (n === 4 && sentToday() >= DAILY_LIMIT) {
      errs.push({ field: 'general', msg: `С этого устройства уже отправлено ${DAILY_LIMIT} заявок за сутки. Если нужно ещё — позвоните диспетчеру.` });
    }
    return errs;
  }

  function showErrors(n: number, errs: FieldError[]) {
    [...(STEP_FIELDS[n] ?? []), 'general' as Field].forEach((f) => setFieldError(f, ''));
    errs.forEach((e) => setFieldError(e.field, e.msg));
    const first = errs[0];
    if (!first) return;
    const ctl = first.field === 'general' ? null : control(first.field);
    const target = ctl?.getAttribute('role') === 'radiogroup' ? ctl.querySelector<HTMLInputElement>('input') : ctl;
    target?.focus();
  }

  form.addEventListener('click', (e) => {
    const t = e.target as HTMLElement;
    if (t.closest('[data-next]')) {
      const errs = validate(current);
      showErrors(current, errs);
      if (!errs.length) show(current + 1);
    }
    if (t.closest('[data-prev]')) { showErrors(current, []); show(current - 1); }
  });

  // Телефон и email проверяем, когда человек закончил ввод, а не на каждую букву (inline-validation)
  (['phone', 'email'] as const).forEach((f) => {
    const input = control(f) as HTMLInputElement;
    input.addEventListener('blur', () => setFieldError(f, checkField(f)));
    input.addEventListener('input', () => { if (input.getAttribute('aria-invalid')) setFieldError(f, checkField(f)); });
  });

  // ---------- Шаг 1: тип ----------
  const EMERGENCY_TYPES = new Set(FAULTS.filter((f) => f.emergency === true).map((f) => f.id));
  function onTypeChange() {
    const type = val('type') as FaultId | '';
    const pole = type === 'pole';
    $('[data-pole-q]')!.hidden = !pole;
    const danger = (type && EMERGENCY_TYPES.has(type)) || (pole && val('poleFalling') === 'yes');
    $('[data-danger]')!.hidden = !danger;
    const countQ = $('[data-count-q]')!;
    countQ.hidden = !type || ['wire', 'cabinet', 'pole', 'street'].includes(type);
    if (type === 'street') setVal('count', 'street');
  }
  form.addEventListener('change', (e) => {
    const name = (e.target as HTMLInputElement).name;
    if (name === 'type' || name === 'poleFalling') { onTypeChange(); setFieldError(name, ''); }
    if (name === 'consent') setFieldError('consent', '');
    if (['name', 'phone', 'email'].includes(name)) toggleConsent();
  });

  // ---------- Шаг 2: где ----------
  const coordsEl = $('[data-coords]')!;
  async function initMap() {
    if (map) { map.invalidateSize(); return; }
    const el = $('[data-map]')!;
    try {
      ({ L, map } = await createMap(el, { center: state.lat != null ? [state.lat, state.lon!] : KIROV_CENTER, zoom: state.lat != null ? 17 : 13 }));
    } catch {
      el.innerHTML = '<p style="padding:16px">Карта не загрузилась. Напишите адрес в поле справа.</p>';
      return;
    }
    map.on('click', (ev) => setPoint(ev.latlng.lat, ev.latlng.lng));
    if (state.lat != null) setPoint(state.lat, state.lon!, false);
  }

  function setPoint(lat: number, lon: number, pan = true) {
    state.lat = +lat.toFixed(6);
    state.lon = +lon.toFixed(6);
    if (map && L) {
      if (!marker) {
        marker = addMarker(L, map, lat, lon, 'me', undefined, { draggable: true, label: 'Метка места неисправности. Её можно перетащить' });
        marker.on('dragend', () => { const p = marker!.getLatLng(); setPoint(p.lat, p.lng, false); });
      } else marker.setLatLng([lat, lon]);
      if (pan) map.panTo([lat, lon]);
    }
    const inside = insideCity(state.lat, state.lon);
    coordsEl.textContent = inside ? `Метка: ${state.lat.toFixed(5)}, ${state.lon.toFixed(5)}` : 'Метка за пределами Кирова';
    setFieldError('where', inside ? '' : checkField('where'));
    checkDuplicate();
    saveDraft();
  }

  $('[data-locate]')?.addEventListener('click', () => {
    if (!('geolocation' in navigator)) { coordsEl.textContent = 'Телефон не даёт определить место. Поставьте метку вручную.'; return; }
    coordsEl.textContent = 'Определяем место…';
    navigator.geolocation.getCurrentPosition(
      (pos) => { setPoint(pos.coords.latitude, pos.coords.longitude); map?.setView([pos.coords.latitude, pos.coords.longitude], 17); },
      () => { coordsEl.textContent = 'Не удалось определить место. Разрешите доступ к геопозиции или поставьте метку вручную.'; },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
    );
  });

  // Дубли: открытая заявка в радиусе 50 м
  function checkDuplicate() {
    const box = $('[data-dup]')!;
    if (state.lat == null) { box.hidden = true; return; }
    const t = findNearbyOpen(state.lat, state.lon!, 50);
    if (!t) { box.hidden = true; return; }
    const others = t.alsoSeen ? ` Ещё ${t.alsoSeen} чел. тоже сообщили.` : '';
    $('[data-dup-text]')!.textContent = `Заявка ${t.number}, ${faultTitle(t.type).toLowerCase()}, ${t.address}. Статус — ${statusTitle(t.status).toLowerCase()}.${others}`;
    ($('[data-dup-link]') as HTMLAnchorElement).href = ticketUrl(t, false);
    const join = $<HTMLButtonElement>('[data-dup-join]')!;
    join.dataset.number = t.number;
    join.disabled = state.joined === t.number;
    if (state.joined === t.number) join.innerHTML = `${iconSvg('check', 20)} Вы отметились`;
    box.hidden = false;
  }
  $('[data-dup-join]')?.addEventListener('click', (e) => {
    const btn = e.currentTarget as HTMLButtonElement;
    const n = btn.dataset.number;
    if (!n) return;
    addAlsoSeen(n);
    state.joined = n;
    btn.disabled = true;
    btn.innerHTML = `${iconSvg('check', 20)} Спасибо, отметили`;
  });

  // Подсказки адреса по улицам города
  const streets: Street[] = JSON.parse(document.getElementById('streets-data')?.textContent || '[]');
  const shortName = (n: string) =>
    n.replace(/^улица (.+)$/, 'ул. $1').replace(/^(.+) улица$/, '$1 ул.').replace(/^(.+) проспект$/, '$1 пр-т').replace(/^проспект (.+)$/, 'пр-т $1');
  const addr = $<HTMLInputElement>('#address')!;
  const list = $<HTMLUListElement>('#address-list')!;
  let active = -1;
  let found: Street[] = [];
  function renderSuggest() {
    const q = addr.value.toLowerCase().replace(/(улица|ул\.|проспект|пр-т|,.*)/g, '').trim();
    found = q.length < 2 ? [] : streets.filter((s) => s.name.toLowerCase().includes(q)).slice(0, 8);
    active = -1;
    list.innerHTML = found.map((s, i) => `<li role="option" id="sg-${i}" aria-selected="false">${escapeHtml(shortName(s.name))}</li>`).join('');
    list.hidden = !found.length;
    addr.setAttribute('aria-expanded', String(!!found.length));
  }
  function pick(i: number) {
    const s = found[i];
    if (!s) return;
    addr.value = `${shortName(s.name)}, `;
    list.hidden = true;
    addr.setAttribute('aria-expanded', 'false');
    addr.focus();
    map?.setView([s.lat, s.lon], 16);
    if (state.lat == null) coordsEl.textContent = 'Уточните место: нажмите на карту рядом с фонарём.';
    saveDraft();
  }
  addr.addEventListener('input', () => {
    renderSuggest();
    if (addr.getAttribute('aria-invalid') && !checkField('where')) setFieldError('where', '');
  });
  addr.addEventListener('keydown', (e) => {
    if (list.hidden) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + found.length) % found.length;
      $$('li', list).forEach((li, i) => li.setAttribute('aria-selected', String(i === active)));
      addr.setAttribute('aria-activedescendant', `sg-${active}`);
    } else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); pick(active); }
    else if (e.key === 'Escape') { list.hidden = true; addr.setAttribute('aria-expanded', 'false'); }
  });
  list.addEventListener('mousedown', (e) => {
    const li = (e.target as HTMLElement).closest('li');
    if (li) { e.preventDefault(); pick($$('li', list).indexOf(li)); }
  });
  addr.addEventListener('blur', () => setTimeout(() => (list.hidden = true), 120));

  // ---------- Шаг 3: фото ----------
  const photosEl = $('[data-photos]')!;
  const addBox = $('[data-photo-add]')!;
  async function compress(file: File, max = 1280, quality = 0.72): Promise<string> {
    const bmp = await createImageBitmap(file);
    const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bmp.width * k);
    canvas.height = Math.round(bmp.height * k);
    canvas.getContext('2d')!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close();
    return canvas.toDataURL('image/jpeg', quality);
  }
  function renderPhotos() {
    photosEl.innerHTML = state.photos
      .map((src, i) => `<div class="thumb"><img src="${src}" alt="Фото ${i + 1}"><button type="button" data-remove="${i}" aria-label="Удалить фото ${i + 1}">${iconSvg('close', 18)}</button></div>`)
      .join('');
    addBox.hidden = state.photos.length >= 3;
  }
  $$<HTMLInputElement>('[data-photo-input]').forEach((input) =>
    input.addEventListener('change', async () => {
      for (const f of [...(input.files ?? [])]) {
        if (state.photos.length >= 3) break;
        if (!f.type.startsWith('image/')) continue;
        try { state.photos.push(await compress(f)); } catch { /* пропускаем битый файл */ }
      }
      input.value = '';
      renderPhotos();
    }),
  );
  photosEl.addEventListener('click', (e) => {
    const b = (e.target as HTMLElement).closest<HTMLButtonElement>('[data-remove]');
    if (b) { state.photos.splice(Number(b.dataset.remove), 1); renderPhotos(); }
  });
  const comment = $<HTMLTextAreaElement>('#comment')!;
  const counter = $('[data-counter]')!;
  comment.addEventListener('input', () => (counter.textContent = `${comment.value.length} / 500`));

  // ---------- Шаг 4: контакты ----------
  const hasContact = () => Boolean(val('name') || val('phone') || val('email'));
  function toggleConsent() { $('[data-consent]')!.hidden = !hasContact(); }
  ['name', 'phone', 'email'].forEach((n) => (form.elements.namedItem(n) as HTMLInputElement).addEventListener('input', toggleConsent));

  const COUNT: Record<string, string> = { one: 'один фонарь', several: 'несколько подряд', street: 'вся улица' };
  function renderSummary() {
    const type = val('type') as FaultId;
    const falling = val('poleFalling') === 'yes';
    const where = [val('address'), state.lat != null ? `метка ${state.lat.toFixed(5)}, ${state.lon!.toFixed(5)}` : '', val('pole') ? `опора № ${val('pole')}` : '']
      .filter(Boolean).join(' · ');
    const rows: [string, string][] = [
      ['Что', `${faultTitle(type)}${val('count') ? `, ${COUNT[val('count')]}` : ''}${type === 'pole' ? (falling ? ', может упасть' : ', стоит ровно') : ''}`],
      ['Где', where || '—'],
      ['Фото', state.photos.length ? `${state.photos.length} шт.` : 'нет'],
      ['Срок', termFor(type, falling)],
    ];
    if (val('comment')) rows.splice(3, 0, ['Комментарий', val('comment')]);
    $('[data-summary]')!.innerHTML = `<h3>Проверьте заявку${isEmergency(type, falling) ? ' — аварийная' : ''}</h3><dl>${rows
      .map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join('')}</dl>`;
  }

  // ---------- Отправка ----------
  // Демо: заявка сохраняется в браузере. В рабочей версии здесь SmartCaptcha и POST /api/tickets.
  const submitTicket = async (d: TicketDraft) => createTicket(d);
  let submitting = false;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (submitting) return;
    const errs = validate(4);
    showErrors(4, errs);
    if (errs.length) return;
    const type = val('type') as FaultId;
    const d: TicketDraft = {
      type,
      poleFalling: type === 'pole' ? val('poleFalling') === 'yes' : undefined,
      count: (val('count') || undefined) as TicketDraft['count'],
      address: val('address').replace(/,\s*$/, ''),
      pole: val('pole'),
      lat: state.lat,
      lon: state.lon,
      comment: val('comment'),
      photos: state.photos,
      contact: hasContact() ? { name: val('name'), phone: val('phone'), email: val('email') } : undefined,
    };

    // Состояние отправки: кнопка блокируется сразу, надпись «Отправляем…» — только если ждать дольше 300 мс
    submitting = true;
    const btn = $<HTMLButtonElement>('[data-submit]')!;
    const label = $('[data-submit-label]')!;
    btn.disabled = true;
    form.setAttribute('aria-busy', 'true');
    const slow = window.setTimeout(() => (label.textContent = 'Отправляем…'), 300);
    let t: Awaited<ReturnType<typeof submitTicket>>;
    try {
      t = await submitTicket(d);
    } catch (err) {
      setFieldError('general', (err as Error).message === 'limit'
        ? `С этого устройства уже отправлено ${DAILY_LIMIT} заявок за сутки. Если нужно ещё — позвоните диспетчеру.`
        : 'Не получилось отправить. Проверьте интернет и нажмите ещё раз — всё введённое сохранено.');
      return;
    } finally {
      clearTimeout(slow);
      submitting = false;
      btn.disabled = false;
      form.removeAttribute('aria-busy');
      label.textContent = 'Отправить заявку';
    }
    draft.clear();
    form.hidden = true;
    $('[data-progress]')!.hidden = true;
    $('[data-step-text]')!.hidden = true;
    $$('[data-draft-note], [data-qr-note]').forEach((n) => (n.hidden = true));
    const done = $('[data-done]')!;
    $('[data-done-number]')!.textContent = t.number;
    $('[data-done-term]')!.textContent = t.emergency ? `${t.term}. Заявка аварийная.` : `Нормативный срок ремонта: ${t.term}.`;
    $('[data-done-alarm]')!.hidden = !t.emergency;
    $('[data-done-sms]')!.hidden = !d.contact?.phone;
    $('[data-done-nosms]')!.hidden = Boolean(d.contact?.phone);
    ($('[data-done-link]') as HTMLAnchorElement).href = ticketUrl(t);
    done.hidden = false;
    $<HTMLElement>('#done-title')?.focus();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  $('[data-copy]')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget as HTMLButtonElement;
    const text = $('[data-done-number]')!.textContent || '';
    try { await navigator.clipboard.writeText(text); btn.querySelector('span')!.textContent = 'Скопировано'; }
    catch { btn.querySelector('span')!.textContent = 'Выделите номер вручную'; }
  });

  // ---------- Черновик ----------
  const FIELDS = ['type', 'poleFalling', 'count', 'address', 'pole', 'comment', 'name', 'phone', 'email'];
  let saveTimer = 0;
  function saveDraft() {
    clearTimeout(saveTimer);
    saveTimer = window.setTimeout(() => {
      const data: Record<string, unknown> = { step: current, lat: state.lat, lon: state.lon };
      FIELDS.forEach((f) => (data[f] = val(f)));
      if (FIELDS.some((f) => data[f]) || state.lat != null) draft.save(data);
    }, 250);
  }
  form.addEventListener('input', saveDraft);
  form.addEventListener('change', saveDraft);
  $('[data-draft-reset]')?.addEventListener('click', () => { draft.clear(); location.href = location.pathname; });

  // ---------- Старт: QR-код на опоре или черновик ----------
  const params = new URLSearchParams(location.search);
  const qLat = Number(params.get('lat'));
  const qLon = Number(params.get('lon'));
  let startStep = 1;
  if (params.get('pole') || (qLat && qLon)) {
    if (params.get('pole')) setVal('pole', params.get('pole')!.slice(0, 16));
    if (qLat && qLon && insideCity(qLat, qLon)) { state.lat = qLat; state.lon = qLon; coordsEl.textContent = `Метка: ${qLat.toFixed(5)}, ${qLon.toFixed(5)}`; }
    $('[data-qr-note]')!.hidden = false;
  } else {
    const saved = draft.load();
    if (saved) {
      FIELDS.forEach((f) => typeof saved[f] === 'string' && saved[f] && setVal(f, saved[f] as string));
      if (typeof saved.lat === 'number' && typeof saved.lon === 'number') {
        state.lat = saved.lat; state.lon = saved.lon;
        coordsEl.textContent = `Метка: ${saved.lat.toFixed(5)}, ${saved.lon.toFixed(5)}`;
      }
      startStep = Math.min(Number(saved.step) || 1, 3);
      $('[data-draft-note]')!.hidden = false;
      counter.textContent = `${comment.value.length} / 500`;
    }
  }
  onTypeChange();
  toggleConsent();
  if (startStep > 1 && validate(1).length) startStep = 1;
  show(startStep, false);
}
