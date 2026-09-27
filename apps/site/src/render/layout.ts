/**
 * The document around every page: head metadata, header, footer.
 */

import {
  COMPANY,
  CONTACT_EMAIL,
  LICENCES,
  OG_IMAGE,
  PERSON,
  REPO_URL,
  SITE_URL,
  type PageId,
} from '../content/site.ts';
import { esc, plain, type RenderContext } from './html.ts';
import { icon, intrfaceMark, mark } from './icons.ts';

export interface DocumentOptions {
  path: string;
  title: string;
  description: string;
  body: string;
  /** Extra `<link rel="preload">` lines, e.g. the hero poster. */
  preload?: string[];
  /** Keep the page out of search results and give it no canonical URL. */
  noindex?: boolean;
}

function jsonLd(ctx: RenderContext): string {
  const { copy } = ctx;
  const org = {
    '@type': 'Organization',
    '@id': `${COMPANY.url}/#organization`,
    name: 'INTRFACE',
    legalName: COMPANY.name,
    url: COMPANY.url,
    email: CONTACT_EMAIL,
    taxID: COMPANY.oib,
    identifier: { '@type': 'PropertyValue', propertyID: 'MBS', value: COMPANY.mbs },
    address: {
      '@type': 'PostalAddress',
      streetAddress: COMPANY.street,
      postalCode: COMPANY.postcode,
      addressLocality: COMPANY.town,
      addressCountry: COMPANY.countryCode,
    },
    founder: { '@type': 'Person', name: PERSON.name, jobTitle: 'Director', email: PERSON.email },
  };
  const project = {
    '@type': 'ResearchProject',
    '@id': `${SITE_URL}/#project`,
    name: copy.meta.siteName,
    url: `${SITE_URL}/`,
    description: plain(copy.meta.home.description),
    parentOrganization: { '@id': org['@id'] },
    email: CONTACT_EMAIL,
    sameAs: [REPO_URL],
    logo: `${SITE_URL}/press/poseidon-trident-logo.svg`,
    image: `${SITE_URL}${OG_IMAGE.path}`,
    location: { '@type': 'Place', name: 'Limski kanal, Istria, Croatia' },
  };
  const code = {
    '@type': 'SoftwareSourceCode',
    name: copy.meta.siteName,
    codeRepository: REPO_URL,
    license: `https://spdx.org/licenses/${LICENCES.code}.html`,
    author: { '@id': org['@id'] },
  };
  const graph = { '@context': 'https://schema.org', '@graph': [org, project, code] };
  return `<script type="application/ld+json">${JSON.stringify(graph).replace(/</g, '\\u003c')}</script>`;
}

function header(ctx: RenderContext): string {
  const { nav } = ctx.copy;
  const current = ctx.page;
  const link = (href: string, label: string, page?: PageId) =>
    `<li><a href="${href}"${page && page === current ? ' aria-current="page"' : ''}>${esc(label)}</a></li>`;
  return `<header class="site-header">
  <div class="site-header__inner">
    <a class="wordmark" href="/" aria-label="${esc(nav.home)}">${mark('wordmark__mark')}<span class="wordmark__name" aria-hidden="true">poseidon trident</span></a>
    <nav class="site-nav" aria-label="${esc(nav.label)}">
      <ul>
        ${link('/#problem', nav.problem)}
        ${link('/#how', nav.how)}
        ${link('/#plan', nav.plan)}
        ${link('/press/', nav.press, 'press')}
      </ul>
    </nav>
    <a class="btn btn--primary btn--compact" href="/#partner">${esc(nav.partner)}</a>
  </div>
</header>`;
}

function footer(ctx: RenderContext): string {
  const { footer: f } = ctx.copy;
  const year = 2026;
  return `<footer class="site-footer">
  <div class="shell site-footer__inner">
    <p class="site-footer__maker">
      <a class="wordmark wordmark--footer" href="/" aria-label="${esc(ctx.copy.nav.home)}">${mark('wordmark__mark')}<span class="wordmark__name" aria-hidden="true">poseidon trident</span></a>
      <span class="site-footer__by">${esc(f.project)} <a class="intrface-link" href="${COMPANY.url}" rel="noopener">${intrfaceMark()}<span>intrface</span></a>, ${esc(COMPANY.town)}, ${esc(COMPANY.country)}</span>
    </p>
    <ul class="site-footer__links">
      <li><a href="/press/">${esc(f.press)}</a></li>
      <li><a href="/sources/">${esc(f.sources)}</a></li>
      <li><a href="/evidence/">${esc(f.evidence)}</a></li>
      <li><a href="${REPO_URL}" rel="noopener">${icon('github')}<span>${esc(f.github)}</span></a></li>
      <li><a href="mailto:${CONTACT_EMAIL}">${esc(CONTACT_EMAIL)}</a></li>
    </ul>
    <p class="site-footer__legal">${esc(f.licences)}<br>© ${year} ${esc(COMPANY.name)}, ${esc(COMPANY.street)}, ${esc(COMPANY.postcode)} ${esc(COMPANY.town)}, ${esc(COMPANY.country)}</p>
  </div>
</footer>`;
}

export function renderDocument(ctx: RenderContext, options: DocumentOptions): string {
  const { copy } = ctx;
  const url = `${SITE_URL}${options.path}`;
  const image = `${SITE_URL}${OG_IMAGE.path}`;
  const title = esc(options.title);
  const description = esc(plain(options.description));
  const preload = (options.preload ?? []).join('\n    ');
  return `<!doctype html>
<html lang="${copy.htmlLang}">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
    <title>${title}</title>
    <meta name="description" content="${description}">
    ${options.noindex ? '<meta name="robots" content="noindex">' : `<link rel="canonical" href="${url}">`}
    <meta name="theme-color" content="#f5f1eb">
    <meta name="color-scheme" content="light">
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="${esc(copy.meta.siteName)}">
    <meta property="og:locale" content="${copy.ogLocale}">
    ${options.noindex ? '' : `<meta property="og:url" content="${url}">`}
    <meta property="og:title" content="${title}">
    <meta property="og:description" content="${description}">
    <meta property="og:image" content="${image}">
    <meta property="og:image:type" content="image/png">
    <meta property="og:image:width" content="${OG_IMAGE.width}">
    <meta property="og:image:height" content="${OG_IMAGE.height}">
    <meta property="og:image:alt" content="${esc(copy.meta.ogImageAlt)}">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="${title}">
    <meta name="twitter:description" content="${description}">
    <meta name="twitter:image" content="${image}">
    <meta name="twitter:image:alt" content="${esc(copy.meta.ogImageAlt)}">
    <link rel="icon" href="/favicon.svg" type="image/svg+xml">
    <link rel="icon" href="/favicon-32.png" type="image/png" sizes="32x32">
    <link rel="apple-touch-icon" href="/apple-touch-icon.png">
    <link rel="preload" href="/fonts/google-sans-flex-latin.woff2" as="font" type="font/woff2" crossorigin>
    ${preload}
    <link rel="stylesheet" href="/src/styles/site.css">
    ${jsonLd(ctx)}
  </head>
  <body class="page-${ctx.page}">
    <a class="skip-link" href="#main">${esc(copy.nav.skip)}</a>
    ${header(ctx)}
    <main id="main" tabindex="-1">
${options.body}
    </main>
    ${footer(ctx)}
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
`;
}
