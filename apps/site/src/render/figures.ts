/**
 * Figures drawn at build time as inline SVG or HTML, from the figure data in
 * the locale module. Each one names the claim that sources it.
 */

import type { ClaimId, Copy } from '../content/en.ts';
import { citations, claim, esc, type RenderContext } from './html.ts';

/** One hundred droppers on two longlines; bare ropes are the ones lost. */
export function ropesFigure(ctx: RenderContext): string {
  const f = ctx.copy.figures.ropes;
  const perRow = f.total / 2;
  const lostPerRow = f.lost / 2;
  const pitch = 12;
  const width = perRow * pitch;
  const rowHeight = 118;
  const rows: string[] = [];
  for (let r = 0; r < 2; r++) {
    const y0 = 14 + r * rowHeight;
    const marks: string[] = [];
    for (let i = 0; i < perRow; i++) {
      const x = i * pitch + pitch / 2;
      const lost = i >= perRow - lostPerRow;
      if (lost) {
        marks.push(`<line class="rope rope--bare" x1="${x}" y1="${y0}" x2="${x}" y2="${y0 + 84}"/>`);
      } else {
        marks.push(
          `<line class="rope rope--bare" x1="${x}" y1="${y0}" x2="${x}" y2="${y0 + 8}"/><rect class="rope rope--full" x="${x - 3.5}" y="${y0 + 6}" width="7" height="80" rx="3.5"/>`,
        );
      }
    }
    rows.push(
      `<line class="longline" x1="0" y1="${y0}" x2="${width}" y2="${y0}"/>${marks.join('')}`,
    );
  }
  const height = 14 + rowHeight * 2 - 20;
  const title = claim(ctx, 'fig-ropes-title' as ClaimId, { cite: false });
  return `<figure class="figure figure--ropes" aria-labelledby="fig-ropes-title">
  <p class="figure__title" id="fig-ropes-title">${title}</p>
  <svg class="ropes" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(
    `${f.lostLabel}, ${f.keptLabel}`,
  )}">${rows.join('')}</svg>
  <p class="figure__legend" aria-hidden="true"><span class="key key--full"></span>${esc(f.keptLabel)}<span class="key key--bare"></span>${esc(f.lostLabel)}</p>
  <figcaption>${claim(ctx, f.claim as ClaimId)}</figcaption>
</figure>`;
}

/** Croatian mussel output as three horizontal bars. */
export function outputFigure(ctx: RenderContext): string {
  const f = ctx.copy.figures.output;
  const max = Math.max(...f.rows.map((row) => row.value));
  const rows = f.rows
    .map(
      (row) => `<tr>
      <th scope="row">${esc(row.label)}</th>
      <td><span class="bar" style="--share:${(row.value / max).toFixed(4)}"></span><span class="bar__value">${esc(row.text)}</span></td>
    </tr>`,
    )
    .join('');
  return `<figure class="figure figure--output">
  <p class="figure__title">${esc(ctx.copy.home.problem.outputTitle)}</p>
  <table class="bars">
    <thead class="visually-hidden"><tr><th scope="col">Year</th><th scope="col">${esc(f.unit)}</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
  <figcaption>${claim(ctx, f.claim as ClaimId)}</figcaption>
</figure>`;
}

/** A duration bar for one stage on the shared month axis. */
export function stageBar(copy: Copy, index: number): string {
  const f = copy.figures.stages;
  const row = f.rows[index];
  if (!row) return '';
  const pct = (m: number) => ((m / f.axisMax) * 100).toFixed(2);
  const last = f.ticks.length - 1;
  const ticks = f.ticks
    .map((t, i) => `<span class="stagebar__tick" style="left:${pct(t)}%"><span>${t}${i === last ? ` ${esc(copy.home.plan.monthsAxis)}` : ''}</span></span>`)
    .join('');
  return `<div class="stagebar" aria-hidden="true">
    <div class="stagebar__track">
      <span class="stagebar__min" style="width:${pct(row.min)}%"></span>
      <span class="stagebar__max" style="left:${pct(row.min)}%;width:${pct(row.max - row.min)}%"></span>
    </div>
    <div class="stagebar__axis">${ticks}</div>
  </div>`;
}

export { citations };
