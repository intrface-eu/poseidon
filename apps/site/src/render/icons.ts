/**
 * Icons (Tabler outline geometry, stroke 1.75) and the two brand marks,
 * inlined so they cost no request and take `currentColor`.
 */

const ICONS = {
  arrowRight: '<path d="M5 12h14"/><path d="M13 18l6-6"/><path d="M13 6l6 6"/>',
  arrowUpRight: '<path d="M17 7L7 17"/><path d="M8 7h9v9"/>',
  arrowDown: '<path d="M12 5v14"/><path d="M18 13l-6 6"/><path d="M6 13l6 6"/>',
  mail: '<path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M3 7l9 6 9-6"/>',
  download: '<path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/><path d="M7 11l5 5 5-5"/><path d="M12 4v12"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  github:
    '<path d="M9 19c-4.3 1.4-4.3-2.5-6-3m12 5v-3.5c0-1 .1-1.4-.5-2 2.8-.3 5.5-1.4 5.5-6a4.6 4.6 0 0 0-1.3-3.2 4.2 4.2 0 0 0-.1-3.2s-1.1-.3-3.5 1.3a12.3 12.3 0 0 0-6.2 0C6.5 2.8 5.4 3.1 5.4 3.1a4.2 4.2 0 0 0-.1 3.2A4.6 4.6 0 0 0 4 9.5c0 4.6 2.7 5.7 5.5 6-.6.6-.6 1.2-.5 2V21"/>',
  explode: '<path d="M4 12h5"/><path d="M15 12h5"/><path d="M7 9l-3 3 3 3"/><path d="M17 9l3 3-3 3"/><path d="M12 5v14"/>',
} as const;

export type IconName = keyof typeof ICONS;

export function icon(name: IconName, className = 'icon'): string {
  return `<svg class="${className}" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICONS[name]}</svg>`;
}

/**
 * The Poseidon mark: a three-tined spear crossing a waterline. The part of the
 * shaft below the line takes the sea colour (`--mark-deep`).
 */
export const MARK_PATHS = {
  tines: 'M8 6.5v5.25c0 4.5 3.6 7.75 8 7.75s8-3.25 8-7.75V6.5',
  shaft: 'M16 4.25v17.25',
  water: 'M3.5 21.5h25',
  deep: 'M16 21.5V28',
};

export function mark(className = 'mark'): string {
  return `<svg class="${className}" viewBox="0 0 32 32" width="32" height="32" fill="none" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="${MARK_PATHS.tines}" stroke="currentColor" stroke-width="2.6"/><path d="${MARK_PATHS.shaft}" stroke="currentColor" stroke-width="2.6"/><path d="${MARK_PATHS.water}" stroke="var(--mark-water, currentColor)" stroke-width="1.6"/><path d="${MARK_PATHS.deep}" stroke="var(--mark-deep, currentColor)" stroke-width="2.6"/></svg>`;
}

/** The intrface company mark: the four-point star and its spark. */
export function intrfaceMark(className = 'imark'): string {
  return `<svg class="${className}" viewBox="0 0 1000 1000" width="14" height="14" fill="currentColor" aria-hidden="true" focusable="false"><path d="M500,0c0,276.14-223.86,500-500,500,276.14,0,500,223.86,500,500,0-276.14,223.86-500,500-500-276.14,0-500-223.86-500-500Z"/><path d="M202.17,96.48c0,69.04-55.970,125-125,125,69.04,0,125,55.97,125,125,0-69.04,55.97-125,125-125-69.04,0-125-55.97-125-125Z"/></svg>`;
}
