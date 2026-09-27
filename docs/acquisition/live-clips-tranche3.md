# Live journal event clips, tranche 3

`poseidon_acoustic.live_clips` reads a **previously closed, intact** live journal and writes bounded PCM16 WAV excerpts plus a local manifest. It does not capture, recover, resume, acquire writer ownership, load a native backend, or call an output service. Tests use synthetic files only.

## Python API

```python
from poseidon_acoustic.detector import DetectorConfig
from poseidon_acoustic.live_clips import (
    ClipLimits, detect_live_journal, extract_live_clips,
)

config = DetectorConfig(threshold=0.2, window_ms=20)
limits = ClipLimits()

# Read-only preview; no output directory is created.
detection = detect_live_journal(
    journal_path, "selected-audio-source", config, limits=limits,
)

# Detection is regenerated from verified input, not accepted from the caller.
result = extract_live_clips(
    journal_path,
    new_output_directory,
    "selected-audio-source",
    config,
    pre_frames=100,
    post_frames=100,
    event_ids=None,  # All events, or a nonempty tuple of IDs from this exact run.
    limits=limits,
)
```

The output directory must not exist; its parent must exist. The API rejects overlap with the source, including resolved symlink-parent aliases and source/output directory identity substitution. There is no CLI or replay/API integration in this tranche.

`LiveDetectionResult` contains immutable `LiveEvent` records, run/config identities, source and channel information, exact intent/final hashes, and null clock/UTC/physical uncertainty fields. `LiveClipResult` returns the canonical manifest bytes, their SHA-256, the output path, and the regenerated detection. Refusals raise `LiveClipError`. Its subclass `LiveClipPublicationUncertain` reports a failed publication whose receipt retraction or durability could not be confirmed; it carries `publication_state="uncertain"`, the output path, and the publication/cleanup error text. No success result is returned in that state.

A selector is not authority to provide frame bounds. An ID from another journal, source, detector configuration, or final record does not select an event in this run. Duplicate, malformed, and excessive selectors are refused. An intact empty prefix or a silent input produces an empty event list and, if extraction was requested, a manifest with no WAVs.

## Local detector and identity

The version is `live-nominal-normalized-rms-v1`. The implementation reuses the frozen replay detector's `DetectorConfig`, PCM16 normalization scale, and pure window/event statistics. It runs fixed, non-overlapping windows over the selected source's nominal stored frames. Window rounding, channel-wise RMS, threshold equality, adjacent qualifying-window merging, peaks, and a final partial window match the replay detector's math. Independent synthetic replay vectors test parity; no live data receives a `RecordingManifest`, fabricated UTC, replay identity, or field identity.

The run ID hashes these fields with the live journal's canonical JSON encoding:

- Exact journal intent and final SHA-256 values.
- Selected `source_id` and source-plan SHA-256.
- Local detector configuration ID, which binds the version, threshold, window duration/frame count, and nominal-position meaning.

The event ID additionally binds the run ID, source ID, and exact `[start_frame, end_frame)` bounds. Event IDs use `liveevt_`, not the replay event family. This local manifest is `poseidon.live-event-clips.local.v1`, not a v1 recording/replay document or a wire-protocol change.

## Frames, channels, clocks, and coverage

Every frame index is **source-relative, nominal, stored, and end-exclusive**. Other sources may interleave in the receipt chain. The verifier checks the complete chain, including video and other unselected bytes; the detector and WAVs use only the selected audio source. A window may cross chunks of that source. It never incorporates video units or foreign-source samples.

The existing pure journal validators reject receipt gaps, wrong positions, invalid sequence transitions, and changes in declared clock domain/generation/type. Sequence wrap follows the accepted journal rule. Unknown sequences, absent/repeated/regressing raw timestamps, and unknown clock accuracy do not become inferred physical timing. Raw observations remain attached to each copied receipt segment. A raw driver accuracy of zero remains a raw observation, **not** zero physical uncertainty.

PCM16 little-endian sample bytes and declared channel/role order remain exact. There is no resampling, mixing, channel cancellation, or gap filling. Normalized amplitudes are uncalibrated full-scale values, not sound-pressure measurements. Nominal stored adjacency does not establish physical continuity, exposure, synchronization, complete acquisition, or a quantity of lost capture.

Each requested pre/post window clips to the available committed nominal prefix. The manifest records requested and included padding, clipped frame counts, and exact copied spans. Clipped padding means that the requested nominal range lies outside the committed prefix; it is not measured physical loss. Separate events remain separate excerpts even if their padding overlaps. Duplicate output bytes count toward the aggregate output bound.

Clock relation, physical uncertainty, UTC, exposure, and loss declarations retain the journal's null values. The complete final document and orphan inventory remain in the manifest, including incomplete acquisition, unknown source tails, observed queue-rejection coverage, discard observations, and stop/recovery reason. Recovery must have happened separately. A recovered prefix is accepted only if closed with no integrity error. Orphan bytes are hashed as input evidence but never interpreted as committed samples or appended to a clip.

## Verification and publication

1. Pin the source directory with a read-only descriptor. Bound the entire artifact inventory and reserve two complete input-byte passes before allocating file buffers. Read only bounded regular files through that descriptor, without following file symlinks or opening a writer lease.
2. Validate canonical intent, plan, configuration, start evidence, every committed payload/receipt binding and chain position, and the final prefix/claims against a bounded immutable snapshot. Reuse accepted pure journal contracts; do not run the path-based verifier against a mutable intent whose limits could change mid-scan.
3. Generate detection internally. Admit all selected excerpt frame counts, complete WAV sizes, and their aggregate before allocating WAV buffers. Bound repeated segment metadata and stream the canonical manifest encoding under its remaining byte allowance.
4. Create only a new output directory. Write and fsync exclusive WAV files and a pending manifest. Verify the actual output bytes. Re-read and hash **every** source artifact, not only the selected payload or final file; recheck the directory inventory and file identities after that pass. Checks include device/inode, type, size, mtime and ctime, so replacement, mutation, and write-and-restore during the operation cause refusal.
5. Publish `manifest.json` last with a no-replacement link, then remove its pending name and fsync the output and parent directories. Track the exact linked inode. If linking, pending-name removal, or either directory sync fails, retract `manifest.json` only after checking that its inode and bytes still match this operation's receipt. Confirm absence and sync both directories again. Retain WAVs, pending files, and other partial evidence; do not overwrite existing output or remove source evidence.

Only `manifest.json` is the success receipt. After a publication error with confirmed retraction, that receipt is absent. If it was replaced or changed by another actor, cleanup leaves it untouched. If cleanup, its identity checks, or its directory syncs fail, the API raises `LiveClipPublicationUncertain`: a receipt may remain, or its absence may lack durable confirmation. This is **not** an incomplete-output guarantee. Inspect and reconcile that output rather than treating the failed call as committed success or retrying into the same directory.

The manifest binds full WAV and PCM hashes, copied segment hashes, exact source/chunk/clip frame spans, payload byte offsets, receipt/payload/configuration hashes, the final receipt chain tip, and every input artifact hash. Hashes refer to the exact bytes used and copied. Readers can verify them against the retained journal and WAVs. These are local content hashes, not signatures or proof that source provenance is physically verified. Verification describes the bytes observed during the bounded operation; it cannot prevent a separate actor from changing files after completion.

For this reader, even orphan artifacts must be regular files. Directories, symlinks, FIFOs, and devices in the journal cause refusal, not traversal or adoption. Oversized or otherwise valid journals outside the reader's caps are also refused without partial event selection.

## Hard limits

Callers may tighten these ceilings with `ClipLimits`; they cannot disable or raise them. All limit and frame arguments require actual bounded integers, not booleans, floats, nonfinite values, or overflow-sized values.

| Limit | Ceiling |
| --- | ---: |
| Journal artifact entries | 2,048 |
| Total input artifact bytes, including orphans and any reserve | 32 MiB |
| Two-pass source scan budget, including one EOF probe per file per pass | 80 MiB |
| Per-file input bytes | 8 MiB; 64 KiB for `.json`; 16 MiB for `.reserve` |
| Detected event count, before selection | 64 |
| Frames in one excerpt, including padding | 384,000 |
| Full bytes in one WAV, including its 44-byte header | 4 MiB |
| Aggregate WAV and manifest bytes | 16 MiB |
| Manifest bytes | 1 MiB |

The input budget is independent of output size. Unselected sources, silence, orphans, and all metadata still count. Detection does not stop early to fit a selected event cap. A too-large event or run is refused rather than silently truncated.

## Focused assurance

The synthetic tests cover detector parity, source-bound identities, stereo order and antiphase, partial/chunk-crossing windows, exact WAV bytes and all evidence hashes, interleaved-source integrity, unknown clocks, sequence wrap/gaps, intact and corrupt recovered prefixes, orphan/tail preservation, missing or changed input, strict canonical metadata, read/write races, nonregular files, overlap aliases, all byte/frame/count limits, output/parent fsync failures, pending-name removal failure, owned-receipt retraction, protected foreign replacements, and uncertain cleanup/durability. Browser, device, backend, service, and subprocess tests are not added.

Run through the locked assurance runner with `PYTHONDONTWRITEBYTECODE=1`, the documented `PYTHONPATH`, `-p no:cacheprovider -q tests/acoustic/test_live_clips.py`, under a hard outer timeout. Historical private logs are not included here. Focused tests do not establish ARM64, hardware, field or release qualification.
