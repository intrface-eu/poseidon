# REEF portable runtime and CBOR reference

This is a C++17 host-tested runtime and ESP32 compile-only reference. The controller accepted `contracts/v1/interop.md` and the matching `poseidon.reef-cbor.v1` schemas as the wave 1 integration specification; this does not authorize field use. Synthetic fixtures are codec evidence, not sensor measurements or calibration evidence. No hardware I/O, flashing, radio transmission, or field use occurred in this work.

## Source and integration points

| Path | Role |
|---|---|
| `firmware/reef/include/poseidon/reef.hpp` | Sensor, clock, power, journal and runtime APIs |
| `firmware/reef/src/reef.cpp` | Scheduling, queue, identity and journal implementation |
| `libs/proto-cpp/include/poseidon/telemetry.hpp` | Typed frame, fixed-size packet, codec errors |
| `libs/proto-cpp/src/telemetry.cpp` | Strict CBOR encoder and decoder |
| `libs/proto-cpp/tools/codec_cli.cpp` | Host `decode HEX` / `encode <13 fields>` parity helper |
| `libs/proto-cpp/fixtures/reef-telemetry-v1.json` | 24 valid and 63 invalid synthetic vectors |
| `libs/proto-cpp/tools/generate_vectors.py` | Deterministic stdlib fixture builder |
| `tests/firmware/test_runtime.py` | Standalone unittest compiler/runner |
| `tests/firmware/runtime_cases.cpp` | Release-active C++ checks and fault injection |
| `firmware/reference/` | Pinned PlatformIO/ESP-IDF compile reference |
| `firmware/toolchain/` | PlatformIO `uv.lock` and captured IDF Python constraints |

The core uses fixed arrays and `std::optional`; it does not allocate from the heap or throw. `Runtime` cannot be copied or moved because cloning live sequence state would duplicate identities. One caller owns a runtime, sensor and journal backend; concurrent access is not supported.

Commission an entirely erased reference `ByteStore` explicitly with `BootJournal::provision_blank()`. Construct `Runtime`, then call `start(clock)` once. Start commits a new boot ID before any sampling. Call `poll(clock, power)` with caller-supplied inputs. `sleep_remaining_s(now)` returns a scheduling hint, not a hardware sleep call. Drain the oldest frame through `front()`, encode it, and call `pop()` only after the chosen transport accepts it. The runtime does not provide radio acknowledgements or transport retries.

A real `Sensor::sample()` implementation must return raw counts, a registry-backed calibrated value, or an invalid sample. Invalid combinations become invalid/null readings and increment the local invalid-sample counter. The runtime does not manufacture calibration coefficients or validate a calibration registry. AQUILON owns registry checks at ingestion.

## Wire profile

FPort 10 carries a canonical definite CBOR array of exactly 13 scalar fields. The decoder rejects nonminimal integers, nonminimal array lengths, indefinite forms, unsupported types, enum/range errors, quality contradictions, truncation, trailing bytes and input longer than 64 bytes. Failure leaves caller output unchanged. The widest valid frame in this profile is **44 bytes**; the 64-byte parser ceiling is not permission to transmit at every EU868 data rate.

| Index | Field | Type / rule |
|---|---|---|
| 0 | version | uint, exactly 1 |
| 1 | boot_id | uint64, nonzero |
| 2 | sequence | uint32, no wrap within a session |
| 3 | uptime_s | uint32, monotonic elapsed session seconds |
| 4 | clock_quality | 0 unsynchronized, 1 RTC, 2 network |
| 5 | observed_at_unix_s | null when unsynchronized; uint32 otherwise |
| 6 | battery_mv | null or uint16 |
| 7 | solar_mv | null or uint16 |
| 8 | power_mode | 0 normal, 1 conserve, 2 critical |
| 9 | sensor_kind | 0 none, 1 temperature, 2 salinity, 3 dissolved oxygen |
| 10 | sensor_value | null or int32 |
| 11 | sensor_quality | 0 raw, 1 calibrated, 2 invalid |
| 12 | calibration_id | null or nonzero uint16 |

`none` requires `invalid` quality and null value/calibration. Any invalid sample requires null value/calibration. A real raw sensor requires a value and null calibration. A calibrated sensor requires a value and nonzero calibration ID. Raw counts are not physical units. Calibrated scaling is centi-degrees Celsius, milli-PSU practical salinity (dimensionless), or micrograms/litre dissolved oxygen, according to sensor kind. Scale names do not certify the calibration.

DevEUI comes from a trusted, allowlisted network-server envelope, not from this wire array. Logical identity is `(DevEUI, boot_id, sequence)`. **JSON boot IDs are canonical decimal strings**, including in fixture `fields[1]` and CLI decoded arrays, to preserve uint64 values through JavaScript. The wire field remains uint64. Candidate platform fixtures in `contracts/v1/fixtures/reef-cbor-vectors.json` also pass C++ parity tests; that comparison does not itself approve the contract.

### CLI parity

From the repository root, using an owned temporary build directory:

```sh
BUILD=$(mktemp -d /tmp/reef-codec.XXXXXX)
c++ -std=c++17 -O2 -Wall -Wextra -Werror -pedantic \
  -I libs/proto-cpp/include \
  libs/proto-cpp/src/telemetry.cpp libs/proto-cpp/tools/codec_cli.cpp \
  -o "$BUILD/codec_cli"
"$BUILD/codec_cli" encode 1 1 0 0 0 null null null 0 0 null 2 null
"$BUILD/codec_cli" decode 8d0101000000f6f6f60000f602f6
```

The encode command prints lowercase hex; decode prints a JSON array in wire order. Invalid input returns exit 2, an error on stderr and no stdout. No binary is committed. Remove the owned temporary directory after use. Regenerate the fixture file with `python3 libs/proto-cpp/tools/generate_vectors.py`; tests compare its full document with the checked-in JSON.

## Identity, time and power behavior

`provision_blank()` commits baseline ID zero, which is never emitted. Each successful `start()` allocates IDs 1, 2, and so on. Sequence starts at zero, consumes an identity even for a dropped sample, and emits `UINT32_MAX` at most once. The next sample needs a new committed session. Uptime exceeding `UINT32_MAX` also commits a new session and restarts uptime/sequence at zero. Boot ID exhaustion is terminal; there is no implicit wrap or reprovisioning. The boundary counter and persisted uptime-rotation path have separate tests rather than iterating four billion runtime samples.

The caller supplies uint64 monotonic seconds. A backward clock, including wrap, faults the running instance; recovery requires a new runtime and persisted boot. UTC can move independently as an RTC/network correction. Unix second zero is a valid synchronized value. Unsynchronized uptime never becomes UTC. The wire's uint32 UTC horizon and clock-source accuracy remain integration limits.

The queue has 1–16 slots and drops the newest sample when full, preserving FIFO order. `Statistics` exposes total samples, dropped-newest count, invalid-sample count and counter saturation. Counters saturate rather than wrap. These diagnostics are local API state, not extra fields secretly added to the 13-field wire proposal. Sequence gaps expose dropped samples to a receiver. **The queue and counters are RAM-only and are lost on restart.** Durable telemetry spooling belongs to AQUILON; a device-side persistent queue is not implemented.

Configurable intervals default to 60/300/900 seconds for normal/conserve/critical modes. Example voltage transitions are 12400 mV into conserve, 12800 mV out, 11800 mV into critical, and 12200 mV out. These are synthetic scheduling examples for the provisional battery architecture, **not battery protection, charger settings, safety limits, or measured cutoffs**. Configuration requires strictly ordered hysteresis bands and nonzero nondecreasing intervals. Missing battery voltage selects critical mode; it does not fabricate a healthy battery. Solar values remain nullable telemetry and do not bypass low-battery mode.

Power is evaluated on every poll, even when a probe sample is not due. A mode/config change recalculates the deadline relative to the previous sample. Arithmetic uses elapsed differences rather than potentially overflowing absolute deadline additions. Hardware wake sources, deep sleep retention, battery conditioning and real power consumption are not modeled.

## Dual-slot journal and fault model

The reference journal serializes two 32-byte slots explicitly. It never writes native C++ struct layout.

| Bytes within slot | Contents |
|---|---|
| 0–3 | ASCII `REEF` |
| 4 | Format version 1 |
| 5–7 | Reserved zero |
| 8–15 | Boot ID, little-endian uint64 |
| 16–23 | Bitwise complement of boot ID, little-endian |
| 24–27 | CRC-32/ISO-HDLC of bytes 0–23, little-endian |
| 28–30 | Reserved zero |
| 31 | Commit marker `0xa5`; `0x00` means invalidated |

An update targets the older slot. It writes marker zero and syncs, writes 31 payload bytes and syncs, then writes the commit marker last and syncs. It reads the slot back before returning the ID. The active slot stays untouched. Two committed records must have consecutive IDs; duplicates, nonconsecutive IDs or any commit-marked corrupt slot fail closed instead of silently rolling back to an older ID. A partially written first provisioning record cannot establish identity and cannot be automatically reinitialized.

**Assumption:** `ByteStore` provides ordered, durable byte replacement, truthful reads and sync barriers, with one writer. Tests stop writes before every one of the 33 byte operations, recover from both slots, and cover sync/read failures. This is a simulation contract, **not a real flash/NVS driver**. Flash erase granularity, write ordering, wear, torn-byte behavior, controller caches and brownout electrical behavior require a separately qualified backend. CRC detects accidental corruption; it is not cryptographic authentication. The proof does not cover malicious storage rollback, adversarial edits, arbitrary bit rot of commit markers, or destructive loss of both slots.

## Host verification

The runtime suite requires Python stdlib and a C++17 compiler only:

```sh
PYTHONPATH=apps/aquilon/src python3 -m unittest discover -s tests/firmware -p test_runtime.py -v
REEF_SANITIZE=1 PYTHONPATH=apps/aquilon/src python3 -m unittest discover -s tests/firmware -p test_runtime.py -v
```

Set `REEF_TEST_TMPDIR` to a campaign-owned directory to place both compiled binaries there. The harness creates and cleans its own `TemporaryDirectory` and puts timeouts on compiler and runner processes. It builds with `-DNDEBUG -Wall -Wextra -Werror -pedantic`; negative C++ checks remain active in release builds. `REEF_SANITIZE=1` adds ASan/UBSan when the host compiler supports them.

Evidence on 2026-09-08, Darwin arm64, Apple Clang 21.0.0:

- **T1:** Scoped normal run after adding the A/B layout and unused OTA-binding checks: **113 tests passed**, exit 0, 4.480 seconds.
- **T2:** Scoped ASan/UBSan run: **111 tests passed**, exit 0, 57.898 seconds; no sanitizer finding. This covers the final portable runtime/codec; the later two checks inspect target configuration rather than adding host-executed C++.
- **T3:** Coverage includes 24 valid/63 invalid lane vectors, 4 valid/5 invalid platform candidate vectors, 477 truncated prefixes, nonminimal encodings at all 13 positions, 100 deterministic generated valid frames, 11264 one-byte mutations and 20000 bounded generated inputs. Journal checks cover 34 update write cut points, 34 provisioning cut points, 3 sync failures, 96 read failures, each of 64 committed-record byte corruptions, restart, ambiguity and uint64 exhaustion. These are deterministic test cases, not a field failure-rate estimate.
- **T4:** The full command `PYTHONPATH=apps/aquilon/src python3 -m unittest discover -s tests/firmware -v` passed these 111 tests but exited 1 because the separately owned update suite needs `cryptography`, absent from the machine's Python 3.14.7. The firmware lead then ran the locked update environment aggregate: **129/129 passed**, exit 0, 3.515 seconds (111 runtime + 18 update tests, before the two A/B checks were added). No global package was installed to hide that dependency.

An earlier scoped test had an incorrect 48-byte maximum expectation; the exact profile maximum is 44, and the expectation was corrected. The first sanitizer pass also caught a hardware revision change from HW-REF-1.0 to HW-REF-1.1 during the campaign; pins did not change, references were updated, and the final checks passed.

## Pinned target compile

`firmware/reference/platformio.ini` targets a custom compile reference for MCU-01 ESP32-DevKitC-32E, 4 MB flash, per `hardware/interfaces/reference-v1.json` **HW-REF-1.1**. UART GPIO17/16, I2C GPIO21/22 and EU868 remain unused provisional configuration constants. They do not authorize wiring or RF operation. `app_main()` only encodes a synthetic frame in memory. No sensor, UART, I2C, radio, actuator or persistent-storage driver is initialized.

The build pins PlatformIO 6.1.18 through `firmware/toolchain/uv.lock`, espressif32 6.9.0, ESP-IDF 5.3.1 and all resolved PlatformIO tool package versions. Ninja is pinned per host: 1.13.2 on macOS, 1.7.1 on Linux x86_64; `make compile-esp` and `make compile-esp-monitor` select the matching package. `idf-python-constraints.txt` captures the exact vendor environment from CPython 3.12.13. Apply it before a clean build because ESP-IDF otherwise resolves its own Python dependency ranges. These pins are not a dependency security audit; the vendor environment includes older dependencies and needs a separate security/support review.

Example isolated compile command, from the repository root:

```sh
WORK="$PWD/.local/firmware-build"
export UV_CACHE_DIR="$WORK/reef-uv-cache"
export UV_PROJECT_ENVIRONMENT="$WORK/firmware-pio-venv"
export PLATFORMIO_CORE_DIR="$WORK/firmware-pio-core"
export PLATFORMIO_PACKAGES_DIR="$PLATFORMIO_CORE_DIR/packages"
export PLATFORMIO_BUILD_DIR="$WORK/firmware-pio-ota-build"
export PLATFORMIO_BUILD_CACHE_DIR="$WORK/firmware-pio-cache"
export PIP_CONSTRAINT="$PWD/firmware/toolchain/idf-python-constraints.txt"
if [ "$(uname -s)" = Darwin ]; then export POSEIDON_NINJA_VERSION=1.13.2; else export POSEIDON_NINJA_VERSION=1.7.1; fi
uv run --locked --project firmware/toolchain platformio run \
  --project-dir firmware/reference -e reef_reference
```

Only the controller/lead runs bounded target build attempts. This command does not upload. Generated SDK configuration goes under `PLATFORMIO_BUILD_DIR`, not into source. Small checked-in defaults select reproducible-build mode, fixed project version, 4 MB flash and no UART console/application/boot logs. Bluetooth is disabled. ESP-IDF's hidden `ESP_WIFI_ENABLED` SoC capability remains enabled at compile time; the application never initializes WiFi. These settings are not a guarantee of ROM-level silence if someone flashes an unauthorized image.

Before the A/B integration below, the firmware lead reported the corrected pinned compile **exit 0 in 20.97 seconds** and a final-source check **exit 0 in 7.23 seconds**. RAM was 10148/327680 bytes; application flash was 154020/1048576 bytes. The output was a 154384-byte `firmware.bin` and 2329284-byte `firmware.elf`. The initial attempt failed because the toolchain pin incorrectly used owner `espressif`; installed platform metadata identified owner `platformio`, and that exact correction built. Artifacts remain campaign-local. Reproducible-build settings and version pins are present; a byte-identical clean rebuild is **not claimed** here. The firmware lead owns final artifact hashes and aggregate evidence.

### A/B rollback compile integration

At the controller's next safe checkpoint, the reference gained a 4 MiB example partition table and `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y`. Secure boot, flash encryption and fuse-based antirollback remain disabled. This is an SDK compile/partition proof, not signed-image verification or a deployable update lifecycle.

| Partition | Offset | Size |
|---|---|---|
| nvs | `0x9000` | `0x4000` |
| otadata | `0xd000` | `0x2000` |
| phy_init | `0xf000` | `0x1000` |
| ota_0 | `0x10000` | `0x1f0000` |
| ota_1 | `0x200000` | `0x1f0000` |

The final 64 KiB remains unallocated. There is no factory partition or application data partition. Offsets, alignment, slot equality, overlap and total flash bounds have stdlib tests. A real product must budget image growth, persistent application data, provisioning and recovery images before approving a partition layout.

`src/ota_compile_reference.cpp` binds the addresses of `esp_ota_get_running_partition`, `esp_ota_get_state_partition`, `esp_ota_mark_app_valid_cancel_rollback` and `esp_ota_mark_app_invalid_rollback_and_reboot`, with compile-time signature checks against installed ESP-IDF 5.3.1 headers. **No OTA API is invoked.** `app_main()` does not call the binding accessor. No download, image write, image confirmation, partition selection, reboot or eFuse programming occurs. The compiler may discard unused bindings; this is not evidence of an active update agent.

Use a fresh `PLATFORMIO_BUILD_DIR` for this configuration change, because an existing generated sdkconfig can override changed defaults. A historical pinned build exited 0 in 21.93 seconds. RAM was **10156/327680 bytes**; application flash was **154020/2031616 bytes**. The generated configuration confirmed rollback and the custom partition table enabled, with secure boot, flash encryption and fuse-based antirollback disabled.

Historical compile artifacts were independently read back and hashed:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `firmware.bin` | 154384 | `42e040ce40089d2b905c316250b930c5b1007390d5d12a8b5a8542230f028928` |
| `firmware.elf` | 2329420 | `ba0925179ca05d1a579570179c35513767bedbd961b4c43f8dde88cc072152c0` |
| `bootloader.bin` | 18128 | `316af6465e8e224e1ca7feba41bdcf4ad7d015af1473e4e7a2ca48a9f13e5b83` |
| `partitions.bin` | 3072 | `34e04cbdd359dc4d3cfc3b0237762da1d3a0d8cf8aa729280eecfbaae9fb9ddb` |

The firmware lead verified the final locked aggregate **147/147 passed**, exit 0: 113 runtime/target-reference tests, 18 private-update tests and 16 canonical-manifest tests. This supersedes the earlier 129-test aggregate count. No image was flashed or executed on a device. Actual trial boot, health confirmation, rollback, power-loss recovery and authenticated image trust still need hardware/bootloader integration tests.

## Wave2 operational gap inventory (historical)

This table records the boundary before wave3. The original reference remains **not an operational REEF node or update agent**: `firmware/reference/src/main.cpp` encodes one synthetic frame in memory and returns without starting `Runtime` or invoking OTA bindings. Wave3 adds a separate target, described below, rather than changing this reference. In the historical table, an absent adapter meant missing implementation, not merely an implemented feature awaiting a bench test.

| ID | Implemented reference | Absent operational target code | Separate physical evidence still missing |
|---|---|---|---|
| FW1 | `Sensor` interface, quality rules and sampling/FIFO runtime in `firmware/reef/` | ESP sampling loop, concrete wet-probe/conditioned ADC or bus drivers, and queue-to-transport connection | Probe calibration/accuracy, electrical conditioning, wiring and sensor fault behavior |
| FW2 | Serialized dual-slot journal and deterministic interrupted-write host backend | ESP flash/NVS `ByteStore`, commissioning integration and reset/sleep retention binding | Actual erase/write ordering, brownout recovery, wear and storage endurance |
| FW3 | Monotonic/UTC input types, low-battery hysteresis and sleep-duration calculation | Hardware clock/synchronization providers, voltage acquisition, ESP deep-sleep/wakeup and retained-session integration | Clock uncertainty, energy/autonomy, voltage accuracy and electrical protection; example thresholds are not cutoffs |
| FW4 | C++ CBOR wire codec and AQUILON ChirpStack HTTP adapter | Target UART modem/LoRaWAN driver, OTAA provisioning/join, regional airtime control, RF uplink queue draining and acknowledgement handling | Above-water link, gateway, antenna, coexistence, permitted regional operation and measured latency |
| FW5 | Host 21-byte configuration parser, durable replay/expiry rules and JSON acknowledgement | Embedded command decoder/application binding, authenticated modem downlink receiver and on-air acknowledgement encoding | Delivered-command timing and persistence across physical power interruptions |
| FW6 | Host canonical-manifest Ed25519 verification, installed digest and trial/confirmation model | ESP signature/trust adapter, protected-key provisioning, bounded image transfer/write/verification and running-image evidence | Bootloader signature compatibility, key protection and real signed-image acceptance/rejection; secure boot remains disabled |
| FW7 | Compiled ESP-IDF A/B partition table, rollback bootloader option and unused OTA API bindings | Application update sequence, health/watchdog confirmation and rollback decision wiring; the API bindings execute nothing | Actual slot selection, trial boot, health confirmation, rollback and power-cut recovery on hardware |

AQUILON's host service tests, including later real local AEOLUS integration, do not implement any of these missing ESP adapters. Wave 1 build/test evidence above remains historical; wave 2 changes neither this compile-only target nor its physical qualification status.

## Wave3 concrete persistence and monitor implementation

Wave3 implements a separate `firmware/monitor-target/`; all nine original `firmware/reference/` files remain unchanged. `BootIdentity::allocate_boot(uint64_t&)` now supplies the compatible allocation boundary: the old `BootJournal` preserves its byte format and behavior, while the new [NVS allocator](nvs-identity.md) uses actual ESP-IDF key/value APIs instead of claiming raw-byte persistence equivalence.

The allocator validates the exact development `reef_state` partition at `0x3f0000`, size `0x10000`, and an existing 32-byte RNVS record under `reef_boot/identity_v1`. It publishes a new identity only after set, commit and readback. Ownership, reentrancy and competing instances are guarded; uncertain persistence faults remain latched across close/destruction/new objects in the same process. There is no application commissioning, erase, reseed, partition-image generation or fallback identity. SDK internal NVS recovery is separate from these application guarantees.

The [monitor task](monitor-target.md) owns the allocator and real `Runtime` on one FreeRTOS worker. A one-shot ESP timer callback only notifies it. The process-lifetime control block, closed notification gate and in-flight drain avoid dangling callbacks/task references; unprovable cleanup retains a bounded, visible fault state rather than freeing referenced resources. `start` success means task creation was accepted, not that persistence/startup completed. Inspect phase/error diagnostics separately. Stop requests are atomic and asynchronous; the worker's bounded wait checks them, but vendor I/O latency is not a measured shutdown guarantee.

`monitor_disabled` is the default and makes zero application SDK/RTOS interface calls, including actual `app_main` in host ABI tests. `monitor_persisted` links and calls the real worker/NVS/timer path, but still requires an independently commissioned record if later executed. Absent sensors produce `none/invalid/null`; battery/solar and UTC remain null. No transport drains the queue or claims delivery. The target contains no UART, GPIO, ADC, sensor-bus, network, modem, deep-sleep or actuation implementation.

Current gap status:

- **FW1:** Runtime sampling/task composition is now implemented; concrete environmental sensor/conditioner drivers remain absent.
- **FW2:** The development NVS allocator is now implemented and host-fault-tested; real flash power-loss, wear and recovery qualification remain unperformed.
- **FW3:** ESP monotonic time and task/timer scheduling are implemented; synchronized UTC, voltage providers and deep-sleep integration remain absent, and hardware timing/power behavior is unmeasured.
- **FW4–FW5:** Radio/modem uplink and embedded configuration/downlink/acknowledgement adapters remain absent. No parser-only RAK substitute was added.
- **FW6–FW7:** Protected ESP image trust, image transfer/write verification, actual update-agent/health confirmation and physical A/B recovery remain open. Compile-time bootloader settings and host signed-manifest tests do not close them.

### Wave3 checks

The lead verified the original **147 tests**, exit 0, then the full additive firmware suite: **280 passed, zero skips, exit 0, 7.996 seconds** (147 existing + 100 NVS + 33 monitor/configuration checks). New actual adapter/task code against ABI fakes also passed **133 ASan/UBSan tests**, zero skips/findings, exit 0, 12.516 seconds. These tests include both target entry-point gates; they do not execute ESP hardware.

```sh
WORK="$PWD/.local/firmware-build"
mkdir -p "$WORK/firmware-host-tests"
PYTHONDONTWRITEBYTECODE=1 REEF_TEST_TMPDIR="$WORK/firmware-host-tests" \
PYTHONPATH=apps/aquilon/src:libs/proto-py/src \
UV_CACHE_DIR="$WORK/firmware-uv-cache" \
UV_PROJECT_ENVIRONMENT="$WORK/firmware-update-venv" \
uv run --locked --project firmware/update \
  python -m unittest discover -s tests/firmware -v
```

For the sanitizer subset, add `REEF_SANITIZE=1 MONITOR_SANITIZE=1`, include `tests/firmware` on `PYTHONPATH`, and run `python -m unittest -v test_nvs_boot_identity test_monitor_task` in that same locked environment. The two flags cover the two distinct ABI test wrappers.

All pinned real-SDK builds passed: original `reef_reference` **20.31 s**, `monitor_disabled` **20.12 s**, and `monitor_persisted` **20.77 s**. The lead's nonverbose logs contained no visible warning lines. Controller independent verbose builds exposed nonfatal bootloader git-revision metadata diagnostics and CMake's unused `LEGACY_INCLUDE_COMMON_HEADERS` warning in all three profiles; no repair or suppression was applied. New profiles each use static RAM **11588/327680 bytes** and application flash **183132/2031616 bytes**; these link tallies are not a measured runtime heap/stack/power budget. Build roots are `$WORK/firmware-wave3-reference-build`, `$WORK/firmware-wave3-disabled-build`, and `$WORK/firmware-wave3-persisted-build`, with external profile-specific sdkconfig files. New profile commands use `--project-dir firmware/monitor-target -e monitor_disabled` or `-e monitor_persisted`, retaining the pinned environment/constraints above.

ELF inspection confirms the new profiles link actual monitor worker, NVS allocation/open, `nvs_set_blob`, `nvs_commit` and ESP timer text symbols, and initialize the enabled member to 0 versus 1. CMake's `compile_commands.json` omits PlatformIO-injected gate defines, so it is not used as gate proof. Exact commands, artifact checks and logs are in the campaign's `firmware-wave3-assurance-command.json` descriptor and wave3 result. Source snapshots remain deferred until controller freeze.

## Remaining gates

- **G1:** Calibrated registry metadata, trusted DevEUI lifecycle and explicit authorized reprovisioning policy; the shared wave 1 wire contract itself was accepted.
- **G2:** Physical qualification of the implemented NVS backend: power-cut behavior, persistence endurance, sequence identity across hardware resets/sleep, and target runtime/HIL tests.
- **G3:** Verified sensor/voltage conditioning, battery protection and power budget, clock-source accuracy and hardware sleep behavior.
- **G4:** Radio/gateway choice, reviewed region/data-rate/airtime sizing, hardware interfaces, EMC/conformity and permissions.
- **G5:** Production signing/trust provisioning and bootloader/update integration. Neither target contains an on-device update agent or the host model's protected signed-image verification/confirmation path.

Host tests and a linked ESP32 image do not establish field readiness, marine reliability, safe electrical operation, calibrated measurements or production release.
