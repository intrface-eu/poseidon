# Companion-aware recording intake v1

Implementation contract for reviewed platform tranche 2. Existing v1 recording/event files, evidence.sqlite3 and two-file import remain unchanged. This file defines transport and storage projection only; the Acquisition-owned pure export reader is the scientific validation authority. No live/device/codec operation is added.

## Write transport

`POST /api/v1/acquisition-sessions/{platform_session_id}/recordings` accepts exactly seven multipart FILE parts, no scalar fields: `wav`, `manifest`, `binding`, `source_receipt`, `source_header`, `source_final`, `export_receipt`. Each part has its original flat export basename. The reader must find exactly one selected export and all six files named by its export receipt; the receipt is the seventh file. Reject extra/duplicate/missing names, paths, archives, multi-export packages and unknown roles. Filename metadata is never a server filesystem path.

Authorize the existing target session before substantive parsing. Only admin credentials may submit; scoped admins are limited to their assigned site. Revalidate principal, session, registered device and source-snapshot binding at commit. Keep the original import/demo development-only. Return the existing 202 job object after complete commit, including for an exact qualified retry. No partial success or fallback to the old import route.

Hub mechanical entry point:

```
submit_recording_with_companions(
    wav_stream, manifest_bytes, companions_by_role,
    *, session_id, filenames_by_role,
) -> existing job dict
```

`companions_by_role` contains the five exact raw JSON byte values. `filenames_by_role` contains all seven original basenames. Both mappings have exact key sets. The backend constructs an in-memory/bounded staged-file resolver for the upstream reader; it never follows metadata paths or reimplements scientific projections.

The reader interface coordinated with Acquisition is:

```
validate_export_bundle(export_receipt_bytes, resolver, *, limits)
resolver(name: str, max_bytes: int) -> bytes
```

Frozen mechanical interface: import `ExportReadLimits`, `ExportReadError`, `ValidatedExport`, `VerifiedExportFile`, `validate_export_bundle` and `file_map_resolver` from `poseidon_acoustic.legacy_export_reader`. `file_map_resolver(files: Mapping[str, bytes])` snapshots exactly the six safe-basename/raw-byte entries; the receipt is passed separately. Pass `limits=ExportReadLimits()` (its frozen defaults match the part and aggregate caps below). `ExportReadError` is a `ValueError` subclass.

`ValidatedExport` fields are `manifest: RecordingManifest`, `capture_session_id`, `source_id`, `selected_index`, `header_sha256`, `final_sha256`, `export_receipt_sha256`, `files: tuple[VerifiedExportFile, ...]`, and `projection_bytes: bytes`. Its `file_for_role(role)` returns a frozen file record with `role`, `name`, `size`, `sha256`, `data: bytes`. The files cover all seven roles. The projection is immutable canonical JSON with source/mapping/time/provenance/discontinuity and fixed unverified coverage. Positive acceptance must wait for the actual reader implementation/test-ready notification; a frozen signature is not evidence of a working validator, and no stub may substitute.

## Ratified limits

| Item | Bytes/count |
|---|---:|
| wav | 8388608 |
| manifest | 16384 |
| binding | 262144 |
| source_receipt | 16384 |
| source_header | 1048576 |
| source_final | 2097152 |
| export_receipt | 65536 |
| aggregate companions | 4194304 |
| multipart overhead | 262144 |
| total actual request bytes | 12861440 |
| file parts / scalar fields | 7 / 0 |
| simultaneous new-route admissions per Hub | 2 |
| queued + running + preparing slots | 32 |
| retained + reserved companion logical bytes | 268435456 |

Keep PCM16, 1–8 channels, at most 384000 Hz and 1800 seconds. These are local software bounds, not disk/RSS guarantees or acquisition/hardware settings. No truncation or automatic eviction. Exact retries must not replace stored provenance; capacity handling must distinguish validation of an existing import from reservation for a new job.

## Read DTO

`GET /api/v1/recordings/{recording_id}/acquisition-companion` is record/site/device scoped, including revocation checks. A known legacy recording returns:

```json
{"schema_version":"poseidon.recording-acquisition-companion.v1","state":"absent","recording_id":"..."}
```

A retained companion returns exactly this transport shape:

```
{
  schema_version: "poseidon.recording-acquisition-companion.v1",
  state: "retained",
  recording_id: string,
  platform_session_id: string,
  capture_session_id: string,
  source_id: string,
  selected_index: integer,
  source_header_sha256: sha256,
  source_final_sha256: sha256,
  wav_sha256: sha256,
  manifest_sha256: sha256,
  imported_at: UTC,
  actor_subject: string,
  auth_mode: "local_development_key" | "scoped_token",
  job: { id: string, status: "queued" | "running" | "succeeded" | "failed" },
  documents: [{ role, name, bytes, sha256 }],
  binding: object,
  validation: object
}
```

`documents` contains the five JSON roles in the order binding, source_receipt, source_header, source_final, export_receipt. `binding` is the parsed, already reader-validated ORIGINAL binding document, with no field normalization or replacement. `validation` is the parsed exact reader projection retained separately as immutable bytes. These are existing Acquisition semantics, not a second platform scientific parser. Preserve exact raw documents separately from both parsed transport objects.

A retained import can be inspected while its job is pending or failed. This is not an available recording or a complete capture claim. Preserve normal visibility of queued jobs and deny out-of-scope existence disclosure.

`GET /api/v1/recordings/{id}/acquisition-companion/documents/{role}` accepts only the five JSON roles and returns exact stored bytes, `Content-Type: application/json`, `Content-Disposition: attachment` with its validated basename, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`, and `X-Poseidon-Document-SHA256`. It never reads a client path. Legacy absence is 404 for raw-document requests. Tokens and internal paths never appear in replies.

## Binding, identity and failure

The existing platform session is a manual scope context, not silently the raw capture session. Pin it on first qualified import to capture_session_id, source_id, header SHA256 and final SHA256. Target site/device and provenance source ID/kind must match the validated export mapping/origin and existing registry rules. Manual clock metadata never upgrades imported timing. Preserve all false verification flags and stored-segments-only/unattested-tail meaning.

Qualified idempotency includes exact source/manifest/companion bytes, target context and source snapshot/segment mapping. Existing legacy data cannot be silently backfilled or rescoped. Existing source-only retry remains compatible and cannot remove companions. Compare authorization before exposing conflicting stored identities.

Hub schema v3 adds exact companion BLOBs, immutable import/projection and snapshot bindings, and durable owned intents. Recording packages stay exactly source.wav+manifest.json. Source/job/companions/pin/recording-session binding/audit become visible in one commit. Intents reserve ownership before staging and permit abort-only reconciliation after interruption, including rename-before-SQLite-commit. Never adopt/delete unknown or tampered files, never auto-complete under stale authority, and never label a DB transaction alone as power-loss proof.

Use existing error envelope: 401 credentials, 403 role, 404 hidden/out-of-scope, 400 malformed/inconsistent/unsupported, 413 byte/part limits, 409 identity/binding/capacity, safe 500 storage/recovery failure.

## Operator view

Keep a separate seven-file import option with session selection and explicit limits. Old two-file import remains intact. Inspect both session IDs, selected segment, ordered channels, nominal/reference intervals, epoch/rounding/declared uncertainty, gaps/losses, exact hashes and raw documents. Show delivered-file consistency versus omitted original input/session data, unverified origin/clock/authorization and incomplete acquisition coverage. Waveforms remain nominal segment seconds. Evidence strings are inert escaped text; do not add capture controls, calibrated/verified-UTC claims, metrics or a redesign.
