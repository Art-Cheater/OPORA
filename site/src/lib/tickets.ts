// Модуль заявок. В демо-версии хранит всё в localStorage браузера.
// Для запуска замените реализацию функций на запросы к API (контракт — в README.md),
// интерфейс функций менять не нужно: страницы вызывают только их.
import { FAULTS, POLE_FALLING_TERM, SEED_POINTS, CITY, type FaultId, type StatusId, STATUSES } from '../data/site';

export interface TicketEvent {
  at: string; // ISO
  status: StatusId;
  comment: string;
}

export interface Ticket {
  number: string;
  key: string;
  type: FaultId;
  count?: 'one' | 'several' | 'street';
  emergency: boolean;
  address: string;
  pole?: string;
  lat?: number;
  lon?: number;
  comment?: string;
  photos?: string[];
  /** Контакты заявителя. Никогда не показываются на публичных страницах и карте. */
  contact?: { name?: string; phone?: string; email?: string };
  term: string;
  status: StatusId;
  history: TicketEvent[];
  createdAt: string;
  district: string;
  alsoSeen: number;
  source: 'site' | 'phone';
  showOnHome?: boolean;
}

export interface TicketDraft {
  type: FaultId;
  poleFalling?: boolean;
  count?: Ticket['count'];
  address: string;
  pole?: string;
  lat?: number;
  lon?: number;
  comment?: string;
  photos?: string[];
  contact?: Ticket['contact'];
}

const STORE = 'ks-tickets-v1';
const SEQ = 'ks-seq-v1';
const SENT = 'ks-sent-v1';
const DRAFT = 'ks-draft-v1';
export const DAILY_LIMIT = 5;
export const OPEN: StatusId[] = ['accepted', 'assigned', 'working', 'planned'];

const store = {
  get<T>(key: string, fallback: T): T {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : fallback;
    } catch {
      return fallback;
    }
  },
  set(key: string, value: unknown) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch {
      return false; // приватный режим или переполнено хранилище
    }
  },
};

// ---------- Номера и ключи ----------

const yy = () => String(new Date().getFullYear()).slice(-2);

export function formatNumber(seq: number) {
  return `КС-${yy()}-${String(seq).padStart(6, '0')}`;
}

/** Принимает «004812», «кс 26 4812», «KS-26-004812» — возвращает «КС-26-004812». */
export function normalizeNumber(input: string): string | null {
  const digits = input.replace(/[^0-9]/g, '');
  if (!digits) return null;
  if (digits.length > 6 && digits.length <= 8) return `КС-${digits.slice(0, 2)}-${digits.slice(2).padStart(6, '0')}`;
  if (digits.length <= 6) return formatNumber(Number(digits));
  return null;
}

function randomKey(len = 12) {
  const abc = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
  const bytes = new Uint8Array(len);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => abc[b % abc.length]).join('');
}

export function ticketUrl(t: Pick<Ticket, 'number' | 'key'>, withKey = true) {
  const params = new URLSearchParams({ n: t.number });
  if (withKey) params.set('k', t.key);
  return `/zayavka/?${params}`;
}

// ---------- Справочники ----------

export const faultTitle = (id: FaultId) => FAULTS.find((f) => f.id === id)?.title ?? 'Неисправность';
export const statusTitle = (id: StatusId) => STATUSES[id].title;

export function termFor(type: FaultId, poleFalling?: boolean) {
  if (type === 'pole' && poleFalling) return POLE_FALLING_TERM;
  return FAULTS.find((f) => f.id === type)?.term ?? '';
}

export function isEmergency(type: FaultId, poleFalling?: boolean) {
  const f = FAULTS.find((x) => x.id === type);
  if (!f) return false;
  return f.emergency === 'ask' ? Boolean(poleFalling) : f.emergency;
}

/** Грубое определение района для демо (в рабочей версии — по геокодеру). */
export function districtFor(lat?: number, lon?: number) {
  if (lat == null || lon == null) return 'Не указан';
  if (lat < 58.56) return 'Нововятский';
  if (lon > 49.675 && lat > 58.595) return 'Первомайский';
  if (lat >= 58.603) return 'Октябрьский';
  return 'Ленинский';
}

export function insideCity(lat: number, lon: number) {
  const [s, w, n, e] = CITY?.bbox ?? [58.43, 49.11, 58.74, 49.82];
  return lat >= s && lat <= n && lon >= w && lon <= e;
}

export function distanceM(aLat: number, aLon: number, bLat: number, bLon: number) {
  const R = 6371e3;
  const toRad = (x: number) => (x * Math.PI) / 180;
  const dLat = toRad(bLat - aLat);
  const dLon = toRad(bLon - aLon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// ---------- Демо-данные ----------

function seed(): Ticket[] {
  const now = Date.now();
  const ago = (h: number) => new Date(now - h * 3_600_000).toISOString();
  const p = SEED_POINTS;
  const mk = (t: Partial<Ticket> & Pick<Ticket, 'number' | 'type' | 'address' | 'status' | 'history'>): Ticket => ({
    key: randomKey(),
    emergency: isEmergency(t.type),
    term: termFor(t.type),
    createdAt: t.history[0].at,
    district: districtFor(t.lat, t.lon),
    alsoSeen: 0,
    source: 'site',
    ...t,
  });
  return [
    mk({
      number: formatNumber(4812), key: 'demo4812', type: 'off', count: 'one', address: 'ул. Молодой Гвардии, д. 45',
      pole: '17-034', ...p.molodoyGvardii, status: 'done', comment: 'Не горит с понедельника, темно у перехода.',
      history: [
        { at: ago(44), status: 'accepted', comment: 'Заявка с сайта, 1 фото' },
        { at: ago(33.5), status: 'assigned', comment: 'Бригада № 4, выезд сегодня до 12:00' },
        { at: ago(33), status: 'working', comment: 'Бригада на месте' },
        { at: ago(28), status: 'done', comment: 'Заменён светильник. Проверьте вечером и нажмите «Спасибо, горит» или «Всё ещё не горит»' },
      ],
    }),
    mk({
      number: formatNumber(4790), type: 'street', count: 'street', address: 'ул. Чапаева, д. 20–48', ...p.chapaeva,
      status: 'working', alsoSeen: 11, showOnHome: false,
      history: [
        { at: ago(20), status: 'accepted', comment: 'Заявка по телефону' },
        { at: ago(19), status: 'assigned', comment: 'Аварийная бригада № 2' },
        { at: ago(6), status: 'working', comment: 'Повреждён подземный кабель, ведём раскопку. Свет будет сегодня к 21:00' },
      ],
    }),
    mk({
      number: formatNumber(4801), type: 'off', count: 'several', address: 'Октябрьский пр-т, д. 110', ...p.oktyabrsky,
      status: 'assigned', alsoSeen: 3,
      history: [
        { at: ago(15), status: 'accepted', comment: 'Заявка с сайта' },
        { at: ago(2), status: 'assigned', comment: 'Бригада № 7, выезд завтра до 13:00' },
      ],
    }),
    mk({
      number: formatNumber(4806), type: 'wire', address: 'Московская ул., д. 102', ...p.moskovskaya, status: 'working',
      history: [
        { at: ago(1.6), status: 'accepted', comment: 'Аварийная заявка с сайта, 2 фото' },
        { at: ago(1.4), status: 'assigned', comment: 'Аварийная бригада № 1' },
        { at: ago(0.7), status: 'working', comment: 'Бригада на месте, участок огорожен' },
      ],
    }),
    mk({
      number: formatNumber(4808), type: 'blink', count: 'one', address: 'ул. Карла Маркса, д. 70', ...p.karlaMarksa, status: 'accepted',
      history: [{ at: ago(9), status: 'accepted', comment: 'Заявка с сайта' }],
    }),
    mk({
      number: formatNumber(4810), type: 'day', count: 'several', address: 'ул. Лепсе, д. 30', ...p.lepse, status: 'accepted',
      history: [{ at: ago(4), status: 'accepted', comment: 'Заявка с сайта, 1 фото' }],
    }),
    mk({
      number: formatNumber(4795), type: 'pole', address: 'ул. Менделеева, д. 5', ...p.menedeleeva, status: 'planned', term: termFor('pole', false),
      history: [
        { at: ago(70), status: 'accepted', comment: 'Заявка с сайта' },
        { at: ago(60), status: 'assigned', comment: 'Бригада № 3' },
        { at: ago(52), status: 'planned', comment: 'Опора треснула у основания, угрозы падения нет. Замена опоры запланирована на 3 октября' },
      ],
    }),
    mk({
      number: formatNumber(4799), type: 'off', count: 'one', address: 'Солнечная ул., д. 25, двор', ...p.solnechnaya, status: 'foreign',
      history: [
        { at: ago(50), status: 'accepted', comment: 'Заявка с сайта' },
        { at: ago(47), status: 'foreign', comment: 'Фонарь над подъездом обслуживает управляющая компания дома. Передали ей заявку' },
      ],
    }),
    mk({
      number: formatNumber(4811), type: 'cabinet', address: 'Перекрёсток ул. Ленина и ул. Воровского', ...p.leninVorovskogo, status: 'assigned',
      history: [
        { at: ago(3), status: 'accepted', comment: 'Аварийная заявка по телефону' },
        { at: ago(2.5), status: 'assigned', comment: 'Аварийная бригада № 1, выезд до 18:00' },
      ],
    }),
    mk({
      number: formatNumber(4805), type: 'off', count: 'one', address: 'ул. Строителей, д. 10', ...p.stroiteley, status: 'done',
      history: [
        { at: ago(96), status: 'accepted', comment: 'Заявка с сайта' },
        { at: ago(80), status: 'assigned', comment: 'Бригада № 5' },
        { at: ago(78), status: 'working', comment: 'Бригада на месте' },
        { at: ago(77), status: 'done', comment: 'Заменена лампа' },
      ],
    }),
  ];
}

// ---------- Хранилище ----------

export function listTickets(): Ticket[] {
  let all = store.get<Ticket[] | null>(STORE, null);
  if (!all) {
    all = seed();
    store.set(STORE, all);
  }
  return all;
}

function saveAll(all: Ticket[]) {
  return store.set(STORE, all);
}

function mutate(number: string, fn: (t: Ticket) => void): Ticket | null {
  const all = listTickets();
  const t = all.find((x) => x.number === number);
  if (!t) return null;
  fn(t);
  saveAll(all);
  return t;
}

export function getTicket(number: string): Ticket | null {
  return listTickets().find((t) => t.number === number) ?? null;
}

/** Открытая заявка рядом с точкой — чтобы не плодить дубли. */
export function findNearbyOpen(lat: number, lon: number, radius = 50): (Ticket & { distance: number }) | null {
  let best: (Ticket & { distance: number }) | null = null;
  for (const t of listTickets()) {
    if (!OPEN.includes(t.status) || t.lat == null || t.lon == null) continue;
    const distance = distanceM(lat, lon, t.lat, t.lon);
    if (distance <= radius && (!best || distance < best.distance)) best = { ...t, distance };
  }
  return best;
}

export function sentToday() {
  const since = Date.now() - 86_400_000;
  return store.get<number[]>(SENT, []).filter((ts) => ts > since).length;
}

export function createTicket(d: TicketDraft): Ticket {
  if (sentToday() >= DAILY_LIMIT) throw new Error('limit');
  const all = listTickets();
  const seq = store.get<number>(SEQ, 4812) + 1;
  const photos = d.photos?.length ?? 0;
  const emergency = isEmergency(d.type, d.poleFalling);
  const now = new Date().toISOString();
  const t: Ticket = {
    number: formatNumber(seq),
    key: randomKey(),
    type: d.type,
    count: d.count,
    emergency,
    address: d.address || 'Метка на карте',
    pole: d.pole || undefined,
    lat: d.lat,
    lon: d.lon,
    comment: d.comment || undefined,
    photos: d.photos,
    contact: d.contact,
    term: termFor(d.type, d.poleFalling),
    status: 'accepted',
    history: [{ at: now, status: 'accepted', comment: `${emergency ? 'Аварийная заявка' : 'Заявка'} с сайта${photos ? `, ${photos} фото` : ''}` }],
    createdAt: now,
    district: districtFor(d.lat, d.lon),
    alsoSeen: 0,
    source: 'site',
  };
  all.push(t);
  if (!saveAll(all)) {
    // Не поместились фото — сохраняем без них.
    t.photos = undefined;
    saveAll(all);
  }
  store.set(SEQ, seq);
  store.set(SENT, [...store.get<number[]>(SENT, []), Date.now()]);
  return t;
}

export function addAlsoSeen(number: string) {
  return mutate(number, (t) => { t.alsoSeen += 1; });
}

/** Оценка заявителя после ремонта. Требует ключ из ссылки. */
export function feedback(number: string, key: string, stillBroken: boolean) {
  return mutate(number, (t) => {
    if (t.key !== key) throw new Error('key');
    const at = new Date().toISOString();
    if (stillBroken) {
      t.status = 'accepted';
      t.history.push({ at, status: 'accepted', comment: 'Заявитель сообщил: всё ещё не горит. Заявка открыта снова' });
    } else {
      t.history.push({ at, status: 'done', comment: 'Заявитель подтвердил: горит. Спасибо!' });
    }
  });
}

/** Смена статуса диспетчером. */
export function setStatus(number: string, status: StatusId, comment: string) {
  return mutate(number, (t) => {
    t.status = status;
    t.history.push({ at: new Date().toISOString(), status, comment: comment || statusTitle(status) });
  });
}

export function setShowOnHome(number: string, show: boolean) {
  return mutate(number, (t) => { t.showOnHome = show; });
}

export function resetDemo() {
  for (const k of [STORE, SEQ, SENT]) localStorage.removeItem(k);
}

// ---------- Черновик формы ----------

export const draft = {
  load: () => store.get<Record<string, unknown> | null>(DRAFT, null),
  save: (data: Record<string, unknown>) => store.set(DRAFT, data),
  clear: () => { try { localStorage.removeItem(DRAFT); } catch { /* ничего */ } },
};

// ---------- Форматирование ----------

const dtFmt = new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Kirov', day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });
export const fmtDateTime = (iso: string) => dtFmt.format(new Date(iso)).replace(' в ', ', ');

export const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
