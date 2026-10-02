// Экспорт фирменной графики из SVG-мастера: знак, «Пиксель К», фавиконки.
// Запуск: node --experimental-strip-types scripts/render-brand.mjs
import sharp from 'sharp';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { pixelKSvg } from '../src/lib/logo.ts';

const out = new URL('../public/brand/', import.meta.url);
await mkdir(out, { recursive: true });
const pub = new URL('../public/', import.meta.url);

const png = (svg, width, file) => sharp(Buffer.from(svg), { density: 600 }).resize({ width }).png().toFile(fileURLToPath(new URL(file, out)));


const favicon = pixelKSvg();
await writeFile(new URL('favicon.svg', pub), favicon);
await writeFile(new URL('pixel-k.svg', out), pixelKSvg({ bar: '#14213D', on: '#FFB81C', off: '#E4E7EC', bg: '' }));
await png(pixelKSvg({ bar: '#14213D', on: '#FFB81C', off: '#E4E7EC', bg: '' }), 1024, 'pixel-k.png');
await sharp(Buffer.from(favicon), { density: 600 }).resize(180).png().toFile(fileURLToPath(new URL('apple-touch-icon.png', pub)));
await sharp(Buffer.from(favicon), { density: 600 }).resize(192).png().toFile(fileURLToPath(new URL('icon-192.png', pub)));
await sharp(Buffer.from(pixelKSvg({ radius: 0 })), { density: 600 }).resize(512).png().toFile(fileURLToPath(new URL('icon-512.png', pub)));
// favicon.ico (PNG внутри ICO, 32×32) — для старых браузеров
const ico32 = await sharp(Buffer.from(favicon), { density: 600 }).resize(32).png().toBuffer();
const header = Buffer.alloc(22);
header.writeUInt16LE(0, 0); header.writeUInt16LE(1, 2); header.writeUInt16LE(1, 4);
header.writeUInt8(32, 6); header.writeUInt8(32, 7); header.writeUInt8(0, 8); header.writeUInt8(0, 9);
header.writeUInt16LE(1, 10); header.writeUInt16LE(32, 12); header.writeUInt32LE(ico32.length, 14); header.writeUInt32LE(22, 18);
await writeFile(new URL('favicon.ico', pub), Buffer.concat([header, ico32]));
console.log('brand exported');
