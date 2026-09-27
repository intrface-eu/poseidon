# Pure single-export reader

`poseidon_acoustic.legacy_export_reader` validates one complete, committed selected-export package for the Platform companion route. It has no file/device/native/network access and does not call `Session.recover` or `export_segments`. The caller owns upload storage and supplies bounded immutable bytes.

```python
from poseidon_acoustic.legacy_export_reader import (
    ExportReadError, ExportReadLimits, file_map_resolver, validate_export_bundle,
)

# six_files: exactly six safe basename -> bytes entries; receipt is separate.
validated = validate_export_bundle(
    export_receipt_bytes,
    file_map_resolver(six_files),
    limits=ExportReadLimits(),
)
manifest = validated.manifest
raw_binding = validated.file_for_role("binding").data
projection_bytes = validated.projection_bytes
```

Public signature:
`validate_export_bundle(export_receipt_bytes: bytes, bounded_read_only_file_resolver: Callable[[str, int], bytes], *, limits: ExportReadLimits) -> ValidatedExport`.
The resolver receives `(expected_basename, maximum_bytes)` once for each of six expected files. `file_map_resolver` snapshots six entries so later mutation of the caller's map cannot affect validation. The transport must separately reject extra/duplicate multipart roles; an arbitrary resolver cannot enumerate undisclosed files.

`ExportReadError` subclasses `ValueError`. `ValidatedExport`, `VerifiedExportFile`, `ExportReadLimits`, the returned `RecordingManifest`, file tuples and raw/projection bytes are immutable. Parse projection bytes into a detached view for presentation; commit the validated bytes, not a mutable caller-rewritten dictionary.

| ID | Result | Fields |
|---|---|---|
| ER1 | `ValidatedExport` | `manifest`, `capture_session_id`, `source_id`, `selected_index`, `header_sha256`, `final_sha256`, `export_receipt_sha256`, `files`, `projection_bytes`; method `file_for_role(role)` |
| ER2 | `VerifiedExportFile` | `role`, `name`, `size`, `sha256`, `data:bytes` |
| ER3 | Fixed roles | `wav`, `manifest`, `binding`, `source_receipt`, `source_header`, `source_final`, `export_receipt` |
| ER4 | Projection schema | `poseidon.validated-single-export.v1`: manifest/recording identity, source/capture identity, snapshot hashes, original source/channel order, selected receipt/mapping, time/origin projections, capture extent/accounting, role digests and verification coverage |

## Limits and raw-byte rules

`ExportReadLimits()` uses the ratified caps below. Callers may tighten them, not increase them. Integers must be positive and not booleans.

| Field | Bytes |
|---|---:|
| `wav_bytes` | 8,388,608 |
| `manifest_bytes` | 16,384 |
| `binding_bytes` | 262,144 |
| `source_receipt_bytes` | 16,384 |
| `source_header_bytes` | 1,048,576 |
| `source_final_bytes` | 2,097,152 |
| `export_receipt_bytes` | 65,536 |
| `aggregate_companion_bytes` | 4,194,304 |

The aggregate companion cap covers the five JSON companion roles, including export receipt, not WAV/manifest. JSON depth is bounded at 32; duplicate keys, nonfinite values, malformed types and unsafe names fail. Hash/size comparisons use exact supplied bytes before parsing.

Header and selected receipt retain existing session-canonical newline rules. Binding/export receipt and v1 manifest retain their exact emitted representations. **`source_final` is the exception:** the accepted writer copies its bytes verbatim and compares parsed semantics, so this reader also accepts writer-valid whitespace/JSON byte-encoding variants while preserving their original bytes and raw digest. It never normalizes that source document before hashing. Tests cover UTF-8 pretty JSON, UTF-16 and UTF-8 BOM finals emitted by the unchanged exporter behavior.

The reader reuses the session pure JSON parser, `Source`/`ClockMap`/PCM validation, accepted epoch/origin/time projection and shared binding/receipt construction. Two small pure projection helpers were extracted from the writer and its JSON parser step was shared; the existing deterministic export receipt stays byte-identical.

## Verification coverage

| ID | Meaning | Result |
|---|---|---|
| VC1 | All six listed delivered files plus export receipt; selected segment raw bytes and selected projection consistency | Checked against raw hashes/sizes, known fields, exact supported PCM format/rate/channels/frames, selected final membership, epoch/origin rules and logical geometry/accounting bounds |
| VC2 | Missing predecessor receipt, unselected source segments and original input file | Retained declared hashes, not verified original bytes; hash-link consistency does not establish receipt/input authenticity |
| VC3 | Full acquisition, physical channel assignment, clock/epoch calibration, origin or permission | Not verified; fixed false flags remain false, including `full_original_session_bytes_verified`, `original_input_bytes_verified`, `acquisition_completeness_verified`, `clock_relation_verified`, `epoch_declaration_verified`, `origin_verified`, `authorization_verified` |

Exactly one export is supported. Multi-export receipts, abnormal final states, unresolved/bench origin, missing/null legacy epoch uncertainty, default-filled source clock fields, inconsistent raw/semantic projections and forged verification flags fail. A normal final still means stored segments with an unattested tail, not planned-duration capture. Unsigned self-consistent bundles are not authenticated evidence; Platform stores its authenticated importer actor separately.

The reader's scope is fixed legacy exported files. It does not admit new live journals, grant live device access, convert formats, fabricate UTC/uncertainty or upgrade an origin declaration. Existing v1 recording/event/evidence formats are unchanged.

## Reproduce

```sh
export PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src
python3 -m unittest discover -s tests/acoustic -p test_legacy_export_reader.py -v
python3 -m unittest discover -s tests/acoustic -p 'test_legacy_export*.py' -v
python3 -m unittest discover -s tests/acoustic -p test_session.py -v
```

The 20 reader tests use the real exporter/replay, one candidate-producing and one zero-candidate selected segment, mutations with every hash rewritten, immutable-output checks and a `python -S` subprocess with no site packages/native imports. The 37 prior exporter tests and 41 session tests also pass after helper extraction. Existing demo receipt SHA256 remains `d63f5c492b948483ea25811483ea3e606f0f3b69cf75045eeae064e6b9da9804`.

Synthetic reader integration fixtures use positive and zero-candidate exports, each with one export and all seven roles. Receipt/projection hashes and candidate counts `[1,0]` were recorded for that historical run; the private run artifacts are not included in this repository.
