# File acquisition sessions and offline NEREID

This guide describes the wave-1 stdlib reference paths. Wave 2 adds a [pinned recorded MP4/H264 adapter](recorded-codec-wave2.md) and a [strict legacy-v1 segment export bridge](legacy-export-wave2.md); the PGM-only statements below apply to the original reference decoder, not the new codec adapter.

These are stdlib reference tools for local files and deterministic synthetic input. All paths are hardware-unverified. They do not open microphones, hydrophones, cameras, GPIO, servos or speakers. They do not change `RecordingManifest` v1, the replay CLI, the evidence database, or Hub imports.

## Run the reference paths

Use Python 3.11+ on a Unix host with local filesystem locking, hard links and directory `fsync`. No new package installation is needed. From the repository root:

```sh
export PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src
RUN="$(mktemp -d)"

python3 -m poseidon_acoustic.session_cli demo --output-dir "$RUN/audio"
python3 -m poseidon_acoustic.session_cli recover --session "$RUN/audio"
python3 -m poseidon_nereid.cli demo --output-dir "$RUN/video"
```

The audio demo writes four independent PCM16 WAV segments containing 8,000 synthetic frames at 8 kHz. The NEREID demo writes eight timestamped 16×12 PGM frames, captures them into a session, indexes an 8×6 ROI, and copies four frames into an independent `unknown` observation excerpt. Frame 3 has an operator-declared occlusion flag. The wiper output is an in-memory simulation audit ending inhibited and de-energized.

The fixtures contain integer-generated PCM samples and grayscale patterns, not animal sounds, farm images or biological ground truth. A synthetic file stays `synthetic` when read through the file adapter.

Exercise the streaming WAV file path with a generated segment:

```sh
python3 -m poseidon_acoustic.session_cli capture-wav \
  --wav "$RUN/audio/chunk-000000.wav" \
  --output-dir "$RUN/wav-file-capture" \
  --session-id synthetic-wav-import --source-id synthetic-wav-file \
  --provenance synthetic --sample-rate-hz 8000 --channel pcm-0 \
  --source-domain synthetic-wav-seconds \
  --reference-epoch synthetic-session-start \
  --anchor-uncertainty-s 0.01 --drift-uncertainty-ppm 2
```

For a real local file, provenance, channel IDs, rate and clock relation are operator declarations. The tool records the original WAV SHA-256 and checks it again after streaming. Repeat `--channel` in WAV channel order. It supports only uncompressed PCM16 WAV and preserves channel ordering; it does not normalize, mix, calibrate or play the samples. Digital sample amplitude is not underwater SPL.

Exercise PGM capture, ROI indexing and independent excerpts:

```sh
python3 -m poseidon_nereid.cli capture \
  --frames-manifest "$RUN/video/input/frames.json" \
  --output-dir "$RUN/pgm-file-capture" --session-id synthetic-pgm-import

python3 -m poseidon_nereid.cli index \
  --session "$RUN/pgm-file-capture" --source-id synthetic-camera \
  --output-dir "$RUN/review-index" --roi 2 2 8 6 --occluded-frame 3

python3 -m poseidon_nereid.cli excerpt \
  --session "$RUN/pgm-file-capture" --source-id synthetic-camera \
  --output-dir "$RUN/review-excerpt" \
  --observation-id independent-synthetic-unknown \
  --reference-domain reference_seconds --reference-epoch synthetic-session-start \
  --start-s 0.6 --end-s 1.2 --uncertainty-s 0.03 \
  --label unknown --observer synthetic-fixture-generator
```

Every output directory must be new. Existing sources, outputs and unknown files are never overwritten or evicted. These commands create local artifacts only. `python3 -m poseidon_acoustic.session_cli live` and `python3 -m poseidon_nereid.cli live` return exit 2 before device access; there is no authorization flag that enables them.

## Acquisition records and recovery

The acquisition-owned schema family is `poseidon.acquisition-session.provisional.v1`. It is a separate sidecar contract, not a substitute for a v1 recording manifest. `Source.provenance=file` describes an input origin, not platform `field` or `bench` provenance; never infer `field` from `file`. The session limit of 16 channels/768 kHz exceeds old replay's 8 channels/384 kHz, so not every reference segment is v1-replay-compatible. No full session ingestion or automatic provenance conversion is claimed.

| File | Purpose |
|---|---|
| `session.acquisition-v1.json` | Immutable session ID, source IDs, ordered channel IDs/roles, media, provenance, optional original-input checksum, source origins, clock relations and storage limits. |
| `chunk-NNNNNN.wav` or `.pgm` | Bounded source segment bytes. WAV segments are individually readable. Each PGM segment contains one frame. |
| `chunk-NNNNNN.json` | Commit receipt: header digest, previous-receipt digest, payload digest/size, source identity, sample/frame extent, source/reference interval, endpoint uncertainties, gaps and drops. |
| `halt.acquisition-v1.json` | Durable byte-capacity, chunk-capacity or known source-error stop. |
| `segments.acquisition-v1.json` | Finalized segment/receipt hashes, per-source accounting, state and preserved-uncommitted-artifact hashes. |

Frozen `Source`, `Channel` and `ClockMap` objects prevent in-process identity edits. Both direct append and recovery validate PCM16 WAV headers/data lengths, channel count, sample rate and frame count against source/receipt metadata. PGM uses the same bounded canonical decoder in the store and NEREID. Recovery rejects changed headers, malformed/noncanonical receipts, checksum mismatches, invalid paths and final manifests that disagree with stored evidence. Hashes detect changes; they are not signatures or proof against an actor who can rewrite the whole workspace.

A chunk commits only after its payload and receipt have each been staged, file-synced, linked without replacing an existing destination, and directory-synced. Receipts form a sequence and digest chain. A nonblocking advisory lock refuses concurrent writers. The receipt is the commit point: an orphan payload or partial staging file is not silently adopted as a captured segment.

```sh
python3 -m poseidon_acoustic.session_cli recover --session /path/to/interrupted-session
python3 -m poseidon_acoustic.session_cli finalize --session /path/to/interrupted-session
```

Recovery checks all committed bytes. It retains unknown files and incomplete staging files, lists them separately, and hashes them when finalizing an incomplete snapshot. A redundant staging hard link to the same already-published inode is not a second lost segment. Failure during finalization can be retried without replacing the failed staging artifact. Corrupt committed bytes stop recovery rather than producing a usable-looking manifest.

A clean, unfinalized workspace can accept the next explicit source segment. An interrupted, capacity-halted or finalized workspace cannot resume capture by overwriting or skipping its evidence. Finalize the known committed subset and start a new session after review. `finalized` means the stored segment set is closed, not that a planned recording duration completed. Trailing extent remains explicitly unattested: loss before a receipt/staging artifact exists cannot be reconstructed. Known input failures produce `source_failed`; retained uncommitted files produce `recovered_incomplete`.

Missing units count gaps between committed sample/frame extents, including a declared late start. `dropped_units` is the declared subset of missing units; the receipt keeps unexplained missing units separate. Positive timestamp gaps also require a reason. These counts cannot reveal an unreported final buffer loss or certify hardware drop counters.

Default storage is 16 MiB and 256 chunks. The hard limits are 4,096 chunks, 16 sources, 16 audio channels and 8 MiB per chunk. The store reserves `8192 + 512 × max_chunks` bytes for finalization and accounts for existing files before appending. Capacity exhaustion writes a stop rather than deleting the oldest recording. Externally enlarged workspaces or insufficient finalization space fail closed while preserving bytes. The append path re-verifies earlier receipts and payloads; this is a bounded reference implementation, not a demonstrated real-time recorder.

Regular-file inputs reject leaf symlinks, FIFOs, sockets and device nodes. Workspace entries must be regular files and internal evidence paths are flat filenames. Use a private, operator-controlled local directory; this is not a hostile multiuser filesystem sandbox. Fault-injection tests do not validate real power-loss behavior on SD cards, network filesystems, Linux ARM64 or Raspberry Pi hardware.

## Time convention and platform mapping

Every source has distinct named source/reference clock domains and an explicit reference epoch. `reference_seconds` may mean seconds relative to a named session start; it does not imply UTC.

```text
reference_s = reference_anchor_s + (source_s - source_anchor_s) * (1 + drift_ppm / 1e6)
uncertainty_s = anchor_uncertainty_s + abs(source_s - source_anchor_s) * drift_uncertainty_ppm / 1e6
```

`drift_ppm` is the source-to-reference mapping scale. Positive values increase the reference interval for a fixed source interval; this is not an ambiguous oscillator-fast sign. The anchor difference is the declared offset. Values must be finite, scale positive, and uncertainties nonnegative. Segment intervals that lose positive duration through floating-point precision are rejected.

`ClockMap.from_relation(relation, reference_epoch=...)` maps the fields in `contracts/v1/fixtures/clock-relation.valid.json`. The fixture is tested directly: source time 10 maps to reference time 10.1201 with uncertainty 0.02005 seconds. Source/reference domains, method and evidence reference survive `relation()` unchanged. The canonical relation has **no `reference_epoch` field**. A caller must supply and preserve that context separately; the adapter never infers UTC or a session epoch. Measured/shared-clock method claims require an evidence reference but remain unverified by this tool.

## Video evidence boundary

The file decoder accepts only canonical 8-bit P5 PGM:

```text
P5\n<width> <height>\n255\n<exactly width*height binary bytes>
```

There is no MP4, H264, general PGM comment parser, codec process or live video decoder. The pixel bound is 1,048,576 pixels per image. `poseidon_nereid.cli fixture` generates a reproducible example `frames.json` using `poseidon.nereid-frames.provisional.v1`; it binds a source description to ordered frame indexes, explicit half-open source intervals, plain filenames, SHA-256 values and declared gaps/drops. File input is bounded by frame count, index size and cumulative bytes, and the index checksum becomes immutable source metadata.

`poseidon.nereid-index.provisional.v1` retains frame indexes, source/reference times, uncertainty, gaps/drops, dimensions and ROI. The ROI must fit every frame; it is never silently clamped. Quality thresholds are configurable through `QualityPolicy`: normalized mean, grayscale range contrast and clipped-pixel fraction generate named rules. These are not validated visibility, focus, smudge, fouling, species or feeding classifiers. Occlusion is `operator_declared` only for explicitly named frame indexes and otherwise `not_assessed`. Passing image rules does not establish clear biological observation.

`poseidon.nereid-excerpt.provisional.v1` accepts independent `observed_event`, `hard_negative`, `unknown` and `unusable` intervals, with an observer, domain/epoch and uncertainty. It needs no acoustic candidate. The generic `observed_event` label does not imply predation and must not silently map to a platform feeding label. The lead-owned dataset/observation import applies its own reviewed label and exposure rules.

Excerpt selection uses half-open uncertainty-envelope overlap, plus optional padding. It copies original frame bytes and retains ROI/quality metadata, rather than changing the evidence pixels. Nominal uncovered intervals remain explicit, including an interval with zero matching frames. Nominal time coverage is not verified synchronization or independently reviewed usable exposure. Default excerpt limits are 128 frames and 16 MiB, checked before output creation.

## Wiper simulation and checks

`Wiper` accepts only the in-memory `SimulatedActuator`. It starts inhibited, requires an operator enable and a simulated independent-inhibit release, and enforces wipe/cooldown times, tick-watchdog faults, declared jams, cycle count and bounded audit storage. Inhibit/stop removes simulated power; rearming cannot bypass the current cooldown. Invalid, reversed, nonfinite or numerically unusable clocks fault off. Faults latch for that simulation instance.

There is no scheduler that cuts physical power when Python stops ticking, no physical independent watchdog, no travel sensor and no hardware jam detector. Restart resets the in-memory cycle budget but starts inhibited and off. Do not substitute a real actuator: operational authorization, persistent budgets, independent power removal, electrical/travel limits and bench validation remain future work.

```sh
python3 -m unittest discover -s tests/acoustic -v
python3 -m unittest discover -s tests/nereid -v

# Fresh runs produce byte-identical fixture/session outputs.
python3 -m poseidon_acoustic.session_cli demo --output-dir "$RUN/audio-repeat"
python3 -m poseidon_nereid.cli demo --output-dir "$RUN/video-repeat"
diff -r "$RUN/audio" "$RUN/audio-repeat"
diff -r "$RUN/video" "$RUN/video-repeat"
```

The tests cover existing replay behavior, deterministic PCM across chunk partitions, WAV truncation/rate/width checks, clock fixture mapping, discontinuities, capacity stops, interrupted payload/receipt/final publication, checksums, orphan preservation, malformed JSON, NaN, path/symlink/FIFO rejection, PGM budgets, ROI bounds, independent excerpts with no candidates/frames, and simulated wiper faults. They prove software behavior only, not field synchronization, calibrated capture, biological performance, actuator safety or stock-loss prevention.
