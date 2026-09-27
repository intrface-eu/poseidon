# Signed local lifecycle API v1

All routes below use `/api/v1/lifecycle`. They orchestrate persisted **local simulated targets only**. No endpoint flashes, installs, executes an artifact, runs a service or sends a field command. Device registration remains separate from target state. Ed25519 and artifact checks run against real bytes; health acknowledgements are declared software-test results, not measured hardware health.

`LocalLifecycle(raw_hub)` exposes the following methods with explicit `identity` as first argument; errors are HubError. It stores namespaced JSON records in Hub `platform_documents` in transactions. Reads/writes enforce human role/site scope internally, not only HTTP.

| Method/path | Method | Request | Response |
|---|---|---|---|
| GET `/keys` | list_keys(identity) | none | page of public key records |
| POST `/keys` | add_key(identity,body) | `{id,site_ids,public_key_hex}` (32-byte Ed25519 public key) | public key record, 201 |
| POST `/keys/{id}/revoke` | revoke_key(identity,id) | empty | key record |
| GET `/targets` | list_targets(identity) | none | page of targets |
| POST `/targets` | create_target(identity,body) | `{id,device_id,simulation:true,initial_sha256,initial_version,security_floor}` | target, 201 |
| GET `/targets/{id}` | get_target(identity,id) | none | target |
| POST `/targets/{id}/stage` | stage(identity,id,body) | `{manifest:<signed-manifest>,artifact_base64}` | target |
| POST `/targets/{id}/activate` | transition(identity,id,"activate") | empty | target |
| POST `/targets/{id}/confirm` | transition(identity,id,"confirm") | empty | target |
| POST `/targets/{id}/rollback` | transition(identity,id,"rollback") | empty | target |
| POST `/targets/{id}/recover` | transition(identity,id,"recover") | empty | target |
| GET `/targets/{id}/history` | history(identity,id) | none | page of transition audit records |

Admin writes, viewer/reviewer/admin scoped reads; device principals denied. Key mutations require local development key (trust-root changes are not delegated to scoped admin). Key visibility does not expose private data. Public key records `{id,site_ids,public_key_hex,created_at,revoked_at}`. At most 100 keys, 100 targets and 1000 transitions per target are software test limits. Target creation checks registered device, allowed site, active state and source_kind synthetic/bench; field devices are rejected. Device kind must be reef/hub, not gateway. Hardware revision derives from registered device, never request guesswork.

Target response fields: `{id,device_id,site_id,target_kind,hardware_revision,simulation:true,state,current_sha256,current_version,security_floor,highest_sequence,staged_manifest_id,trial_manifest_id,previous_sha256,revision,updated_at}`. `initial_sha256` represents a declared local baseline, not verified installed image bytes. History records `{revision,action,actor_subject,auth_mode,created_at,details}`. No artifact bytes returned. Pages are `{items,total,limit,offset}` with fixed local bounded limits; these routes do not accept query filters.

Stage verifies exact artifact bytes (1 MiB maximum local API limit), hash/length, signature/key scope/revocation, compatibility, issuance/expiry against server UTC, monotonic sequence, security floor, and exact previous SHA256. Stage does not activate. Activate moves staged to trial and rechecks expiry/trust. Confirm requires trial, commits the new digest/version and advances the security floor. Rollback/recover from unconfirmed trial restores the declared previous baseline if it meets the floor. A confirmed image cannot silently roll back below the advanced floor. Recovery is explicit on restart; no auto-confirm or auto-deploy. Sequence high-water remains consumed after failed trial or rollback. Each accepted transition appends actor-stamped history in the same transaction.

JSON request limit for stage is 1536 KiB including base64; other lifecycle bodies use 64 KiB. Strict body keys, no arbitrary file paths/URLs/shell input. API failures use existing `{error:{code,message}}`. Forms label all targets simulation-only and confirmation as declared local test health. Signing is performed offline; no private signing key field or server signing endpoint exists.
