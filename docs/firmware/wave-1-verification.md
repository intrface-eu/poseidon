# Firmware wave 1 verification

2026-09-08. State: ready for controller review of the reference implementation, not field or production release. All measurements below are test/build results on Darwin arm64; no physical device, gateway, sensor, radio, battery or boot trust was exercised.

## Implemented scope

- **A1 — REEF:** fixed-memory C++17 sensor/clock/power interfaces, raw/calibrated/invalid quality, persistent boot allocation, nonwrapping sequence identity, bounded FIFO/drop counters, low-battery hysteresis and sleep scheduling hints. The dual-slot journal models ordered byte writes and sync barriers; it is not an ESP flash backend.
- **A2 — Telemetry:** strict canonical 13-field CBOR codec, C++ CLI, Python codec and shared-platform vector parity. Full-width boot IDs use decimal text in JSON/SQLite. A clock enum remains a claim; normalized observation time stays unknown without independent clock evidence.
- **A3 — AQUILON:** authenticated ChirpStack v4 HTTP integration boundary, local device/application/calibration checks, SQLite spool/replay floors, bounded retries/health and a per-device credential bridge to the approved telemetry API shape. Only owned loopback mocks were contacted.
- **A4 — Delivery persistence:** SQLite v1-to-v2 additive migration, durable first-attempt canonical envelope before HTTP, frozen-byte retries, byte-budget accounting and atomic cleanup. Accepted-but-response-lost traffic followed by abrupt process exit retains the exact attempt and enters a conservative hold without valid residence-time evidence.
- **A5 — Updates:** real Ed25519 verification of the approved platform envelope through the shared signing-byte helper, persisted installed digest and verifier profile, sequence/security/base-image checks, staged/trial/confirmed model and simulated rollback. Confirmation requires the running image digest, not just a potentially reused version label. The earlier private profile remains explicitly selected and never auto-detected.
- **A6 — ESP reference:** pinned PlatformIO/ESP-IDF build for HW-REF-1.1 MCU-01, 4 MiB A/B partition example, rollback bootloader and compile-time OTA API bindings. `app_main` does not call OTA, sensor, radio or bus APIs. Secure boot, fuse antirollback and flash encryption remain disabled.

See [runtime and build details](runtime.md), [update contracts and state model](update-reference.md), [wire reference](../telemetry/reef-wire-reference.md), and [AQUILON operation and provisioning](../telemetry/aquilon.md).

## Commands and actual results

Run from the repository root. The example paths below contain only owned dependency/build products.

**T1 — Firmware aggregate: 147 passed, zero skipped, exit 0, 3.627 seconds.** This includes 113 runtime/target-reference checks, 18 private-update checks and 16 canonical-manifest checks.

```sh
PYTHONPATH=apps/aquilon/src:libs/proto-py/src \
UV_CACHE_DIR="$PWD/.local/firmware-uv-cache" \
UV_PROJECT_ENVIRONMENT="$PWD/.local/firmware-update-venv" \
uv run --locked --project firmware/update \
  python -m unittest discover -s tests/firmware -v
```

**T2 — AQUILON plus canonical bridge: 67 passed, zero skipped, exit 0, 1.326 seconds.** Tests include strict parsers, 96 lane/platform golden-vector cases, registry/calibration rules, scoped HTTP authentication, wrong credentials, spool-full handling, retry exhaustion/recovery, migration, first-attempt commit interruptions, lost responses and process death.

```sh
PYTHONPATH=apps/aquilon/src:libs/proto-py/src \
  python3 -m unittest discover -s tests/aquilon -v
```

The standalone command with only `PYTHONPATH=apps/aquilon/src` needs no installed dependency. The child verified 49 tests passed and 18 optional bridge tests skipped in that mode; it is not the full bridge acceptance command.

**T3 — C++ sanitizer evidence: 111 passed, exit 0, no ASan/UBSan finding, 57.898 seconds.** The child ran this against the final portable runtime/codec before two additional configuration-only A/B checks. It covers 477 truncated prefixes, 11264 one-byte mutations, 20000 bounded generated inputs and journal write/sync/read interruption boundaries. These counts are not statistical failure-rate evidence.

```sh
REEF_SANITIZE=1 PYTHONPATH=apps/aquilon/src \
  python3 -m unittest discover -s tests/firmware -p test_runtime.py -v
```

**T4 — Final A/B compile reference: exit 0, 21.93 seconds.** RAM use: 10156/327680 bytes. Application flash use: 154020/2031616 bytes. The build produced an application, bootloader and partition table, not a validated installed system.

```sh
PIP_CONSTRAINT="$PWD/firmware/toolchain/idf-python-constraints.txt" \
UV_CACHE_DIR="$PWD/.local/reef-uv-cache" \
UV_PROJECT_ENVIRONMENT="$PWD/.local/firmware-pio-venv" \
PLATFORMIO_CORE_DIR="$PWD/.local/firmware-pio-core" \
PLATFORMIO_BUILD_DIR="$PWD/.local/firmware-pio-ota-build" \
PLATFORMIO_BUILD_CACHE_DIR="$PWD/.local/firmware-pio-cache" \
uv run --locked --project firmware/toolchain \
  platformio run --project-dir firmware/reference -e reef_reference
```

Historical outputs under the owned `firmware-pio-ota-build/reef_reference/` directory:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `firmware.bin` | 154384 | `42e040ce40089d2b905c316250b930c5b1007390d5d12a8b5a8542230f028928` |
| `firmware.elf` | 2329420 | `ba0925179ca05d1a579570179c35513767bedbd961b4c43f8dde88cc072152c0` |
| `bootloader.bin` | 18128 | `316af6465e8e224e1ca7feba41bdcf4ad7d015af1473e4e7a2ca48a9f13e5b83` |
| `partitions.bin` | 3072 | `34e04cbdd359dc4d3cfc3b0237762da1d3a0d8cf8aa729280eecfbaae9fb9ddb` |

The effective generated config has rollback and the custom partition table enabled; secure boot, flash encryption and fuse antirollback are unset. WiFi capability remains compiled because of ESP-IDF's hidden SoC setting, but no WiFi initialization occurs. Version pins and reproducible-build settings exist; an independent byte-identical clean rebuild is not claimed.

## Failures found and corrected

- **F1 — Initial target pin:** the first build failed because the toolchain package owner was incorrectly `espressif`. The installed pinned platform metadata specified `platformio`; correcting that owner built with the same SDK/compiler versions.
- **F2 — Test expectations/dependencies:** a 48-byte maximum-frame expectation was corrected to the actual 44-byte bound. Hardware advanced from HW-REF-1.0 to 1.1 during verification; GPIO assignments stayed unchanged and citations were updated. Plain full firmware discovery lacked `cryptography`; the documented locked environment resolved that dependency without global installation.
- **F3 — Canonical parser:** controller review found a bounded 5000-digit JSON integer leaking `ValueError`. The parser now returns `Rejected`, preserves duplicate-key/noncanonical rejection behavior, and does not change interpreter limits.
- **F4 — Confirmation identity:** review found reused release labels could make version-only health confirmation ambiguous. `running_sha256` is now required and checked against the candidate. The regression rejects old/wrong digests without advancing the security floor.

## Gates still open

- **G1 — Physical interfaces:** real sensor conditioning/calibration, probe/tether, radio/modem/gateway/region, GPIO drivers, flash backend, deep sleep, power/brownout/wear and RF/solar/thermal behavior. Above-water RF and wired submerged probes remain the architecture; no underwater mesh claim.
- **G2 — Device update trust:** actual supported bootloader signature compatibility, protected key provisioning/rotation, real image read/write/verification, running-image attestation, bounded trial health policy and authorized power-cut/rollback tests. Host Ed25519 and API compilation do not prove ESP secure boot.
- **G3 — Downlinks:** the bounded 21-byte sample-interval command and JSON acknowledgement are host foundations. LoRaWAN acknowledgement encoding and authenticated ChirpStack/modem command transport are not implemented; full images are not sent over LoRaWAN.
- **G4 — Platform operation:** an actual ChirpStack-to-AEOLUS service run, production registry synchronization, credential enrollment/rotation, TLS ingress and managed delivery recovery remain controller/integration work. Restarted rows without clock evidence hold rather than regain age zero. Frozen-envelope headroom must be budgeted; the implementation does not discard data or expand limits to make room.
- **G5 — Release evidence:** site/budget/operating envelope, permissions, manufacturing, calibration, physical safety and field efficacy remain open. Dependency pins are not a security/support audit; Linux/ARM64 execution and a clean byte-identical target rebuild were not performed.

The lane did not run root-owned `make check`, `make test` or `make build-ui`. No root integration files were edited, and no persistent application service, firmware flash, physical I/O, external hosting or field activity was started.
