# SIREN: synthetic scheduling and WAV export

This is a **simulation-only** Python standard-library implementation. It generates normalized samples, attenuates a whole buffer, reserves synthetic time, and writes files. No real output driver, speaker playback, GPIO access, device discovery, or physical-output enable option is included. Reports, state, audit entries, and reservation objects carry `simulation_only=true` and `physical_output_enabled=false`.

Digital peak/RMS is not underwater SPL. The example sine frequency is a software fixture, not a safe biological frequency or a deterrence program. Every numeric default and ceiling below is a **software test envelope ONLY**. There is no approved program catalog, calibration record, permit, acoustic efficacy result, or physical safety proof in this implementation.

## Reproduce locally

Run from the repository root with Python 3.11+ on macOS or Linux. These commands do not start a service or play audio. The demo requires a new output directory whose parent already exists; it refuses to overwrite an existing directory.

```sh
export PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src
python3 -m unittest discover -s tests/siren -v
python3 -m poseidon_siren demo --output apps/siren/synthetic-demo-run
python3 -m poseidon_siren status --state apps/siren/synthetic-demo-run/scheduler
```

An already generated example is retained under `apps/siren/synthetic-demo/`; the commands above use a different directory. Choose another unused name for each later run. The demo produces `synthetic-sine.wav`, `synthetic-report.json`, and `scheduler/{state.json,writer.lock}`. Keep the WAV beside its report: WAV PCM itself does not carry the provenance record. The 2,000 samples at 8,000 Hz contain a synthetic 440 Hz sine at input amplitude 0.8, attenuated to the configured digital bounds. The demo reserves 250 ms on an integer synthetic clock, records a startup denial and overlap denial, then stops and closes inhibited. The report includes the full audit and does not describe a field recording. `status` also performs startup inhibit and records open/close; it is not a read-only persistence operation. Failures return exit code 2 with `physical_output_enabled=false`.

The tests generate their fixtures in temporary directories. They use only synthetic samples, clocks, file fault injection, and one bounded child process that deliberately exits after a committed reservation but before its acknowledgment. No hardware mock is presented as independent safety evidence.

## DSP behavior

`poseidon_dsp.SignalSpec` accepts a sample rate, sample count, positive frequency below Nyquist, and amplitude in `[0, 1]`. It rejects booleans, nonfinite values, out-of-range values, and oversized requests before generating samples. Hard ceilings are 96,000 samples/second, 960,000 samples, and 10 seconds. `reserved_duration_ms` rounds the file duration **up**, so scheduling never understates it.

`limit_samples` accepts a bounded iterable of finite normalized samples in `[-1, 1]`. It applies one gain no greater than 1, chosen from peak and whole-buffer RMS constraints. Defaults are normalized peak 0.25 and whole-buffer RMS 0.15. Zero limits produce silence. Empty, out-of-range, nonfinite, and overlong inputs fail. This is an offline buffer attenuator, not a real-time limiter, sliding-window RMS bound, calibrated exposure controller, or driver-underrun handler.

`export_wav` rechecks samples, digital bounds, rate, and duration; it does not trust a caller-constructed result object. It writes a **new** mono PCM16 file with exclusive creation, refusing existing files and symlinks. Quantization truncates toward zero with scale 32767, so decoded normalized peak/RMS cannot rise. Write failures propagate; a partial WAV may remain, with no returned completion report. File export alone is offline math and does not grant a scheduler reservation or output authorization.

## Scheduler behavior

`poseidon_siren.Scheduler.initialize(new_directory, Budget(...))` explicitly creates a simulation workspace. `Scheduler(existing_directory)` never recreates missing state. Both must be used as context managers. A workspace uses one process-level exclusive `flock`; operations on an instance also serialize across threads.

| Setting | Default | Meaning |
|---|---:|---|
| `window_ms` | 10,000 | Width of every rolling accounting window |
| `max_on_ms` | 1,000 | Maximum reserved time intersecting any such window |
| `max_burst_ms` | 500 | Maximum duration of one reservation |
| `cooldown_ms` | 1,000 | Required gap **after the prior reserved end**, not its start |

Configuration uses integers, rejects booleans/nonfinite values, and requires `max_burst_ms <= max_on_ms <= window_ms`. Hard ceilings are one day for window/cooldown and 10,000 ms for a burst. Configuration is immutable; opening with a different `expected_config` faults rather than migrating or expanding it.

The caller supplies **synthetic integer milliseconds**, in `[0, 10^12]`, on one nondecreasing timeline stored in the workspace. These are not wall time, host uptime, measured clock health, or trusted elapsed time. Floats (including NaN/infinity), negative values, overflow, and a clock lower than the persisted last value latch inhibit and a fault. A restart does not start this timeline at zero. Deliberately advancing the synthetic clock advances simulated budget expiry; that is not a physical safety control.

The state machine has inhibited, simulation-rearmed, and faulted states. It has no physical-emitting state.

- Every open durably records startup inhibit. Rearm requires `rearm_simulation(now_ms, acknowledge_simulation_only=True)`. It cannot clear a fault.
- `request(now_ms, duration_ms)` grants only a reservation. It commits the full interval `[now_ms, now_ms + duration_ms)` before returning. It rejects overlap even at an unchanged clock value and checks cooldown against the reserved end.
- Window accounting uses interval intersections, not start counts or only elapsed time. It evaluates all extrema of the rolling occupancy function across prior and proposed intervals, including the proposed future duration. Integer arithmetic avoids rounding allowances.
- `stop`, `close`, and faults inhibit. None refunds or shortens a reservation, even if the simulated operation stops immediately or never exports its file. Explicit rearm retains every reservation and cooldown.
- Budget/overlap/inhibit denials are audited and do not themselves latch a fault. Invalid clock/duration, injected simulation fault, storage failure, and capacity exhaustion do. The first persisted control fault cannot be cleared by rearm or restart.

There is **no budget-clear, clock-reset, fault-clear, automatic-rearm, or config-migration API**. Normal restart retains the entire reservation history, last clock, configuration, and audit, then inhibits. History does not silently expire from storage: old intervals cease contributing to a particular rolling window through the interval math alone. The bounded prototype faults at 128 reservations or when its 512-entry audit fills; it never drops old records to make room. The state envelope is capped at 1 MiB. Even repeated `status` opens consume audit capacity.

## Persistence and recovery policy

A SHA-256 checksum covers a canonical JSON payload. Startup checks exact fields, types, version, simulation flags, configuration, clock order, reservation/cooldown/window consistency, and agreement between grants and reservation audit entries. Duplicate keys, nonfinite JSON, malformed/truncated/oversized files, checksum mismatch, symlinks, missing files, and a busy writer lock prevent startup. Rejected state is left for inspection, not replaced with an empty budget. The live writer also checks for external state changes before each write and refuses to overwrite them.

Each mutation writes a same-directory temporary file, flushes and fsyncs it, atomically replaces the snapshot, then fsyncs the directory. No reservation acknowledgment or successful rearm returns before this completes. A write failure inhibits the current instance and raises `SirenFault`. If storage later allows a fault snapshot, it retains even an unacknowledged reservation conservatively. A crash after committed reservation persistence but before acknowledgment still leaves that full interval charged on restart.

If disk failure prevents saving a fault, software cannot promise a durable fault record. Startup inhibit still applies on the next open, and the last valid committed budget is retained. If replacement occurred but directory fsync failed, the current instance refuses further writes against its uncertain snapshot; restart reads and validates whichever durable snapshot survived. The test covering that branch observes the replaced reservation retained and overlap blocked after explicit simulation rearm. A missing or corrupt snapshot has **no automatic recovery**. Preserve it for inspection and treat that workspace as faulted.

Only a deliberately **new, separate simulation workspace** can begin a fresh test history. That is not a reset for an operating device, and separate workspaces do not share budgets. The checksum detects accidental corruption; it is not authentication, anti-rollback storage, or protection against an operator editing and rehashing history. Filesystem durability, storage hardware, hostile modification, process signals during every instruction, and target Linux/Pi behavior are not qualified by these tests. The implementation must not be attached to an output device.

## Provisional independent physical inhibit contract

**Documentation/proposal only.** Hardware and firmware owners must review the eventual physical interface. No wiring, pinout, timing value, voltage level, watchdog implementation, independent inhibit mock, or physical release handshake is implemented here.

| ID | Proposed requirement | Evidence still needed |
|---|---|---|
| I1 | Independent hardware must hold the output stage inhibited on power-up, host reset, software absence, loss of supervision, or loss of its own supply where practicable. A persisted software rearm must not release it. | Reviewed circuit/failure analysis and physical fault-injection measurements. |
| I2 | A local physical stop must inhibit the output stage without relying on this process, its clock, network, scheduler, or database. Stop must latch until an explicit reviewed local recovery procedure. | Independent stop-path and power-stage measurements, including stuck host/output commands and wiring faults. |
| I3 | Any future release handshake needs explicit state/feedback agreement, bounded validity, and a reviewed fail-silent response to disagreement or stale supervision. There is no proposed automatic release based on these simulation flags. | Hardware/firmware contract, accepted fault model, specialist-set timing bounds, and hardware-in-loop tests. |
| I4 | End-to-end electrical limits, pressure/exposure measures, particle-motion assessment where needed, and non-target protection require separate engineering and ecological evidence. | Calibrated chain measurements, uncertainty, approved test conditions, permissions, and controlled safety/efficacy review. |

A mock or a passing scheduler test cannot prove any I1–I4 requirement. No digital amplitude, software time budget, or fixture frequency substitutes for those gates. Monitoring remains separate from any future acoustic intervention authorization.
