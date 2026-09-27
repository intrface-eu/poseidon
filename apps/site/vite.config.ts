import { resolve } from 'node:path';
import { defineConfig, type Plugin } from 'vite';
import { SITE_URL, PAGES } from './src/content/site.ts';
import { pageForHtmlPath, renderPage, robots, sitemap } from './src/render/index.ts';

/**
 * Every page is rendered at build time from the copy module
 * (src/content/en.ts) by src/render/. The HTML files in the repository are
 * empty entry points; this plugin replaces their contents.
 */
function pages(): Plugin {
  return {
    name: 'poseidon-pages',
    transformIndexHtml: {
      order: 'pre',
      handler(_html, ctx) {
        return renderPage(pageForHtmlPath(ctx.filename)).html;
      },
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'sitemap.xml', source: sitemap(SITE_URL) });
      this.emitFile({ type: 'asset', fileName: 'robots.txt', source: robots(SITE_URL) });
    },
  };
}

export default defineConfig({
  base: '/',
  plugins: [pages()],
  build: {
    target: 'es2022',
    assetsInlineLimit: 0,
    reportCompressedSize: true,
    chunkSizeWarningLimit: 800,
    rolldownOptions: {
      input: Object.fromEntries(PAGES.map((p) => [p.id, resolve(import.meta.dirname, p.html)])),
    },
  },
  server: { host: '127.0.0.1', port: 5180, strictPort: false },
  preview: { host: '127.0.0.1', port: 5181, strictPort: false },
});
