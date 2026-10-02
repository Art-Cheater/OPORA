// @ts-check
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://svet.progwebs.ru',
  trailingSlash: 'always',
  build: { format: 'directory' },
  compressHTML: true,
  image: { responsiveStyles: false },
});
