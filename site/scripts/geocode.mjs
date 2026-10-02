// Разовое получение координат улиц Кирова через Nominatim (OpenStreetMap).
// Результат: src/data/geo.json. Запускать вручную: npm run geo
// Правила Nominatim: не чаще 1 запроса в секунду, осмысленный User-Agent, без автодополнения в реальном времени.
import { writeFile } from 'node:fs/promises';

const STREETS = [
  'улица Ленина', 'Октябрьский проспект', 'улица Воровского', 'Московская улица', 'улица Карла Маркса',
  'улица Чапаева', 'улица Молодой Гвардии', 'Профсоюзная улица', 'улица Горького', 'улица МОПРа',
  'улица Свободы', 'Комсомольская улица', 'улица Труда', 'Спасская улица', 'Преображенская улица',
  'улица Герцена', 'улица Дерендяева', 'Милицейская улица', 'Красноармейская улица', 'Ленинградская улица',
  'Солнечная улица', 'Пролетарская улица', 'улица Лепсе', 'улица Щорса', 'улица Строителей',
  'улица Попова', 'Производственная улица', 'улица Некрасова', 'Мостовая улица', 'Уральская улица',
  'улица Менделеева', 'улица Орджоникидзе', 'улица Большевиков', 'улица Маклина', 'Богородская улица',
  'Пятницкая улица', 'Казанская улица', 'улица Володарского', 'улица Декабристов', 'Хлыновская улица',
  'улица Сурикова', 'Ульяновская улица', 'улица Азина', 'улица Филатова', 'Воровского улица',
];

// Точки для демо-аварий, образца заявки и демо-заявок диспетчера.
const POINTS = {
  chapaeva: 'улица Чапаева, 36, Киров',
  oktyabrsky: 'Октябрьский проспект, 110, Киров',
  leninVorovskogo: 'улица Ленина, 101, Киров',
  novovyatsk: 'Советская улица, Нововятский район, Киров',
  molodoyGvardii: 'улица Молодой Гвардии, 45, Киров',
  bogorodskaya: 'Богородская улица, Киров',
  moskovskaya: 'Московская улица, 102, Киров',
  profsoyuznaya: 'Профсоюзная улица, 20, Киров',
  karlaMarksa: 'улица Карла Маркса, 70, Киров',
  svobody: 'улица Свободы, 120, Киров',
  solnechnaya: 'Солнечная улица, 25, Киров',
  lepse: 'улица Лепсе, 30, Киров',
  stroiteley: 'улица Строителей, 10, Киров',
  gorkogo: 'улица Горького, 50, Киров',
  menedeleeva: 'улица Менделеева, 5, Киров',
  centre: 'Театральная площадь, Киров',
};

const UA = 'kirovsvet-site-build/0.1 (demo geocoding; contact: site maintainer)';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function search(params) {
  const url = new URL('https://nominatim.openstreetmap.org/search');
  for (const [k, v] of Object.entries({ format: 'jsonv2', limit: '1', countrycodes: 'ru', 'accept-language': 'ru', ...params })) {
    url.searchParams.set(k, v);
  }
  const res = await fetch(url, { headers: { 'User-Agent': UA } });
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  const [hit] = await res.json();
  await sleep(1100);
  return hit ?? null;
}

const round = (n) => Math.round(Number(n) * 1e5) / 1e5;

const out = { streets: [], points: {}, city: null };

const city = await search({ q: 'городской округ город Киров, Кировская область' });
if (city) {
  const [s, n, w, e] = city.boundingbox.map(Number);
  out.city = { lat: round(city.lat), lon: round(city.lon), bbox: [round(s), round(w), round(n), round(e)] };
}

const seen = new Set();
for (const street of STREETS) {
  const hit = await search({ street, city: 'Киров', state: 'Кировская область' });
  if (!hit) { console.warn('нет:', street); continue; }
  const name = hit.name || street;
  if (seen.has(name)) continue;
  seen.add(name);
  out.streets.push({ name: street, lat: round(hit.lat), lon: round(hit.lon) });
  console.log('ok', street, hit.lat, hit.lon);
}

for (const [key, q] of Object.entries(POINTS)) {
  const hit = await search({ q });
  if (!hit) { console.warn('нет точки:', key); continue; }
  out.points[key] = { lat: round(hit.lat), lon: round(hit.lon), label: hit.display_name.split(',').slice(0, 3).join(',') };
  console.log('pt', key, hit.lat, hit.lon);
}

await writeFile(new URL('../src/data/geo.json', import.meta.url), JSON.stringify(out, null, 2) + '\n');
console.log('streets:', out.streets.length, 'points:', Object.keys(out.points).length);
