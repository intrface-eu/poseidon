# Linux live capture software

This is a separate local `poseidon.live-capture-journal.v1` implementation. It does
not change `Session`, `ClockMap`, recorded-file codecs, or legacy export formats.
The host-fake tests exercise Python processes and files, not physical capture.

## Interfaces

- `live_models.CapturePlanV1` contains immutable source tuples, explicit resource
  limits, capture identity, actor, and an unverified approval reference. Its
  `canonical_bytes` and `sha256` bind all declarations. `from_bytes` rejects
  missing fields, duplicate keys, nonfinite values, normalization and format
  substitution. Source metadata stays canonical immutable bytes.
- Audio is exact interleaved `S16_LE`, at most eight ordered channel IDs/roles and
  384000 nominal Hz. Physical selectors are literal `/dev/snd/pcmC<number>D<number>c`
  plus an explicit subdevice and expected `pcm_id`. Period/buffer targets also
  act as lower bounds; separate maxima bound returned buffering.
- Video is single-planar even-width `YUYV`, at most 1048576 pixels, with explicit
  rational cadence, `/dev/video<number>`, expected driver/card/bus identity, at
  most eight mappings, and an aggregate mapped-byte budget. No discovery, format
  fallback, mixer, playback, camera controls, or automatic reopen is provided.
- `CaptureLimitsV1` requires duration, chunk frames/bytes, queue items, per-source
  and aggregate queue bytes, output bytes/chunks, metadata reserve, poll timeout,
  and shutdown timeout. These are software policies, not measured operating limits.
- A backend factory exposes `synthetic` and `open(source, limits, admission)`.
  Its backend implements `configure() -> canonical JSON bytes`, `start()`,
  `read(timeout_s) -> CapturedBlockV1 | None`, and `close()`. `None` means retry;
  `EndOfSource` is allowed only for synthetic fixtures. `BackendFault` retains
  error code, domain and signed native code. Blocks own immutable bytes, unit
  count, canonical raw metadata and optional uint32 driver sequence.
- `LinuxBackendFactory` requires explicit artifact, artifact hash, build hash and
  profile hash. It rechecks/consumes its worker ticket before artifact access or
  native loading. The binding's production/test-fake distinction is separate
  from this Python host-fake gate.

## Gate and runtime

The operation gate is an accidental-operation guard, not a permit validator,
physical interlock, calibration check, or hostile-code sandbox. An acknowledged
open can itself initialize hardware. OS node ACLs and separate authorization
remain necessary.

`acknowledgment_text(plan)` issues a random, process-local, 60-second challenge.
A separate exact response to that challenge can create one Linux capture-only
grant. The grant binds the plan, expires after 60 seconds and is consumed once.
The capture identity cannot be granted again in that process. Challenges/grants
are not restored from files, environment variables or prior CLI invocations.
Worker tickets are registered during grant consumption, transferred to owned
spawn processes, and consumed before native access; merely constructing a ticket
object does not issue a grant. Help, import, validation and denial do not inspect,
resolve, enumerate or open device paths, or load a native library.

The supervisor owns at most one audio process, one video process, and one
file-only journal writer process. It writes intent before spawning source
workers. All returned configurations and a start-request record must commit
before either source may start. Separate host start-return observations precede
payload receipts. Backend handles and native scratch storage belong to their
source worker. The coordinator transfers immutable payloads through bounded
queues, never native memoryviews. Queue budgets cover queued payload bytes;
fixed per-message metadata caps and bounded in-flight source/coordinator/writer
copies are additional memory costs, not a claim that RSS equals `queue_bytes`.

Queue pressure, storage limits, discontinuity, XRUN, suspension, disconnect,
malformed returns or cancellation stop the operation. Accepted queued data may
drain until the shutdown deadline; no evidence is evicted. The writer runs in a
separate process so a stalled write cannot indefinitely block the coordinator.
Owned workers receive cancellation, then bounded join/terminate/kill attempts;
no other processes are targeted. OS-uninterruptible I/O is not a real-time or
power-loss durability guarantee. If the writer cannot seal, the result explicitly
reports `finalized=false`; later file-only recovery is required.

The coordinator requires the main thread. It installs SIGTERM/SIGINT handlers
before creating resources; handlers only latch a signal, including during spawn
and cleanup. It registers each worker before starting it, observes cancellation
at safe boundaries, and attempts every owned cleanup before restoring the prior
handlers. Repeated signals do not interrupt that cleanup. The CLI returns nonzero
whenever `owned_workers_reaped=false`, even if the writer produced a valid seal.

## Journal and evidence meaning

The writer reserves actual metadata space and creates a new private directory.
File reads reject nonregular artifacts before open and recheck descriptor identity.
Recovery releases `.reserve` only after checking its regular type, exact size and
zero-filled contents; mismatched replacements remain untouched and block sealing.
Payload bytes are fsynced and published without replacement, then a chained
receipt is fsynced and published. The receipt is the commit point. Append uses
incremental counters/hashes, not a history rescan. Finalization or recovery
performs one integrity scan and seals only the verified stored prefix.

A fixed regular `.owner.lock` holds a nonblocking exclusive `flock`. Recovery
acquires it before scanning or sealing and refuses an active owner. During actual
`Process.start`, `DupFd` transfers the same locked file description to the writer;
the parent keeps only a passive lease and permanently loses mutation authority,
including after failed startup. It closes that lease after all child cleanup
attempts. Release uses close, never `LOCK_UN`, so a live duplicate stays locked.
Stopped or crashed owners permit prefix recovery once all duplicates close.
Directory/lock replacements and already-finalized stale writers cannot mutate the
journal. Locks are cooperative local-process ownership, not a hostile-code sandbox.

`verify_live_journal(path)` is a bounded, file-only local-directory verifier, not
a remote upload resolver. Its frozen result contains counts, prefix hash,
source positions, orphan names, integrity status and canonical final bytes.
`LiveJournal.recover(path)` does not resume capture, adopt orphans, repair corrupt
receipts or delete partial evidence. Payloads without receipts, interrupted
publication files and corrupt trailing records remain on disk. The final record
binds the orphan inventory hash/count and lists its first 64 names; the verifier
returns the complete bounded inventory. An invalid existing final is retained,
not silently replaced.

Unknown UTC, physical uncertainty, exposure, clock relation, physical loss and
source trailing extent remain null. Nominal positions are stored-unit counts,
not measured ADC time or camera exposure. Driver-reported accuracy, including a
reported zero, remains a raw claim. Repeated or absent timestamps are preserved;
no intermediate timestamps or physical synchronization are inferred. Observed
queue-rejection counts are separate from unknown total application/physical loss.
Even a normally closed writer does not prove planned-duration or physical capture
completeness. Every fake provider is synthetic with `device_access_occurred=false`.
No live-to-legacy or Hub admission mapping is supplied here.

## Host-fake checks

The initial Darwin/Python 3.14.7 run covered 44 tests, with no skips, including
zero-I/O denial, challenge/grant freshness, immutable models,
spawned audio/video workers, short reads/retries, queue pressure, cancellation,
stalled source/writer shutdown, timestamp/null semantics, sequence wrap/gaps,
checksums, retained orphans, and real process interruption after payload,
receipt and final publication.

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src \
python3 -m unittest discover -s tests/acoustic -p 'test_live_[jms]*.py' -v
```

The suite runs the actual `synthetic-demo` CLI in an owned subprocess with a
15-second hard timeout. Its fixed 8000-Hz mono values belong only to the named
host fixture and are not physical-plan defaults. `validate --plan <file>` is
file-only. A future separately authorized native attempt uses `capture` with
`--ack-prompt` on a Linux local terminal, a new canonical plan/output directory,
and all artifact identity arguments; persisted `--ack` text does not rearm it.
No device operation was used to obtain these test results.

`test_live_lifecycle.py` adds real synthetic subprocess checks for both signals
during capture and spawn, repeated signals during cleanup, startup/cleanup
failures, handler restoration, writer crash-release, active recovery refusal and
stale parent mutation. Each fixture has a hard deadline and an exact owned process
group; it checks that no writer, source or resource tracker remains after exit.
Run it with the journal/supervisor/models tests through
`scripts/assurance/run_pytest.py -p no:cacheprovider` in the existing locked pytest
lane. These lifecycle checks do not qualify native libraries or devices.

## Remaining gates

1. Establish the root-approved Linux/ARM64 image and actual compiler, libc,
   UAPI/ALSA development/runtime, Python and artifact/build/profile identities.
   Compile/link the production C source and run its separate non-skipping Linux
   ABI and injected-provider tests. Darwin host fakes do not satisfy this gate.
2. Supply the actual capture chain, exact node/driver identities, supported native
   mode and least-privilege ACLs. Obtain separate authorization before any
   enumeration, query, open, capture, unplug or restart trial. This implementation
   does not grant those actions.
3. Measure sustained throughput, USB/driver faults, clock/ADC/camera latency,
   exposure/synchronization uncertainty and storage/power-loss behavior. Physical
   calibration, site permission and scientific qualification remain unestablished.
