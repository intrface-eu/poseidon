# apps/site

The public page for Poseidon at https://poseidon.intrface.eu: one
editorial page plus `/press`, `/sources` and `/evidence`. Static HTML rendered
at build time, one stylesheet, a small script, and three.js loaded after first
paint for the hero and the listening-head viewer.

The page describes a design and a software stack, not a tested product. No
unit has been built or put in water, and nothing on the page claims that the
system detects, deters, is permitted or conforms to anything.

## Run it

Bun only. Never npm, yarn or pnpm.

```sh
bun install
bun run dev         # dev server on 127.0.0.1:5180
bun run build       # static site in dist/
bun run preview     # serve dist/ on 127.0.0.1:5181
bun run typecheck   # tsc --noEmit
bun test            # claims register and rendered-page checks
bun run qa          # screenshots of the built site into qa/out/ (build first)
bun run qa:assets   # regenerate posters, og image and icons into public/ (build first, then build again)
```

`qa` and `qa:assets` use playwright-core from `apps/aeolus-ui/node_modules`
(set `PLAYWRIGHT_CORE` to use another copy) and a Chromium installed by
Playwright. They run under a 900 s alarm, close the browser in `finally` and
stop their local server.

## Deploy

The site runs as a Cloudflare Worker with static assets, configured in
`wrangler.jsonc` (route `poseidon.intrface.eu/*`, assets from `./dist`,
unknown paths answered by `dist/404.html`):

```sh
bun run build
bunx wrangler@4 deploy
```

Each page is a directory with an `index.html` (`/press/`, `/sources/`,
`/evidence/`); `html_handling: auto-trailing-slash` serves them.
`sitemap.xml` and `robots.txt` are generated; `404.html` is kept out of the
sitemap and marked `noindex`. Hashed files under `dist/assets/` can be cached
for a year; the HTML should not be cached long.

## How it is built

- `src/content/en.ts` holds every word on the site. `claims` are factual
  sentences; everything else is framing and may not contain a number, € or %.
  A Croatian version is a second module with the same `Copy` shape, added to
  `LOCALES` in `src/render/index.ts`.
- `src/content/claims.json` maps each claim to its sources: IDs from
  `content/sources.md` (S, P, F) or paths in this repository. Citation marks
  and the source notes are generated from it. `tests/claims.test.ts` fails if
  a claim has no source, a source ID or repo path does not exist, a claim is
  unused, framing copy carries a figure, or banned words appear.
- `content/pitch.md`, `ask.md`, `press-kit.md` and `sources.md` are the
  written sources the copy was tightened from.
- `src/content/site.ts` holds the company details, contact, repository,
  licences, page list (including the 404 page) and asset paths.
- `src/render/*` turns the copy into HTML. `vite.config.ts` replaces each empty
  HTML entry (`index.html`, `press/index.html`, ...) with the rendered page and
  emits `sitemap.xml` and `robots.txt`.
- `src/main.ts` is the only script on first load. It starts the 3D when the
  browser has WebGL, is not on Save-Data or 2G, and does not ask for reduced
  motion; otherwise the poster images stay.
- `src/three/` holds the viewers. `models.ts` says which files load. Both
  mark `hero-3d-first-frame` and `head-3d-first-frame` with `performance.mark`
  when their first frame is drawn.

## 3D models

`src/three/models.ts` names the files and what to do with them. Both come
from `hardware/showcase/` (see `scene-manifest-v4.json` there for node and
clip names) and are copied into `public/models/` by hand:

- `hero.glb`: the unit on its pole at a mussel farm. Draco geometry and WebP
  textures. The page hides `mountFloat`, `waterSurface` (the sea band is CSS)
  and `longlineFront` (it runs between the camera and the unit), plays `swim`
  on a loop and `descend` once. Phones and machines with four cores or less,
  or four GB of memory or less, also hide `longlineBack`.
- `head.glb`: the listening head alone. The button scrubs its `explode` clip.

The Draco decoder ships with the build (`DRACO_GLTF_CONFIG` in
`src/three/runtime.ts`); meshopt files load too. After replacing a model,
build, run `bun run qa:assets`, and build again so the posters match.

## Images

| Path | Made by | From |
| --- | --- | --- |
| `/og-image.png` (1200x630, 256 colours, under 300 KB) | `qa:assets`: wordmark and headline set over the render | `hardware/showcase/renders-v4/og-image.png` |
| `/posters/hero-wide.webp`, `hero-narrow.webp`, `head.webp` | `qa:assets`, from the live 3D | `public/models/` |
| `/press/poseidon-{hero,farm,unit,head-exploded}.png` | `qa:assets`: the renders with metadata stripped | `hardware/showcase/renders-v4/{hero-16x9,farm-wide,unit-closeup,head-exploded}.png` |
| `/press/poseidon-*.webp` | `qa:assets`: 800 px previews for the press page | the same renders |
| `/press/poseidon-logo.svg`, `-logo-dark.svg` | by hand | outlined from Google Sans Flex |
| `/favicon.svg`, `/favicon-32.png`, `/apple-touch-icon.png` | `qa:assets` for the PNGs | the three-tined mark |

`qa:assets` reads the renders from `hardware/showcase/renders-v4/` (set
`RENDERS_DIR` to use another folder) and needs ImageMagick (`magick`). The
renders are CC-BY-4.0; the press page credits each one as "Render:
INTRFACE, CC BY 4.0". A press image appears with its download link as soon as
its file exists in `public/press/`.

## Links into the repository

`REPO_REF` in `src/content/site.ts` sets the branch that evidence and
contributing links point at (`main`). Those links resolve once the work is on
that branch.
