import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

export const SITE_ROOT = resolve(HERE, '..', '..');
export const PUBLIC_DIR = resolve(SITE_ROOT, 'public');
export const REPO_ROOT = resolve(SITE_ROOT, '..', '..');

/** Size in bytes and, for PNG files, pixel dimensions of a file in public/. */
export function publicFileInfo(urlPath: string): { bytes: number; width?: number; height?: number } {
  const file = resolve(PUBLIC_DIR, urlPath.replace(/^\/+/, ''));
  const bytes = statSync(file).size;
  if (!file.endsWith('.png')) return { bytes };
  const head = readFileSync(file).subarray(16, 24);
  return { bytes, width: head.readUInt32BE(0), height: head.readUInt32BE(4) };
}

/** True when a file referenced by its public URL path is present in public/. */
export function publicFileExists(urlPath: string): boolean {
  return existsSync(resolve(PUBLIC_DIR, urlPath.replace(/^\/+/, '')));
}
