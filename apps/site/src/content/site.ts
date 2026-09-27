/**
 * Facts about the site and the company that do not change with the language:
 * addresses, identifiers, URLs, file paths. Copy lives in the locale modules
 * (`en.ts`); this file holds only data.
 */

export const SITE_URL = 'https://poseidon.intrface.eu';

export const CONTACT_EMAIL = 'basic@intrface.eu';

export const REPO_URL = 'https://github.com/intrface-eu/poseidon-trident';

/**
 * The branch repository links point at. The public default branch is `main`;
 * the paths linked from /evidence must exist there when the site goes live.
 */
export const REPO_REF = 'main';

export function repoLink(path: string): string {
  const clean = path.replace(/^\/+/, '');
  const isDir = !/\.[a-z0-9]+$/i.test(clean);
  return `${REPO_URL}/${isDir ? 'tree' : 'blob'}/${REPO_REF}/${clean}`;
}

export const COMPANY = {
  name: 'INTRFACE j.d.o.o.',
  street: 'Dalmatinska 34',
  postcode: '52450',
  town: 'Vrsar',
  country: 'Croatia',
  countryCode: 'HR',
  oib: '34363240459',
  mbs: '130172611',
  court: 'Commercial Court in Pazin',
  url: 'https://intrface.eu',
} as const;

export const PERSON = {
  name: 'Alex Bašić',
  email: CONTACT_EMAIL,
} as const;

/** Licence identifiers, as SPDX expressions. */
export const LICENCES = {
  code: 'AGPL-3.0-or-later',
  hardware: 'CERN-OHL-S-2.0',
  docs: 'CC-BY-4.0',
} as const;

/** The social card: the og render with the wordmark and headline set over it by `bun run qa:assets`. */
export const OG_IMAGE = {
  path: '/og-image.png',
  width: 1200,
  height: 630,
  /** Where the final file comes from in the repository. */
  source: 'hardware/showcase/renders-v4/og-image.png',
} as const;

/** Poster frames shown before, or instead of, the live 3D. */
export const POSTERS = {
  heroWide: '/posters/hero-wide.webp',
  heroNarrow: '/posters/hero-narrow.webp',
  head: '/posters/head.webp',
} as const;

/**
 * Press downloads. Each entry is linked from /press once its file exists in
 * `public/`; until then the press page lists it as coming. Renders come from
 * `hardware/showcase/renders-v4/` through `bun run qa:assets`, which also
 * writes the web-sized WebP `preview` the page shows.
 */
export interface PressAsset {
  id: 'hero' | 'farm' | 'unit' | 'head-exploded' | 'logo-light' | 'logo-dark';
  path: string;
  /** Smaller image the press page shows; the download stays full size. */
  preview?: string;
  /** Render licence credit, shown under the image. */
  render?: boolean;
  source: string;
}

const RENDER_DIR = 'hardware/showcase/renders-v4';

export const PRESS_ASSETS: PressAsset[] = [
  { id: 'hero', path: '/press/poseidon-trident-hero.png', preview: '/press/poseidon-trident-hero.webp', render: true, source: `${RENDER_DIR}/hero-16x9.png` },
  { id: 'farm', path: '/press/poseidon-trident-farm.png', preview: '/press/poseidon-trident-farm.webp', render: true, source: `${RENDER_DIR}/farm-wide.png` },
  { id: 'unit', path: '/press/poseidon-trident-unit.png', preview: '/press/poseidon-trident-unit.webp', render: true, source: `${RENDER_DIR}/unit-closeup.png` },
  {
    id: 'head-exploded',
    path: '/press/poseidon-trident-head-exploded.png',
    preview: '/press/poseidon-trident-head-exploded.webp',
    render: true,
    source: `${RENDER_DIR}/head-exploded.png`,
  },
  { id: 'logo-light', path: '/press/poseidon-trident-logo.svg', source: 'apps/site/public/press/poseidon-trident-logo.svg' },
  { id: 'logo-dark', path: '/press/poseidon-trident-logo-dark.svg', source: 'apps/site/public/press/poseidon-trident-logo-dark.svg' },
];

/** Licence line for the renders, in the form the credit asks for. */
export const RENDER_LICENCE = 'CC BY 4.0';

export type PageId = 'home' | 'press' | 'sources' | 'evidence' | 'notFound';

/**
 * Every HTML page. `listed: false` keeps a page out of the sitemap and
 * search results; the host serves 404.html for unknown paths.
 */
export const PAGES: { id: PageId; path: string; html: string; listed: boolean }[] = [
  { id: 'home', path: '/', html: 'index.html', listed: true },
  { id: 'press', path: '/press/', html: 'press/index.html', listed: true },
  { id: 'sources', path: '/sources/', html: 'sources/index.html', listed: true },
  { id: 'evidence', path: '/evidence/', html: 'evidence/index.html', listed: true },
  { id: 'notFound', path: '/404.html', html: '404.html', listed: false },
];

export function mailto(subject?: string): string {
  if (!subject) return `mailto:${CONTACT_EMAIL}`;
  return `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}`;
}
