# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js, React, and TypeScript, managed and run with Bun. The app talks to the local FastAPI service only through a same-origin server proxy.

## Users

The product is being built by a solo operator in stages for an EU/EEA-first marine platform focused initially on Limski kanal/zaljev, Croatia, with orada as the target predator. The expected scientific identification, gilthead seabream (*Sparus aurata*), still needs confirmation with the farm and ecology partner.

[Inferred from the settled implementation brief] The first web-app user is that same solo operator working at a desk to import recordings, monitor local replay jobs, inspect candidate events, attach optional video evidence, and record a human review.

## Product Purpose

Poseidon is a staged marine monitoring platform. Its first software slice supports local, passive review of declared WAV recordings and clearly marked synthetic fixtures. It preserves provenance, exposes candidate acoustic events, and records operator observations without claiming species identification, confirmed feeding, deterrence, stock-loss prevention, calibrated underwater sound pressure, or field readiness.

Success for this tranche means one operator can authenticate to a local workspace, submit valid evidence, follow processing to a terminal state, find and inspect events, view the source-derived normalized waveform, and save a revision-checked review.

## Positioning

The operator workbench keeps every event tied to its recording, source provenance, calibration status, detector run, review revision, and optional operator-declared video offset. It treats candidate detection and human observation as separate records instead of turning replay output into a biological claim.

## Operating Context

- The current workflow is local and monitor-only. The API and web app bind to loopback by default.
- The current evidence source is a declared WAV plus a strict manifest, or the repository's deterministic synthetic demo.
- [Inferred] Review happens as a focused desk workflow: inspect the queue, select a recording or event, compare the event interval with the all-channel peak envelope, then enter a label, notes, and reviewer name.
- Limski zaljev is a protected marine reserve. Site access, collection, installation, research, and any acoustic activity remain subject to separate evidence and permissions.
- The broader platform is planned in stages for passive monitoring first. Active output, field hardware, fleet operations, and production release remain later gated work.

## Capabilities and Constraints

- Local access uses a workspace token stored only in an HttpOnly, SameSite=Strict session cookie. The browser does not receive the backend URL or retain the token in local storage.
- The web app may load the marked synthetic demo or import one WAV and one manifest. It polls real jobs until they succeed or fail.
- Recordings and events are paginated. Events can be filtered by recording and review state.
- Event detail uses the API waveform endpoint's bounded min/max buckets. Values are normalized PCM16 full-scale amplitude, combine extrema across all channels, and are not SPL.
- Human labels are `confirmed_feeding`, `non_feeding`, or `uncertain`. They are operator-entered observations, not detector conclusions. Confirmed-feeding reviews require notes.
- Reviews use optimistic revisions and preserve server history. A stale edit must not overwrite a newer review.
- One optional MP4 can be attached to a recording with an operator-declared offset. Container checks and browser playback do not verify alignment or decode support.
- The current app has no emit, arm, relay, device-control, field-capture, fleet-map, customer, cloud-upload, or hardware-status capability. `emission_enabled` remains false.
- Empty, offline, unauthenticated, loading, malformed-input, timeout, conflict, and retry states are part of the product, not demo-only exceptions.
- Development limits include 64 MiB each for WAV and video, 16 KiB for a manifest, 1,800 seconds per WAV, and 32 queued or running jobs.

## Brand Commitments

Use the Poseidon and AEOLUS names. The voice is precise, restrained, and explicit about what the evidence does and does not establish. Do not turn the marine subject into decorative ocean imagery or imply active protection capability.

## Evidence on Hand

- Frozen local monitor contract: `docs/development/monitor-api-contract.md`.
- Passive replay rules and manifest schema: `docs/development/passive-replay.md`.
- Active production requirements and gates: `docs/requirements/production-requirements.md`.
- Staged product scope and Lim Bay prior-trial record: `docs/production-roadmap.md`.
- Deterministic synthetic WAV generator and acoustic candidate models under `apps/acoustic/` and `libs/proto-py/`.
- No field recording, calibrated receive chain, customer evidence, fleet data, connected hardware, production API deployment, or validated biological performance is available to present as fact.

## Product Principles

1. Keep provenance and calibration limits visible wherever evidence is interpreted.
2. Separate machine-found candidates from human-entered observations.
3. Show real backend state, including emptiness and failure, rather than inventing operational data.
4. Preserve the local, monitor-only boundary and expose no implied output control.
5. Favor a compact record-review workflow over status theater or marketing claims.

## Accessibility & Inclusion

The operator app must support keyboard navigation, visible focus, explicit labels, daylight-readable contrast, responsive desktop and mobile layouts, and non-hover access to every waveform value through an accessible table.
