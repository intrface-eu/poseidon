# Recorded MP4/H264 acquisition, wave 2

This adapter decodes real local recorded MP4/avc1 H264 into source-bound PGM8 frames and uses the existing acquisition session, NEREID index and independent excerpt code. PGM remains the stdlib reference format; it is no longer the only recorded-video input. The earlier `session-and-video.md` statement that there is no MP4 decoder describes wave 1.

This is software-only evidence. Nothing here opens a device, camera, microphone, speaker or network media source. There is no species, feeding, visibility or fouling classifier, brightness calibration, field synchronization claim or hardware approval.

## Locked environment and interpreter boundary

From the repository root, with an installed Python 3.12 and uv:

```sh
ROOT="$PWD"
uv sync --project "$ROOT/apps/nereid" --locked --python 3.12 --no-python-downloads
export PYTHONPATH="$ROOT/libs/proto-py/src:$ROOT/apps/acoustic/src:$ROOT/apps/nereid/src"
CODEC_PYTHON="$ROOT/apps/nereid/.venv/bin/python"
"$CODEC_PYTHON" --version
uv lock --project "$ROOT/apps/nereid" --check --offline
```

`apps/nereid/pyproject.toml` pins `av==16.1.0` and Python `>=3.12,<3.13`; `uv.lock` records wheel hashes. `tool.uv.no-build=true` refuses a source-build fallback. A missing compatible wheel is a blocker, not permission to install or repair global FFmpeg. No system `ffmpeg` executable is used.

The tested host used Python **3.12.13**, PyAV **16.1.0**, macOS arm64, Darwin 25.6.0. Its wheel is `av-16.1.0-cp312-cp312-macosx_14_0_arm64.whl`, SHA256 `ae3fb658eec00852ebd7412fdc141f17f3ddce8afee2d2e1cf366263ad2a3b35`.

The parent adapter and old PGM modules do not import PyAV. The owned worker launches with **`sys.executable`**, not an interpreter found on PATH. It requires Python 3.12 and the pinned PyAV version. An API environment without PyAV can import the adapter but cannot call decode/fixture in-process: the worker returns an explicit dependency error. There is no auto-install, fallback decoder or silent test skip. An API integration must invoke the CLI with the absolute `apps/nereid/.venv/bin/python` path and the source import paths above. It must not copy PyAV into the API environment implicitly.

## Reproduce the actual codec path

Every output directory must be new. Review outputs must also stay outside their source bundle/session, including resolved symlink-parent aliases; otherwise adding a directory could invalidate a finalized source inventory. Both index CLIs and both excerpt APIs enforce this boundary. These commands generate synthetic files only; use a separate private directory for real recorded evidence.

```sh
RUN="$(mktemp -d)"
"$CODEC_PYTHON" -m poseidon_nereid.codec_cli fixture --output-dir "$RUN/input"
"$CODEC_PYTHON" -m poseidon_nereid.codec_cli decode \
  --input "$RUN/input/synthetic.mp4" \
  --declaration "$RUN/input/declaration.codec-v1.json" \
  --output-dir "$RUN/bundle" --session-id synthetic-recorded-codec-wave2
"$CODEC_PYTHON" -m poseidon_nereid.codec_cli index \
  --bundle "$RUN/bundle" --output-dir "$RUN/index"
"$CODEC_PYTHON" -m poseidon_nereid.codec_cli excerpt \
  --bundle "$RUN/bundle" --output-dir "$RUN/excerpt" \
  --observation-id synthetic-independent-unknown \
  --reference-domain reference_seconds --reference-epoch synthetic-codec-epoch \
  --start-s 10.04 --end-s 10.12 --uncertainty-s 0 \
  --label unknown --observer synthetic-recipe-v1
```

The real encoder is bundled **libx264**, one thread, CRF 18, medium preset, two B frames, fixed B adaptation and disabled scene-cut insertion. It encodes six 32×24 integer-pattern frames with input PTS `[2000,2040,2100,2120,2200,2240]` at `1/1000`. The MP4 contains an explicit SYNTHETIC title and the fixture writes a separate recipe. There is no farm/animal imagery or biological ground truth.

The decoded stream retains PTS `[32000,32640,33600,33920,35200,35840]` at `1/16000`, not a zero-based constant-FPS approximation. Presentation frames associate with encoded sample indexes `[0,2,3,1,5,4]`; B-frame reordering does not change that association. The CLI run above indexes six frames and copies four into the excerpt because the declared clock uncertainty expands the observation selection.

## Explicit time and provenance declaration

For a recorded file, supply `poseidon.nereid-codec-declaration.provisional.v1`. The fixture declaration is a complete example; do not relabel it as field evidence. Required fields are:

- `source_id`, the original encoded file's `source_sha256`, and the **absolute container `stream_index`**. Index 1 means stream 1, not the second video stream found by a filter.
- `provenance` (`synthetic` or `file`) and a bounded `origin` description. `file` does not mean `field` or calibrated.
- Every `ClockMap` field: source/reference domains, explicit reference epoch, both anchors, drift, both uncertainty terms, method and nullable evidence reference. A nonzero PTS is not an epoch. Container dates, average rate and filenames never imply UTC.
- `infer_intervals_from_next_pts`, an explicit boolean; a rational `max_frame_interval_s`; and `duration_attestations` containing rational `pts_s`, rational positive `duration_s` and an `evidence_ref` for each attested frame. Rationals use `[numerator,denominator]`.

The adapter never assumes constant FPS. It requires strictly increasing decoded presentation timestamps and a unique encoded sample for every frame. It rejects missing/repeated/backwards PTS, missing packet DTS, discarded/extra frames, ambiguous sample association and unsupported edit lists. It does not repair order by sorting or remove duplicates.

Interior intervals may end at the next PTS **only when inference was explicitly enabled**, within the declared interval bound. They are marked `inferred_next_presentation_pts_not_exposure`. A timestamp interval is not camera exposure or independently assessed usable observation. In VFR media, a long hold and a lost interval can be indistinguishable: reject the file or supply shorter attested intervals when the inference is not justified. The final frame always needs an explicit duration attestation; the adapter does not substitute FPS or container/decoder duration. Attestations remain `operator_attested_unverified`, with their evidence reference retained.

A shorter attested interval leaves an uncovered gap and records that missing-frame count is unknown; the adapter does not invent dropped-frame counts. Overlaps and durations above the declared bound fail. Raw packet duration and decoder frame duration remain separately recorded because, with B frames and VFR, they need not equal a presentation hold. The synthetic recipe attests the final frame's duration as `1/50` second.

Exact PTS/time bases, source endpoints and durations remain rational in the codec sidecar. The unchanged session model uses floats. The bridge records each endpoint's exact float-projection error, rejects errors above one nanosecond and rejects intervals that collapse in either source or reference time. This numeric bound is not a statement of physical timestamp accuracy.

## Source binding and grayscale transformation

The bundle contains:

| Artifact | Binding and meaning |
|---|---|
| `source.mp4` | Byte-identical copy of the original encoded container. The original source is read-only and its SHA256 is checked before and after decoding, including failure paths. The archive is also checked. |
| `declaration.codec-v1.json` | Canonical copy of the explicit source, clock and duration declarations. |
| `mapping.codec-v1.json` | Versioned codec map binding original hash/length, stream/track index, original dimensions, edit list and raw sample-table timing, demux PTS/DTS/time bases, byte offsets/sizes and encoded-sample hashes, emitted-frame hashes, transformation, exact timing and decoder environment. |
| `frame-NNNNNN.pgm` | Canonical P5 PGM8 derivative at the original decoded width/height. |
| `frames.json` | Existing wave-1 PGM manifest. Its source origin binds the codec-map SHA256; its own digest becomes the immutable session input digest. |
| `session/` | Existing acquisition session with PGM chunk receipts, clock mapping and finalized hash chain. `session.py` is unchanged. |

The transform `decoded-y-plane-to-pgm8.v1` copies rows from the decoded **8-bit Y-prime plane**, removes stride padding and discards chroma. It does not normalize range, resize, rotate, apply display matrices, linearize gamma or calibrate color/brightness. Original pixel-format, colorspace, range, transfer/primaries codes and the unapplied track matrix remain recorded; unspecified codes stay unspecified. A limited-range input remains limited-range luma codes in PGM, not a normalized grayscale rendering.

**PGM frames are not the original full-color bytes.** Only `source.mp4` preserves those encoded bytes. The derivative source/channel description, transform and codec review sidecars say so explicitly.

`build_codec_index` verifies the original container, codec map, PGM manifest, PGM bytes and existing finalized session before using `build_index`. `export_codec_excerpt` calls the old excerpt exporter and adds `excerpt.codec-v1.json`. The latter retains the selected exact codec mappings and the original source hash; the full MP4 is **not** copied into excerpts. `requires_source_bundle=true` and `source_container_included=false` make that dependency explicit. Codec-mapping `path` values name frames in the source bundle; join them to the copied `chunk-NNNNNN.pgm` paths in `excerpt.nereid-v1.json` by `frame_index` and SHA256. A matching observation needs the same declared reference domain and epoch and can select zero frames.

Hashes detect mutation; they are not signatures or protection against an actor who can rewrite the whole evidence chain. Use private operator-controlled local directories, not a hostile shared-filesystem workspace.

## Input and process bounds

The adapter accepts nonfragmented, self-contained MP4 with an `avc1` H264 selected track and decoded 8-bit `yuv420p`. It checks MP4 box extents, sample tables/counts, local `mdat` byte ranges, track identities, data references and edit structure before native parsing. It supports one sample description per track, one playable edit plus an optional initial empty edit, and one picture per selected sample. It rejects external references, fragmented/size-to-EOF boxes, other selected codecs/depths/pixel formats, in-band parameter changes and midstream dimension changes. It is not a general media player. Nonselected tracks are not emitted or offered as new decoder formats.

| Bound | Default | Hard maximum |
|---|---:|---:|
| Encoded input | 16 MiB | 32 MiB |
| Container streams | 4 | 4 |
| Selected decoded frames | 128 | 256 |
| Total sample/table entries | 4,096 | 4,096 |
| Width or height | 1,024 | 2,048 |
| Pixels per frame | 1,048,576 | 1,048,576 |
| Track/decode/presentation duration | 60 s | 120 s |
| Bundle storage, including archive and session copies | 64 MiB | 128 MiB |
| Native worker wall time | 15 s | 30 s |
| RSS watchdog threshold | 512 MiB | 1 GiB |
| Codec-map / worker-result JSON | 2 MiB | 2 MiB |

The storage admission check reserves three 2 MiB metadata/scratch allowances plus 8 KiB before native work. Actual session storage uses the remaining budget; no evidence is evicted. A failed decode may leave its newly created archive/partial PGM bundle for inspection, but no successful frame/session bridge is returned. Existing directories and source bytes are never overwritten. Transient owned job directories are removed after the process is reaped.

Only bounded regular-file bytes reach `av.open`, through an in-memory file object with the MOV demuxer fixed. Device/protocol path spellings fail before file access; leaf symlinks, FIFOs, sockets and nonregular inputs fail before native decoding. External `io_open` calls are denied and the protocol whitelist is empty. No media URL or device string is passed to FFmpeg.

The owned process has one codec thread, no core dump, bounded CPU time, file size and file descriptors. FFmpeg's maximum single allocation is 16 MiB; H264 receives `max_pixels` and strict bitstream/buffer/error options. Access-unit checks bound NAL count and reject multiple pictures per sample before PyAV can return a large frame list. The parent samples the owned PID's RSS every 10 ms and kills/reaps that exact process on memory, timeout or supervisor failure. There is no process-name sweep or service management.

Linux also sets `RLIMIT_AS` to twice the RSS threshold. macOS does not provide that usable address-space limit here: its RSS watchdog is sampled, **not an atomic memory cap**. This process boundary is not a native-code exploit sandbox. Hostile-media security isolation, atomic macOS memory containment and Linux/ARM64 qualification remain open; tests here do not prove them.

## Native build and verification

The loaded macOS wheel reports:

| Native library | Version |
|---|---|
| libavcodec | 62.11.100 |
| libavformat | 62.3.100 |
| libavutil | 60.8.100 |
| libavdevice | 62.1.100 |
| libavfilter | 11.4.100 |
| libswscale | 9.1.100 |
| libswresample | 6.1.100 |

The worker checks `dladdr` locations for libavcodec/libavformat/libavutil and refuses libraries outside the pinned wheel's `.dylibs`/`av.libs` directories. The map records these relative paths and the full native build configuration. This wheel compiles hardware-related libraries, but the adapter chooses the software `h264` decoder, sets one thread and never supplies a hardware accelerator or device. Having libavdevice installed is not live capture. `avcodec_license()` reports `LGPL version 3 or later`; bundled libx264 and distribution/codec licensing still need release review. No licensing approval follows from these tests.

Run all codec and wave-1 regressions in the explicit codec environment:

```sh
"$CODEC_PYTHON" -m unittest discover -s tests/nereid -v
"$CODEC_PYTHON" -m unittest discover -s tests/acoustic -p test_session.py -v
```

Recorded results on 2026-09-08: **64 NEREID tests passed** (31 codec tests, 33 PGM/wiper tests including the new source-containment regression), **41 acquisition session tests passed**, exit 0. `uv lock --check --offline` passed. The codec suite uses the real bundled encoder/decoder; missing PyAV is a test error, not a skip. It also creates an empty owned Python environment to prove a caller without PyAV gets an explicit error instead of another interpreter or decoder.

Tests cover real VFR/nonzero PTS/B-frame association and raw byte offsets, a real second H264 stream, repeat-byte determinism, declared versus inferred intervals, missing/repeated/backwards/unrepresentable times, attested gaps, sample-table counts/offsets, corrupted H264, truncated/wrong/fragmented containers, external references, dimensions/bytes/frames/duration/storage limits, owned-process timeout/RSS cleanup, immutable source checks, review-chain corruption, no device/URL input and excerpt budget/epoch boundaries. They do not use biological calibration or a classifier.

Retained CLI evidence is under `apps/nereid/fixtures/recorded-codec-wave2/`: `input/`, `bundle/`, `index/`, `excerpt/` and `artifacts.sha256.json`. The manifest covers 35 generated files totaling 65,477 bytes, excluding itself. Each of fixture/decode/index/excerpt exited 0. Original synthetic MP4 SHA256:

```text
2eb6715d3125c0d3e9df06b0a06c87eddee49546294da9acf7581bdeeb34d597
```

Fresh generation and repeated decoding produced identical bytes within this pinned host/native build. Cross-platform bit identity is not claimed. Existing wave-1 data artifacts, reports and hash manifests were not rewritten. The only wave-1 source change adds the review-output containment guard and its regression; PGM/session behavior otherwise stays unchanged. Root/API integration, broader recorded-camera compatibility, permissioned field data, measured clocks, optical calibration, biological performance and hardware remain separate gates.
