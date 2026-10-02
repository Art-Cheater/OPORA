// @ts-check
import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://kirovsvet.truthqwark.ru',
  trailingSlash: 'always',
  build: { format: 'directory' },
  compressHTML: true,
  image: { responsiveStyles: false },
});
