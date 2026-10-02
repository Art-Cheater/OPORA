// Подготовка сгенерированных изображений (design/generated) для сборки (src/assets/img).
// Фото → JPEG до 2560 px; прозрачные иллюстрации и логотипы → PNG с обрезкой пустых полей.
// Дальше Astro сам делает AVIF/WebP нужных размеров.
import sharp from 'sharp';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const src = (f) => fileURLToPath(new URL(`../design/generated/${f}.png`, import.meta.url));
const dst = (f) => fileURLToPath(new URL(`../src/assets/img/${f}`, import.meta.url));
await mkdir(dst(''), { recursive: true });

const PHOTOS = {
  'hero-desktop': 2560, 'hero-mobile': 1200, 'about-crew': 2400, construction: 2400, 'news-severnaya': 1600,
  'news-storm': 1600, 'news-site': 1600, panorama: 2560, 'not-found': 2000, dispatch: 1600, 'pole-number': 1200,
  sticker: 1000, 'aerial-lines': 2560, og: 1200,
};
const CUTOUTS = {
  'owner-street': 900, 'owner-yard': 900, 'owner-traffic': 900, 'chey-isometric': 1800,
  'logo-horizontal-t': 900, 'logo-horizontal-dark-t': 900, 'logo-vertical-t': 900, 'logo-mark-t': 600, 'logo-vertical': 1200,
};

for (const [name, width] of Object.entries(PHOTOS)) {
  let img = sharp(src(name)).flatten({ background: '#14213D' });
  if (name === 'og') img = img.resize(1200, 630, { fit: 'cover', position: 'centre' });
  else img = img.resize({ width, withoutEnlargement: true });
  await img.jpeg({ quality: 86, mozjpeg: true }).toFile(dst(`${name}.jpg`));
}
for (const [name, width] of Object.entries(CUTOUTS)) {
  await sharp(src(name)).trim({ threshold: 1 }).resize({ width, withoutEnlargement: true })
    .png({ compressionLevel: 9, palette: false }).toFile(dst(`${name}.png`));
}
console.log('images ready');
