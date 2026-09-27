# Development tranche 002: local monitor application

Date: 2026-09-07. Verified working tree on `dev`, based on `da5b22c`. No commit, push, remote deployment, or field operation was performed.

## Delivered scope

The project now has a working local monitor application, not only a replay CLI. This is the software foundation for evidence review; it does not complete the marine product or its production gates.

| Area | Implementation |
|---|---|
| Hub | `apps/trident/`: persistent workspace, private access key, single-owner lock, bounded recording imports, durable processing jobs, restart recovery, paginated evidence, revision-checked append-only observations, source waveform envelopes, and immutable MP4 attachments. |
| API | `apps/aeolus-api/`: loopback FastAPI service, bearer authentication, streamed request limits, strict validation, safe errors, supervised job worker, and authenticated media ranges. Dependencies are locked with uv. |
| Operator UI | `apps/aeolus-ui/`: Next.js/Bun workbench with local session, bounded same-origin API proxy, import/processing flow, recording and event selection, waveform/table, human observations, conflict resolution, video evidence, and explicit provenance/limits. |
| Runtime | `scripts/dev.py` and `Makefile`: locked setup, developer and built-UI modes, configurable loopback ports/workspace, occupied-port refusal, private directory initialization, readiness checks, and cleanup limited to owned process groups. |
| Design record | `PRODUCT.md`, `DESIGN.md`, and `.impeccable/design.json`: documented product boundaries and observed interface tokens/components. These are not claims of field validation. |

The [monitor contract](../development/monitor-api-contract.md) defines the interfaces and limits. The original replay/evidence schema remains compatible. New monitor tasks 132–135 are separate from the production field/output gates; uncertainty about deterrence must not block offline monitor development.

## Reproducible commands

```sh
make setup
make check
make test
make build-ui
make serve API_PORT=8181 UI_PORT=3100 DATA_DIR=.local/monitor-app READINESS_TIMEOUT=90
```

Stop the dev server before building. For source development use `make dev` with the same overrides. Obtain a key only on explicit operator request:

```sh
make token DATA_DIR=.local/monitor-app
```

The key is not included in this report, generated HTML, screenshots, or committed configuration. Local single-operator key authentication is not production RBAC, certificate provisioning, or remote device authorization.

## Test evidence

| Check | Observed result |
|---|---|
| `make setup` | Frozen uv and Bun dependencies resolved; existing installations required no changes in the final setup run. |
| `make check` | Task graph validation, generated task consistency, Python compilation, and actual `tsc --noEmit` passed. |
| `make test` | 138 tests passed: 11 task-tooling, 31 acoustic replay, 25 hub, 20 launcher, 40 API, and 11 UI helper tests. |
| Python versions | Standard-library suites were exercised on Python 3.11.15 and 3.14.7. The final combined API suite used its locked Python 3.11 environment. The CI matrix covers both versions but was not run remotely. |
| API warnings | Two upstream TestClient deprecation warnings remain: httpx transport and the AnyIO BlockingPortal alias. They were not suppressed or counted as failures. |
| `make build-ui` | Next.js 16.3.4 created the optimized bundle, passed TypeScript, and emitted `/`, the not-found page, session route, and backend proxy route. This was an actual build, not a help-command exit. |
| Built-mode health | API `/healthz` and the built operator page returned HTTP 200. |
| Built browser smoke | Actual login, event selection, waveform, complete identifiers, mobile containment, and the first-body design contract comment passed without page runtime errors. The browser closed afterward. |
| Repository hygiene | `git diff --check` passed. No unrelated listener was stopped. |

The 138 count is distinct automated tests, not doubled for repeated interpreter runs. Browser acceptance and restart checks are additional integration evidence, not included in that count.

## Real browser acceptance

The bounded browser flow used the running API, real Hub storage, and clearly marked synthetic fixtures. It passed:

- **BQA1:** bad-key rejection followed by valid unlock; protected data was not treated as loaded before authentication.
- **BQA2:** synthetic demo submission, terminal job status, and a genuine browser multipart WAV/manifest import under a separate synthetic recording identity.
- **BQA3:** recording/event selection, source-derived waveform, interval highlighting, and accessible waveform data.
- **BQA4:** saved observation verified after reload and reselection.
- **BQA5:** a concurrent update caused HTTP 409 while preserving the draft. The UI showed both draft and complete server review; another update caused another 409. Explicit overwrite then persisted revision 6.
- **BQA6:** silent synthetic MP4 attachment, declared alignment offset, authenticated Range delivery, and browser decoding.
- **BQA7:** logout denied subsequent cookie-authenticated data access.
- **BQA8:** simulated browser-network failure and recovery. This is not a tested 4G outage, gateway failure, or field-connectivity claim.

The initial QA authentication helper had a race and skipped the key form before it appeared. That test defect was corrected; it was not bypassed. Live socket testing then exposed a real same-origin bug caused by Next's internal `localhost` URL. The application now validates the actual loopback Host and matching origin/port. Matching legitimate hosts reach authentication; external or mismatched origins are rejected. An independent socket check verified the HttpOnly, SameSite=Strict cookie and logout behavior without printing the key.

Local screenshots/results are under `apps/aeolus-ui/qa/artifacts/`, including the `aeolus-reviewer-confirmation-*` captures and result JSON. They contain synthetic data. The QA runner has a hard timeout and closes its browser in `finally`; no QA browser was left running.

Homebrew ffmpeg on this machine failed because of a missing x265 library. The QA fixture generator used macOS AVFoundation to produce a silent synthetic MP4 instead. No camera capture or global Homebrew repair occurred. The application itself does not require that fixture-generation fallback.

## Independent UI review

The packaged finish-reviewer reference was unavailable. A fresh, read-only reviewer inspected screenshots and source against the written direction; it did not inherit the build thread or rerun the reported functional tests.

| Finding | Final verdict | Accepted correction |
|---|---|---|
| UX1 | Resolved | Mobile chart has contained horizontal scrolling, readable 16-unit labels on a minimum 760px canvas, a visible scroll instruction, and an adjacent accessible table. |
| UX2 | Resolved | Conflict recovery shows the complete latest server review and preserved draft. Actions state and perform replacement or explicit overwrite against the displayed revision. |
| UX3 | Resolved | Full event, recording, run, and video SHA-256 values are selectable, wrap on mobile, preserve case, and do not depend on hover. |

Final reviewer verdict: **PASS**. One mechanical detector pass produced a grid-background advisory on access/empty-inspector surfaces; the reviewer judged it non-material in this inspection-workbench context. It was not represented as a clean detector result.

The design seed `326c98b2` survives in the built HTML's inline contract script. A real browser verified that the resulting design comment is the body's first child. Static-comment-only inspection would not detect this runtime insertion.

## Restart and data preservation

A private checkpoint recorded two recordings, four candidate events, one latest review, the jobs, video metadata, and an access-key digest. It stored no raw key.

The managed development pair was stopped. Both owned listeners disappeared; the unrelated process on port 3000 remained. The built UI and API were then started on 3100/8181 against the same workspace.

Post-restart checks confirmed:

- **RST1:** exact recording/event/review/job/video metadata equality with the checkpoint.
- **RST2:** unchanged access-key digest.
- **RST3:** stored video bytes matched the recorded SHA-256, and an authenticated `bytes=0-15` request returned 206 with the expected range and length.
- **RST4:** built-mode browser login and evidence inspection worked after restart.

The restart probe initially treated TCP TIME_WAIT as a live listener. It now uses `SO_REUSEADDR` for its ephemeral bind probe and has real occupied-listener and close/rebind regressions. The launcher also handles SIGTERM, exited process-group leaders, and missing workspace parents. These changes do not relax Hub ownership or unrelated-file safeguards.

## Corrections made during integration

The final acceptance included fixes for clean-checkout workspace initialization, process cleanup, origin normalization, oversized integer input, mobile chart labels, revision comparison, complete identifiers, and Bun command argument order. In particular, `bun --cwd ... run ...` printed help and exited zero on this installed Bun; recipes now use `bun run --cwd ...`, and the final run visibly executed the tests, typecheck, and build.

## Completion boundary

Tasks 132–135 can be marked done for this local monitor tranche. Their completion does not complete production tasks 114–129 or prove biological efficacy.

Still required for the full product: authorized local datasets and validated detection, live acquisition and camera synchronization/wiper support, REEF firmware and solar behavior, AQUILON/LoRaWAN integration, production cloud/device security and signed updates, editable mechanical/electrical fabrication packages, physical prototypes and calibration, ecological trials, EU conformity, manufacturing validation, deployment/service procedures, and funded support. Active acoustic work remains separately gated; flora work remains research-only until supported.

No field capture, underwater emission, hardware procurement, CAD fabrication, firmware flashing, ecological approval, conformity assessment, manufacturing qualification, external hosting, remote CI run, commit, or push is claimed by this tranche.
