/**
 * The secondary pages: /press, /sources and /evidence.
 */

import register from '../content/claims.json' with { type: 'json' };
import type { ClaimId } from '../content/en.ts';
import {
  COMPANY,
  CONTACT_EMAIL,
  LICENCES,
  PERSON,
  PRESS_ASSETS,
  RENDER_LICENCE,
  REPO_URL,
  SITE_URL,
  mailto,
  repoLink,
} from '../content/site.ts';
import { compareSourceIds, isSourceId, loadSources } from '../content/sources.ts';
import { contactBlock } from './home.ts';
import { claim, esc, inline, plain, claimText, type RenderContext } from './html.ts';
import { icon } from './icons.ts';
import { publicFileExists, publicFileInfo } from './paths.ts';

function fileSize(bytes: number): string {
  return bytes >= 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function pageHead(title: string, lead: string, extra = ''): string {
  return `<header class="pagehead">
  <div class="column">
    <h1 class="display display--page">${esc(title)}</h1>
    <p class="lead">${lead}</p>
    ${extra}
  </div>
</header>`;
}

function copyBlock(ctx: RenderContext, id: string, ids: ClaimId[]): string {
  const { actions } = ctx.copy;
  const paragraphs = ids.map((cid) => `<p>${claim(ctx, cid, { cite: false })}</p>`).join('');
  return `<div class="boiler">
  <div class="boiler__text" id="${id}">${paragraphs}</div>
  <button class="btn btn--secondary btn--compact" type="button" data-copy="${id}" data-label-done="${esc(
    actions.copied,
  )}" data-label-failed="${esc(actions.copyFailed)}">${icon('copy')}<span>${esc(actions.copy)}</span></button>
  <p class="boiler__status" role="status" aria-live="polite"></p>
</div>`;
}

export function renderPressBody(ctx: RenderContext): string {
  const t = ctx.copy.press;
  const f = t.facts;
  const row = (term: string, value: string) => `<div><dt>${esc(term)}</dt><dd>${value}</dd></div>`;
  const facts = [
    row(f.project, 'Poseidon'),
    row(f.company, `${esc(COMPANY.name)}, ${esc(t.companyType)}`),
    row(f.address, `${esc(COMPANY.street)}, ${esc(COMPANY.postcode)} ${esc(COMPANY.town)}, ${esc(COMPANY.country)}`),
    row(f.registration, `OIB ${esc(COMPANY.oib)}; MBS ${esc(COMPANY.mbs)}, ${esc(COMPANY.court)}`),
    row(f.director, esc(PERSON.name)),
    row(f.site, claim(ctx, 'fact-site')),
    row(f.problem, claim(ctx, 'fact-problem')),
    row(f.what, claim(ctx, 'fact-what', { cite: false })),
    row(f.status, claim(ctx, 'fact-status', { cite: false })),
    row(f.next, claim(ctx, 'fact-next', { cite: false })),
    row(
      f.licences,
      esc(t.licenceLine.replace('{code}', LICENCES.code).replace('{hardware}', LICENCES.hardware).replace('{docs}', LICENCES.docs)),
    ),
    row(f.repository, `<a href="${REPO_URL}" rel="noopener">${esc(REPO_URL.replace('https://', ''))}</a>`),
    row(f.website, `<a href="${SITE_URL}/">${esc(SITE_URL.replace('https://', ''))}</a>`),
    row(f.contact, `${esc(PERSON.name)}, <a href="${mailto('Press: Poseidon')}">${esc(CONTACT_EMAIL)}</a>`),
  ].join('');

  const questions = t.questions
    .map((item) => `<div class="qa__item"><dt>${esc(item.q)}</dt><dd>${claim(ctx, item.claim as ClaimId, { cite: false })}</dd></div>`)
    .join('');

  const assets = PRESS_ASSETS.map((asset) => {
    const label = t.assets[asset.id];
    if (!publicFileExists(asset.path)) {
      return `<li class="asset asset--pending"><div class="asset__thumb asset__thumb--empty" aria-hidden="true"></div><p class="asset__name">${esc(
        label,
      )}</p><p class="asset__meta">${esc(t.comingSoon)}</p></li>`;
    }
    const dark = asset.id === 'logo-dark';
    const preview = asset.preview && publicFileExists(asset.preview) ? asset.preview : asset.path;
    const info = publicFileInfo(asset.path);
    const format = asset.path.endsWith('.svg') ? 'SVG' : 'PNG';
    const size = info.width ? `${format}, ${info.width} × ${info.height}, ${fileSize(info.bytes)}` : `${format}, ${fileSize(info.bytes)}`;
    const credit = asset.render ? `<p class="asset__credit">${esc(t.credit.replace('{licence}', RENDER_LICENCE))}</p>` : '';
    return `<li class="asset"><div class="asset__thumb${dark ? ' asset__thumb--dark' : ''}${asset.render ? ' asset__thumb--render' : ''}"><img src="${preview}" alt="${esc(
      label,
    )}" loading="lazy" decoding="async"></div><p class="asset__name">${esc(label)}</p>${credit}<p class="asset__meta"><a href="${
      asset.path
    }" download>${icon('download')}<span>${esc(ctx.copy.actions.download)}</span></a><span class="asset__size">${esc(size)}</span></p></li>`;
  }).join('');

  const head = pageHead(
    t.heading,
    `${esc(t.lead)}`,
    `<p class="pagehead__action"><a class="btn btn--primary" href="${mailto('Press: Poseidon')}">${icon('mail')}<span>${esc(
      CONTACT_EMAIL,
    )}</span></a></p>`,
  );

  return `${head}
<section class="section section--paper section--tight" aria-labelledby="boiler-title">
  <div class="column">
    <h2 class="h3" id="boiler-title">${esc(t.shortHeading)}</h2>
    ${copyBlock(ctx, 'boiler-50', ['press-50'])}
    <h2 class="h3">${esc(t.longHeading)}</h2>
    ${copyBlock(ctx, 'boiler-150', ['press-150a', 'press-150b'])}
  </div>
</section>
<section class="section section--paper section--tight" aria-labelledby="facts-title">
  <div class="column">
    <h2 class="h2 h2--small" id="facts-title">${esc(t.factsHeading)}</h2>
    <dl class="facts">${facts}</dl>
  </div>
</section>
<section class="section section--raised" aria-labelledby="qa-title">
  <div class="column">
    <h2 class="h2 h2--small" id="qa-title">${esc(t.qaHeading)}</h2>
    <dl class="qa">${questions}</dl>
  </div>
</section>
<section class="section section--paper" aria-labelledby="images-title">
  <div class="column">
    <h2 class="h2 h2--small" id="images-title">${esc(t.imagesHeading)}</h2>
    <p>${esc(t.imagesLead)}</p>
  </div>
  <ul class="wide assets">${assets}</ul>
</section>
${contactBlock(ctx)}`;
}

export function renderSourcesBody(ctx: RenderContext): string {
  const t = ctx.copy.sourcesPage;
  const all = loadSources();
  const groups = (['S', 'P', 'F'] as const)
    .map((g) => {
      const rows = all
        .filter((s) => s.group === g)
        .sort((a, b) => compareSourceIds(a.id, b.id))
        .map((s) => {
          const links = s.links
            .map((l) => {
              const host = new URL(l.url).hostname.replace(/^www\./, '');
              const text = l.label ? `${l.label}: ${host}` : host;
              return `<a href="${esc(l.url)}" rel="noopener">${esc(text)}</a>`;
            })
            .join('');
          return `<li class="srcrow" id="${s.id}">
        <span class="srcrow__id">${s.id}</span>
        <div class="srcrow__body"><p>${inline(s.text)}</p><p class="srcrow__links">${links}</p></div>
        <p class="srcrow__date"><span class="visually-hidden">${esc(t.accessed)} </span><time>${esc(s.accessed)}</time></p>
      </li>`;
        })
        .join('');
      return `<section class="section section--paper section--tight" aria-labelledby="group-${g}">
  <div class="column column--wide">
    <h2 class="h2 h2--small" id="group-${g}">${esc(t.groups[g])}</h2>
    <p class="srchead" aria-hidden="true"><span>${esc(t.id)}</span><span>${esc(t.source)}</span><span>${esc(t.accessed)}</span></p>
    <ol class="srclist">${rows}</ol>
  </div>
</section>`;
    })
    .join('\n');
  return `${pageHead(t.heading, esc(t.lead))}\n${groups}`;
}

const CONTENT_PREFIX = 'apps/site/content/';

export function renderEvidenceBody(ctx: RenderContext): string {
  const t = ctx.copy.evidencePage;
  const entries = Object.entries(register.claims as Record<string, string[]>)
    .filter(([id]) => id.startsWith('today-') || id.startsWith('unit-') || id.startsWith('how-') || id === 'open-licences' || id === 'open-contribute' || id === 'next-access')
    .map(([id, sources]) => ({ id: id as ClaimId, paths: sources.filter((s) => !isSourceId(s) && !s.startsWith(CONTENT_PREFIX)) }))
    .filter((e) => e.paths.length > 0);
  const items = entries
    .map(
      (e) => `<li class="evrow">
      <p class="evrow__claim">${inline(claimText(ctx, e.id))}</p>
      <ul class="evrow__paths" aria-label="${esc(t.linksLabel)}">${e.paths
        .map((path) => `<li><a href="${repoLink(path)}" rel="noopener">${icon('github')}<code>${esc(path)}</code></a></li>`)
        .join('')}</ul>
    </li>`,
    )
    .join('');
  return `${pageHead(t.heading, esc(t.lead))}
<section class="section section--paper section--tight" aria-label="${esc(plain(t.heading))}">
  <div class="column column--wide">
    <ol class="evlist">${items}</ol>
  </div>
</section>`;
}

export function renderNotFoundBody(ctx: RenderContext): string {
  const t = ctx.copy.notFound;
  const link = (href: string, label: string) => `<li><a href="${href}">${icon('arrowRight')}<span>${esc(label)}</span></a></li>`;
  const links = `<ul class="linklist">
      ${link('/', t.links.home)}
      ${link('/press/', t.links.press)}
      ${link('/sources/', t.links.sources)}
      ${link('/evidence/', t.links.evidence)}
    </ul>`;
  return `${pageHead(t.heading, esc(t.lead), links)}
${contactBlock(ctx)}`;
}
