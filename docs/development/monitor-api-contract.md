# Local monitor application contract v1

Implementation contract for the next development tranche, 2026-09-07. This is local, monitor-only software, not a field-deployment or acoustic-output authorization. Existing replay schemas and SQLite evidence remain compatible. Physical, scientific, compliance, and production gates remain open; they do not block synthetic/offline monitoring software.

## Components and ownership

- `apps/trident/src/poseidon_trident/`: standard-library hub and durable workspace; no HTTP or device control.
- `apps/aeolus-api/src/poseidon_api/`: FastAPI adapter and one background job worker.
- `apps/aeolus-ui/`: Next.js/TypeScript with Bun; same-origin authenticated server proxy to the API.
- The existing `poseidon_proto` models and `poseidon_acoustic` replay pipeline remain the source of recording and candidate semantics.
- Python source roots: `libs/proto-py/src:apps/acoustic/src:apps/trident/src:apps/aeolus-api/src`.

## Runtime boundary

API and UI bind to loopback by default. No emit/arm/relay/kill-switch endpoint exists. `emission_enabled` is always false; this is absence of output capability, not verified physical safety hardware. No network broker, field sensor, camera capture, external upload, automatic deployment, or hidden sample fleet is introduced.

A persistent hub workspace contains a private `access.token` file, hub metadata/job/review database, existing-format acoustic evidence database, and immutable recording/media directories. Do not add tables to the original evidence database. Reuse its replay transaction/idempotency semantics. Reject unrelated stores, unsafe paths, and unexpected existing files rather than overwriting them.

One process owns a workspace at a time. A lock prevents concurrent hub owners. Interrupted processing is recoverable after restart. Every SQLite connection/file/worker is closed. Input failures must not replace existing evidence or leave a successful job claim.

## Python Hub interface

`from poseidon_trident import Hub, HubError`

`Hub(data_dir: Path | str)` initializes a private workspace or opens a compatible existing one; context manager and `close()` release its ownership. `HubError` exposes `code: str`, `message: str`, `status_code: int`; no raw traceback or secret appears in HTTP responses.

Methods (thread-safe with short-lived SQLite connections):

- `access_token() -> str`: token is generated once with restrictive file permissions, never logged or returned by an HTTP endpoint.
- `status() -> dict`: status shape below.
- `submit_recording(wav_stream, manifest_bytes: bytes) -> dict`: bounded stream import, strict manifest/hash/header checks and atomic source preservation, returning a job. Repeated identical import reuses its identity; a conflicting recording ID is HTTP 409.
- `submit_demo() -> dict`: reuse the existing marked synthetic demo; submit through the same import path. Repeated loading does not invent additional field records.
- `process_next_job() -> bool`: atomically claim one queued job, run existing replay, record result or an actionable failure, and return whether a job was processed. No exception may silently kill the API's worker loop.
- `get_job(job_id) -> dict`; `list_jobs(limit=20, offset=0) -> page`.
- `list_recordings(limit=50, offset=0) -> page`; `get_recording(recording_id) -> dict`.
- `list_events(recording_id=None, review=None, limit=50, offset=0) -> page`; `get_event(event_id) -> dict`.
- `save_review(event_id, label, notes, reviewer, expected_revision) -> dict`: atomic optimistic revision check; preserve append-only review history. No destructive delete endpoint.
- `waveform(recording_id, points=512) -> dict`: bounded downsampled min/max envelope from the original recording. No audio playback or inferred biological frequency.
- `attach_video(recording_id, video_stream, offset_s=0.0) -> dict`: bounded MP4 evidence attachment with hash, safe stored filename, and an explicitly declared alignment offset. Basic container/type checks are not proof that every browser can decode it. Reject replacement rather than silently overwriting a prior attachment.
- `video_path(recording_id) -> Path`: trusted internal accessor for an authenticated streaming response; not a client-supplied server path.

If a method's contract cannot be met, report it to the controller before changing the interface. Do not independently rename response fields.

## JSON shapes

All timestamps are UTC RFC3339 strings. All input numbers must be finite and correctly typed; booleans are not integers. Identifiers retain existing strict safe-ID rules. No filesystem path or token is exposed in API JSON.

`page`: `{ "items": [...], "total": 0, "limit": 50, "offset": 0 }`.

`status`: `{ "mode": "monitor_only", "emission_enabled": false, "state": "ready", "uptime_s": 0.0, "recordings": 0, "events": 0, "jobs": { "queued": 0, "running": 0, "failed": 0 } }`. Counts reflect stored software data, not connected hardware or biological outcomes.

`job`: `{ "id": "job_...", "status": "queued|running|succeeded|failed", "recording_id": "...", "created_at": "...", "updated_at": "...", "error": null }`. Errors are safe messages. A failed job does not appear as a successfully imported recording. Queue/restart behavior is testable, not an in-memory-only promise.

`recording`: all existing manifest fields plus `duration_s`, `sample_rate_hz`, `channel_count`, `event_count`, `reviewed_count`, `imported_at`, and `video`.

`video`: null or `{ "sha256": "...", "offset_s": 0.0, "uploaded_at": "...", "alignment": "operator_declared" }`. Camera evidence may be absent; no thumbnail or synchronization claim is fabricated.

`event`: the existing acoustic-candidate JSON with one additive `review` field (null or the latest review). GET event detail returns `{ "event": <event>, "recording": <recording> }`.

`review`: `{ "label": "confirmed_feeding|non_feeding|uncertain", "notes": "...", "reviewer": "...", "revision": 1, "updated_at": "..." }`. Labels are human-entered observations, never detector conclusions. Synthetic provenance remains visible regardless of label. Initial expected revision is 0; a stale revision is 409. Limit notes to 2000 characters and reviewer to 80; notes are required for confirmed-feeding labels. The reviewer name is operator-entered, not identity attested by a multi-user account system.

`waveform`: `{ "recording_id": "...", "duration_s": 0.2, "sample_rate_hz": 8000, "channel_count": 1, "amplitude_units": "normalized_pcm16_full_scale", "calibration_status": "uncalibrated", "buckets": [{ "start_s": 0.0, "end_s": 0.01, "min": -0.6, "max": 0.6 }] }`. Envelope combines extrema across channels and must be labeled accordingly. Point count 16–2048. All chart data is from this endpoint, with an accessible table alternative.

## HTTP API

Prefix `/api/v1`. All routes below require `Authorization: Bearer <workspace token>` except GET `/healthz`, which returns liveness only. Constant-time token comparison; secrets are never reflected.

| Method and path | Request | Response |
|---|---|---|
| GET `/healthz` | None | 200 `{ "status": "ok" }` |
| GET `/api/v1/status` | None | 200 status |
| POST `/api/v1/recordings` | Multipart `wav` file and `manifest` file | 202 job; invalid input 400/413, identity conflict 409 |
| POST `/api/v1/demo` | Empty body | 202 job, explicitly synthetic |
| GET `/api/v1/jobs` | `limit`, `offset` | 200 page |
| GET `/api/v1/jobs/{id}` | None | 200 job or 404 |
| GET `/api/v1/recordings` | `limit`, `offset` | 200 page |
| GET `/api/v1/recordings/{id}` | None | 200 recording or 404 |
| GET `/api/v1/events` | Optional `recording_id`, `review` (`unreviewed` or a review label), `limit`, `offset` | 200 page |
| GET `/api/v1/events/{id}` | None | 200 event detail or 404 |
| PUT `/api/v1/events/{id}/review` | JSON `label`, `notes`, `reviewer`, `expected_revision` | 200 review or 409 |
| GET `/api/v1/recordings/{id}/waveform` | Optional `points` | 200 waveform |
| POST `/api/v1/recordings/{id}/video` | Multipart `video`, numeric `offset_s` | 201 video metadata; existing attachment 409 |
| GET `/api/v1/recordings/{id}/video` | Optional HTTP Range | Authenticated video/mp4 response or 404 |

Errors: `{ "error": { "code": "...", "message": "..." } }`. Enforce validation at the public HTTP boundary as well as in Hub. Pagination maximum 200, offset nonnegative. Reject unknown query enum values. No permissive CORS, filesystem-path import, shell command, arbitrary URL fetch, or external proxy endpoint.

Development resource limits: WAV/video maximum 64 MiB each, manifest maximum 16 KiB, WAV duration maximum 1800 seconds, 32 queued/running jobs maximum. These are software limits, not selected acquisition parameters. Bound actual streamed bytes, not only Content-Length. Reject unsupported compressed/width/channel WAV formats consistently with the existing replay implementation. No automatic cleanup of user data when a quota or import fails.

## UI session and proxy

Next.js uses a server-only `POSEIDON_API_URL`, default `http://127.0.0.1:8080`. Never expose it as a user-controlled open proxy.

- POST `/api/session` accepts `{token}`; validates it against backend status before issuing an HttpOnly, SameSite=Strict cookie with a bounded lifetime. Use Secure for HTTPS. Never store the token in localStorage or embed it in rendered HTML.
- DELETE `/api/session` clears the cookie.
- `/api/backend/...` forwards only the known API paths/methods, using that cookie as backend authorization. Validate same-origin on mutations, disallow arbitrary target hosts, strip unsafe forwarded headers, and preserve safe content types/statuses. Stream video and multipart bodies with bounded sizes; do not load a full video into JSON or log tokens.
- No logged-in state or success toast before a real backend acknowledgement. Handle expired/missing keys, offline API, timeouts, 409 conflicts, malformed upload, and restart.

This is a local single-operator development session, not production RBAC, Internet hosting, or completed device provisioning.

## Verification and delivery

Core: unittest in `tests/trident/`. API: tests in `tests/api/` using its locked dev dependencies. UI: Bun typecheck/build and browser QA against the real API, not a mock-only page. Test fresh empty state, unlock failure/success, synthetic import, queued-to-complete refresh, recording selection, waveform, review save/reload, stale-revision rejection, genuine file upload, optional video/error state, API-offline recovery, and desktop/mobile layout.

Browser scripts close their browser in `try/finally` and run under a hard timeout. Limit visual review to one batched desktop/mobile pass, one grouped fix pass, and one confirmation pass. No stakeholder contact, purchase, remote deployment, commit, or push is part of this tranche.
