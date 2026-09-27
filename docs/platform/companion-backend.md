# Companion-aware backend intake

This tranche retains one selected acquisition export through the existing Hub and API. It fixes missing companion ingestion; it does not authorize capture, device operation, field placement, calibration, or production release. The transport and reader response shapes are in [companion-import-v1.md](../../contracts/companion-import-v1.md).

## Actual validation and API

The Hub calls `poseidon_acoustic.legacy_export_reader.validate_export_bundle` with `ExportReadLimits` and the real bounded `file_map_resolver`. Acquisition owns that reader and its scientific rules. Platform checks transport bounds, registered identity, storage consistency, and authorization; it does not copy the scientific parser or reconstruct an incomplete source session.

The write route is `POST /api/v1/acquisition-sessions/{platform_session_id}/recordings`. It accepts one selected export and exactly seven file parts, with no scalar fields:

| Role | Maximum bytes |
|---|---:|
| `wav` | 8388608 |
| `manifest` | 16384 |
| `binding` | 262144 |
| `source_receipt` | 16384 |
| `source_header` | 1048576 |
| `source_final` | 2097152 |
| `export_receipt` | 65536 |

Companions have an aggregate 4194304-byte cap. Multipart overhead has a 262144-byte allowance; the actual whole-request cap is 12861440 bytes. There are two simultaneous new-route admissions per Hub, 32 queued/running/preparing slots, and 268435456 retained-plus-reserved companion logical bytes. Excess data is rejected, not truncated. These are local software limits, not limits on total disk allocation, process memory, or physical acquisition.

The receipt must identify the six other delivered files. Parts may arrive in any order. Original basenames must match the approved flat filename patterns and actual reader references; filenames never select server paths. Missing, duplicate, unknown, unsafe, inconsistent, partial, archive, and multi-export inputs do not fall back to legacy import. WAV remains PCM16, 1–8 channels, at most 384000 Hz and 1800 seconds, with the smaller 8 MiB new-route byte cap.

The existing `POST /api/v1/recordings` and `Hub.submit_recording(wav_stream, manifest_bytes)` keep their two-file behavior and development-only permission. The new mechanical method is:

```python
submit_recording_with_companions(
    wav_stream, manifest_bytes, companions_by_role,
    *, session_id, filenames_by_role,
) -> job
```

`companions_by_role` holds exactly five raw JSON byte values. `filenames_by_role` holds all seven names. The result is the unchanged job object and HTTP 202, only after commit. No PyAV, FFmpeg, native-device library, exporter, `Session.recover`, or subprocess decoder runs in this intake. Test fixtures use the real exporter separately; that is not part of handling an upload. The API dependency files and separate codec environment did not change.

## Authority and immutable association

The API authenticates the request and eagerly authorizes an existing session before multipart parsing. Only an admin may upload; a scoped admin must own the target site. The registered device must be active and match the session. The Hub rechecks principal/token, context, device, source mapping, and capacity in its write transaction.

Admission is an eager lease returned by `companion_admission(session_id)`, not a lazy generator that could lose the request-bound principal context. Its release does not require a still-valid credential. The lease covers parsing, intake, and upload closure. The parser closes already-opened spools on byte overflow, disconnect, and cancellation as well as ordinary multipart errors; this cleanup uses the current pinned Starlette parser interface and has an actual streamed-overflow regression test.

The manual platform context and raw capture session remain different namespaces. First intake pins the context to capture session ID, source ID, source-header SHA-256, and source-final SHA-256. Site, device, and provenance source ID/kind must match the validated export and existing registry rules. Later imports in that context must match the pin. A snapshot/source/selected-index tuple cannot acquire another recording ID or context.

Manual session clock fields do not replace imported timing. Registry administration is not proof of source origin or permission to operate equipment. Historical companion reads do not require the original importing credential or registry device to remain active; they require the current reader's authorized site/device scope.

## Storage, reservations, and interruption

Hub schema v3 adds four tables: `acquisition_source_bindings`, `recording_companion_imports`, `recording_companion_documents`, and `companion_import_intents`. The v2-to-v3 migration is additive. A v1 workspace receives the v2 and v3 additions in one transaction. Failed migration leaves the supported old schema intact. Legacy source/job/review/media rows, the development credential, v1 files, and `evidence.sqlite3` retain their existing formats and bytes.

Every recording directory still contains exactly `source.wav` and `manifest.json`. The five companion documents are exact SQLite BLOBs with their original role, basename, byte count, and SHA-256. Source-final bytes may be valid noncanonical JSON, including UTF-16/BOM formatting accepted by the actual reader; they are never decoded and rewritten for retention. The reader's exact immutable `projection_bytes` and its SHA-256 are separate from those originals.

After bounded validation, the Hub checks for a qualified duplicate before reserving new capacity. For a new import, an intent reserves the recording target, a random server staging name, one queue slot, and companion logical bytes before Hub staging starts. The shared legacy/new queue predicate includes these preparing reservations.

The intent also temporarily holds the exact expected WAV and manifest as strict BLOBs, capped at 8388608 and 16384 bytes. This bounded source duplication supplies exact-prefix evidence for interrupted receiving files. It does not change the ratified companion logical-byte quota. Intent deletion removes those temporary BLOB references on commit or completed abort; this is not secure erasure or a promise that SQLite immediately releases disk pages.

Ownership checkpoints work as follows:

1. Create the staging directory exclusively, then record its device/inode before creating data files.
2. Create each file exclusively, record its device/inode while empty, then write bytes.
3. After file flush/fsync, checkpoint that file as complete.
4. Mark the package ready only when both complete files match the reserved bytes, hashes, sizes, and recorded identities.
5. Rename without replacing an existing target. In one SQLite transaction recheck authority/capacity and insert job, pending source, snapshot pin, recording-session binding, five documents, projection, and actor audit; delete the intent in that same commit.

Startup aborts registered incomplete intents before serving the workspace. It never completes an import under stale authorization. A receiving file is removable only when its recorded inode matches and every byte equals the reserved original prefix. A completed file must retain its full length and hash. A valid short prefix alone is not ownership proof. Unknown files, unregistered files, changed prefixes, inode substitutions, symlinks, hard links, and shortened completed files are preserved and stop reconciliation.

There is a deliberate fail-closed boundary between exclusive directory/file creation and persistence of its creation checkpoint. A process loss in that narrow window leaves an object whose ownership is ambiguous. Startup preserves it and refuses to open the workspace rather than adopting or deleting it. Missing files, interrupted cleanup, or storage errors can likewise require inspection when the remaining ownership/content evidence is insufficient. No broad staging cleanup or new manual repair command is supplied. The prior legacy orphan behavior remains unchanged.

The tests cover acknowledged ownership checkpoints and rename/transaction interruption, including an owned process that exits after rename. They do not prove real power-cut, filesystem, or storage-device durability.

## Idempotency and reads

Qualified retries retain the existing v1 source fingerprint/job ID and additionally require exact manifest/companion bytes and names, context, source snapshot, selected-index mapping, and reader projection. They return the original job without replacing importer provenance and do not need a second reservation at full queue/companion capacity. Changed evidence, remapping, or legacy data without companions produces a conflict. An ordinary two-file retry cannot remove companions or act as a backfill route.

`GET /api/v1/recordings/{id}/acquisition-companion` returns the versioned transport DTO. Known legacy records return explicit `state:absent`. Retained imports include both session IDs, source/index/hash metadata, original importer, current job state, the five role digests, parsed original binding, and parsed retained reader projection. Queued and failed processing jobs remain inspectable through this route without pretending their recording is available.

`GET /api/v1/recordings/{id}/acquisition-companion/documents/{role}` returns only an approved JSON role's exact bytes. It uses attachment disposition, `application/json`, `nosniff`, `no-store`, and `X-Poseidon-Document-SHA256`. Both read routes enforce recording/site/exact-device scope and credential revocation. Invalid roles cannot become filesystem paths.

Every projection or raw-document read checks the entire retained import: all five BLOB lengths/hashes, projection digest, source/manifest bytes and geometry, source/context/segment bindings, and the real Acquisition reader's exact resulting projection and identities. Workspace reopen performs the same checks before job recovery; backup/restore inherits that check by opening the real Hub. Corruption is refused, never normalized or repaired. A failed replay alone does not delete companions or block their inspection.

The existing standalone backup `verify` command checks its outer file manifest, not scientific meaning. Rewriting that unsigned outer manifest cannot make a corrupt retained projection pass restore: the restored Hub runs the reader checks. Fully replacing all evidence with another internally consistent unsigned bundle is not detectable exporter authentication or a tamper-proof-host claim.

## Meaning and remaining boundaries

The retained projection distinguishes checked delivered files and selected segment bytes from omitted original-input, predecessor, and full-session bytes. Preserve its false verification flags. Normal finalized acquisition still means stored segments only with an unattested tail; it is not complete acquisition coverage. Epoch/origin/authorization declarations and clock uncertainty remain declarations. Processing success, administrative authority, matching hashes, and nominal video offsets do not verify UTC, calibration, or biological ground truth. Existing waveforms remain nominal segment seconds; this slice does not calculate a verified candidate UTC timeline.

Read/reopen integrity work grows with retained imports and source sizes. No production throughput, storage-allocation, retention, external identity/TLS, remote audit, or hardware result is claimed. New live journals, unknown-UTC or bench-origin admission, native codec intake, and field operations require separate reviewed work.

## Verification

All fixtures are synthetic, produced by the actual acquisition session/exporter and read by the actual pure reader. Tests use private temporary workspaces. Commands from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/trident/src:apps/aeolus-api/src \
uv run --project apps/aeolus-api --frozen pytest tests/api -q

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/trident/src:tests/trident \
python3 -S -W error::ResourceWarning -m unittest \
  test_hub test_media_and_limits test_recovery_and_safety test_platform test_companion_import -q

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/trident/src \
uv run --project apps/aeolus-api --frozen python -W error::ResourceWarning \
  -m unittest discover -s tests/trident -q

PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/trident/src \
python3 -W error::ResourceWarning -m unittest discover -s tests/ops -q
```

The suites cover real candidate/zero/stereo/gap exports, UTF-16 final retention, malformed and hash-rewritten inconsistencies, scope and revocation during upload/commit, upload closure and byte limits, queue/reservation accounting, idempotency/concurrency, migration, 20 acknowledged interruption phases, ambiguous receiving ownership, raw/projection corruption, and actual backup/restore. Lead/root own final UI/browser and integrated acceptance. Earlier sealed evidence stays historical and unchanged.
