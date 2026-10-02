// Карта на Leaflet + OpenStreetMap. В рабочей версии по ТЗ — Яндекс Карты и геокодер:
// замените createMap/marker, остальной код страниц от этого не зависит.
import type { Map as LMap, Marker, LatLngExpression } from 'leaflet';
import { CITY } from '../data/site';

export const KIROV_CENTER: [number, number] = [58.6036, 49.668];

export type MarkerKind = 'fault' | 'alarm' | 'ticket' | 'planned' | 'construction' | 'done' | 'me' | 'office';

let leafletPromise: Promise<typeof import('leaflet')> | null = null;

export function loadLeaflet() {
  if (!leafletPromise) {
    leafletPromise = Promise.all([import('leaflet'), import('leaflet/dist/leaflet.css')]).then(([L]) => L.default ?? L);
  }
  return leafletPromise;
}

export async function createMap(el: HTMLElement, opts: { center?: LatLngExpression; zoom?: number; scrollWheel?: boolean } = {}) {
  const L = await loadLeaflet();
  const [s, w, n, e] = CITY?.bbox ?? [58.43, 49.11, 58.74, 49.82];
  const map = L.map(el, {
    center: opts.center ?? KIROV_CENTER,
    zoom: opts.zoom ?? 13,
    minZoom: 10,
    maxBounds: L.latLngBounds([s - 0.15, w - 0.3], [n + 0.15, e + 0.3]),
    scrollWheelZoom: opts.scrollWheel ?? false,
    attributionControl: true,
  });
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  map.attributionControl.setPrefix(false);
  return { L, map };
}

export function markerIcon(L: typeof import('leaflet'), kind: MarkerKind, label = '') {
  const safe = label.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
  return L.divIcon({
    className: `mk mk--${kind}`,
    html: `<span class="mk__dot" aria-hidden="true"></span>${safe ? `<span class="visually-hidden">${safe}</span>` : ''}`,
    iconSize: [28, 28],
    iconAnchor: [14, 14],
    popupAnchor: [0, -14],
  });
}

/** Текст подписи из HTML подсказки: маркер — это кнопка, и у неё должно быть имя для скринридера. */
const textFromHtml = (html?: string) =>
  html ? new DOMParser().parseFromString(html.replace(/<br\s*\/?>/gi, '. '), 'text/html').body.textContent?.trim() ?? '' : '';

export function addMarker(
  L: typeof import('leaflet'), map: LMap, lat: number, lon: number, kind: MarkerKind, popupHtml?: string,
  opts: { draggable?: boolean; label?: string } = {},
): Marker {
  const label = opts.label ?? textFromHtml(popupHtml);
  const m = L.marker([lat, lon], { icon: markerIcon(L, kind, label), draggable: opts.draggable ?? false, keyboard: true, title: label }).addTo(map);
  if (popupHtml) m.bindPopup(popupHtml);
  return m;
}
