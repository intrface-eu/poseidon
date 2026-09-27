/**
 * Reads apps/site/content/sources.md, the one list of external sources.
 *
 * Runs at build time only (from the page renderer and the tests), never in
 * the browser. The markdown tables stay the source of truth; this file only
 * turns them into records.
 */

import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export interface SourceLink {
  label: string;
  url: string;
}

export interface SourceEntry {
  id: string;
  group: 'S' | 'P' | 'F';
  /** The citation text, with markdown italics kept as `*...*`. */
  text: string;
  links: SourceLink[];
  accessed: string;
}

const HERE = dirname(fileURLToPath(import.meta.url));
export const SOURCES_FILE = resolve(HERE, '..', '..', 'content', 'sources.md');

function parseLinks(cell: string): SourceLink[] {
  return cell
    .split(/\s;\s/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const match = part.match(/^(?:(.*?):\s*)?(https?:\/\/\S+)$/);
      if (!match) return null;
      const url = match[2] ?? '';
      const label = (match[1] ?? '').trim();
      return { label, url };
    })
    .filter((link): link is SourceLink => link !== null);
}

export function parseSources(markdown: string): SourceEntry[] {
  const out: SourceEntry[] = [];
  for (const line of markdown.split('\n')) {
    if (!line.startsWith('|')) continue;
    const cells = line
      .slice(1, line.endsWith('|') ? -1 : undefined)
      .split('|')
      .map((cell) => cell.trim());
    const [id, text, links, accessed] = cells;
    if (!id || !/^[SPF]\d+$/.test(id)) continue;
    out.push({
      id,
      group: id[0] as SourceEntry['group'],
      text: text ?? '',
      links: parseLinks(links ?? ''),
      accessed: accessed ?? '',
    });
  }
  return out;
}

let cache: SourceEntry[] | null = null;

export function loadSources(): SourceEntry[] {
  if (!cache) cache = parseSources(readFileSync(SOURCES_FILE, 'utf8'));
  return cache;
}

export function sourceById(id: string): SourceEntry | undefined {
  return loadSources().find((entry) => entry.id === id);
}

/** Orders IDs the way the sources page lists them: S, then P, then F, by number. */
export function compareSourceIds(a: string, b: string): number {
  const order = { S: 0, P: 1, F: 2 } as Record<string, number>;
  const ga = order[a[0] ?? ''] ?? 9;
  const gb = order[b[0] ?? ''] ?? 9;
  if (ga !== gb) return ga - gb;
  return Number(a.slice(1)) - Number(b.slice(1));
}

export const isSourceId = (value: string): boolean => /^[SPF]\d+$/.test(value);
