# Platform interoperability v1

Controller-review candidate, 2026-09-08. These schemas are additive. Existing strict recording/event v1 manifests and the acoustic evidence database do not change. JSON shape validation is followed by domain validation in `poseidon_proto.platform.validate_contract`; a valid shape is not a verified claim.

## REEF and AQUILON

`poseidon.reef-cbor.v1` adopts the firmware proposal: FPort 10, canonical definite CBOR array of exactly 13 scalars, at most 64 bytes. See `poseidon_proto.reef` and `fixtures/reef-cbor-vectors.json`. No floats, tags, maps, indefinite lengths, nonminimal integer encodings or trailing bytes. The parser bound is not an RF airtime authorization.

| Index | Meaning | Representation |
|---|---|---|
| 0 | version | uint 1 |
| 1 | persistent boot counter | nonzero uint64 on air; canonical decimal string in JSON/SQLite |
| 2 | sequence | uint32, no wrapping within a boot |
| 3 | uptime | uint32 seconds; never UTC |
| 4 | clock claim | 0 unsynchronized, 1 RTC, 2 network |
| 5 | observed time claim | null when unsynchronized, otherwise uint32 Unix seconds |
| 6, 7 | battery, solar voltage | null or uint16 millivolts |
| 8 | power mode | 0 normal, 1 conserve, 2 critical |
| 9 | sensor kind | 0 none, 1 temperature, 2 salinity, 3 dissolved oxygen |
| 10 | sensor value | null or int32 |
| 11 | sensor quality claim | 0 raw counts, 1 calibrated claim, 2 invalid |
| 12 | calibration code | null or nonzero uint16 |

Absent sensor requires quality=invalid (2); absent/invalid sensor means null value and calibration. Raw counts have null calibration and normalize to `temperature_raw`, `salinity_raw` or `dissolved_oxygen_raw` with `unit:count`, `quality:uncalibrated`. Counts are not physical measurements. Calibrated claims require an immutable matching device-specific calibration mapping: temperature centi-degC maps to `temperature/Cel` divided by 100; salinity milli-PSU maps to `salinity/1` divided by 1000 (practical salinity is dimensionless); oxygen microgram/L maps to `dissolved_oxygen/ug/L` without scaling. Battery/solar millivolts map to `battery_voltage/V`, `solar_voltage/V` divided by 1000 and remain uncalibrated. A registry reference is a declared reference, not a manufactured calibration certificate.

Boot JSON text is `[1-9][0-9]{0,19}` and must numerically be <=18446744073709551615. Compare integer values, not lexical order. Persist monotonically increasing boot IDs; no automatic reset/reprovisioning bypass. Stored identical deliveries may deduplicate; unknown older boot/sequence deliveries fail. Freeze the normalized envelope at first delivery attempt, including delivery age and receipt metadata; a retry must preserve that envelope exactly (JSON key order is immaterial). The local spool must still expire old pending work independently rather than rewriting a submitted envelope. A lifecycle reset needs a separately reviewed explicit generation/reset process, not a quiet counter clear.

AQUILON binds trusted network-server DevEUI metadata to one unique device registry mapping. Immutable registry site/source_kind wins over sender fields. `PUT /devices/{id}/aquilon-mapping` stores `{dev_eui,calibration_refs:[{code,sensor_kind,calibration_id}]}` once, admin-only; GET returns the mapping to an authorized admin or the matching device principal. DevEUI is 16 lowercase hex digits. A local credential resolver selects a different scoped credential for each registered device. A gateway-wide bearer token cannot ingest arbitrary identities. Credentials never go into frames, provenance, logs or golden vectors.

Normalized AQUILON telemetry adds `radio` with DevEUI, uptime, power mode, frame SHA256, network receipt time and raw time/calibration claims. Source is `provenance.transport:aquilon`. An RTC/network enum alone does not establish uncertainty or synchronization: keep normalized `clock_quality` unknown and `observed_at:null` unless separate clock evidence supplies the method, reference and uncertainty. Preserve the original claim in `radio.observed_at_unix_s` and `radio.clock_claim`. Server `received_at` is distinct from these times. `delivery_age_s` is a bounded sender claim, not an attested age; the adapter must measure its local spool residence against a monotonic clock and stop/recover conservatively if its time basis is lost.

## Acquisition and independent review

An acquisition session keeps identity/provenance immutable and may carry a `clock_relation`. Relation domains explicitly name source and reference clocks; neither domain implies UTC. The mapping is:

```
reference_s = reference_anchor_s + (source_s - source_anchor_s) * (1 + drift_ppm / 1e6)
uncertainty_s = anchor_uncertainty_s + abs(source_s - source_anchor_s) * drift_uncertainty_ppm / 1e6
```

Positive drift increases the reference-time interval for a fixed source interval. Scale must be positive. Operator-declared relation remains a claim, never verified sync. Measured/shared-clock relations require an evidence reference. Source checksums, channel/chunk/frame boundaries, drops/discontinuities, storage stops and finalized-segment digests remain acquisition-owned immutable session sidecars; current platform association does not discard or rewrite them and does not claim they were all ingested. Binding checks site/device/source_kind against v1 recording provenance and preserves the exact source hash. `source_id` names the declared acquisition source, not an invented WAV ID.

Observations use half-open `[start_s,end_s)` recording-relative seconds, no candidate requirement. Optional `review_context` carries protocol ID, evidence refs, visibility, sync uncertainty and whether the interval was independently reviewed coverage. Missing context is unknown, not automatically scoreable exposure. Exact authenticated actor and declared observer are separate. Immutable source hash and revision history remain attached.

| Platform label | Acquisition label | Scoring boundary |
|---|---|---|
| feeding_observed | observed_predation | Human label only; require protocol/evidence/visibility acceptance before scoring |
| no_feeding_observed | hard_negative | Reviewed negative evidence only, never all noncandidate time |
| uncertain | unknown | Exclude from scored exposure |
| not_visible | unusable | Exclude from scored exposure |

Only independently reviewed, usable intervals satisfying the frozen evaluation protocol enter false-alert-hour denominators. Missing/unreviewed/unknown/unusable time never does. The UI and database do not themselves certify ground truth. Acquisition dataset versions and recording/day/site split groups remain separate immutable research artifacts.

## Signed artifacts

`fixtures/signed-manifest.valid.json` validates only the schema shape; its all-zero signature is deliberately not a valid signed release. Executable lifecycle tests create ephemeral Ed25519 test keys and sign real payloads. No production private key is published or generated.

`poseidon-json-v1` is ASCII JSON escaping, sorted keys and no insignificant whitespace, integer-only numeric signed payload fields, with no Unicode normalization. It is not RFC 8785. Ed25519 signs `b'poseidon.signed-manifest.v1\0' + key_id.encode('ascii') + b'\0' + canonical_json(payload)`. Algorithm, canonicalization and signature length are fixed by schema. Artifact digest, exact byte length, kind, hardware target, expiry, sequence/security floor and previous digest are checked before stage. Configuration cannot enable emission. Bulk firmware updates do not use LoRaWAN; local reference targets do not flash equipment or attest bootloader security.
