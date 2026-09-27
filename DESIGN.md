---
name: AEOLUS Operator Workbench
description: A daylight evidence-inspection interface for passive acoustic review.
colors:
  canvas: "#e9eeec"
  canvas-deep: "#dde5e2"
  surface: "#f7f9f8"
  paper: "#ffffff"
  ink: "#182321"
  ink-soft: "#34433f"
  muted: "#586864"
  faint: "#74827f"
  line: "#cbd5d2"
  line-strong: "#9eaeaa"
  accent: "#008aa6"
  accent-dark: "#00677c"
  accent-wash: "#e0f3f6"
  accent-ink: "#004f60"
  warning: "#9d5c00"
  warning-wash: "#fff2d7"
  danger: "#a13a32"
  danger-wash: "#fff0ee"
  success: "#34715d"
  success-wash: "#e8f4ef"
typography:
  display:
    fontFamily: "ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
    fontSize: "2rem"
    fontWeight: 700
    lineHeight: 1.08
    letterSpacing: "-0.035em"
  headline:
    fontSize: "1.08rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.012em"
  title:
    fontSize: "0.9rem"
    fontWeight: 700
    lineHeight: 1.2
  body:
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
  label:
    fontSize: "0.77rem"
    fontWeight: 700
    letterSpacing: "normal"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.68rem"
    fontWeight: 400
rounded:
  tag: "2px"
  control: "3px"
spacing:
  space-4: "4px"
  space-8: "8px"
  space-12: "12px"
  space-16: "16px"
  space-24: "24px"
components:
  button-primary:
    backgroundColor: "{colors.accent-dark}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 14px"
  field:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "8px 10px"
  state-tag:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-soft}"
    rounded: "{rounded.tag}"
    padding: "2px 6px"
---

# Design System: AEOLUS Operator Workbench

## Overview
**Creative North Star: "Quality-control inspection traveler"**

This provisional system documents the shipped operator UI. It uses daylight off-white and cool-gray surfaces, graphite text, one measured teal accent, thin solid rules, compact records, and native controls. Information stays tied to its source, state, and revision instead of becoming decorative dashboard summaries.

**Key Characteristics:**
- Dense, readable inspection layouts with restrained hierarchy.
- Teal reserved for selection, focus, and primary action.
- Provenance, calibration, identifiers, and revisions remain visible.
- Empty, loading, error, disabled, and conflict states use the same visual grammar as steady state.

## Colors
The palette is cool, low-chroma, and built for daylight legibility.
### Primary
- **Measured teal:** The `accent` family marks selected records, waveform evidence, focus, and primary action.
### Secondary
- **Evidence states:** The `success`, `warning`, and `danger` families distinguish accepted, uncertain, and failed states without replacing text labels.
### Neutral
- **Inspection neutrals:** `canvas`, `surface`, and `paper` separate layers; `ink`, `muted`, `line`, and their stronger or softer variants carry hierarchy and rules.
**The Measured Accent Rule.** Teal identifies action or evidence state; it does not fill large decorative areas.

## Typography
**Display Font:** System UI sans serif
**Body Font:** System UI sans serif
**Label/Mono Font:** System monospace for full identifiers; system UI for labels
**Character:** Compact and procedural. Small labels, tabular numerals, and full-value identifiers favor scanning and comparison over display styling.
### Hierarchy
- **Display:** The `display` role is limited to access-state page titles.
- **Headline:** The `headline` role titles workbench panels.
- **Title:** The `title` role separates inspection blocks.
- **Body:** The `body` role carries instructions and state text; explanatory copy is capped at 65ch where implemented.
- **Label:** The `label` role names fields and ledger values; table and status numerals use tabular figures.

## Layout
The desktop workbench uses a 246px recording rail, a flexible event register, and a larger evidence inspector with 12px gaps. At 1320px the inspector moves below the two-column register; at 980px sticky rails release and intake fields reflow; at 720px the interface becomes one column and dense rows become compact two-column records.
On screens up to 720px, the waveform shows a scroll cue and keeps a 760px inspection canvas inside horizontal overflow. Its accessible data table stays available in a disclosure, scrolls independently to 300px, and keeps the header row visible.

## Elevation & Depth
Surfaces are flat and separated by tonal layers and 1px rules. Shadows are limited to the access panel (`0 10px 26px rgba(24, 35, 33, 0.09)`), sticky header (`0 5px 16px rgba(24, 35, 33, 0.06)`), and waveform tooltip (`0 5px 14px rgba(24, 35, 33, 0.12)`); selected rows use a 3px inset teal edge.

## Shapes
Controls use restrained 3px corners, tags use 2px corners, and panels remain square. Circular geometry appears only in 7px state dots. Borders, not rounded cards, define the inspection traveler.

## Components
### Buttons and Fields
- Primary buttons use dark teal, 38px minimum height, and a 160ms color transition. Secondary buttons stay white and gain a teal wash on hover. Every native control uses the shared 3px focus shape and a 3px translucent teal outline on `:focus-visible`.
- Inputs, selects, and text areas use white fill and a strong neutral rule. Disabled controls retain their layout and drop to 0.58 opacity.
### Tags, Registers, and Ledgers
- Tags are compact uppercase stamps. Provenance and review variants always pair color with text.
- Selected recording and event rows use the accent wash plus an inset 3px leading edge. Full recording, run, event, and SHA-256 values use selectable monospace text with wrapping; measurements use tabular numerals.
### Waveform Evidence
- The envelope uses a translucent teal fill with a 2px teal stroke. The candidate interval adds a pale hatched window and dark teal edges. Pointer and keyboard inspection expose exact bucket values; the table prints start, end, minimum, and maximum values to six decimals.
### Revision Conflict
- A warning message preserves the draft and compares it with the latest server review in two ruled columns. At 720px the columns stack, the divider moves to the top, and both resolution actions become full-width rows.

## Do's and Don'ts
### Do:
- **Do** keep source identifiers, calibration limits, normalized units, and review revisions next to the evidence they qualify.
- **Do** preserve text labels alongside every status color and keep exact values selectable or available in a table.
- **Do** keep the 720px waveform scroll and stacked conflict behavior when composing narrower surfaces.
### Don't:
- **Don't** add decorative marine imagery, oversized metric cards, gradients, or broad accent fills to this provisional system.
- **Don't** present normalized waveform values as SPL or turn candidate and human-review states into one claim.
- **Don't** hide conflict, error, empty, loading, disabled, or provenance states to simplify a screen.
