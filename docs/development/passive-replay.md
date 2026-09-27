# Passive WAV replay

This slice replays an existing WAV through a local normalized-amplitude detector. It does not import capture or device APIs, play audio, contact a service, classify a species, identify a predator, or validate shell-crack detection.

The detector is uncalibrated. Its peak and RMS values are normalized PCM16 full-scale amplitude, not sound pressure level (SPL). It applies no frequency filter because the useful local band has not been measured.

## Run the synthetic demo

From the repository root, use the Make target on a clean checkout:

```sh
make sim
```

The Make target creates the ignored `.local` parent before it invokes the CLI. For a direct CLI run on a clean checkout, create that real parent directory first:

```sh
mkdir .local
PYTHONPATH=libs/proto-py/src:apps/acoustic/src \
  python3 -m poseidon_acoustic demo --output-dir .local/demo
```

The demo creates `.local/demo` only when the path is new or an existing empty directory. It refuses a symbolic link, file, or nonempty directory. It never deletes or overwrites an artifact. Choose another clean directory for another run:

```sh
make sim OUTPUT_DIR=.local/demo-2
```

The demo writes:

- `synthetic.wav`: deterministic mono PCM16 data with two separated high-amplitude regions.
- `recording-manifest.json`: a version 1 manifest marked `provenance: synthetic`.
- `evidence.sqlite3`: the local evidence store.
- `events.ndjson`: two example candidate records.

The demo performs no playback. Its WAV exists only as replay input. Synthetic provenance is reserved for this demo and test data, not field evidence.

## Replay a WAV

A replay requires an existing WAV and matching manifest:

```sh
PYTHONPATH=libs/proto-py/src:apps/acoustic/src \
  python3 -m poseidon_acoustic replay \
  --wav PATH/recording.wav \
  --manifest PATH/recording-manifest.json \
  --database PATH/evidence.sqlite3 \
  --threshold 0.2 \
  --window-ms 20
```

The supported input is an uncompressed little-endian RIFF/WAV containing 16-bit PCM, one through eight channels, and a sample rate from 1 through 384000 Hz. Replay checks the full file SHA-256, complete PCM frame count, frame alignment, header values, sample width, compression, and channel cap before it starts a database transaction. The file is hashed again through the same open file handle after analysis; a changed source is rejected.

`threshold` is finite and in `(0, 1]`. `window-ms` is finite and in `(0, 10000]`. Windows are fixed, adjacent, and non-overlapping. A window is active when the maximum per-channel normalized RMS meets the threshold. Per-channel analysis prevents antiphase stereo channels from cancelling each other. Adjacent active windows form one candidate. `end_frame` is exclusive, including an event that ends in a partial final window at EOF.

The default detector is only a replay baseline. A new threshold or window setting gets a different config and run identity.

## Recording manifest version 1

The manifest is a JSON object with exactly these fields:

| Field | Rule |
| --- | --- |
| `schema_version` | Integer `1`; booleans are rejected. |
| `recording_id` | Nonempty safe identifier. |
| `site_id` | Nonempty safe identifier. |
| `zone_id` | Nonempty safe identifier. |
| `device_id` | Nonempty safe identifier. |
| `started_at` | Timezone-aware RFC3339 timestamp. |
| `provenance` | `field` or `synthetic`; synthetic is for demo and test data. |
| `wav_sha256` | Exactly 64 lowercase hexadecimal characters. |
| `calibration_status` | `uncalibrated` only. A future calibrated schema needs evidence from a real calibration chain. |

Safe identifiers start with a letter or digit and then use letters, digits, `.`, `_`, or `-`.

## Candidate evidence

Each version 1 event includes recording, site, zone, and device identity; `event_type: acoustic_candidate`; `source: replay`; provenance; start and exclusive end frames; time offsets; sample rate and channel count; maximum normalized peak and RMS summaries; explicit normalized PCM16 units; uncalibrated status; detector, config, and run identity; and `emission_enabled: false`.

The event has no species label, predator claim, biological threshold, confidence score, calibrated SPL, or emission result.

## Examine stored results

Read an existing store as deterministic JSON Lines:

```sh
PYTHONPATH=libs/proto-py/src:apps/acoustic/src \
  python3 -m poseidon_acoustic events --database PATH/evidence.sqlite3
```

The command errors if the database is missing. It does not create or adopt an unrelated SQLite file. A recording ID stays bound to its canonical manifest, content hash, and site, zone, and device context. Replaying the same manifest and config verifies and reuses the exact stored run. It does not overwrite prior evidence. A different config creates a different run.

The SQLite file is local only. Keep the source WAV, manifest, and database together when retaining evidence. JSONL output preserves the `synthetic` or `field` marker.

## Local checks

```sh
PYTHONPATH=libs/proto-py/src:apps/acoustic/src \
  python3 -m unittest discover -s tests/acoustic -v

make check
make test
```

## Gates before field capture

This synthetic slice does not authorize or perform field work. Before adding field capture, the project needs:

1. Approved site access and the budget needed for field work.
2. A named capture device and channel layout with recorded hardware provenance.
3. A measured calibration chain before any SPL field or `calibrated` status is accepted.
4. Local acoustic measurements before choosing frequency bands or biological thresholds.
5. A data retention, review, and access plan for field recordings.
6. Separate safety and permission review for any active emission system.

These gates do not block the local synthetic replay and tests described here.
