/**
 * The project page: one editorial column from the surface to the seabed.
 * Hero, the problem, how it works, where it stands, the ask, team and open
 * source, the sources for the page, and contact.
 */

import type { ClaimId } from '../content/en.ts';
import { COMPANY, CONTACT_EMAIL, PERSON, POSTERS, REPO_URL, mailto, repoLink } from '../content/site.ts';
import { compareSourceIds, loadSources } from '../content/sources.ts';
import { outputFigure, ropesFigure, stageBar } from './figures.ts';
import { claim, claimText, esc, inline, p, plain, type RenderContext } from './html.ts';
import { icon } from './icons.ts';
import { publicFileExists } from './paths.ts';

function heroPoster(ctx: RenderContext): string {
  const { hero } = ctx.copy.home;
  const wide = publicFileExists(POSTERS.heroWide);
  const narrow = publicFileExists(POSTERS.heroNarrow);
  if (!wide && !narrow) return '';
  const fallback = narrow ? POSTERS.heroNarrow : POSTERS.heroWide;
  const source = wide && narrow ? `<source media="(min-width: 900px)" srcset="${POSTERS.heroWide}">` : '';
  return `<picture class="stage__poster">${source}<img src="${fallback}" alt="${esc(hero.posterAlt)}" decoding="async" fetchpriority="high"></picture>`;
}

function hero(ctx: RenderContext): string {
  const { actions, home } = ctx.copy;
  const poster = heroPoster(ctx);
  return `<section class="hero" aria-labelledby="hero-title">
  <div class="hero__water" aria-hidden="true"></div>
  <div class="stage hero__stage${poster ? ' has-poster' : ''}" data-stage="hero" aria-label="${esc(home.hero.stageLabel)}" role="group">
    ${poster}
    <canvas class="stage__canvas" aria-hidden="true"></canvas>
  </div>
  <div class="hero__copy">
    <h1 id="hero-title" class="display">${claim(ctx, 'hero-headline', { cite: false })}</h1>
    <p class="hero__lead">${claim(ctx, 'hero-lead', { cite: false })}</p>
    <p class="hero__want">${claim(ctx, 'hero-want', { cite: false })}</p>
    <div class="hero__actions">
      <a class="btn btn--primary" href="#partner">${esc(actions.partner)}${icon('arrowDown')}</a>
      <a class="btn btn--secondary" href="#plan">${esc(actions.readPlan)}</a>
    </div>
    <p class="hero__repo"><a href="${REPO_URL}" rel="noopener">${icon('github')}<span>${esc(actions.repo)}</span></a></p>
  </div>
  <p class="hero__caption">${claim(ctx, 'hero-caption', { cite: false })}</p>
</section>`;
}

function problem(ctx: RenderContext): string {
  const t = ctx.copy.home.problem;
  const fix = (term: string, ids: ClaimId[]) =>
    `<div class="fixes__row"><dt>${esc(term)}</dt><dd>${ids.map((id) => claim(ctx, id)).join(' ')}</dd></div>`;
  return `<section class="section section--paper" id="problem" aria-labelledby="problem-title">
  <div class="column">
    <h2 id="problem-title" class="h2">${claim(ctx, 'problem-heading', { cite: false })}</h2>
    ${p(ctx, ['problem-who', 'problem-ropes', 'problem-young', 'problem-night', 'problem-value'], 'lead')}
  </div>
  <div class="wide">${ropesFigure(ctx)}</div>
  <div class="column">
    ${p(ctx, ['problem-france', 'problem-spezia', 'problem-common', 'problem-fidelity'])}
  </div>
  <div class="wide">${outputFigure(ctx)}</div>
  <div class="column">
    <h3 class="h3">${esc(t.whoLoses)}</h3>
    ${p(ctx, ['problem-small', 'problem-2025', 'problem-compensation'])}
    <h3 class="h3">${esc(t.limHeading)}</h3>
    ${p(ctx, ['lim-geo', 'lim-farming', 'lim-reserve', 'lim-last-farmer'])}
    <p class="note">${claim(ctx, 'lim-no-figure')}</p>
    <h3 class="h3">${esc(t.fixesHeading)}</h3>
    <dl class="fixes">
      ${fix(t.fixNets, ['fix-nets', 'fix-nets-heavy', 'fix-nets-cost'])}
      ${fix(t.fixFishing, ['fix-fishing'])}
      ${fix(t.fixSound, ['fix-sound-lim', 'fix-sound-elsewhere'])}
    </dl>
  </div>
  <div class="column">
    <p class="pull">${claim(ctx, 'missing-data')}</p>
    ${p(ctx, ['missing-why'])}
  </div>
</section>`;
}

function headFigure(ctx: RenderContext): string {
  const t = ctx.copy.home.how;
  const { actions } = ctx.copy;
  const hasPoster = publicFileExists(POSTERS.head);
  const poster = hasPoster
    ? `<picture class="stage__poster"><img src="${POSTERS.head}" alt="${esc(t.headPosterAlt)}" loading="lazy" decoding="async"></picture>`
    : '';
  const parts: ClaimId[] = ['part-dome', 'part-hydrophone', 'part-tube', 'part-cable', 'part-clamp'];
  return `<figure class="headfig" aria-labelledby="head-title">
  <div class="stage headfig__stage${poster ? ' has-poster' : ''}" data-stage="head" role="group" aria-label="${esc(t.headStageLabel)}">
    ${poster}
    <canvas class="stage__canvas" aria-hidden="true"></canvas>
  </div>
  <div class="headfig__side">
    <h3 class="h3" id="head-title">${esc(t.headHeading)}</h3>
    <ul class="parts">${parts.map((id) => `<li>${claim(ctx, id, { cite: false })}</li>`).join('')}</ul>
    <button class="btn btn--on-sea headfig__toggle" type="button" data-explode aria-pressed="false" hidden
      data-label-explode="${esc(actions.explode)}" data-label-assemble="${esc(actions.assemble)}">${icon('explode')}<span>${esc(actions.explode)}</span></button>
    <figcaption>${claim(ctx, 'head-caption', { cite: false })} <span class="headfig__drag" hidden>${esc(actions.dragHint)}</span></figcaption>
  </div>
</figure>`;
}

function how(ctx: RenderContext): string {
  const t = ctx.copy.home.how;
  const steps = t.steps
    .map(
      (step, i) => `<li class="steps__item"><span class="steps__n" aria-hidden="true">${i + 1}</span><h3 class="steps__title">${esc(
        step.title,
      )}</h3><p>${claim(ctx, step.claim as ClaimId)}</p></li>`,
    )
    .join('');
  return `<section class="section section--sea" id="how" aria-labelledby="how-title">
  <div class="column column--wide">
    <h2 id="how-title" class="h2">${esc(t.heading)}</h2>
  </div>
  <ol class="wide steps">${steps}</ol>
  <div class="column">
    ${p(ctx, ['how-eagle-rays', 'how-no-recording'], 'lead')}
    ${p(ctx, ['how-value'])}
    <h3 class="h3">${esc(t.unitHeading)}</h3>
    ${p(ctx, ['unit-parts'])}
    ${p(ctx, ['unit-surface'])}
    ${p(ctx, ['unit-head'])}
    ${p(ctx, ['unit-first-rigs'])}
    ${p(ctx, ['unit-flow', 'unit-sensors'])}
    <p class="statement">${claim(ctx, 'unit-listens-only')}</p>
  </div>
  <div class="wide">${headFigure(ctx)}</div>
</section>`;
}

function plan(ctx: RenderContext): string {
  const t = ctx.copy.home.plan;
  const today: ClaimId[] = [
    'today-detector',
    'today-hub',
    'today-review',
    'today-telemetry',
    'today-firmware',
    'today-scheduler',
    'today-hardware',
    'today-research',
  ];
  const next: ClaimId[] = ['next-access', 'next-build', 'next-answer'];
  const list = (ids: ClaimId[]) => `<ul class="ticks">${ids.map((id) => `<li>${claim(ctx, id)}</li>`).join('')}</ul>`;
  const stages = t.stages
    .map((stage, i) => {
      const k = stage.claimPrefix;
      const id = (suffix: string) => `${k}-${suffix}` as ClaimId;
      return `<li class="phase">
      <div class="phase__head">
        <h4 class="phase__title"><span class="phase__n">${esc(t.stageLabel)} ${i + 1}:</span> ${esc(stage.title)}</h4>
      </div>
      <dl class="phase__facts">
        <div><dt>${esc(t.duration)}</dt><dd>${claim(ctx, id('months'))}</dd></div>
        <div><dt>${esc(t.cost)}</dt><dd>${claim(ctx, id('cost'))}</dd></div>
      </dl>
      ${stageBar(ctx.copy, i)}
      <p class="phase__body">${claim(ctx, id('body'))}</p>
      <p class="phase__end"><span class="phase__end-label">${esc(t.endsWith)}</span> ${claim(ctx, id('end'))}</p>
    </li>`;
    })
    .join('');
  return `<section class="section section--paper" id="plan" aria-labelledby="plan-title">
  <div class="column column--wide">
    <h2 id="plan-title" class="h2">${esc(t.heading)}</h2>
  </div>
  <div class="wide split">
    <div class="split__col">
      <h3 class="h3">${esc(t.todayHeading)}</h3>
      ${list(today)}
    </div>
    <div class="split__col">
      <h3 class="h3">${esc(t.nextHeading)}</h3>
      ${list(next)}
      <p class="limits">${claim(ctx, 'today-limits')}</p>
    </div>
  </div>
  <div class="column column--wide">
    <h3 class="h3">${esc(t.stagesHeading)}</h3>
  </div>
  <ol class="wide stages">${stages}</ol>
  <div class="column budget">
    <p class="budget__total">${claim(ctx, 'budget-total')}</p>
    ${p(ctx, ['budget-rig', 'budget-unit', 'budget-basis'], 'budget__note')}
  </div>
</section>`;
}

function ask(ctx: RenderContext): string {
  const t = ctx.copy.home.ask;
  const { actions } = ctx.copy;
  const cards = t.cards
    .map((card) => {
      const get = `ask-${card.id}-get` as ClaimId;
      const need = `ask-${card.id}-need` as ClaimId;
      const titleId = `ask-${card.id}`;
      return `<li class="card">
      <h3 class="card__title" id="${titleId}">${esc(card.title)}</h3>
      <dl class="card__terms">
        <div><dt>${esc(t.getLabel)}</dt><dd>${claim(ctx, get)}</dd></div>
        <div><dt>${esc(t.needLabel)}</dt><dd>${claim(ctx, need)}</dd></div>
      </dl>
      <a class="card__action" href="${esc(mailto(`${t.subjectPrefix}: ${card.subject}`))}" aria-describedby="${titleId}">${icon('mail')}<span>${esc(
        actions.writeAbout,
      )}</span></a>
    </li>`;
    })
    .join('');
  return `<section class="section section--raised" id="partner" aria-labelledby="partner-title">
  <div class="column column--wide">
    <h2 id="partner-title" class="h2">${esc(t.heading)}</h2>
    ${p(ctx, ['ask-lead'], 'lead')}
  </div>
  <ul class="wide cards">${cards}</ul>
  <div class="column">
    <p class="more"><a href="${repoLink('apps/site/content/ask.md')}" rel="noopener">${esc(t.fullList)}${icon('arrowUpRight')}</a></p>
  </div>
</section>`;
}

function teamAndOpen(ctx: RenderContext): string {
  const { team, open } = ctx.copy.home;
  return `<section class="section section--paper" id="team" aria-label="${esc(team.heading)}">
  <div class="wide split split--even">
    <div class="split__col">
      <h2 class="h2 h2--small" id="team-title">${esc(team.heading)}</h2>
      ${p(ctx, ['team-company', 'team-alex'])}
      ${p(ctx, ['team-grow'])}
      <p class="more"><a href="${COMPANY.url}" rel="noopener">${esc(team.companyLink)}${icon('arrowUpRight')}</a></p>
    </div>
    <div class="split__col" id="open">
      <h2 class="h2 h2--small">${esc(open.heading)}</h2>
      ${p(ctx, ['open-licences'])}
      ${p(ctx, ['open-why'])}
      ${p(ctx, ['open-contribute'])}
      <ul class="linklist">
        <li><a href="${REPO_URL}" rel="noopener">${icon('github')}<span>${esc(open.repoLink)}</span></a></li>
        <li><a href="${repoLink('CONTRIBUTING.md')}" rel="noopener">${icon('arrowUpRight')}<span>${esc(open.contributeLink)}</span></a></li>
        <li><a href="${repoLink('NOTICE')}" rel="noopener">${icon('arrowUpRight')}<span>${esc(open.licencesLink)}</span></a></li>
      </ul>
    </div>
  </div>
</section>`;
}

function sourceNotes(ctx: RenderContext): string {
  const all = loadSources();
  const ids = [...ctx.cited];
  const byId = new Map(all.map((s) => [s.id, s]));
  const items = ids
    .map((id) => byId.get(id))
    .filter((s): s is NonNullable<typeof s> => Boolean(s))
    .sort((a, b) => compareSourceIds(a.id, b.id))
    .map((s) => {
      const link = s.links[0];
      const host = link ? new URL(link.url).hostname.replace(/^www\./, '') : '';
      return `<li id="src-${s.id}"><span class="notes__id">${s.id}</span><span class="notes__text">${inline(
        s.text,
      )}${link ? ` <a href="${esc(link.url)}" rel="noopener">${esc(host)}</a>` : ''}</span></li>`;
    })
    .join('');
  return `<section class="section section--paper section--notes" id="sources" aria-labelledby="sources-title">
  <div class="column">
    <h2 class="h3" id="sources-title">${esc(ctx.copy.home.sources.heading)}</h2>
    <ol class="notes">${items}</ol>
    <p class="more"><a href="/sources/">${esc(ctx.copy.actions.allSources)}${icon('arrowRight')}</a></p>
  </div>
</section>`;
}

export function contactBlock(ctx: RenderContext, headingLevel: 'h2' | 'h3' = 'h2'): string {
  const t = ctx.copy.home.contact;
  const f = ctx.copy.footer;
  return `<section class="section section--deep contact" id="contact" aria-labelledby="contact-title">
  <div class="wide contact__grid">
    <div class="contact__main">
      <${headingLevel} class="h2" id="contact-title">${esc(t.heading)}</${headingLevel}>
      <p class="contact__lead">${esc(t.lead)}</p>
      <p class="contact__email"><a href="${mailto('Poseidon')}">${esc(CONTACT_EMAIL)}</a></p>
      <p class="contact__person">${esc(PERSON.name)}, ${esc(t.role)}</p>
    </div>
    <div class="contact__side">
      <h3 class="label">${esc(t.addressLabel)}</h3>
      <address class="contact__address">${esc(COMPANY.name)}<br>${esc(COMPANY.street)}<br>${esc(COMPANY.postcode)} ${esc(
        COMPANY.town,
      )}<br>${esc(COMPANY.country)}</address>
      <p class="contact__reg">${esc(plain(claimText(ctx, 'company-registration')))}</p>
      <h3 class="label">${esc(t.linksLabel)}</h3>
      <ul class="contact__links">
        <li><a href="/press/">${esc(f.press)}</a></li>
        <li><a href="/sources/">${esc(f.sources)}</a></li>
        <li><a href="/evidence/">${esc(f.evidence)}</a></li>
        <li><a href="${REPO_URL}" rel="noopener">${esc(f.github)}</a></li>
      </ul>
    </div>
  </div>
</section>`;
}

export function renderHomeBody(ctx: RenderContext): string {
  const parts = [hero(ctx), problem(ctx), how(ctx), plan(ctx), ask(ctx), teamAndOpen(ctx)];
  /* Notes come after every citation has been collected. */
  parts.push(sourceNotes(ctx));
  parts.push(contactBlock(ctx));
  return parts.join('\n');
}
