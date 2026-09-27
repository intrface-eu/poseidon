# Local platform backend

The Hub and API store independent observations, acquisition associations, scoped credentials, registered devices, and authenticated telemetry. They run in the existing local monitor workspace. These are software foundations, not an Internet deployment, verified sensor fleet, or completed production security.

The HTTP shapes live in [platform-v1-api.md](../../contracts/platform-v1-api.md), the wire rules in [interop.md](../../contracts/v1/interop.md), and local signed-target routes in [lifecycle-api.md](../../contracts/v1/lifecycle-api.md). Existing recording manifests, acoustic candidates, and the acoustic evidence database keep their v1 format.

## Identity and scope

`Hub.authenticate(token)` returns an internal authentication result. `Hub.for_principal(result)` returns a request-bound facade; the API uses this facade for every protected monitor/platform method. `current_identity()` exposes only subject, role, sites, device, and authentication mode. Token hashes and internal credential references never appear in HTTP identity or principal responses.

A context variable carries the identity inside each facade call, including calls on API worker threads. The shared Hub never stores a mutable current user. Each call checks that the principal and current credential remain active. Rotation invalidates the old token and already-created facades on their next call. Device revocation also revokes all its device credentials. Revoked identities and device mappings cannot be reset through re-enrollment or rotation.

The raw Python Hub remains a trusted local operator interface for standalone callers and existing tests. Calling it directly is not a substitute for authenticating an external request. The workspace development key has local administrative authority, has no implicit fleet-ingest permission, and is never returned over HTTP.

- Viewers read data in their sites. Reviewers also write human observations, candidate reviews, and video evidence there.
- Scoped admins manage only their sites. Grants must be subsets of their sites; a multi-site principal is not visible or manageable through a narrower admin grant.
- Device credentials bind one active registry device and one site. Device queries filter the exact device, not the rest of that site. Devices cannot review evidence, manage principals, or inspect the security audit.
- Unbound legacy recordings, including imports with a matching manifest site name, remain development-key-only. Existing uploads and the synthetic demo therefore require that key. Initial session binding also requires it. No new implicit site is inferred from old manifests.
- Recordings, candidates, jobs, waveform/video, acquisition associations, telemetry, and status counts apply scope before pagination or counting. Missing and out-of-scope resource details return 404. Role-denied operations return 403.

Credential enrollment and rotation generate 32 random bytes encoded as a URL-safe token. Only its SHA-256 digest persists. These are high-entropy bearer credentials, not passwords. Enrollment/rotation responses show the token once. Every `/api/v1` response uses `Cache-Control: no-store`, including errors and media ranges, so shared browser/proxy caches do not retain evidence across credential changes. Subject identifiers and device identities remain exact, immutable identifiers. Observer/reviewer display text is not an authenticated identity.

## Observations and acquisition metadata

Independent observations do not create or relabel detector candidates. They work on a recording with zero candidates and use half-open recording-relative intervals `[start_s, end_s)`. The source recording determines duration, SHA-256, and source kind. A client cannot replace this provenance through JSON fields.

Creation requires revision zero. Each update checks the current revision within a SQLite write transaction and appends a new row. A stale revision returns `observation_conflict` (409), without overwriting history. An observation ID cannot move recordings. Creation timestamp and source provenance stay fixed; each revision captures the authenticated actor and separately declared observer. Optional `review_context` passes through unchanged when supplied. Missing protocol, visibility, synchronization, or reviewed-coverage context is not invented and never becomes a scored denominator automatically.

Acquisition sessions store the validated contract object, including optional `clock_relation`, without editing the recording manifest. Binding compares the exact site, device, and source kind to the manifest and stores the source hash in its audit record. The link is immutable; an identical binding retry is allowed, but reassignment fails. A session with no declared device can exist, but cannot bind a v1 recording that declares a device. `provenance.source_id` stays a declared acquisition-source reference, not an invented WAV identity.

Operator offsets and affine clock relations stay declared metadata. Binding does not verify synchronization, ingest all acquisition sidecars, or prove biological ground truth.

## Devices, AQUILON, and telemetry

The registry starts empty. A row means registered, not connected. Device ID, site, source kind, hardware revision, and AQUILON mapping cannot be replaced. The mapping route stores a unique lowercase DevEUI and device-specific calibration references once. Authorized admins and the matching device credential can read it. The adapter must select a separate credential for each device; a gateway credential cannot impersonate its fleet.

Telemetry accepts only the exact device/site credential. Registry site and source kind must agree with the envelope; AQUILON radio DevEUI must match the immutable registry mapping. A calibrated measurement must have a matching device-specific sensor-kind/reference mapping and, for AQUILON, the matching radio calibration code. Raw counts and voltage readings do not acquire calibration or physical accuracy from storage. No calibration certificate or measured field value is generated by the backend.

The transaction key is `(device_id, boot_id, sequence)`. Boot IDs are canonical nonzero uint64 decimal **text**, including values above JavaScript's exact integer range and SQLite's signed integer range. New boot counters must not go backwards; sequences strictly increase within a boot. Stored identical retries deduplicate before high-water/age checks, including retries from earlier boots. An identity with different content returns `telemetry_conflict` (409). Unknown older boots or sequences fail. High-water state persists across restart, rotation, and revocation.

A retry must preserve the original envelope exactly, including `delivery_age_s`, radio receipt metadata, and clock/provenance fields. JSON key order does not matter. A sender must not regenerate a different age or timestamp for the same transaction key after the first attempted delivery.

Server receipt time and actor are separate from the envelope. `delivery_age_s` is bounded to seven days, but remains a sender claim. When `observed_at` is supplied, ingestion rejects times older than seven days or future times beyond the declared clock uncertainty. An unknown clock carries no UTC observation time; a synchronized clock without event time also provides no event-age evidence. Those cases rely on the bounded sender age claim. A compromised sender can lie about that claim; this is not attested time or a proof of offline residence.

Successful registration, provisioning, rotation/revocation, session binding, observation/review/media writes, telemetry ingestion, and duplicates append actor-stamped audit records in their data transaction. Role denials and conflicts append a safe operation/code-only record when storage is available. The audit endpoint is admin-only and scoped before counting. It never returns credentials. This local database trail is not a remotely anchored, tamper-evident security log; failed authentication and HTTP-parser rejections do not currently enter it.

## Storage and resource boundaries

Hub schema v2 adds tables for principals, devices, AQUILON mappings, sessions and bindings, independent observations/history, telemetry, security audit, and lead-owned lifecycle documents. The migration accepts only the exact supported v1 schema, runs additive DDL in one transaction, and advances the Hub metadata/version only when validation passes. A failed migration rolls back. Unsupported or unrelated stores remain rejected.

The migration does not modify v1 source/job/review/video rows, media bytes, the development token, or the acoustic evidence database. The workspace lock and short-lived SQLite connection/operation lifecycle remain in use. New writes do not delete user data or replace source files.

New JSON bodies are bounded to 64 KiB, telemetry to 16 KiB and 32 measurements. Local lifecycle stage has its separately documented 1536 KiB JSON limit for a maximum 1 MiB artifact. Actual streamed bytes are counted, not only Content-Length. New JSON rejects duplicate keys, unknown keys, nonfinite values, and unexpected query parameters. Existing multipart/WAV/video limits remain unchanged. Pages have a maximum of 200 rows. Registry/telemetry/audit retention, disk quotas, rate limits, credential expiry, external user identity, and a deployed TLS/network boundary are not supplied by this tranche.

The API pins `cryptography==46.0.3` in its local uv project for Ed25519 lifecycle checks. Hub/import/replay use the standard library unless a lifecycle route or module is invoked. No service, firmware image, actuator, or artifact executes through these routes.

## Tests

From the repository root:

```sh
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/trident/src:apps/aeolus-api/src \
  uv run --project apps/aeolus-api --frozen pytest tests/api -q

PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/trident/src \
  python3 -m unittest discover -s tests/trident -p 'test_platform.py' -q
```

The platform tests use isolated temporary workspaces and marked synthetic fixtures. They cover zero-candidate review, revision races, source identity, scope across old/new routes, credential/device revocation, telemetry idempotency and uint64 boot ordering, calibration mappings, body bounds, audit scope, v1 migration preservation, and migration rollback. Existing Hub/API regressions remain separate tests. Lifecycle signature/rollback/recovery tests are maintained with the lifecycle implementation. None of these tests counts as hardware, field, biological, infrastructure, or production-security evidence.
