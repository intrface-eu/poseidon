/**
 * The claims register is the page's contract with the reader.
 *
 * Every factual sentence on the site is a claim in the copy module with at
 * least one source in `src/content/claims.json`: a citation ID from
 * `content/sources.md`, or a path in this repository. These tests fail the
 * build if a claim reaches a page without a source, if a source goes
 * missing, if a figure slips into framing copy, or if banned language
 * appears. They also check the rendered pages for structure.
 */

import { describe, expect, test } from 'bun:test';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import register from '../src/content/claims.json' with { type: 'json' };
import { en } from '../src/content/en.ts';
import { CONTACT_EMAIL, PAGES, PRESS_ASSETS, RENDER_LICENCE, type PageId } from '../src/content/site.ts';
import { isSourceId, loadSources } from '../src/content/sources.ts';
import { renderPage, sitemap } from '../src/render/index.ts';
import { REPO_ROOT, publicFileExists } from '../src/render/paths.ts';

const sources = register.claims as Record<string, string[]>;
const texts = en.claims as Record<string, string>;
const rendered = Object.fromEntries(PAGES.map((p) => [p.id, renderPage(p.id)])) as Record<PageId, ReturnType<typeof renderPage>>;
const allRendered = new Set(Object.values(rendered).flatMap((r) => [...r.ctx.rendered]));

/** Strings in the copy module outside `claims` and `figures`, with their paths. */
function framing(value: unknown, path: string[] = []): { path: string; text: string }[] {
  if (typeof value === 'string') return [{ path: path.join('.'), text: value }];
  if (Array.isArray(value)) return value.flatMap((v, i) => framing(v, [...path, String(i)]));
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([k, v]) => (path.length === 0 && (k === 'claims' || k === 'figures') ? [] : framing(v, [...path, k])));
  }
  return [];
}

function allCopy(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (Array.isArray(value)) return value.flatMap(allCopy);
  if (value && typeof value === 'object') return Object.values(value).flatMap(allCopy);
  return [];
}

function visibleText(html: string): string {
  return html
    .replace(/<script[\s\S]*?<\/script>/g, ' ')
    .replace(/<style[\s\S]*?<\/style>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&[a-z]+;/g, ' ')
    .replace(/\s+/g, ' ');
}

describe('claims register', () => {
  test('every claim in the copy has a register entry, and every entry has copy', () => {
    const copyIds = Object.keys(texts).sort();
    const registerIds = Object.keys(sources).sort();
    expect(registerIds.filter((id) => !(id in texts))).toEqual([]);
    expect(copyIds.filter((id) => !(id in sources))).toEqual([]);
  });

  test('every claim has at least one source', () => {
    const empty = Object.entries(sources).filter(([, list]) => list.length === 0).map(([id]) => id);
    expect(empty).toEqual([]);
  });

  test('every citation ID exists in content/sources.md', () => {
    const known = new Set(loadSources().map((s) => s.id));
    const missing = Object.entries(sources).flatMap(([id, list]) => list.filter((s) => isSourceId(s) && !known.has(s)).map((s) => `${id}: ${s}`));
    expect(missing).toEqual([]);
  });

  test('every repo path source exists', () => {
    const missing = Object.entries(sources).flatMap(([id, list]) =>
      list.filter((s) => !isSourceId(s) && !existsSync(resolve(REPO_ROOT, s))).map((s) => `${id}: ${s}`),
    );
    expect(missing).toEqual([]);
  });

  test('every rendered claim is registered, and every claim is rendered somewhere', () => {
    expect([...allRendered].filter((id) => !(id in sources))).toEqual([]);
    expect(Object.keys(texts).filter((id) => !allRendered.has(id))).toEqual([]);
  });

  test('figures name a registered claim', () => {
    for (const figure of Object.values(en.figures)) expect(figure.claim in sources).toBe(true);
  });

  test('each source in sources.md has a link and a checked date', () => {
    for (const s of loadSources()) {
      expect(s.links.length).toBeGreaterThan(0);
      expect(s.accessed.length).toBeGreaterThan(0);
    }
  });
});

describe('copy rules', () => {
  test('framing copy carries no figures: numbers, currency and percentages are claims', () => {
    /* Allowed: the term "3D", SPDX licence identifiers, and claim ID prefixes. */
    const allowed = (text: string) => text.replace(/\b3D\b/g, '').replace(/\b(AGPL-3\.0-or-later|CERN-OHL-S-2\.0|CC-BY-4\.0)\b/g, '');
    const offenders = framing(en).filter(({ path, text }) => !path.endsWith('.claimPrefix') && /[0-9€%]/.test(allowed(text)));
    expect(offenders).toEqual([]);
  });

  test('no tool names, internal jargon, hype or efficacy claims', () => {
    const banned: RegExp[] = [
      /\b(claude|anthropic|openai|chatgpt|gpt-?\d|codex|copilot|gemini|cursor|omp|llm|ai agent)\b/i,
      /\b(asset contract|scene code|placeholder|lorem|todo|tbd|fixme)\b/i,
      /\b(OPEN|CONCEPT)\b/,
      /\b(revolutionary|cutting-edge|game-?changing|world-class|seamless(ly)?|robust|comprehensive|leverag(e|es|ing)|state-of-the-art|groundbreaking)\b/i,
      /\b(proven to|clinically|guarantee[sd]?|certified|ce[- ]marked|ce marking|conformity assessed|fully permitted)\b/i,
    ];
    const strings = allCopy(en);
    const hits = strings.flatMap((s) => banned.filter((re) => re.test(s)).map((re) => `${re.source} :: ${s.slice(0, 80)}`));
    expect(hits).toEqual([]);
    for (const page of PAGES) {
      const text = visibleText(rendered[page.id].html);
      const pageHits = banned.filter((re) => re.test(text)).map((re) => `${page.id}: ${re.source}`);
      expect(pageHits).toEqual([]);
    }
  });

  test('deterrence by sound is stated as the research question once on the home page', () => {
    const text = visibleText(rendered.home.html).toLowerCase();
    const mentions = text.match(/research question/g) ?? [];
    expect(mentions.length).toBe(1);
  });
});

describe('rendered pages', () => {
  for (const page of PAGES) {
    const { html } = rendered[page.id];

    test(`${page.id}: one h1, a title, a description, a canonical URL and share tags`, () => {
      expect(html.match(/<h1[\s>]/g)?.length).toBe(1);
      expect(html).toMatch(/<title>[^<]+<\/title>/);
      expect(html).toMatch(/<meta name="description" content="[^"]{40,}">/);
      if (page.listed) {
        expect(html).toContain(`<link rel="canonical" href="https://poseidon.intrface.eu${page.path}">`);
        expect(html).not.toContain('noindex');
      } else {
        expect(html).toContain('<meta name="robots" content="noindex">');
        expect(html).not.toContain('rel="canonical"');
      }
      expect(html).toContain('<meta property="og:image" content="https://poseidon.intrface.eu/og-image.png">');
      expect(html).toContain('<meta name="twitter:card" content="summary_large_image">');
      expect(html).toContain('application/ld+json');
    });

    test(`${page.id}: every image has alt text`, () => {
      const imgs = html.match(/<img\b[^>]*>/g) ?? [];
      for (const img of imgs) expect(img).toMatch(/\balt="[^"]+"/);
    });

    test(`${page.id}: in-page links resolve`, () => {
      const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
      const local = [...html.matchAll(/href="#([^"]+)"/g)].map((m) => m[1]);
      expect(local.filter((id) => !ids.has(id))).toEqual([]);
      const homeIds = new Set([...rendered.home.html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
      const toHome = [...html.matchAll(/href="\/#([^"]+)"/g)].map((m) => m[1]);
      expect(toHome.filter((id) => !homeIds.has(id))).toEqual([]);
      const sourceIds = new Set([...rendered.sources.html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
      const toSources = [...html.matchAll(/href="\/sources\/#([^"]+)"/g)].map((m) => m[1]);
      expect(toSources.filter((id) => !sourceIds.has(id))).toEqual([]);
    });

    test(`${page.id}: contact address is real`, () => {
      expect(html).toContain(`mailto:${CONTACT_EMAIL}`);
      expect(html).not.toMatch(/example\.(com|org)|@placeholder|your@/i);
    });
  }

  test('home: the ask cards each open a mail with their own subject', () => {
    const subjects = [...rendered.home.html.matchAll(/href="mailto:[^"?]+\?subject=([^"]+)"/g)].map((m) => decodeURIComponent(m[1] ?? ''));
    const cardSubjects = subjects.filter((s) => s.startsWith(`${en.home.ask.subjectPrefix}: `));
    expect(cardSubjects.length).toBe(en.home.ask.cards.length);
    expect(new Set(cardSubjects).size).toBe(cardSubjects.length);
  });

  test('home: the first screen states the ask and links to contact', () => {
    const hero = rendered.home.html.slice(rendered.home.html.indexOf('class="hero"'), rendered.home.html.indexOf('id="problem"'));
    expect(hero).toContain('href="#partner"');
    expect(hero).toContain(en.actions.partner);
  });

  test('home: each cited source is listed in the notes', () => {
    for (const id of rendered.home.ctx.cited) expect(rendered.home.html).toContain(`id="src-${id}"`);
  });

  test('press: every asset slot is listed', () => {
    for (const asset of PRESS_ASSETS) expect(rendered.press.html).toContain(en.press.assets[asset.id]);
  });

  test('press: each render present is offered as a download with its credit', () => {
    for (const asset of PRESS_ASSETS.filter((a) => a.render && publicFileExists(a.path))) {
      expect(rendered.press.html).toContain(`href="${asset.path}" download`);
    }
    if (PRESS_ASSETS.some((a) => a.render && publicFileExists(a.path))) {
      expect(rendered.press.html).toContain(en.press.credit.replace('{licence}', RENDER_LICENCE));
    }
  });

  test('404: links back to every listed page and stays out of the sitemap', () => {
    for (const page of PAGES.filter((p) => p.listed)) expect(rendered.notFound.html).toContain(`href="${page.path}"`);
    expect(sitemap('https://poseidon.intrface.eu')).not.toContain('404');
  });
});
