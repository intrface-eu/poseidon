# Finalized audio segments to legacy v1 replay

`poseidon_acoustic.legacy_export` exports selected, finalized PCM16 WAV segments as standalone `RecordingManifest` v1 recordings. It calls the existing `Session.recover()` validator and `RecordingManifest.from_dict()`; it does not change either contract. Every WAV is an independent, byte-identical copy of one committed source segment. There is no mixing, channel reordering, downsampling, gap filling, concatenation or calibration.

The separate companion binding retains metadata that v1 cannot represent. Keep it and the export receipt with the WAV/manifest. This is not full-session Hub ingestion: the old replay/store accepts the v1 pair but does not ingest or enforce the companion's clock, source-channel, gap or origin-declaration metadata.

## Deterministic local example

Python 3.11+ and the existing source tree are sufficient; no added packages, services or devices are used. Run from the repository root:

```sh
export PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src

# The context owns and removes all example artifacts, including the SQLite DB.
python3 - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from poseidon_acoustic.legacy_export_cli import run_demo
from poseidon_acoustic.session import canonical

with TemporaryDirectory() as temporary:
    result = run_demo(Path(temporary).resolve() / "legacy-demo")
    print(canonical(result).decode(), end="")
PY
```

For retained local artifacts, give the CLI a **new** output directory under an existing, real parent:

```sh
python3 -m poseidon_acoustic.legacy_export_cli demo \
  --output-dir /absolute/real/parent/new-synthetic-legacy-demo
```

The example writes a finalized synthetic session, its export, `evidence.sqlite3`, `events.ndjson` and `demo-result.json`. It runs the real `replay_to_store`, detector and SQLite store, not a substitute implementation. The first 1,600-frame segment contains two integer-generated bursts and yields two synthetic candidates. The second 1,600-frame segment contains silence and yields zero candidates; it still becomes a stored recording/run. Both use 8 kHz mono PCM16. A deliberately omitted 800-frame interval remains an explicit gap/drop declaration, not new samples. The declared clock has a 0.25-second offset, 20 ppm source-to-reference scale and uncertainty growth.

The session/export bytes, event IDs and JSON example results repeat exactly in independent directories. No claim depends on SQLite's physical file layout. The example's fixed January 2026 UTC epoch is a synthetic convention, not the time of a sensor observation or test run. These samples are not animal sounds or field evidence.

## Export an existing finalized session

Example for the synthetic source created by `poseidon_acoustic.session_cli demo`:

```sh
python3 -m poseidon_acoustic.legacy_export_cli export \
  --session /absolute/real/parent/synthetic-audio-session \
  --output-dir /absolute/real/parent/new-v1-export \
  --source-id synthetic-audio \
  --site-id synthetic-site --zone-id synthetic-zone --device-id synthetic-device \
  --segment 0=synthetic-recording-0 --segment 2=synthetic-recording-2 \
  --reference-domain reference_seconds \
  --reference-epoch synthetic-session-start \
  --epoch-utc 2026-01-01T00:00:00Z \
  --epoch-uncertainty-s 0.005 \
  --epoch-declared-by synthetic-fixture-generator \
  --epoch-evidence-ref synthetic-epoch-convention-v1
```

Each `--segment INDEX=RECORDING_ID` names a finalized receipt index, not a sample index. All selections must belong to `--source-id`; the CLI repeats the explicitly supplied site/zone/device mapping for them. The Python API takes a tuple of `SegmentMapping` objects, each carrying its own recording/site/zone/device IDs. No mapping or recording ID is inferred. Export order follows original segment index. Duplicate selections, recording IDs or existing destinations fail before any new output is written. Existing replay-store rules still reject conflicting recording identities across separate exports.

All supplied directory components must be real directories, not symlinks; output parents must already exist. On macOS, `/tmp` and `/var` may be system symlinks. Resolve an owned temporary directory as in the Python example rather than passing an alias. Symlinked source entries, FIFOs, sockets and devices are refused. Do not put export output inside its source session.

## UTC and provenance declarations

`EpochDeclaration` requires `source_id`, `reference_domain`, `reference_epoch`, `epoch_utc`, `uncertainty_s`, `declared_by` and `evidence_ref`. The three identity fields must exactly match the selected source and its sidecar clock. The declaration means:

```text
reference_s = 0 at the named reference epoch
UTC = epoch_utc + reference_s seconds
segment.started_at = epoch_utc + receipt.reference_start_s seconds
```

The sidecar's own source-to-reference drift/offset mapping remains authoritative; the exporter does not map the segment's source time directly to UTC or assume `reference_seconds` already means UTC. It preserves the original clock domains, reference epoch, anchors, method, evidence reference and uncertainty model. Measured/shared-clock method names remain unverified claims here.

Epoch strings must use RFC3339 UTC `Z` or `+00:00`, at most six fractional digits, and valid Gregorian dates. Local timestamps, nonzero offsets, unknown-offset `-00:00`, leap-second normalization, `24:00`, missing fields and out-of-range dates are refused. Derived starts, ends and declared uncertainty envelopes must remain in years 1–9999. A reference interval that collapses at v1's microsecond precision is refused. Decimal arithmetic derives timestamps, rounds half-even to microseconds and records the rounding error. The binding sums declared source-clock and epoch uncertainty bounds and timestamp rounding; this is not a measured statistical confidence interval.

The WAV sample rate is **not** altered for clock drift. V1 candidate offsets remain segment-local `frame / sample_rate_hz` seconds. With nonzero drift, `started_at + candidate.start_time_s` is not a verified, drift-corrected UTC event time. The binding preserves both nominal-WAV and reference end times and the mapping needed to interpret a local candidate frame:

```text
candidate_source_s = receipt.source_start_s + candidate_frame / sample_rate_hz
candidate_reference_s = original_source.clock.at(candidate_source_s)[0]
candidate_UTC = declared_epoch_utc + candidate_reference_s seconds
```

Synthetic source provenance always stays `synthetic`. A file-origin declaration supplied for a synthetic source is refused. Sidecar `provenance=file` does not mean v1 `field`: file exports require an independent `FileOriginDeclaration` identifying the same source and original `input_sha256`, an explicit `field` or `bench` origin, declarant and evidence reference. CLI flags are all-or-none:

```text
--file-origin field
--original-input-sha256 <the source header's original input checksum>
--origin-declared-by <declarant>
--origin-evidence-ref <declared evidence reference>
```

The reference string is preserved, not opened or verified. Unresolved file origin, absent/mismatched original input checksums, unknown provenance and `bench` origin are refused. V1 supports only `field` and `synthetic`; bench data cannot be relabeled to fit it. Accepted field declarations retain `origin_verified=false` and `authorization_verified=false`. No authorization or permit is manufactured. Every v1 output has `calibration_status=uncalibrated`; epoch and origin declarations remain operator claims.

## Bundle and failure contract

| Artifact | Content |
|---|---|
| `source-header.json` | Exact original immutable session header bytes. |
| `source-final.json` | Exact original finalized session manifest bytes, including all segment hashes, state and accounting. This is an original snapshot, not a claim that every listed segment was exported. |
| `source-receipt-NNNNNN.json` | Exact original selected receipt bytes, retaining source/reference intervals, uncertainties, unit extents, gaps, drops and receipt-chain hash. |
| `chunk-NNNNNN.wav` | Entire original selected PCM16 segment, copied without byte changes. |
| `binding-NNNNNN.json` | Original source metadata and ordered channel IDs/roles; header/final/receipt/segment SHA-256 bindings; explicit v1 identity mapping; time/origin declarations and unverified flags; WAV and v1 manifest hashes; extent/accounting limits. |
| `recording-NNNNNN.v1.json` | Exactly the existing nine v1 fields, validated by `RecordingManifest.from_dict()`. No invented clock/provenance extension fields. |
| `export.receipt.json` | Final commit record listing selected mappings and every exported file's path, size and SHA-256. `export_committed` means the selected export set was written, not a complete acquisition or verified field recording. |

Only the normal `finalized` acquisition state is accepted. `source_failed`, `capacity_halted` and `recovered_incomplete` are conservatively refused, even if some segments are valid. There is no partial-export override in this version. The normal state still attests **stored segments only**, with trailing extent unattested. Selecting a subset does not claim the rest was copied. Gaps and drops remain in their original receipts and source accounting; no missing samples are created.

The exporter checks the whole original session with `Session.recover()` before planning output and again before the final commit. It compares original header/final snapshots, selected receipt/payload hashes and copied output bytes. Recovery may open/create the session's existing advisory `.writer.lock`; the exporter never finalizes or repairs the original session. Original unknown artifacts are not deleted or adopted.

Default output limits are 16 MiB and 128 selected segments. Hard limits are 256 MiB and 256 selected segments. `--max-bytes` includes copied evidence, companion records, v1 manifests and the final receipt. Planning checks this bound before creating output and keeps bounded data in memory. Session recovery retains its own input/workspace limits and validates unselected evidence too. Limits cover logical artifact bytes, not filesystem block allocation or incidental storage overhead. V1 media limits are at most 8 channels and 384,000 Hz; otherwise export fails without conversion.

The output directory must be new. Files publish without replacement and are synced. Each v1 manifest follows its WAV and companion; the bundle receipt publishes last, after source and output revalidation. A failed write, source change or copied-output change leaves inspectable partial output without a committed bundle. The final receipt's own link is retracted on a reported commit-sync failure when the filesystem permits it. If cleanup itself fails, the error explicitly says not to use the failed output. A power loss or storage device that ignores synchronization remains a physical validation gate.

Use only a run that exits zero and has `export.receipt.json`; keep and check its file hashes before handing standalone v1 pairs to downstream replay. Do not treat an individual manifest found in a failed output as proof that its whole selected export set completed. Never overwrite a failed directory to retry: inspect it and choose a new path. Hashes bind the snapshot, not an actor's identity; an actor able to rewrite the entire bundle can replace hashes. Private operator-owned directories are required; this is not a hostile-multiuser filesystem sandbox.

## Checks and remaining gates

```sh
export PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src
python3 -m unittest discover -s tests/acoustic -p test_legacy_export.py -v
python3 -m unittest discover -s tests/acoustic -v
```

Tests cover real replay/detection/storage and candidate identities, byte/hash preservation, clock drift and epoch mismatch, timestamp range/precision, unknown/bench/synthetic provenance, unverified field declarations, rate/channel/encoding mismatch, partial final-state refusal, duplicate destinations, source/output tampering, commit failures, symlinks/FIFOs, budgets and zero-candidate sources. Field-declaration tests use temporary software fixtures; they do not provide field evidence.

Full-session platform ingestion and companion-aware UTC candidate presentation remain separate work. Linux ARM/Pi operation, real power-loss durability, clock/sensor calibration, field provenance verification, site access and permissions, biological performance, acoustic safety and production release remain unverified. No Hub/API/UI or legacy schema changes are part of this bridge.
