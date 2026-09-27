# Platform additions v1

Local implementation surface. Controller-accepted wave-1 wire/session/observation rules are in [v1/interop.md](v1/interop.md); exact signed local routes are in [v1/lifecycle-api.md](v1/lifecycle-api.md). Those records resolve the initial draft below without changing legacy manifests.

Additive `/api/v1` routes; existing recording/candidate manifests and evidence DB stay unchanged. These are local software foundations, not deployed production security or hardware control. New tables belong in the Hub database with a tested migration. A scoped token never gains the local development key's global access.

## Authentication and scope

`GET /identity` returns `{subject, role, site_ids, device_id, auth_mode}`. Roles are `viewer`, `reviewer`, `admin`, `device`; modes are `local_development_key` and `scoped_token`. The workspace development key remains compatible and has explicitly local admin authority. Scoped users may only see sites in `site_ids`; device credentials bind exactly one registered site/device. Unbound legacy recordings are local-development-only until explicitly attached to an acquisition session. Existing v1 routes enforce this scope too, including jobs, status counts, imports, events, waveform and video. No public network exposure is part of this contract.

Admin lifecycle routes: `GET/POST /principals`; `POST /principals/{id}/rotate`; `POST /principals/{id}/revoke`. Create takes `{subject, role, site_ids, device_id}`; device_id is null for human roles. Credential creation/rotation returns `{principal, token}` once, with no-store caching; hashes only persist. Revocation invalidates current tokens. Only the local development credential can grant arbitrary scopes; scoped admin grants must be subsets of their own sites. Device provisioning requires an existing registered device. Read-only audit route `GET /audit` returns a paginated, scoped trail without credentials.

## Independent observations

`GET /recordings/{id}/observations` returns a page; `POST` creates an observation with `{id, start_s, end_s, label, notes, observer, expected_revision:0}`. `PUT /recordings/{id}/observations/{observation_id}` appends a revision with the same fields and the current expected_revision. `GET /recordings/{id}/observations/{observation_id}/history` returns an ascending revision page. Labels: `feeding_observed`, `no_feeding_observed`, `uncertain`, `not_visible`. Require `0 <= start_s < end_s <= recording duration`, finite seconds; notes required for feeding observed. Viewer/device cannot write; reviewer/admin can. No candidate dependency, including zero-candidate recordings.

Stored rows expose `{id, recording_id, start_s, end_s, label, notes, observer, expected_revision, revision, actor_subject, auth_mode, created_at, updated_at, provenance}`. Server captures immutable source provenance `{recording_sha256, source_kind}` from the recording, not from request text. An observation ID cannot move recordings; creation identity and source never change. Observer is a declared display name; actor_subject is the authenticated principal. Optimistic conflicts return 409 and preserve both server history and client draft. These are human observations, not detector labels or automatically proven ground truth.

## Acquisition sessions

`GET/POST /acquisition-sessions`; `GET /acquisition-sessions/{id}`. POST accepts the acquisition-session contract. `PUT /recordings/{id}/acquisition-session` takes `{session_id}` and binds once; no silent reassignment. `GET /recordings/{id}/acquisition-session` returns session or null. Binding requires an authorized admin and matching recording/session source provenance. The legacy manifest is never edited. Recording clock metadata is declared, and operator offsets are never promoted to verified synchronization.

## Devices and telemetry

`GET/POST /devices` and `GET /devices/{id}`. Create `{id, site_id, label, kind, hardware_revision, source_kind}`; kind is `reef`, `aquilon`, or `hub`; source_kind is `synthetic`, `bench`, or `field`. Registration is an admin action, not proof of a connected device. Device identity/site/source_kind are immutable. `POST /devices/{id}/revoke` disables device ingestion and its credentials. Firmware/hardware must agree part IDs separately.

`POST /telemetry` takes the telemetry-envelope schema. Only a device token with matching device and site can ingest. An enrolled AQUILON adapter may only use credentials bound to the corresponding device; it cannot impersonate arbitrary fleet identities. Server stamps receipt time and actor. Identity is `(device_id, boot_id, sequence)`; identical retries return the original record with `duplicate:true`, conflicting contents return 409. Sequence increases within a boot; out-of-order retries already stored may be deduplicated but unknown older sequence is rejected. Bound delivery to 7 days by trusted received time / stated observed time with explicit clock quality; unknown clocks have no invented event age and require bounded queued-age metadata. Envelope has `delivery_age_s` (0..604800), a sender claim rather than attested age. `GET /telemetry` filters optional device_id/site_id and pagination, applying principal scope before counting. Device may query only itself. No default rows or fake fleet.

Errors retain `{error:{code,message}}`; pages retain `{items,total,limit,offset}`. Strict input/unknown-key validation and finite numbers apply everywhere. New JSON requests are bounded to 64 KiB; telemetry to 16 KiB, at most 32 measurements. No command or output endpoint is introduced.

## Signed local lifecycle

Signed config/release/update and local rollout routes will be documented alongside their implementation before UI binding. Only trusted Ed25519 keys, explicit compatibility, expiry, monotonic security floor and replay checks can stage a local target. Rollout simulation does not flash or install software. Bulk firmware bytes do not traverse LoRaWAN.
