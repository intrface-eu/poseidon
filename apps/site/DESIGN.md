---
name: Poseidon
description: The project site for an open listening unit for shellfish farms, read from the surface down.
colors:
  paper: "#f5f1eb"
  paper-raised: "#fbf9f4"
  card: "#ffffff"
  ink: "#0f1729"
  ink-soft: "#283246"
  ink-muted: "#4a566c"
  line: "rgb(15 23 41 / 0.13)"
  line-strong: "rgb(15 23 41 / 0.3)"
  accent: "#0f766e"
  accent-strong: "#0b5c55"
  sea: "#0d3a41"
  sea-deep: "#082a30"
  sea-panel: "#0a3238"
  sea-surface: "rgb(226 240 236 / 0.7)"
  sea-accent: "#8fd6c9"
  on-sea: "#f5f1eb"
  on-sea-soft: "rgb(245 241 235 / 0.84)"
  on-sea-muted: "rgb(245 241 235 / 0.7)"
  on-sea-line: "rgb(245 241 235 / 0.18)"
typography:
  display:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(2.5rem, 2.9vw + 1.2rem, 4rem)"
    fontWeight: 600
    lineHeight: 1.02
    letterSpacing: "-0.04em"
    fontVariation: "'opsz' 72"
  display-page:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(2.5rem, 3vw + 1.25rem, 3.75rem)"
    fontWeight: 600
    lineHeight: 1.02
    letterSpacing: "-0.04em"
  headline:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(2rem, 1.9vw + 1.3rem, 3rem)"
    fontWeight: 600
    lineHeight: 1.06
    letterSpacing: "-0.035em"
    fontVariation: "'opsz' 48"
  headline-small:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(1.75rem, 1.2vw + 1.3rem, 2.4rem)"
    fontWeight: 600
    lineHeight: 1.06
    letterSpacing: "-0.035em"
  pull:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(1.625rem, 1.3vw + 1.2rem, 2.25rem)"
    fontWeight: 560
    lineHeight: 1.22
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  lead:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(1.1875rem, 0.4vw + 1.05rem, 1.3125rem)"
    fontWeight: 400
    lineHeight: 1.58
  body:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.65
  label:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.1em"
  wordmark:
    fontFamily: "Google Sans Flex, Inter, Segoe UI, system-ui, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 560
    lineHeight: 1
    letterSpacing: "-0.04em"
rounded:
  sm: "0.3rem"
  md: "1rem"
  lg: "1.5rem"
  pill: "999px"
spacing:
  gutter: "clamp(1rem, 4vw, 2.5rem)"
  header: "4rem"
  section: "clamp(4.5rem, 9vw, 8rem)"
  section-tight: "clamp(2.5rem, 5vw, 4rem)"
  block: "3rem"
components:
  button-primary:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    rounded: "{rounded.pill}"
    padding: "0.75rem 1.4rem"
    height: "3rem"
  button-primary-hover:
    backgroundColor: "#1d2a44"
    textColor: "{colors.paper}"
  button-secondary:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "0.75rem 1.4rem"
    height: "3rem"
  button-secondary-hover:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
  button-on-sea:
    backgroundColor: "{colors.on-sea}"
    textColor: "{colors.sea-deep}"
    rounded: "{rounded.pill}"
    padding: "0.75rem 1.4rem"
    height: "3rem"
  button-compact:
    rounded: "{rounded.pill}"
    padding: "0.5rem 1.1rem"
    height: "2.5rem"
  card:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "1.5rem 1.5rem 1.25rem"
  limits:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.md}"
    padding: "1.25rem 1.4rem"
  nav-link:
    textColor: "{colors.ink-muted}"
    rounded: "{rounded.pill}"
    padding: "0 0.75rem"
    height: "2.75rem"
  section-sea:
    backgroundColor: "{colors.sea}"
    textColor: "{colors.on-sea-soft}"
  section-deep:
    backgroundColor: "{colors.sea-deep}"
    textColor: "{colors.on-sea-soft}"
  footer:
    backgroundColor: "{colors.sea-deep}"
    textColor: "{colors.on-sea-muted}"
---

# Design System: Poseidon

## Overview

**Creative North Star: "The Waterline"**

The page reads from the surface down. Paper is air and reading; the sea colour is what lies under the waterline. The hero draws that line literally: a paper band above, a sea band below, and the unit standing across both in a 3D view whose camera sits at the water surface. Further down, sections alternate between paper, raised paper and sea, and the page ends on the deep sea of the contact block and footer. Every sea band starts at a thin bright rule, the waterline, and nothing else on the page uses a drop edge.

The system is a sibling of the INTRFACE site: the same typeface (Google Sans Flex), the same paper, ink and teal accent, the same lowercase wordmark set tight at weight 560, the same pill buttons and hairline ledgers. What this project adds is the marine layer: sea, sea-deep, sea-panel and a pale sea accent that replaces teal wherever the ground is dark. The tone is a research brief, not a pitch: one editorial column, facts carrying small citation marks, figures drawn as plain SVG and HTML, and limits stated in the place they apply.

Density is moderate. Sections breathe (4.5 to 8rem of block padding), reading columns hold to 68ch, and ledgers (fixes, ticks, facts, sources, evidence) carry detail in hairline rows instead of boxes.

**Key Characteristics:**
- Split-level hero: CSS paper over CSS sea, a transparent WebGL canvas across both.
- One typeface, tight negative tracking on display sizes, weight steps of 400, 500, 560 and 600.
- Teal accent on paper, sea accent on sea; never both on one ground.
- Hairline ledgers over cards; cards only where a thing is an offer (the ask) or a held fact (limits, boilerplate, assets).
- Citations as small tabular superscript links, collected into notes at the page foot.

## Colors

Warm paper and navy ink carry reading; two sea greens carry depth; one teal per ground carries action.

### Primary
- **Working Teal** (accent): links, citation marks, source IDs, stage numbers, tick marks, the targeted note chip. The only chromatic accent on paper grounds. Hover deepens to **Harbour Teal** (accent-strong).

### Secondary
- **Lim Bay Sea** (sea): the hero water band, How-it-works section, the kept-rope and output bars, the stagebar fill, the 3D fog colour. It is ground and data ink at once.
- **Channel Deep** (sea-deep): contact section, footer, dark press-asset thumbnails. The page's floor.
- **Kelp Panel** (sea-panel): the head viewer's stage on sea ground, with a hairline inset.

### Tertiary
- **Shallows** (sea-accent): links, citations, step numerals and the contact email underline on sea grounds. The teal's stand-in where teal would fail contrast. Link hover on sea lifts to `#c4ece4`.
- **Surface Glint** (sea-surface): only as the 1px inset rule at the top of a sea band.

### Neutral
- **Paper** (paper): page, header and default sections; also the text colour on sea (on-sea).
- **Raised Paper** (paper-raised): the alternate section band (the ask, press Q&A), bounded by hairlines.
- **Card White** (card): offer cards, limits box, boilerplate, asset thumbs, secondary-button hover.
- **Ink** (ink): headings, strong text, primary buttons, focus ring on paper.
- **Soft Ink** (ink-soft): lead and body copy in ledgers and cards.
- **Muted Ink** (ink-muted): labels, captions, notes, axis ticks, nav at rest.
- **Hairline / Strong Hairline** (line, line-strong): row rules, section borders, secondary button border, phase dividers.
- **On-sea soft / muted / line**: body, captions and rules on sea grounds, as paper at 84%, 70% and 18%.

### Named Rules
**The One Accent Per Ground Rule.** Paper grounds get Working Teal; sea grounds get Shallows. The two never share a ground, and no other hue enters the UI.

**The Sea Is Data Rule.** Where a figure needs a filled mark (a bar, a kept rope, a stagebar), it fills with sea. The minimum-to-maximum range of an estimate is sea hatching at 45 degrees, never a second colour.

## Typography

**Display Font:** Google Sans Flex (self-hosted variable, 400 to 650, latin and latin-ext subsets; fallback Inter, Segoe UI, system-ui)
**Body Font:** Google Sans Flex
**Label/Mono Font:** Google Sans Flex for labels; `ui-monospace` only for repository paths in `code`.

**Character:** One geometric-humanist family doing every job, pulled tight at display sizes (-0.04em) and opened wide only for small uppercase labels. Optical size is set explicitly on display (72) and headline (48).

### Hierarchy
- **Display** (600, clamp 2.5 to 4rem, 1.02): the single h1 per page; 15ch in the hero, 18ch on page heads. Page heads use the slightly smaller display-page step.
- **Headline** (600, clamp 2 to 3rem, 1.06): section h2, max 22ch, 1.75rem below. Headline-small (to 2.4rem, 24ch) for paired columns and secondary pages.
- **Pull** (560, clamp 1.625 to 2.25rem, 1.22): one pull line per section at most, under a 2px ink rule. The **statement** step (560, to 1.75rem) plays the same role on sea.
- **Title** (600, 1.375rem, 1.2): h3 inside a section, 3rem above; step titles, phase titles (to 1.75rem), card titles (1.25rem) sit at this level.
- **Lead** (400, clamp 1.1875 to 1.3125rem, 1.58): the first paragraph under a heading, in ink-soft (on-sea on sea).
- **Body** (400, 1.0625rem, 1.65): max 68ch. Captions, notes and meta drop to 1rem, never smaller.
- **Label** (600, 0.8125rem, 0.1em, uppercase, ink-muted): field names in definition lists (duration, estimate, you get, we need), contact group headings, the sources table head. Never placed above a heading.
- **Citation** (600, max(0.7em, 0.75rem), tabular): superscript source IDs after a claim, comma separated.

### Named Rules
**The Figures Are Tabular Rule.** Every number that can sit next to another number (citations, bars, stage facts, axes, source IDs, dates) uses tabular numerals.

**The Floor Is One Rem Rule.** No running text below 1rem; only labels, citations and stagebar ticks (0.8125rem) go under it.

## Layout

A named-line grid does the work on every section: `full | wide (7rem) | col (44rem) | (17rem) | full`, with gutters of clamp(1rem, 4vw, 2.5rem). Reading copy sits in `col`; figures, step lists, card grids, splits and stage ledgers break out to `wide` (68rem). Header, hero and footer share the same 68rem measure. Below 900px the grid collapses to gutter, one column, gutter.

Sections stack with 3rem between children and clamp(4.5rem, 9vw, 8rem) of block padding (tight sections: 2.5 to 4rem). The home order runs paper (problem), sea (how it works), paper (plan), raised (the ask), paper (team and open source, sources), deep (contact), deep footer.

**The hero is split-level.** Its grid has an `air` row (min clamp(27rem, 58svh, 36rem)), a `water` row (clamp(18rem, 46svh, 30rem); clamp(13rem, 56vw, 17rem) on phones) and a `note` row. The CSS sea band covers water and note; the stage spans air and water and fades out over its last 3rem; copy sits bottom-aligned in air, max 41rem; the model caption sits in the note row on plain sea, never over the 3D. The 3D camera reads the band's top to place its horizon and `--stage-focus-x` (0.72 desktop, 0.5 phone) to place the unit across the width. It stands far enough back to hold both the air above the unit (`--stage-air-m`, default 1.3 m) and the depth down to the listening head (`--stage-depth-m`, default 3.1 m). Below 900px the copy moves to its own row above air, so the unit never sits behind text.

Two-up splits (today/next, team/open, contact) use `repeat(2, 1fr)` or 1.5fr/1fr and stack below 900px. Offer cards run 3, 2, 1 columns at 1024 and 640px. Ledger rows with a term column (fixes 10.5rem, facts 13rem, sources 3.5rem/1fr/7.5rem) drop the term column below 640px.

The header is sticky on desktop; below 860px it scrolls away and nav links wrap onto their own row under the wordmark and the compact partner button. Touch targets are at least 2.75rem on every link that stands alone.

## Elevation & Depth

Flat by default. Depth comes from the ground changing (paper, raised, sea, deep), not from lifted surfaces. The page has three shadow uses and no more: the waterline (a 1px inset glint at the top of the hero water band and the sea section), the head viewer's inset hairline on sea, and a soft drop under an offer card on hover.

### Shadow Vocabulary
- **Waterline** (`box-shadow: inset 0 1px 0 rgb(226 240 236 / 0.7)`): the first pixel of a sea band. The deep contact section has none; it continues the sea.
- **Panel hairline** (`box-shadow: inset 0 0 0 1px rgb(245 241 235 / 0.18)`): the 3D stage on sea.
- **Card lift** (`box-shadow: 0 10px 28px -18px rgb(15 23 41 / 0.35)`): offer card on hover only, with the border moving to line-strong.

### Named Rules
**The Waterline Rule.** Sea begins at a thin bright rule. Paper surfaces never carry an edge shadow at rest.

## Shapes

Round where the hand touches, square where the eye reads. Buttons, nav links, the skip link and the stagebar track are full pills (999px). Held containers (offer cards, the limits box, boilerplate, asset thumbs) take 1rem; the 3D head stage takes 1.5rem. Small data marks (bar ends, note ID chips) round at 0.3rem, only on the free end of a bar. Sections, ledgers and figures are square and bounded only by 1px hairlines; the pull line and phase dividers use a stronger rule (2px ink, line-strong). The focus ring rounds at 4px.

The mark is a three-tined spear crossing a waterline: tines and shaft in currentColor, the water stroke in teal and the shaft below it in sea (both sea-accent in the footer).

## Components

### Buttons
Pills set in 600 weight at 1rem, 3rem tall, with an optional 1.125em outline icon after or before the label.
- **Shape:** full pill (999px).
- **Primary:** ink ground, paper text; the one call to partner. Hover shifts to `#1d2a44` and lifts 1px.
- **Secondary:** transparent with a line-strong border; hover fills card white and the border darkens to ink.
- **On sea:** paper ground, sea-deep text, for controls on sea (the explode toggle). Hover goes pure white.
- **Compact:** 2.5rem tall, 0.9375rem text; header and page-head actions.
- **Focus:** 2px ink outline at 3px offset on paper, paper outline on sea, deep and footer.

### Cards / Containers
- **Offer card** (the ask): card white, hairline border, 1rem radius, 1.5rem padding; title, a definition list of label/value pairs, and a mail action pinned to the foot. Lift on hover.
- **Limits box:** the same shell without hover, holding the one paragraph that says what does not work yet.
- **Boilerplate:** the same shell with a copy button; a status line in teal after copying.

### Navigation
Wordmark left (mark plus lowercase "poseidon", 560, -0.04em), four text links in ink-muted at 500 weight, compact primary button right. Current page is ink with an underline at 0.35em offset. Footer repeats the wordmark on sea-deep with the INTRFACE star mark inline in the byline.

### Ledgers
Hairline-ruled rows carry most detail: fixes (term, then claims), ticks (a 0.7rem teal dash per item), facts, Q&A, sources (ID, text and links, checked date) and evidence (claim, repository paths). A targeted source row gets a faint teal gradient; a targeted note gets a teal chip.

### Citations
After a factual sentence, source IDs print as small teal superscript links (sea accent on sea), linking to the page's notes on home and to the sources page elsewhere. The renderer adds them from the claims register; copy never types them.

### Stage phases
Each stage is a ruled row: title with a teal "Stage n:" prefix on the left; on the right, duration and estimate as label/value pairs, a stagebar, the body and an "Ends with" line. The stagebar is a pill track in line, a solid sea segment to the minimum and a hatched sea segment to the maximum, on a shared month axis.

### Figures
Framed top and bottom by hairlines, titled in 1.1875rem 600, captioned in ink-muted at 62ch. The ropes figure draws a hundred droppers on two longlines: kept ropes as sea capsules, lost ropes as bare muted strokes. The output figure is a table of sea bars sized by `--share`, with the value set beside each bar. Every figure names the claim that sources it.

### 3D stages
A poster image fills the stage first; the canvas fades in over 900ms on the out-expo ease once live, and the poster fades out. The hero canvas is transparent and renders twice per frame across a clipping plane at y = 0: clear air above, sea-coloured fog below, so the CSS paper and sea show through and meet the scene at the horizon. The head viewer turns slowly on a sea-panel stage, accepts horizontal drag, and has an explode/assemble toggle (900ms, instant under reduced motion). Model files and visibility rules live in one config; 3D colours shared with CSS are declared beside it.

## Do's and Don'ts

### Do:
- **Do** put every factual sentence in the `claims` block of the locale module with a register entry naming its sources; headings, labels and actions carry no numbers, currency or percentages.
- **Do** keep all copy for a locale in one module (`en.ts`); a Croatian version is a second module of the same shape.
- **Do** state each limit once, where it belongs: under the model it describes, in the limits box, or in the stage it bounds. State deterrence by sound as the research question once on the home page.
- **Do** use contact basic@intrface.eu and nothing else.
- **Do** switch accent to Shallows (#8fd6c9) and focus to paper on any sea ground.
- **Do** break figures, card grids and stage ledgers to the wide column; keep prose in the 44rem column at 68ch.
- **Do** give every loose link a 2.75rem touch target and every figure a caption in ink-muted.

### Don't:
- **Don't** claim efficacy, permits or conformity: no "proven to", "guaranteed", "certified", "CE marked", "fully permitted".
- **Don't** name AI tools or models, or use internal jargon and hype words ("revolutionary", "seamless", "robust", "comprehensive", "leverage").
- **Don't** place Working Teal on a sea ground or Shallows on paper.
- **Don't** add drop shadows to surfaces at rest; depth is the ground changing.
- **Don't** put an uppercase label above a heading; labels name fields and groups only.
- **Don't** box sections or ledgers in cards; hairline rows carry detail.
- **Don't** use a second data colour; ranges are hatched sea.
