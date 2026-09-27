/**
 * String helpers for the build-time renderer. Everything the pages print goes
 * through `esc` or `inline`; nothing takes raw HTML from copy.
 */

import register from '../content/claims.json' with { type: 'json' };
import type { ClaimId, Copy } from '../content/en.ts';
import type { PageId } from '../content/site.ts';
import { compareSourceIds, isSourceId } from '../content/sources.ts';

export function esc(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** `*italic*`, `**bold**` and `[text](href)`, after escaping. */
export function inline(value: string): string {
  let out = esc(value);
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_m, text: string, href: string) => {
    const external = /^https?:/.test(href);
    return `<a href="${href}"${external ? ' rel="noopener"' : ''}>${text}</a>`;
  });
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  return out;
}

/** Plain text with markup stripped, for attributes and meta tags. */
export function plain(value: string): string {
  return value
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1');
}

export function attrs(map: Record<string, string | number | boolean | undefined | null>): string {
  return Object.entries(map)
    .filter(([, v]) => v !== undefined && v !== null && v !== false)
    .map(([k, v]) => (v === true ? ` ${k}` : ` ${k}="${esc(String(v))}"`))
    .join('');
}

const claimSources = register.claims as Record<string, string[]>;

export interface RenderContext {
  copy: Copy;
  page: PageId;
  /** Source IDs cited on this page, in first-use order. */
  cited: Set<string>;
  /** Where a citation link points: in-page notes or the sources page. */
  citeHref: (id: string) => string;
  /** Claim IDs rendered on this page, for the register test. */
  rendered: Set<string>;
}

export function createContext(copy: Copy, page: PageId): RenderContext {
  return {
    copy,
    page,
    cited: new Set(),
    rendered: new Set(),
    citeHref: page === 'home' ? (id) => `#src-${id}` : (id) => `/sources/#${id}`,
  };
}

export function claimText(ctx: RenderContext, id: ClaimId): string {
  ctx.rendered.add(id);
  const text = ctx.copy.claims[id];
  if (text === undefined) throw new Error(`claim "${id}" has no text in locale ${ctx.copy.locale}`);
  return text;
}

/** The external source IDs behind a claim, ordered. */
export function externalSources(id: string): string[] {
  return (claimSources[id] ?? []).filter(isSourceId).sort(compareSourceIds);
}

export function citations(ctx: RenderContext, id: ClaimId): string {
  const ids = externalSources(id);
  if (ids.length === 0) return '';
  const links = ids
    .map((sid) => {
      ctx.cited.add(sid);
      return `<a href="${ctx.citeHref(sid)}" aria-label="Source ${sid}">${sid}</a>`;
    })
    .join('<span class="cite__sep" aria-hidden="true">,</span>');
  return `<sup class="cite">${links}</sup>`;
}

/** A claim as inline HTML, with its citations unless `cite` is false. */
export function claim(ctx: RenderContext, id: ClaimId, options: { cite?: boolean } = {}): string {
  const text = inline(claimText(ctx, id));
  const cite = options.cite === false ? '' : citations(ctx, id);
  return `${text}${cite}`;
}

/** Several claims run together as one paragraph's worth of sentences. */
export function claims(ctx: RenderContext, ids: ClaimId[]): string {
  return ids.map((id) => claim(ctx, id)).join(' ');
}

export function p(ctx: RenderContext, ids: ClaimId[], className?: string): string {
  return `<p${className ? ` class="${className}"` : ''}>${claims(ctx, ids)}</p>`;
}

export function slug(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}
