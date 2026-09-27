# Development monitor target

This slice implements a real single-owner FreeRTOS worker and `ESP_TIMER_TASK` one-shot timer around the existing REEF `Runtime`. It is a development application, not an operational field node. Host tests execute the actual monitor, NVS adapter, runtime, codec, and target entry point against explicitly synthetic SDK ABI fakes. Target compiles remain firmware-lead-owned; neither profile was executed on hardware by this child.

## D1. Files and interfaces

- `firmware/esp-idf/include/poseidon/monitor_task.hpp` and `src/monitor_task.cpp`: `MonitorTask`, checked `EspMonotonicClock`, `checked_monitor_delay_us`, and `NoProviderSensor`.
- `firmware/monitor-target/`: separate PlatformIO/CMake application, fixed development partition CSV, SDK defaults, and actual `app_main`.
- `tests/firmware/monitor_task_cases.cpp` and `abi_monitor/**`: bounded deterministic task/timer/NVS interleavings linked to actual product implementations, not a replacement `MonitorTask`.
- `tests/firmware/test_monitor_task.py`: compiler/runner and target configuration checks.

`MonitorTask(bool enabled=false)` is a noncopyable handle. `start(Config)` returns `MonitorError::none` when worker creation was accepted, **not** when NVS or runtime startup succeeded. `snapshot()` supplies bounded local diagnostic status. `request_stop()` is an atomic, asynchronous request; it never calls the SDK or deletes a task. The destructor also only requests stop with atomics. The worker's fixed one-second maximum notification wait observes stop requests; no output/actuator emergency-stop latency is claimed.

A handle may be destroyed after its member calls finish while its worker is still stopping. The worker and callbacks never retain the handle address or caller-owned sensor/storage references. As with any C++ object, callers must not destroy a handle concurrently with another thread executing one of that handle's member functions.

The single process-lifetime slot owns `NvsBootIdentity(true)`, `NoProviderSensor`, `Runtime`, clock, timer handle, and synchronization state. It is placement-constructed only by an enabled valid first start, never freed or reused. A second start or another facade cannot take that slot or stop its owner, even after a clean stop or task-creation failure. Recovery requires a new boot/process, not an automatic restart loop.

## D2. Disabled and persisted profiles

`monitor_disabled` is the default. Its `app_main` calls the actual monitor with a false build-time gate. Constructor, disabled start including invalid configuration, stop, snapshot, frame-peek rejection, and destruction call **zero application SDK/FreeRTOS interfaces**. The enabled control and NVS allocator are not constructed on that path. This does not assert that ESP-IDF's own chip startup performs no hardware operations; no target was run.

`monitor_persisted` fixes `POSEIDON_MONITOR_PERSISTED=1` at compile time and calls the actual worker-creation path. The same worker opens existing NVS, starts/allocates through `Runtime`, polls, arms/stops/deletes the timer, and closes NVS. `app_main` does not open storage on a different owner task. The profile cannot run usefully without independently commissioned valid storage. There is no remote gate setter, commissioning, erase/reseed/reset fallback, or in-memory identity substitute.

The new CSV adds only `reef_state,data,nvs,0x3f0000,0x10000`, ending at `0x400000`, to the development 4 MiB A/B layout. The existing reference project remains untouched and its board definition is reused read-only. This is not a production flash budget or permission to write/flash a partition table or NVS image.

Required existing state is the persistence adapter's 32-byte development `RNVS` record under `reef_boot/identity_v1`: format version 1, commissioned marker 1, reserved zeros, little-endian uint64 floor and complement, and little-endian CRC-32/ISO-HDLC over bytes 0..23. CRC uses reflected polynomial `0xedb88320`, initial/final XOR `0xffffffff`, reflected input/output. A marker and checksum are not authenticated commissioning. Existing floor zero may advance to one; normal firmware never creates that baseline or emits boot zero. Missing, erased, corrupt, exhausted, or uncertain state stops startup.

All NVS validation/allocation/cleanup semantics belong to `NvsBootIdentity`; the monitor calls its public interface on one worker and keeps primary monitor SDK/journal errors separate from cleanup errors. NVS internal recovery, early writes, wear, and coherent old-flash rollback are not turned into hardware durability or rollback-resistance guarantees by this wrapper.

## D3. Timer and shutdown lifetime

The pinned implementation is ESP-IDF 5.3.1 `components/esp_timer/src/esp_timer.c`. Its `esp_timer_delete` queues `EVENT_ID_DELETE_TIMER` at lines 289–314; it is not a callback join. Dispatch copies callback/argument, unlocks, then invokes at lines 453–457. A callback may therefore have been selected before stop but enter after an application's zero-in-flight observation.

The monitor does not rely on deletion joining callbacks:

1. Callback registration precedes its final open-gate check. The callback uses bounded atomic operations and only calls `xTaskNotifyGive`; it performs no clock read, NVS, sampling, queue mutation, logging, or encoding.
2. Worker shutdown closes the notification gate, stops the timer, and waits for already registered callbacks that could have observed the open gate. It does not delete its task while a notifier can still use the task handle.
3. If notifications do not drain within eight bounded grace iterations, status becomes `retained_shutdown`. The one worker and static context remain alive with notifications disabled and bounded waits. They are never freed merely because a caller or shutdown grace expired. Cleanup can finish if the notifier eventually returns.
4. A selected-but-not-entered callback can arrive later, but its argument still names the process-lifetime context and its final gate check is closed. It makes no SDK notification to a deleted worker.
5. After drain, the worker requests timer deletion and closes its own NVS allocation. Only the worker self-deletes via `vTaskDelete(nullptr)`; no external task/context deletion exists.

Timer stop/deletion or NVS cleanup failure publishes `retained_fault` and bounded retained-resource diagnostics. At most one monitor task/control/timer slot can exist; failed cleanup is not reported as full release. Timer callbacks remain gated off. There is no unbounded stream of replacement tasks or contexts.

Live snapshot fields are individually atomic 32-bit diagnostics, not a seqlock over racing non-atomic data and not a transactionally coherent multi-field sample. Mirrors saturate and set `diagnostic_saturated` if the existing runtime's uint64 counters exceed their display width. `peek_stopped` copies the full oldest queued frame only after terminal worker state; there is no mutable queue access or pop operation.

## D4. Scheduling and absent providers

`EspMonotonicClock` checks signed `esp_timer_get_time` before converting microseconds to seconds and rejects regression at microsecond precision, including regression within the same whole second. Failed reads leave output arguments unchanged. Clock output is always unsynchronized with null UTC. Uptime is never converted to an observed UTC time.

One-shot delay calculation checks seconds-to-microseconds multiplication and the signed absolute deadline bound before calling the SDK, preserving output on error. It accounts for the current fractional second. Already-due work schedules a one-microsecond one-shot, not fabricated past samples. A `UINT32_MAX`-second interval remains checked 64-bit microseconds rather than overflowing an arbitrary `pdMS_TO_TICKS` multiplication. Clock/arithmetic/setup errors fault and shut down the monitor.

The worker calls actual `Runtime.start` and `Runtime.poll`. `ulTaskNotifyTake(pdTRUE, fixed_bound)` clears/coalesces accumulated notifications; delayed wakes cause one present-time poll, not a replay burst for every missed interval. Fixed waits permit stop/fault observation and are not deep sleep or validated power autonomy.

No sensor or voltage provider exists in this slice. The actual `NoProviderSensor` returns kind none, invalid quality, null value and calibration. Battery and solar remain null. The existing runtime selects critical scheduling for unknown battery; that is conservative unknown-power behavior, not a measured critical battery or approved cutoff. Runtime `samples` counts attempted telemetry cycles, including invalid/no-provider frames, not real sensor measurements.

No transport exists. The queue retains oldest frames; a full queue increments the existing dropped-newest counter. Nothing pops a frame, reports network acceptance, or increments delivery. The queue is RAM, not a device telemetry flash spool.

## T1. Host verification

From the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests/firmware -p test_monitor_task.py -v
MONITOR_SANITIZE=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests/firmware -p test_monitor_task.py -v
```

Both runs passed **33 tests, zero skips** on 2026-09-08: ordinary run **3.299 seconds**, ASan/UBSan run **6.016 seconds**, exit 0. The suite comprises 31 actual C++ cases and two partition/toolchain configuration checks. Both disabled and persisted `app_main` variants link to actual monitor/NVS/runtime sources under the fake ABI; the persisted entry-point test observes real product open/allocation/poll calls, not unused function addresses.

The C++17 compiler uses `-pthread -Wall -Wextra -Werror -pedantic`. Each of two host compiles has a 90-second deadline; each case runs in a separate eight-second-bounded subprocess and a new process-lifetime monitor slot. Internal fake scheduling barriers have two-second bounds. Host compiler artifacts use an owned temporary directory. The fake ABI supplies synthetic pre-existing RNVS bytes in memory only; it is not partition-image or commissioning tooling.

Cases cover zero-SDK disabled and invalid paths, task/timer setup errors, missing/erased existing NVS, primary-versus-cleanup errors, subsecond clock regression, overflow/long intervals, delayed notification coalescing, null providers, queue-full drops, no delivery, stop racing task creation/arming, rejected competing handles/restarts, failed cleanup retention, blocked in-flight callback retention, selected-before-stop callbacks entering after worker exit, and handle destruction with late callbacks. Sanitizers add host memory/undefined-behavior evidence, not target scheduler or flash qualification.

## T2. Parent-owned target checks

`firmware/monitor-target/platformio.ini` reuses the original pinned platform/package versions: espressif32 6.9.0, framework-espidf 3.50301.0 (ESP-IDF 5.3.1), Xtensa toolchain 13.2.0+20240530, and the original companion tool pins except Ninja. `make compile-esp` and `make compile-esp-monitor` select registry-published `platformio/tool-ninja` 1.13.2 on macOS and 1.7.1 on Linux x86_64 through `POSEIDON_NINJA_VERSION`; direct PlatformIO invocations must set that variable to the matching version. PlatformIO itself remains pinned to 6.1.18.

Both profiles require a caller-owned absolute `PLATFORMIO_BUILD_DIR`; their sdkconfig paths are separately named `sdkconfig.monitor_disabled` and `sdkconfig.monitor_persisted` inside that build root. The firmware lead owns bounded real-SDK compiles and canonical evidence for the original reference and both new profiles. See the lead's runtime guide/reports for those commands/results; this guide does not replace that build evidence or create source snapshots.

## G1. Remaining gates

- Independent commissioning and lifecycle authorization for the existing RNVS record; no baseline/image/reset tooling is supplied.
- Real flash/NVS recovery, wear, brownout, power-cycle and adversarial rollback behavior; checksums/readback are not those proofs.
- Real FreeRTOS timing, callback/shutdown interleavings, stack/heap margins, tick configuration and power behavior on the selected board.
- Battery/solar/sensor drivers, trusted calibration and clock evidence, device telemetry durability, radio/modem/gateway transport and delivery, deep sleep, and protected boot/update integration.
- Exact RAK/module/RUI3/region contract and separate physical-I/O authorization. This target provides no UART, GPIO, ADC, bus, network, modem, actuation, serial, flash, or fuse execution path in its application slice.

Host passes and parent-owned compiles do not make the firmware operational or authorize target execution.
