/**
 * Browser QA for the built site, and the raster assets made from it.
 *
 *   bun run build
 *   perl -e 'alarm 900; exec @ARGV' bun qa/shots.ts            # screenshots to qa/out/
 *   perl -e 'alarm 900; exec @ARGV' bun qa/shots.ts --assets   # posters, og image, icons to public/
 *
 * Needs playwright-core and a Chromium from `bunx playwright install
 * chromium`. Set PLAYWRIGHT_CORE to its path if it is not resolvable from
 * here; by default the copy in apps/aeolus-ui is used. The browser always
 * closes in `finally`, and the local server stops with it.
 */

import { mkdirSync } from 'node:fs';
import { extname, join, resolve } from 'node:path';
import { en } from '../src/content/en.ts';
import { PRESS_ASSETS } from '../src/content/site.ts';

const ROOT = resolve(import.meta.dirname, '..');
const DIST = join(ROOT, 'dist');
const PUBLIC = join(ROOT, 'public');
const OUT = join(ROOT, 'qa', 'out');
const PLAYWRIGHT = process.env.PLAYWRIGHT_CORE ?? resolve(ROOT, '..', 'aeolus-ui', 'node_modules', 'playwright-core');
const ASSETS = process.argv.includes('--assets');
/** Press renders from the showcase run; read only. */
const RENDERS = process.env.RENDERS_DIR ?? resolve(ROOT, '..', '..', 'hardware', 'showcase', 'renders-v4');

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
  '.glb': 'model/gltf-binary',
  '.wasm': 'application/wasm',
  '.xml': 'application/xml',
  '.txt': 'text/plain',
};

const server = Bun.serve({
  hostname: '127.0.0.1',
  port: 0,
  async fetch(request) {
    let path = decodeURIComponent(new URL(request.url).pathname);
    if (path.endsWith('/')) path += 'index.html';
    const file = Bun.file(join(DIST, path));
    /* Like the host: unknown paths get the site's 404 page. */
    if (!(await file.exists())) return new Response(Bun.file(join(DIST, '404.html')), { status: 404, headers: { 'content-type': TYPES['.html']! } });
    return new Response(file, { headers: { 'content-type': TYPES[extname(path)] ?? 'application/octet-stream' } });
  },
});
const base = `http://127.0.0.1:${server.port}`;

/* playwright-core is resolved at run time from outside this package, so it is untyped here. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Page = any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Browser = any;

const { chromium } = (await import(PLAYWRIGHT)) as { chromium: { launch(options: object): Promise<Browser> } };
const browser: Browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
});

const VIEWPORTS = {
  desktop: { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
  phone: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true },
} as const;

async function waitLive(page: Page, selector: string, timeout = 60_000): Promise<boolean> {
  try {
    await page.waitForSelector(`${selector}.is-live`, { timeout });
    await page.waitForTimeout(1500);
    return true;
  } catch {
    return false;
  }
}

async function screenshots(): Promise<void> {
  mkdirSync(OUT, { recursive: true });
  const report: string[] = [];
  for (const [name, options] of Object.entries(VIEWPORTS)) {
    const context = await browser.newContext(options);
    const page = await context.newPage();
    const errors: string[] = [];
    page.on('pageerror', (e: Error) => errors.push(e.message));
    let expect404 = false;
    page.on('console', (m: { type(): string; text(): string }) => {
      if (m.type() !== 'error') return;
      if (expect404 && m.text().includes('status of 404')) return;
      errors.push(m.text());
    });
    await page.goto(`${base}/`, { waitUntil: 'load' });
    await page.screenshot({ path: join(OUT, `${name}-home-00-first-paint.png`) });
    const heroLive = await waitLive(page, '[data-stage="hero"]');
    const firstFrame = async (mark: string) =>
      page.evaluate((m: string) => Math.round(performance.getEntriesByName(m)[0]?.startTime ?? -1), mark);
    const heroFrame = await firstFrame('hero-3d-first-frame');
    await page.screenshot({ path: join(OUT, `${name}-home-01-hero.png`) });
    /* Pin the header out of the way so it does not repeat inside section captures. */
    await page.addStyleTag({ content: '.site-header { position: static !important; }' });
    const sections = ['problem', 'how', 'plan', 'partner', 'team', 'sources', 'contact'];
    for (const [i, id] of sections.entries()) {
      const locator = page.locator(`#${id}`);
      await locator.scrollIntoViewIfNeeded();
      if (id === 'how') await waitLive(page, '[data-stage="head"]', 45_000);
      await page.waitForTimeout(300);
      const file = join(OUT, `${name}-home-${String(i + 2).padStart(2, '0')}-${id}.png`);
      try {
        await locator.screenshot({ path: file });
      } catch {
        /* Very tall sections exceed the capture limit: take them a screen at a time. */
        const box = await locator.boundingBox();
        const top = (await page.evaluate(() => window.scrollY)) + (box?.y ?? 0);
        const height = options.viewport.height;
        for (let y = 0, n = 0; y < (box?.height ?? 0); y += height - 80, n++) {
          await page.evaluate((to: number) => window.scrollTo(0, to), top + y);
          await page.waitForTimeout(200);
          await page.screenshot({ path: file.replace('.png', `-${String.fromCharCode(97 + n)}.png`) });
        }
      }
    }
    const explode = page.locator('[data-explode]');
    if (await explode.isVisible()) {
      await explode.scrollIntoViewIfNeeded();
      await explode.click();
      await page.waitForTimeout(1600);
      /* A capture taller than the viewport blanks the WebGL canvas, so tall layouts shoot the stage alone. */
      const fig = page.locator('.headfig');
      const figBox = await fig.boundingBox();
      const target = (figBox?.height ?? 0) > options.viewport.height ? page.locator('.headfig__stage') : fig;
      await target.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      await target.screenshot({ path: join(OUT, `${name}-home-04b-head-exploded.png`) });
    }
    await page.locator('.site-footer').screenshot({ path: join(OUT, `${name}-home-10-footer.png`) });
    const headFrame = await firstFrame('head-3d-first-frame');
    for (const sub of ['press', 'sources', 'evidence', '404']) {
      expect404 = sub === '404';
      await page.goto(expect404 ? `${base}/no-such-page/` : `${base}/${sub}/`, { waitUntil: 'load' });
      /* Scroll through once so lazy images load before the full-page capture. */
      await page.evaluate(async () => {
        for (let y = 0; y < document.body.scrollHeight; y += 600) {
          window.scrollTo(0, y);
          await new Promise((r) => setTimeout(r, 40));
        }
        window.scrollTo(0, 0);
      });
      await page.waitForTimeout(500);
      await page.screenshot({ path: join(OUT, `${name}-${sub}.png`), fullPage: true });
      if (sub === 'press') {
        /* Full-page captures can miss lazy images; shoot the image grid on its own too. */
        const images = page.locator('.assets');
        await images.scrollIntoViewIfNeeded();
        await page.waitForTimeout(600);
        await images.screenshot({ path: join(OUT, `${name}-press-images.png`) });
      }
    }
    report.push(
      `${name}: hero 3D live=${heroLive}, first frame ${heroFrame} ms; head first frame ${headFrame} ms (after scrolling to it); errors=${
        errors.length ? errors.join(' | ') : 'none'
      }`,
    );
    await context.close();
  }

  /* The poster path: reduced motion keeps the 3D off. */
  const still = await browser.newContext({ ...VIEWPORTS.desktop, reducedMotion: 'reduce' });
  const page = await still.newPage();
  await page.goto(`${base}/`, { waitUntil: 'load' });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: join(OUT, 'desktop-home-reduced-motion.png') });
  await still.close();
  console.log(report.join('\n'));
}

async function toWebp(page: Page, png: Buffer, quality: number): Promise<Buffer> {
  const dataUrl: string = await page.evaluate(
    async ({ src, q }: { src: string; q: number }) => {
      const img = new Image();
      img.src = src;
      await img.decode();
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth;
      canvas.height = img.naturalHeight;
      canvas.getContext('2d')!.drawImage(img, 0, 0);
      return canvas.toDataURL('image/webp', q);
    },
    { src: `data:image/png;base64,${png.toString('base64')}`, q: quality },
  );
  return Buffer.from(dataUrl.split(',')[1] ?? '', 'base64');
}

const HIDE_COPY = '.hero__copy, .hero__caption { visibility: hidden !important; } .stage__poster { display: none !important; }';

/** Press downloads: the full renders without metadata, plus WebP previews for the page. */
function pressRenders(): void {
  for (const asset of PRESS_ASSETS) {
    if (!asset.render || !asset.preview) continue;
    const from = join(RENDERS, asset.source.split('/').pop() ?? '');
    const run = (args: string[]) => {
      const result = Bun.spawnSync(args);
      if (result.exitCode !== 0) throw new Error(`${args.join(' ')}: ${result.stderr.toString()}`);
    };
    run(['magick', from, '-strip', join(PUBLIC, asset.path)]);
    run(['magick', from, '-strip', '-resize', '800x800>', '-quality', '78', '-define', 'webp:method=6', join(PUBLIC, asset.preview)]);
  }
}

async function assets(): Promise<void> {
  mkdirSync(join(PUBLIC, 'posters'), { recursive: true });
  pressRenders();

  for (const [name, file] of [['desktop', 'hero-wide'], ['phone', 'hero-narrow']] as const) {
    const context = await browser.newContext({ ...VIEWPORTS[name], deviceScaleFactor: name === 'phone' ? 2 : 1 });
    const page = await context.newPage();
    await page.goto(`${base}/`, { waitUntil: 'load' });
    await page.addStyleTag({ content: HIDE_COPY });
    if (!(await waitLive(page, '[data-stage="hero"]'))) throw new Error(`hero 3D did not start (${name})`);
    await page.waitForTimeout(2000);
    const png = await page.locator('[data-stage="hero"]').screenshot();
    await Bun.write(join(PUBLIC, 'posters', `${file}.webp`), await toWebp(page, png, 0.8));

    if (name === 'desktop') {
      const head = page.locator('[data-stage="head"]');
      await head.scrollIntoViewIfNeeded();
      if (!(await waitLive(page, '[data-stage="head"]'))) throw new Error('head 3D did not start');
      await page.waitForTimeout(1500);
      await Bun.write(join(PUBLIC, 'posters', 'head.webp'), await toWebp(page, await head.screenshot(), 0.82));
    }
    await context.close();
  }

  /* Share image: the og render with the wordmark and headline over its calm left third. */
  const og = await browser.newContext({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
  const page = await og.newPage();
  const render = await Bun.file(join(RENDERS, 'og-image.png')).arrayBuffer();
  const logo = await Bun.file(join(PUBLIC, 'press', 'poseidon-logo.svg')).text();
  await page.goto(`${base}/`, { waitUntil: 'load' });
  await page.setContent(`<!doctype html><html><head><meta charset="utf-8"><style>
    @font-face { font-family: 'Google Sans Flex'; src: url('${base}/fonts/google-sans-flex-latin.woff2') format('woff2'); font-weight: 100 1000; }
    html, body { margin: 0; width: 1200px; height: 630px; overflow: hidden; }
    body { background: url(data:image/png;base64,${Buffer.from(render).toString('base64')}) 0 0 / 1200px 630px; font-family: 'Google Sans Flex', sans-serif; color: #0f1729; }
    .logo { position: absolute; left: 56px; top: 44px; width: auto; height: 47.6px; }
    h1 { position: absolute; left: 56px; top: 104px; width: 440px; margin: 0; font-size: 36px; line-height: 1.08; font-weight: 600; letter-spacing: -0.035em; font-variation-settings: 'opsz' 48; }
  </style></head><body>${logo.replace('<svg ', '<svg class="logo" ')}<h1>${en.claims['hero-headline']}</h1></body></html>`);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  const raw = join(OUT, 'og-raw.png');
  mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: raw, clip: { x: 0, y: 0, width: 1200, height: 630 } });
  await og.close();
  /* 256-colour PNG without metadata keeps the card under 300 KB. */
  const quant = Bun.spawnSync(['magick', raw, '-strip', '-dither', 'FloydSteinberg', '-colors', '256', `PNG8:${join(PUBLIC, 'og-image.png')}`]);
  if (quant.exitCode !== 0) throw new Error(`og-image: magick failed: ${quant.stderr.toString()}`);

  /* Icons from the favicon mark. */
  const icons = await browser.newContext({ viewport: { width: 200, height: 200 }, deviceScaleFactor: 1 });
  const iconPage = await icons.newPage();
  const svg = await Bun.file(join(PUBLIC, 'favicon.svg')).text();
  await iconPage.setContent(`<html><body style="margin:0;background:transparent">${svg.replace('<svg ', '<svg id="m" width="32" height="32" ')}</body></html>`);
  await iconPage.locator('#m').screenshot({ path: join(PUBLIC, 'favicon-32.png'), omitBackground: true });
  const touch = svg.replace('rx="7" ', '').replace('<svg ', '<svg id="m" width="180" height="180" ').replace('<g ', '<g transform="translate(3.2 3.2) scale(0.8)" ');
  await iconPage.setContent(`<html><body style="margin:0">${touch}</body></html>`);
  await iconPage.locator('#m').screenshot({ path: join(PUBLIC, 'apple-touch-icon.png') });
  await icons.close();
  console.log(
    'assets written to public/: posters/hero-wide.webp, posters/hero-narrow.webp, posters/head.webp, og-image.png, favicon-32.png, apple-touch-icon.png, press renders and previews',
  );
}

try {
  if (ASSETS) await assets();
  else await screenshots();
} finally {
  await browser.close();
  server.stop(true);
}
