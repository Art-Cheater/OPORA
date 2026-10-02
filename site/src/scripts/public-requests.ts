/** Открытые заявки с публичной карты. Лишние поля из ответа не показываем. */

export interface PublicRequest {
  address: string;
  status: string;
  district?: string;
  lat?: number;
  lon?: number;
}

export function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!);
}

export async function loadPublicRequests(): Promise<PublicRequest[]> {
  const response = await fetch('/api/map.json', { headers: { Accept: 'application/json' }, credentials: 'omit' });
  if (!response.ok) throw new Error('map');
  const data = await response.json();
  if (!data || data.ok !== true || !Array.isArray(data.items)) throw new Error('map');
  return data.items.map(asPublicRequest).filter((item): item is PublicRequest => item !== null);
}

function asPublicRequest(raw: unknown): PublicRequest | null {
  if (!raw || typeof raw !== 'object') return null;
  const item = raw as Record<string, unknown>;
  const address = typeof item.address === 'string' ? item.address.trim() : '';
  const status = typeof item.status === 'string' ? item.status.trim() : '';
  if (!address || !status) return null;
  const point: PublicRequest = { address, status };
  if (typeof item.district === 'string' && item.district.trim()) point.district = item.district.trim();
  if (typeof item.lat === 'number' && typeof item.lon === 'number' && Number.isFinite(item.lat) && Number.isFinite(item.lon)) {
    point.lat = item.lat;
    point.lon = item.lon;
  }
  return point;
}

export function pluralRequests(count: number) {
  const mod10 = count % 10;
  const mod100 = count % 100;
  const word = mod10 === 1 && mod100 !== 11 ? 'заявка' : mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20) ? 'заявки' : 'заявок';
  return `${count} ${word}`;
}
