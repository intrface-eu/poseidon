# AEOLUS platform workflows

The existing daylight evidence workbench now exposes additive local platform APIs. The candidate inspector, WAV/manifest intake, source-derived waveform, optional video and revision-checked candidate reviews remain separate from independent observations. No output, capture, field enrollment, installation or flashing control was added.

## Operator paths

| Section | What it does | Boundary |
|---|---|---|
| Evidence review | Existing recordings, candidates, import, waveform, video and candidate review | Legacy unbound import/demo requires the local development key. Scoped reviewers/admins may review or attach evidence only where the API grants scope. |
| Observation intervals | Select any recording, create or revise a half-open recording-relative interval, inspect waveform and ascending history | No candidate is required. Authenticated actor, declared observer and immutable source hash stay separate. A 409 retains the draft and requires an explicit comparison/resolution. |
| Devices & telemetry | Inspect registry records, register synthetic/bench identities, revoke a device, inspect exact stored telemetry and AQUILON mappings | Registration is not connection health. No default fleet or generated readings. Only admins or the matching device may read mappings; mapping writes are immutable. |
| Acquisition sessions | Declare source/clock metadata, inspect sessions, bind a selected recording once | Binding unbound legacy data requires the development key. Clock relations name both domains; no offset implies verified UTC. |
| Identity & access | Inspect current identity, issue scoped tokens, rotate/revoke principals | API authorization remains authoritative. New token displays are transient, shown only after an API acknowledgment, and cleared on dismissal, section change or page hide. |
| Audit trail | Read scoped actor-stamped audit records | Admin-only; no credentials in audit detail. |
| Signed local lifecycle | Store public trust keys, create local test targets, stage signed artifact bytes, activate a trial, declare local test health, roll back/recover, inspect history | Simulation only. No private-key entry, signing endpoint, execution or physical command. Trust-root mutation requires the local development key. |

Independent review context can include protocol ID, evidence references, visibility, synchronization uncertainty and a declared independently reviewed coverage flag. Missing context remains unknown, not scoreable exposure. Neither a label nor a coverage checkbox certifies an evaluation protocol or ground truth.

Acquisition session forms offer unknown or operator-declared clock quality. An optional advanced clock-relation JSON field accepts the exact versioned relation shape. Measured/shared-clock relations require an evidence reference at the API. Existing source sidecars are not rewritten or claimed to have been fully ingested.

Telemetry is a receipt table rather than a live-health chart. Units, measurement quality, calibration references, source, receipt time and raw radio claims remain inspectable. Boot IDs remain canonical uint64 decimal strings, including values above JavaScript's safe integer range. Unknown clocks do not acquire an invented observation timestamp. Digital RMS remains normalized PCM16 full-scale, never underwater SPL.

## Session and proxy

`POST /api/session` validates `/api/v1/identity`, including device identities that cannot use the evidence monitor. It stores the supplied credential only in the HttpOnly, SameSite=Strict session cookie. The current subject, role, authentication mode, site scope and optional device binding appear in the workbench.

`/api/backend/...` remains an explicit method/path/query allowlist. Mutations require same-origin checks; backend authorization independently enforces scope. All proxy responses use `Cache-Control: no-store`. Normal platform JSON bodies are bounded to 64 KiB, telemetry to 16 KiB, lifecycle staging to 1536 KiB including base64, and existing multipart uploads keep their development limit. Lifecycle lists accept no query filters. Unsupported commands, arbitrary URLs, paths and verbs are not forwarded.

One-time tokens are not stored in local/session storage, rendered in server HTML, copied to logs, or included in screenshots. Token creation/rotation responses live only in the mounted client component; public principal lists contain no secret. Provisioning test credentials does not authorize enrolling physical devices.

## Verification commands

Run the unit/contract/render suite with:

```sh
bun run --cwd apps/aeolus-ui test
```

The platform browser runner starts its own frozen Python API and built Next server on checked-free loopback ports, creates an owned temporary Hub workspace, and reads only that new workspace's key. It closes the browser in `finally`, applies a 300-second browser deadline and 330-second process-group hard timeout, reaps only its own process groups and removes its temporary workspace. It never starts a persistent service.

```sh
PLATFORM_QA_ARTIFACTS=.local/platform-ui-evidence \
  python3 apps/aeolus-ui/qa/run-platform-qa.py
```

Build the current bundle before running this command, within the controller-granted frontend slot. `next.config.ts` explicitly sets the monorepo root so Turbopack can bundle `libs/proto-ts`.

The browser script drives real APIs through real UI forms. Its fixtures are synthetic: PCM16 silence with zero candidates, declared observation intervals, test registry identities, synthetic telemetry, and non-executable artifact bytes signed with an ephemeral test key. Secret display states use assertions, not screenshots or traces. The script preserves failures and lists completed checks; a partial run is not reported as a pass.

### Legacy candidate-review and video gate

Run this separate mode from the repository root; the default platform checks are not legacy proof:

```sh
env -u PLATFORM_QA_RESIDUAL_ONLY -u PLATFORM_QA_REMAINING_ONLY \
  PLATFORM_QA_LEGACY_ONLY=1 \
  PLATFORM_QA_ARTIFACTS=.local/legacy-proof \
  python3 scripts/assurance/run_command.py --timeout 480 --term-grace 20 \
  --cwd . -- python3 apps/aeolus-ui/qa/run-platform-qa.py
```

The result identifies `suite: legacy-candidate-review-video`. It covers real demo candidates, waveform rendering and table row count with exact first/last-row comparisons, candidate-review save/reload and repeated 409 draft resolution, declared reviewer versus authenticated `review.save` audit actor, MP4 attachment, unverified offset labels, decoding/playback/seek, exact full/Range bytes, and media denial after logout. Persistence checks use reload/refetch, not service restart.

The mode reuses `apps/nereid/fixtures/recorded-codec-wave2/input/synthetic.mp4` and its declaration/recipe. It checks the source hash and video-only track, then keeps playback muted with volume zero. No capture, external media, speaker output, codec generation or global repair runs. Use a fresh artifacts directory and the existing project-pinned Chromium installation; no app rebuild is needed for QA-only changes.

## Open gates

These workflows do not complete production authentication, deployment security, acquisition-sidecar ingestion, field permission, calibration, verified synchronization, hardware health, bootloader qualification or biological validation. Existing legacy candidate import/video browser paths require their own regression run when that scope changes. The platform browser script is not physical or field evidence.
