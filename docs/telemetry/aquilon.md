# AQUILON local telemetry runtime

AQUILON implements a Python 3.11+ standard-library reference runtime for REEF telemetry through the ChirpStack v4 **JSON HTTP integration**. Wave1 used owned temporary SQLite files and loopback mocks. Wave2 additionally exercises the actual repository Hub/FastAPI ingest implementation under owned temporary Uvicorn processes. Neither wave used an actual ChirpStack server, broker, radio, sensor, existing service workspace, or deployed service.

The root controller accepted `contracts/v1/interop.md` and its resolved schemas as the **wave-1 integration specification** during this work. The wire now follows `poseidon.reef-cbor.v1`. The standalone spool document stays a private normalized format; the optional `platform_bridge.py` produces and validates the separate approved `poseidon.telemetry.v1` envelope. Only that optional bridge imports shared platform code. Wave1's approved API client evidence used a route-shaped loopback mock. The separate wave2 discovery root now tests that client against the actual repository API; this remains local software evidence, not a deployment claim.

## D1. Module boundaries

| Module under `apps/aquilon/src/aquilon/` | Boundary |
|---|---|
| `wire.py` | `Telemetry`, `decode_payload(bytes)`, `encode_payload(Telemetry)` retain standalone support for the root-reviewed 13-scalar CBOR profile. |
| `adapter.py` | `LocalRegistry`, `Device`, `Calibration`, `ClockPolicy`, `ChirpStackAdapter.parse(body, event=..., received_at=...)` validate network envelopes and produce private `Accepted` records. |
| `spool.py` | `SQLiteSpool.enqueue`, `freeze_forwarding`, `deliver_due`, `retry_exhausted`, `health`; `Sink.send(identity, body)` must accept idempotently or raise. |
| `runtime.py` | `AquilonRuntime.ingest` composes parsing and durable acceptance; `health` reports limits, counters, and missing integrations. |
| `transport.py` | `HTTPIntegrationConfig`, `make_webhook_handler`, and loopback-only `LocalHTTPSink`. Creating a handler does not start a listener. |
| `__main__.py` | Bounded synthetic fixture replay to a new spool and inspection of an existing spool. No server or forwarding service is started. |
| `platform_bridge.py` | Optional approved envelope normalizer, immutable local mapping/credential snapshots, process-local residence evidence, and loopback-only `POST /api/v1/telemetry` client. |

`Accepted` is an internal trusted object from the adapter, not an alternative public ingest API. Direct in-process callers own their inputs and registry configuration. The authenticated HTTP handler sets authenticated transport provenance only after checking the shared header.

## D2. ChirpStack HTTP boundary and local provisioning

ChirpStack v4's HTTP integration sends JSON uplink events to a configured endpoint with the `event=up` query parameter. This adapter supports that integration path rather than inventing an MQTT broker facade. The required fields are:

- `deviceInfo.devEui`: exactly 16 hexadecimal characters, normalized to lowercase.
- `deviceInfo.applicationId`: exact match to the local allowlisted device record.
- `fPort`: JSON integer `10`, not a string or boolean.
- `time`: timezone-bearing RFC3339 network-server event timestamp; up to nine fractional digits. The original text stays in source metadata; the normalized copy has microsecond precision.
- `data`: canonical padded standard base64 containing the private CBOR payload.

Other v4 envelope fields, including receive/transmit radio metadata, are bounded and ignored. They do not change identity, calibration, clock evidence, or sensor units. Unknown devices, disabled devices, and application mismatches are rejected. Authentication establishes trust in the configured network-server integration sender, not independent radio/device cryptographic proof.

Local reference configuration, **not deployment credentials**:

```python
from aquilon.adapter import ChirpStackAdapter, Device, LocalRegistry
from aquilon.runtime import AquilonRuntime
from aquilon.spool import SQLiteSpool
from aquilon.transport import HTTPIntegrationConfig, make_webhook_handler

registry = LocalRegistry([
    Device(
        dev_eui="00000000000000a1",
        application_id="00000000-0000-4000-8000-000000000001",
        provenance="synthetic-local-reference",
    ),
])
config = HTTPIntegrationConfig(
    shared_secret="SYNTHETIC-NOT-A-DEPLOYED-SECRET-000001",
    auth_header="X-Aquilon-Integration-Key",
    path="/chirpstack",
    integration_id="synthetic-local-integration",
    timeout_seconds=2,
)
# Use a new SQLite path inside an owned temporary directory for a local test.
# The tests construct HTTPServer(("127.0.0.1", 0), handler), reserving a free
# port atomically, and close the server, thread, connections, and spool.
```

The equivalent integration configuration uses JSON encoding, the matching endpoint path plus ChirpStack's event query, and the exact configured shared header. Configure a real unique secret outside source control only after deployment authorization. Never copy the synthetic example into a service. Secret values are absent from config representations, responses, and request logs; header comparison uses `hmac.compare_digest` over bytes. Duplicate authentication headers fail authentication.

Requests need one `Content-Length`, one JSON content type, and no transfer/content encoding or `Expect` header. The handler rejects unknown routes/events, duplicate lengths, oversized input, and malformed framing. It closes each connection. Normal responses are `200` for durable accepted/duplicate records, `401` for failed authentication, `400`/`413`/`431` for transport rejection, `422` for invalid uplinks/replays, and `503` for unavailable/full storage. A `200` does not mean the upstream sink has received the record.

The handler uses a bounded socket timeout and a total body-read deadline, default two seconds. The standard-library HTTP parser also limits header lines/count; the handler rejects aggregate parsed headers above 8 KiB and request targets above 2 KiB. A deployed ingress still needs TLS, a total header deadline, connection/rate limits, secret rotation, and trusted network isolation. This reference does not expose an Internet-ready server.

## D3. Wire, parsing, units, and time

The root-reviewed `poseidon.reef-cbor.v1` wire is a definite canonical CBOR array of exactly 13 scalar fields, at most 64 bytes:

`version, boot_id, sequence, uptime_s, clock_quality, observed_at_unix_s, battery_mv, solar_mv, power_mode, sensor_kind, sensor_value, sensor_quality, calibration_id`.

The decoder rejects nonminimal integers/array encodings, indefinite lengths, maps, strings, nested arrays, tags, floats, booleans, trailing bytes, truncation, and field-range violations. `boot_id` is nonzero uint64 on air; it becomes a canonical decimal **string** in normalized JSON and SQLite storage, without leading zeros. `sequence` and `uptime_s` are uint32. A sequence must not wrap within a boot. Battery/solar values are nullable uint16 millivolts; missing readings do not become zero. `sensor_kind=none` requires invalid quality and null value/calibration. Invalid real sensors also require null value/calibration.

JSON input is at most 16 KiB, depth 12, 2,048 parsed nodes, and 4,096 characters per string. Duplicate object keys, invalid Unicode/surrogates, nonfinite floats/constants, and integer tokens over 21 characters are rejected. Base64 is at most 88 characters and must round-trip canonically, including pad bits. The 64-byte CBOR bound is a parser limit, **not regional data-rate or airtime authorization**.

Raw sensor values remain instrument counts with `raw_counts` set and `value`, `unit`, and `calibration` null. Calibrated values retain the exact signed `wire_value` and require a nonzero per-device calibration ID. The private scales are centi-degrees Celsius, milli practical salinity (dimensionless), and micrograms per litre of dissolved oxygen. Normalized values use `degC`, `practical_salinity_dimensionless`, and `ug/L`. No raw-to-physical conversion, calibration certificate, uncertainty estimate, or physical-validity range is inferred.

Time fields have different meanings:

| Field | Meaning |
|---|---|
| `received_at` | Local gateway receipt clock, supplied separately from the envelope. |
| `network_event_at` | Authenticated integration sender's event time, not sensor observation evidence. |
| `clock_claim` | Device enum claim: unsynchronized, RTC, or network. |
| `claimed_observed_at` | Nullable timestamp claim from the wire, checked against the local clock policy. |
| `observed_at` | Always null until a separately reviewed independent clock-evidence adapter exists. |
| `clock_quality` | Always `unknown` in normalized output; enum claims do not verify UTC observation. |
| `uptime_s` | Diagnostic uptime only; never converted into UTC. |

Unsynchronized wire samples must have no observation timestamp. RTC/network wire samples require one. Default development acceptance limits are 60 seconds into the future, 86,400 seconds event age, and 86,400 seconds claimed observation age; a claim cannot exceed network event time by more than the future allowance. `ClockPolicy` makes these bounded limits configurable. These are local anti-stale checks, not field-approved timing accuracy or evidence that the host clock is correct. Offline samples older than the configured ingress policy are rejected; already accepted spool records remain deliverable regardless of later age.

Calibration records bind immutable `(DevEUI, calibration_id)` references to sensor kind, source reference, approval state, validity interval, and synthetic status. The local snapshot rejects duplicate keys and exposes read-only maps. Changing calibration metadata requires a new ID, not changing the meaning of an old queued reading. The payload's small ID is only a lookup reference; it is not calibration metadata or a certificate.

A calibrated sample without a timestamp claim is rejected as `calibration_time_unknown`: receipt time cannot establish calibration validity at unknown observation time. Otherwise the claim must fall in the approved reference's half-open validity interval and match device/kind. Output labels `validity_time_basis=claimed_observed_at` and `validity_evidence=claim-time-range-check-not-verified-observation`. Even with a valid reference, sensor quality remains a device claim plus local metadata checks, not independently verified measurement evidence. The standalone local snapshot is not automatically synchronized with the platform registry. Wave2 tests separately exercise the actual platform's immutable mapping enforcement.

## D4. Durable acceptance, replay, and delivery

SQLite uses `BEGIN IMMEDIATE`, `synchronous=FULL`, and rollback-journal mode. Logical identity is `reef-draft-v1:<DevEUI>:<boot_id>:<sequence>`. Spool insertion, accepted-identity receipt, high-water update, and accepted counter commit in one transaction. Boot IDs compare numerically as Python integers, not lexically or as signed SQLite integers.

Defaults are 1,024 spool rows, 4 MiB combined queued source JSON plus frozen forwarding-envelope/digest bytes, 4,096 recent identity receipts, 1,024 device high-water records, and a 32 MiB main database page limit. Exhausted rows still count against the queue bounds. Receipt pruning never prunes device high-water marks. Exact duplicates found in receipts or pending rows return duplicate without insertion; conflicting bytes for the same retained identity are rejected. A duplicate accepted before a newer boot remains an acknowledged no-op while its receipt exists. Unknown identities with a lower boot or nonincreasing sequence are rejected, including old records whose receipt was pruned. A device cannot reset its boot floor through this API.

The byte queue limit counts source documents, frozen envelope bytes, and each frozen source digest's 64 ASCII bytes, not all SQLite overhead. The additive SQLite v1-to-v2 migration creates a `forwarding` table without resetting accepted rows, receipts, or replay floors. Its identity foreign key cascades deletion with the source row. `freeze_forwarding(identity, source_body, build_envelope)` binds exact source bytes to their SHA256 and commits the first validated canonical envelope before returning anything to the network client. Existing frozen bytes bypass the builder; failed writes/commits do not permit a send. Failed/exhausted rows retain the frozen bytes across restart. Leave byte-budget headroom for first-attempt envelopes; if that space is unavailable, forwarding fails closed until capacity is explicitly restored, rather than dropping source records or expanding the configured limit. `max_disk_bytes` bounds **main database pages only**. Allow additional disk space for a rollback journal up to roughly the main database size plus journal/filesystem overhead; this is not a filesystem quota or total disk hard cap. No unbounded WAL is used. Full row/byte/page rejection rolls back the attempted accepted identity and replay floor, allowing the same record to retry after capacity recovers. Tests cover page-full rollback as well as logical queue fullness. An actual filesystem/SQLite I/O failure may prevent writing its own health counter.

`deliver_due(sink, now=..., limit=32)` performs a bounded batch; the maximum permitted batch is 1,024. Each failure schedules deterministic exponential delay, default 2, 4, 8, 16 seconds before the fifth failure exhausts the row; delay is capped at 300 seconds by default. Exhaustion retains the payload and marks health rather than silently dropping it. `retry_exhausted(identity, now=...)` is an explicit local operator recovery step, not automatic infinite retry. It does not change replay floors.

Retry deadlines persist as host Unix scheduler times across restart. Host clock validation remains an operating gate: a backward wall-clock jump can delay an already scheduled retry. There is no claim of a reboot-stable monotonic clock. Normalized observation evidence never derives from scheduler or receipt time.

Delivery is at least once. The sink must durably deduplicate the identity and reject conflicting payload reuse before acknowledging. An accepted request with a lost response, a process crash between sink acceptance and spool deletion, or multiple spool processes can cause repeated sends. The local mock tests this behavior. Spool deletion occurs only after sink success, and accepted receipts/high-water marks survive it.

`LocalHTTPSink` is a private **mock** protocol, not AEOLUS ingest. It permits only explicit numeric `127.0.0.1` or `::1` HTTP URLs with a port; no DNS, external hosts, credentials in URLs, redirects, or proxies. It sends the shared header and `Idempotency-Key`; a bounded 200/201 JSON acknowledgement must contain `accepted: true` and the same `identity`. A socket-shutdown watchdog bounds the total attempt, including slow-trickled response headers, and is cancelled/joined on exit. Responses are limited to 4 KiB. Error messages omit credentials and remote response contents.

Health exposes queue rows/combined bytes, frozen row/byte counts, exhausted count, next due time, receipt/device counts, configured queue bounds, and fixed persistent counters for acceptance, duplicates, replay/conflict rejection, parser/auth/transport rejection, full queue, delivery, failure, exhaustion, and recovery. It also states `platform_ingest=not-integrated` and `registry=local-reference-only`. There is no unauthenticated HTTP health endpoint.

## D5. Approved wave-1 platform bridge

The optional bridge requires `libs/proto-py/src` on `PYTHONPATH`, without dependency installation. `PlatformNormalizer` redecodes the retained frame using `poseidon_proto.reef.decode_frame` and `json_fields`, uses `poseidon_proto.platform.validate_contract("telemetry-envelope", ...)`, and serializes with the shared `canonical_json`. It does not copy another codec or shared serializer. The private normalized spool document remains unchanged, so standalone replay does not acquire a shared-package dependency.

`RegistrySnapshot` contains a bounded tuple of immutable `DeviceBinding` records. Each explicit DevEUI/application mapping selects one device ID, site ID, source kind, and source ID. Duplicate DevEUIs/device IDs and mismatched local records fail. Sender-supplied site/source/measurement fields are ignored; measurement values are reconstructed from the shared-decoded frame. Each `CalibrationBinding` maps the wire code and sensor kind to the approved platform calibration ID and exact local reference. Missing, wrong, duplicate, or synthetic-to-field calibration mappings fail. The platform's immutable mapping API remains the provisioning authority; this client uses a trusted injected snapshot, not an implemented remote registry sync.

The external envelope uses `temperature_raw`, `salinity_raw`, or `dissolved_oxygen_raw` with `unit=count`, `quality=uncalibrated` for instrument counts. Calibrated claims use the approved `Cel`, `1`, and `ug/L` units. Battery and solar become uncalibrated volts; missing readings remain null/invalid. `provenance.transport` is `aquilon`. `radio` retains frame digest, DevEUI, uptime, power mode, network time, calibration code, clock enum claim, and raw claimed Unix timestamp. External `observed_at` stays null; its structured `clock_quality` stays unknown with no invented method/reference/uncertainty.

`CredentialResolver` accepts at most 1,024 distinct `DeviceCredential` records and selects a token only for the mapped device/site. Missing, disabled, wrong-site credentials and reuse of one token across devices fail locally. Tokens are absent from representations, spool documents, envelopes, and logs. `PlatformAPIClient` posts only to the exact `/api/v1/telemetry` path on a numeric-loopback HTTP endpoint, uses the selected device's Bearer token, bounds requests/responses to 16 KiB, and inherits the total network deadline. The response must match the actual API shape `{id,envelope,received_at,actor_subject,duplicate}` and acknowledge the identical shared-validated envelope. Auth failures, mismatched acknowledgements, redirects, and malformed responses do not acknowledge the spool row.

`PlatformBridgeRuntime` wraps normal acceptance and records the process-local monotonic clock **only for newly accepted identities**, starting before parsing/SQLite admission. `MonotonicAdmissions` has a capacity equal to the spool row capacity and holds only process-local clock/source-digest evidence. Frozen retry envelopes live durably in SQLite, at most one per source row and within the shared byte budget. Exact duplicate ingestion cannot refresh the clock. First-dispatch preparation rounds measured local residence upward to whole seconds for `delivery_age_s`, then commits the validated canonical envelope and source-body digest in SQLite before any network call. `PlatformAPIClient.send_frozen` validates the stored bytes but sends those exact bytes; retries do not rebuild normalized fields. The platform's full-document duplicate comparison includes that age; recomputing it on retry would turn lost acknowledgements into content conflicts. Before **every** attempt, the bridge separately checks current measured local residence against the seven-day bound. The frozen field therefore means first-dispatch age, not current retry age or attested capture age.

A valid API acknowledgement alone does not release residence evidence. Successful spool removal commits the source-row deletion, cascading frozen-envelope deletion, and delivered counter together. Only afterward does `SQLiteSpool.deliver_due` call the sink's optional `local_committed(identity)` callback; `PlatformBridgeSink` releases its bounded in-memory admission there. A local DELETE or COMMIT rollback preserves source bytes, frozen bytes, and same-process residence evidence for an identical retry. Simple sinks without this callback retain their existing behavior. Exhausted, unacknowledged, or locally expired rows keep the frozen envelope and digest, including across process death/restart. Restarted/previously accepted rows still have no new monotonic evidence and cannot forward as age zero; a monotonic regression latches the time basis as lost. Persisted first-attempt bytes remain available for a future reviewed recovery policy instead of being forgotten or recomputed. They remain spooled and ordinary bounded retries can exhaust while held. There is deliberately no operator shortcut that fabricates recovery age. A reviewed external time-evidence/reconciliation mechanism is still required to release such records. A process crash after a real API acknowledgement but before local spool deletion also takes this conservative hold path. The underlying SQLite row/receipt/replay-floor durability is unaffected.

Local composition, with an already open owned temporary `spool` and the synthetic `registry` from D2:

```python
from aquilon.platform_bridge import (
    CredentialResolver, DeviceBinding, DeviceCredential, MonotonicAdmissions,
    PlatformAPIClient, PlatformBridgeRuntime, PlatformBridgeSink,
    PlatformNormalizer, RegistrySnapshot,
)

mapping = RegistrySnapshot(registry, (DeviceBinding(
    dev_eui="00000000000000a1",
    application_id="00000000-0000-4000-8000-000000000001",
    device_id="synthetic-reef-a1", site_id="synthetic-site-not-a-farm",
    source_kind="synthetic", source_id="synthetic-reef-source-a1",
),))
credentials = CredentialResolver((DeviceCredential(
    device_id="synthetic-reef-a1", site_id="synthetic-site-not-a-farm",
    token="SYNTHETIC-DEVICE-A1-NOT-DEPLOYED-TOKEN-0001",
),))
admissions = MonotonicAdmissions(capacity=spool.max_rows)
runtime = PlatformBridgeRuntime(ChirpStackAdapter(registry), spool, admissions)
# mock_endpoint is the actual port-zero address of an owned temporary HTTP mock,
# ending in /api/v1/telemetry. This example starts no service or network request.
client = PlatformAPIClient(mock_endpoint, credentials)
sink = PlatformBridgeSink(PlatformNormalizer(mapping), client, admissions, spool)
```

Bridge health identifies `approved-v1-loopback-client-reference`, `immutable-local-platform-mapping-snapshot`, the tracked residence count/capacity, and the external-time-evidence restart gate. It does not claim production integration. The default standalone runtime still reports `platform_ingest=not-integrated`.

## T1. Wave1 verification and replay (historical evidence)

From the repository root:

```sh
PYTHONPATH=apps/aquilon/src python3 -m unittest discover -s tests/aquilon -v
```

Without the optional shared package path, discovery runs 49 core tests and explicitly skips 18 bridge tests. The core covers authenticated loopback webhook requests, framing/parser/schema rejection, a mock HTTP sink, slow-trickle deadlines, lost acknowledgements, restart and process exit without close, retry exhaustion/recovery, row/byte/SQLite-page fullness, concurrent acceptance, uint64 storage, sequence wrap/lower boot rejection, calibration/raw distinction, time-claim rules, and strict CBOR. Wire parity reads 24 valid/63 invalid C++ vectors and 4 valid/5 invalid root-reviewed platform vectors. Another test feeds 1,000 deterministic synthetic random byte strings to the bounded decoder.

Run all 67 tests, including the shared domain-validator and approved route-shaped mock bridge:

```sh
PYTHONPATH=apps/aquilon/src:libs/proto-py/src python3 -m unittest discover -s tests/aquilon -v
```

The additional 18 tests exercise authenticated webhook through the actual spool and bridge into a loopback API-shaped mock, immutable site/source/calibration mapping, credential absence/wrong scope/mock 401/403, matching acknowledgements, lost-response idempotency with durable first-dispatch bytes, current seven-day residence checks, restart/duplicate age holds, and monotonic regression. The expanded suite proves v1-to-v2 migration, combined byte accounting, exhausted frozen-record retention/atomic cleanup, abrupt `os._exit` immediately before and after the freeze commit, forced freeze INSERT/COMMIT/budget rejection with zero network calls, and HTTP acceptance with lost response followed by child process exit. Reopening that last database retains exactly the bytes accepted by the mock and conservatively holds delivery without new clock evidence. All 67 passed with zero skips when the shared path was supplied. None of these tests provides actual AEOLUS/ChirpStack service, physical power-loss, or field evidence.

Replay an existing explicitly synthetic ChirpStack JSON fixture to a **new isolated spool**:

```sh
PYTHONPATH=apps/aquilon/src python3 -m aquilon replay /tmp/owned-fixture/synthetic-uplink.json \
  --spool /tmp/owned-fixture/new-aquilon.sqlite3 \
  --dev-eui 00000000000000a1 \
  --application-id 00000000-0000-4000-8000-000000000001 \
  --received-at 2026-09-08T12:00:00Z
PYTHONPATH=apps/aquilon/src python3 -m aquilon health \
  --spool /tmp/owned-fixture/new-aquilon.sqlite3
```

These are placeholder paths, not supplied recordings or a running service. The explicit replay clock must match the synthetic fixture's time policy. The CLI refuses to overwrite an existing spool and bounds the fixture read; a rejected operation can leave an empty initialized spool for inspection. Its default synthetic registry has no approved calibrations, so calibrated fixtures require an explicit in-process registry in tests rather than a fabricated CLI certificate.

## T2. Wave2 actual Hub/FastAPI integration

The separate root is `tests/aquilon/integration/`, with **no `__init__.py`**. Its only test/helper file is `tests/aquilon/integration/test_real_api.py`. The wave1 discovery root therefore remains dependency-free apart from its optional shared package path; it does not silently import FastAPI/Uvicorn.

`OwnedAPI` starts the actual `poseidon_api.create_app(workspace, start_worker=False)` in an owned Uvicorn child with `lifespan=on`, asyncio, and h11. A parent-created numeric `127.0.0.1` socket binds port zero atomically and passes only that listening descriptor to the child. There is no copied API route handler or success stub. Each test first creates a new temporary Hub, reads only that new workspace's generated development token, and closes the Hub before the API lifespan takes ownership. `/healthz` checks startup.

Tests use real HTTP routes to create synthetic devices, bind their immutable `site_id`, install AQUILON mappings, and issue device-scoped principals. There is no invented site-registration route: the current platform binds the site in `POST /api/v1/devices`. Device disabling uses the actual `POST /devices/{id}/revoke` route, which sets revocation and revokes the device's principals. Rotation and revocation use the real principal routes with empty request bodies. The calibration reference is explicitly synthetic, not a certificate or measured calibration.

Actual AQUILON webhook, spool, normalizer, credential resolver, and API client compose into the real HTTP ingest path. Tests inspect `hub.sqlite3` through a separate read-only connection and inspect the AQUILON database independently. Assertions cover raw counts, uint64 boot text, unknown clock evidence with preserved claims, calibrated-unit/reference mapping, identical duplicate acceptance, conflicting contents, admin ingest denial, wrong site/device scope, revoked principal, revoked device, and rotated credentials.

`AfterRealAcceptance` is a fault-injection boundary, not an API replacement. It first calls the real network transport, verifies the actual API acknowledged the exact envelope, then raises or arms a local storage fault. The response-loss tests prove a platform row exists before retry. An abrupt child-process test goes through the real AQUILON webhook and actual API, loses the accepted response, then calls `os._exit`. Reopening preserves the exact attempted canonical bytes and source digest but holds forwarding without monotonic residence evidence; it does not invent age zero.

Wave2 also closes a product defect found by controller review: the bridge previously discarded process-local admission evidence after the HTTP acknowledgement, before local spool deletion committed. Separate real-API tests now inject a local DELETE failure and a local COMMIT failure **after real server acceptance**. Both preserve the frozen bytes and valid same-process residence. Clearing the fault allows an identical retry, yields one platform row, and drains the local spool. The correction is limited to the optional post-local-commit callback in `SQLiteSpool` and `PlatformBridgeSink`; no API schema, route, lockfile, or platform source changed.

Resource bounds are explicit: API startup has a 12-second deadline; graceful API shutdown has five seconds, followed by an exact-owned-PID kill/reap fallback of two seconds that fails the test if needed. Uvicorn's own graceful shutdown bound is two seconds. The webhook has a one-second startup/read bound and bounded shutdown/join with only its tracked accepted sockets eligible for interruption. The abrupt child has a 15-second subprocess timeout. Each request closes its client connection. Test cleanup closes spools, stops/reaps API children, joins webhook threads, reacquires/releases the actual Hub workspace lock, and removes only owned temporary data. No persistent service or UI/browser runs.

### Exact environment and commands used

The historical integration used an isolated CPython **3.11.15** environment, separate from ESP-IDF's cryptography-41 environment. An initial offline sync lacked the locked pydantic-core wheel; the existing API environment supplied identical dependencies. The resulting environment passed a frozen/offline check with **25 packages checked, “Would make no changes,” exit 0**. No dependency download was performed.

```sh
UV_PROJECT_ENVIRONMENT="$PWD/.local/aquilon-api-venv" \
UV_CACHE_DIR="$PWD/.local/firmware-uv-cache" \
uv sync --frozen --offline --check --no-python-downloads \
  --project apps/aeolus-api
```

The unchanged dependency authority is `apps/aeolus-api/pyproject.toml` plus `apps/aeolus-api/uv.lock`. The runtime test checks FastAPI **0.141.1**, Uvicorn **0.52.4**, cryptography **46.0.3**, pydantic-core **2.46.5**, httpx **0.28.1**, and pytest **9.1.1**. Tests use stdlib unittest, not pytest's cache or a shared app environment.

From the repository root, the final integration command was:

```sh
PYTHONPATH=apps/aquilon/src:libs/proto-py/src:apps/acoustic/src:apps/trident/src:apps/aeolus-api/src \
PYTHONDONTWRITEBYTECODE=1 \
.local/aquilon-api-venv/bin/python \
  -m unittest discover -s tests/aquilon/integration -v
```

Result on 2026-09-08: **12 tests passed, zero skips, exit 0, 4.826 seconds**. The first run had 11 passes and one incorrect test expectation: wrong site/device scope returned `404/not_found`, not the assumed `403`. Inspection confirmed the actual Hub intentionally conceals out-of-scope resources; only the assertion changed, not platform code. The final test covers both wrong-site and same-site/wrong-device credentials.

The independent wave1/core regression command remained:

```sh
PYTHONPATH=apps/aquilon/src:libs/proto-py/src PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s tests/aquilon -v
```

The core suite recorded **67 tests, zero skips, exit 0** after the product correction; core discovery did not enter the separate API integration root. The full integration suite separately recorded **12 actual-API tests passed** and **67 core tests passed**, both without skips. The integration run used an owned process group with a 90-second deadline and TERM/KILL/reap fallback. Private historical harness inputs are not distributed; rerun on the current revision for current evidence.

## G1. Remaining gates

- Wave2 closes the actual repository Hub/FastAPI digital ingest test gap at the owned-loopback level. Controller independent review/acceptance remains separate; identity lifecycle/reset policy and independent clock evidence remain open.
- Production registry/calibration snapshot provisioning/synchronization, immutable ID history, operational credential distribution/rotation/revocation, deployed authenticated idempotent ingest, TLS/network limits, reviewed operating clock/retry policy, and backup/restore procedures remain open. Real local credential lifecycle routes now have wave2 test evidence, not production operations evidence.
- Restarted bridge records require an external residence-time evidence/reconciliation policy. No automatic age-zero recovery or bypass is implemented.
- Actual ChirpStack version/config interoperability, real gateway/OTAA provisioning, target-host deployment, EU868 data-rate/airtime sizing, sensor calibration/uncertainty, and authorized physical/field verification.
- Downlink authorization, device configuration acknowledgement/replay state, and update/boot authority remain with the firmware lead's device lifecycle implementation. This AQUILON slice sends no downlinks, actuator commands, or update images and does not duplicate that state.
