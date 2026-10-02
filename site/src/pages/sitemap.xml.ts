import type { APIRoute } from 'astro';
import { NEWS, SITE } from '../data/site';

const PAGES = ['/', '/soobshit/', '/zayavka/', '/karta/', '/grafik/', '/chey-fonar/', '/voprosy/', '/stroitelstvo/', '/novosti/', '/o-sluzhbe/', '/kontakty/', '/politika/'];

export const GET: APIRoute = () => {
  const urls = [...PAGES, ...NEWS.map((n) => `/novosti/${n.slug}/`)];
  const body = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls
    .map((u) => `  <url><loc>${new URL(u, SITE.url).href}</loc></url>`)
    .join('\n')}\n</urlset>\n`;
  return new Response(body, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
};
