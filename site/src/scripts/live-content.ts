/** Подставляет телефоны и новости, которые задали в кабинете. */

export interface PhoneCard {
  title: string;
  note: string;
  phone: string;
  tel: string;
  hours: string;
}

export interface LiveNews {
  slug: string;
  date: string;
  title: string;
  lead: string;
  image: string | null;
}

export interface LiveContent {
  phones: Record<string, PhoneCard>;
  schedule: {
    on_after_sunset: number;
    off_before_sunrise: number;
    days: { date: string; on: string; off: string }[];
  };
  news: LiveNews[];
}

let pending: Promise<LiveContent | null> | null = null;

export function loadContent(): Promise<LiveContent | null> {
  if (!pending) {
    pending = fetch('/api/content.json', { credentials: 'omit' })
      .then((response) => (response.ok ? response.json() : null))
      .catch(() => null);
  }
  return pending;
}

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]!));
}

function newsCard(item: LiveNews, heading: 'h2' | 'h3') {
  const date = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(item.date));
  const image = item.image ? `<img src="${escapeHtml(item.image)}" alt="">` : '';
  return `<article class="ks-card"><a href="/novosti/${escapeHtml(item.slug)}/">${image}<time datetime="${escapeHtml(item.date)}">${escapeHtml(date)}</time><${heading}>${escapeHtml(item.title)}</${heading}><p>${escapeHtml(item.lead)}</p></a></article>`;
}

export async function applyLiveContent() {
  const data = await loadContent();
  if (!data) return;
  document.querySelectorAll<HTMLElement>('[data-ks-phone]').forEach((el) => {
    const phone = data.phones[el.dataset.ksPhone || ''];
    if (!phone) return;
    const link = el.matches('a') ? el : el.querySelector('a');
    if (link instanceof HTMLAnchorElement && phone.tel) link.href = `tel:${phone.tel}`;
    const text = el.querySelector('[data-ks-phone-text]');
    if (text) text.textContent = phone.phone;
    else if (link && link.childElementCount === 0) link.textContent = phone.phone;
    const note = el.querySelector('[data-ks-phone-note]');
    if (note) note.textContent = phone.note;
    const hours = el.querySelector('[data-ks-phone-hours]');
    if (hours) hours.textContent = phone.hours;
    if (el.getAttribute('aria-label')?.startsWith('Позвонить')) {
      el.setAttribute('aria-label', `Позвонить диспетчеру ${phone.phone}`);
    }
  });
  document.querySelectorAll<HTMLElement>('[data-ks-news]').forEach((el) => {
    if (!data.news.length) return;
    const heading = el.dataset.ksNews === 'list' ? 'h2' : 'h3';
    const items = el.dataset.ksNews === 'home' ? data.news.slice(0, 3) : data.news;
    el.innerHTML = items.map((item) => newsCard(item, heading)).join('');
  });
}
