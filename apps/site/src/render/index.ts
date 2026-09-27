/**
 * Entry for the build-time renderer. `vite.config.ts` calls `renderPage` for
 * each HTML entry; the tests call it to check the output.
 */

import { en, type Copy } from '../content/en.ts';
import { PAGES, type PageId } from '../content/site.ts';
import { renderHomeBody } from './home.ts';
import { createContext, type RenderContext } from './html.ts';
import { renderDocument } from './layout.ts';
import { renderEvidenceBody, renderNotFoundBody, renderPressBody, renderSourcesBody } from './pages.ts';
import { POSTERS } from '../content/site.ts';
import { publicFileExists } from './paths.ts';

export const LOCALES: Record<string, Copy> = { en };

export interface RenderedPage {
  html: string;
  ctx: RenderContext;
}

export function renderPage(page: PageId, copy: Copy = en): RenderedPage {
  const ctx = createContext(copy, page);
  const entry = PAGES.find((p) => p.id === page);
  if (!entry) throw new Error(`unknown page ${page}`);
  let body = '';
  let meta = copy.meta.home;
  const preload: string[] = [];
  switch (page) {
    case 'home':
      body = renderHomeBody(ctx);
      if (publicFileExists(POSTERS.heroWide)) {
        preload.push(`<link rel="preload" as="image" href="${POSTERS.heroWide}" media="(min-width: 900px)" fetchpriority="high">`);
      }
      if (publicFileExists(POSTERS.heroNarrow)) {
        preload.push(`<link rel="preload" as="image" href="${POSTERS.heroNarrow}" media="(max-width: 899px)" fetchpriority="high">`);
      }
      break;
    case 'press':
      body = renderPressBody(ctx);
      meta = copy.meta.press;
      break;
    case 'sources':
      body = renderSourcesBody(ctx);
      meta = copy.meta.sources;
      break;
    case 'evidence':
      body = renderEvidenceBody(ctx);
      meta = copy.meta.evidence;
      break;
    case 'notFound':
      body = renderNotFoundBody(ctx);
      meta = copy.meta.notFound;
      break;
  }
  const html = renderDocument(ctx, {
    path: entry.path,
    title: meta.title,
    description: meta.description,
    body,
    preload,
    noindex: !entry.listed,
  });
  return { html, ctx };
}

export function pageForHtmlPath(file: string): PageId {
  const normalised = file.replace(/\\/g, '/');
  /* Longest entry first, so press/index.html does not match index.html. */
  const byLength = [...PAGES].sort((a, b) => b.html.length - a.html.length);
  const match = byLength.find((p) => normalised.endsWith(`/${p.html}`) || normalised === p.html);
  if (!match) throw new Error(`no page is registered for ${file}`);
  return match.id;
}

export function sitemap(siteUrl: string): string {
  const urls = PAGES.filter((p) => p.listed).map((p) => `  <url><loc>${siteUrl}${p.path}</loc></url>`).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`;
}

export function robots(siteUrl: string): string {
  return `User-agent: *\nAllow: /\n\nSitemap: ${siteUrl}/sitemap.xml\n`;
}
