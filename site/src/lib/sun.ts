// График включения уличного освещения по восходу и закату (уравнение восхода, NOAA/Википедия).
// Свет включается через ON_AFTER_SUNSET минут после заката и выключается за OFF_BEFORE_SUNRISE минут до восхода.
// Реальный график службы задаётся приказом — при запуске сверить смещения с диспетчерской.

export const KIROV = { lat: 58.6036, lon: 49.668 };
export const TZ = 'Europe/Kirov';
export const ON_AFTER_SUNSET = 15;
export const OFF_BEFORE_SUNRISE = 15;

const RAD = Math.PI / 180;
const DAY_MS = 86_400_000;
const J2000 = 2451545.0;
const UNIX_EPOCH_JD = 2440587.5;

const jdToDate = (jd: number) => new Date((jd - UNIX_EPOCH_JD) * DAY_MS);

/** Восход и закат для календарной даты (год, месяц 1–12, день). */
export function sunTimes(y: number, m: number, d: number, lat = KIROV.lat, lon = KIROV.lon) {
  const jdNoon = Date.UTC(y, m - 1, d, 12) / DAY_MS + UNIX_EPOCH_JD;
  const n = Math.round(jdNoon - J2000 + 0.0008);
  const jStar = n - lon / 360;
  const M = (357.5291 + 0.98560028 * jStar) % 360;
  const C = 1.9148 * Math.sin(M * RAD) + 0.02 * Math.sin(2 * M * RAD) + 0.0003 * Math.sin(3 * M * RAD);
  const lambda = (M + C + 180 + 102.9372) % 360;
  const jTransit = J2000 + jStar + 0.0053 * Math.sin(M * RAD) - 0.0069 * Math.sin(2 * lambda * RAD);
  const sinDecl = Math.sin(lambda * RAD) * Math.sin(23.4397 * RAD);
  const cosDecl = Math.cos(Math.asin(sinDecl));
  const cosW = (Math.sin(-0.833 * RAD) - Math.sin(lat * RAD) * sinDecl) / (Math.cos(lat * RAD) * cosDecl);
  const w = Math.acos(Math.min(1, Math.max(-1, cosW))) / RAD;
  return { sunrise: jdToDate(jTransit - w / 360), sunset: jdToDate(jTransit + w / 360) };
}

/** Календарная дата «сейчас» в Кирове. */
export function kirovToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(now)
    .reduce<Record<string, string>>((acc, p) => ((acc[p.type] = p.value), acc), {});
  return { y: Number(parts.year), m: Number(parts.month), d: Number(parts.day) };
}

export interface ScheduleRow {
  date: Date; // полдень этой даты (для подписей)
  on: Date; // включение вечером этой даты
  off: Date; // отключение утром следующего дня
}

/** Строки графика на `days` дней, начиная с даты (y, m, d). */
export function schedule(y: number, m: number, d: number, days = 7): ScheduleRow[] {
  const rows: ScheduleRow[] = [];
  for (let i = 0; i < days; i++) {
    const day = new Date(Date.UTC(y, m - 1, d + i, 12));
    const next = new Date(Date.UTC(y, m - 1, d + i + 1, 12));
    const today = sunTimes(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate());
    const tomorrow = sunTimes(next.getUTCFullYear(), next.getUTCMonth() + 1, next.getUTCDate());
    rows.push({
      date: day,
      on: new Date(today.sunset.getTime() + ON_AFTER_SUNSET * 60_000),
      off: new Date(tomorrow.sunrise.getTime() - OFF_BEFORE_SUNRISE * 60_000),
    });
  }
  return rows;
}

const timeFmt = new Intl.DateTimeFormat('ru-RU', { timeZone: TZ, hour: '2-digit', minute: '2-digit' });
const dayFmt = new Intl.DateTimeFormat('ru-RU', { timeZone: TZ, day: 'numeric', month: 'long' });
const weekdayFmt = new Intl.DateTimeFormat('ru-RU', { timeZone: TZ, weekday: 'short' });

export const fmtTime = (d: Date) => timeFmt.format(d);
export const fmtDay = (d: Date) => dayFmt.format(d);
export const fmtWeekday = (d: Date) => weekdayFmt.format(d).replace('.', '');

/** Длительность горения, например «13 ч 12 мин». */
export function fmtDuration(from: Date, to: Date) {
  const min = Math.round((to.getTime() - from.getTime()) / 60_000);
  return `${Math.floor(min / 60)} ч ${String(min % 60).padStart(2, '0')} мин`;
}
