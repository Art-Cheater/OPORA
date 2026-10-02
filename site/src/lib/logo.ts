// Знак «Пиксель К» для иконок сайта (сетка 3×3, включённые ячейки складываются в букву К).

/** «Пиксель К»: сетка 3×3, включённые ячейки складываются в букву К. */
export const PIXEL_K: ('bar' | 'on' | 'off')[][] = [
  ['bar', 'off', 'on'],
  ['bar', 'on', 'off'],
  ['bar', 'off', 'on'],
];

export function pixelKSvg({ bar = '#FFFFFF', on = '#FFB81C', off = '#2A3553', bg = '#14213D', radius = 14 } = {}) {
  const cell = 26;
  const gap = 5;
  const start = (100 - (cell * 3 + gap * 2)) / 2;
  const colors = { bar, on, off };
  const rects = PIXEL_K.flatMap((row, r) =>
    row.map((k, c) => `<rect x="${start + c * (cell + gap)}" y="${start + r * (cell + gap)}" width="${cell}" height="${cell}" fill="${colors[k]}"/>`),
  ).join('');
  const back = bg ? `<rect width="100" height="100" rx="${radius}" fill="${bg}"/>` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">${back}${rects}</svg>`;
}
