# REEF telemetry wire reference

Status: the controller accepted `contracts/v1/interop.md` and its resolved schemas as the wave 1 integration specification. This document explains the matching `poseidon.reef-cbor.v1` implementation; the platform-owned contract remains authoritative. This is not a field-release contract. Recording/event v1 schemas and the evidence database remain unchanged.

## Compact profile

FPort 10 is proposed for a canonical CBOR definite array of exactly 13 fields. The parser bound is 64 bytes, not an RF payload entitlement. The profile uses only minimally encoded positive/negative integers and null. Indefinite containers, maps, floats, tags, booleans, extra fields, nonminimal integers, truncated values and trailing bytes reject.

| Index | Field | Type and meaning |
|---|---|---|
| 0 | Version | uint, exactly 1 |
| 1 | Boot/session ID | Nonzero uint64, persistently increasing before any sample emission |
| 2 | Sequence | uint32; no wrap within a boot/session |
| 3 | Uptime | uint32 seconds since session origin, never UTC |
| 4 | Clock quality | 0 unsynchronized, 1 RTC, 2 network |
| 5 | Observation time claim | null when unsynchronized; otherwise uint32 Unix seconds claimed by the device |
| 6 | Battery | null or uint16 millivolts |
| 7 | Solar input | null or uint16 millivolts; not panel power or charge current |
| 8 | Power mode | 0 normal, 1 conserve, 2 critical |
| 9 | Sensor kind | 0 none, 1 temperature, 2 salinity, 3 dissolved oxygen |
| 10 | Sensor value | null or int32, with meaning controlled by quality |
| 11 | Sensor quality | 0 raw, 1 calibrated, 2 invalid |
| 12 | Calibration ID | null or nonzero uint16 reference scoped to the device |

A `none` sensor requires `invalid` quality and null value/calibration. Any invalid reading has null value/calibration. A real raw sensor requires a value in instrument counts and null calibration; raw counts never gain physical units. A calibrated sensor requires a value and nonzero calibration ID. The adapter must resolve that ID to immutable approved per-device, per-sensor metadata and establish its validity at the observation time; wire validity alone does not prove calibration.

| Calibrated kind | Wire unit | Explicit normalized conversion |
|---|---|---|
| Temperature | 0.01 degree Celsius | value / 100, `degC` |
| Practical salinity | 0.001 practical-salinity unit | value / 1000, dimensionless practical salinity; not g/L |
| Dissolved oxygen | microgram per litre | value unchanged, `ug/L` |

No range in this parser is a selected sensor accuracy, calibration certificate, physical operating envelope or safety threshold. The int32 range is an encoding bound. A battery millivolt value alone is neither state of charge nor a safe cutoff policy.

## Identity and time

DevEUI is carried by the authenticated ChirpStack envelope and bound to an application/device allowlist; it is not repeated on air. Logical identity is `(DevEUI, boot_id, sequence)`. The host journal allocates a new persistent boot before emission, including restart, sequence exhaustion or uptime exhaustion. Sequence gaps are allowed because the RAM queue explicitly counts dropped newest samples. It does not promise durable sample retention across a node power cut.

At every JSON and SQLite boundary the uint64 boot ID is canonical decimal text in the range `1` through `18446744073709551615`, without a plus sign or leading zeroes. Never parse it into a JavaScript `number` or a signed SQLite integer. The compact CBOR field stays uint64.

AQUILON persists per-device high-water state atomically with accepted spool insertion. Exact duplicates are acknowledged without another enqueue; collisions with different payload bytes, earlier boot IDs and nonincreasing unknown sequences reject. Receipt pruning must not erase the high-water replay floor. A full spool must not consume an identity, allowing transport retry. The forwarding sink must be idempotent because response loss can cause at-least-once delivery.

A node replacement, erased journal or reprovisioned device cannot silently restart at boot 1 under an existing identity. An authenticated lifecycle/reset procedure must either allocate a new identity or migrate a monotonic floor across both device and gateway. That procedure is not implemented in this reference; deletion of persistent state is not recovery.

Keep local `received_at`, network-server event time and the device's `claimed_observed_at` separate. Unsynchronized payloads have no UTC observation time; a network-server timestamp is not substituted for one. RTC/network quality is a source declaration, not measured synchronization uncertainty. Without independent clock evidence, normalized `observed_at` remains null and `clock_quality` remains unknown. Calibration validity checks against a claimed timestamp are labelled `claimed_observed_at`, not a verified observation-time check; without even a claimed timestamp the reference adapter rejects calibrated samples. Clock acceptance limits are local ingestion policy, not field latency evidence.

## Code and fixtures

- **A1 — C++ codec:** `libs/proto-cpp/include/poseidon/telemetry.hpp` and `libs/proto-cpp/src/telemetry.cpp`; CLI at `libs/proto-cpp/tools/codec_cli.cpp`.
- **A2 — Python codec/adapter:** `apps/aquilon/src/aquilon/wire.py` and `adapter.py`; standalone replay remains separate from platform models.
- **A3 — Golden vectors:** `libs/proto-cpp/fixtures/reef-telemetry-v1.json`, explicitly synthetic. Valid records contain fields and exact hex; invalid records contain rejected hex. Boot values in JSON are text.
- **A4 — Tests:** `tests/firmware/` exercises the host runtime, journal and codec; `tests/aquilon/` exercises the Python decoder, fixture parity, real HTTP handler and offline spool. Read `docs/firmware/runtime.md` and `docs/telemetry/aquilon.md` for exact commands.

## Integration and physical gates

The platform lead owns `contracts/` and shared Python/TypeScript schemas. Both codec test suites consume `contracts/v1/fixtures/reef-cbor-vectors.json` as well as the firmware-owned synthetic vectors. The approved normalization uses `Cel`, `1`, `ug/L` and volts with the exact conversions in `contracts/v1/interop.md`; private spool fields retain their declared units and are not submitted as platform envelopes. The separate canonical bridge passed shared domain-validator and API-shaped loopback tests, including a durable first-attempt envelope, lost response, abrupt process exit and conservative restart hold. Current residence expiry is checked separately without changing attempted bytes. A live multi-service platform run remains controller-owned evidence.

Hardware reference `HW-REF-1.1` identifies an above-water ESP32-DevKitC-32E and a provisional UART LoRaWAN modem candidate. A separate gateway and ChirpStack network server are required; there is no underwater mesh. The reference does not join a network, select a transmission data rate, implement a modem driver or prove RF compliance. Confirm EU-region module SKU, antenna/gateway, connector pins, regulator and radio burst current, airtime/duty-cycle budget and permits before any live use.
