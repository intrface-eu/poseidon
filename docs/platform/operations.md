# Local platform operations and recovery

The supported application path remains the loopback FastAPI/Next monitor with its private SQLite/media workspace. New identity, observations, telemetry and simulated update state live in the migrated Hub database; recording/candidate evidence keeps the original database format. No PostgreSQL adapter or external media upload is silently substituted.

The separate `ops/compose/compose.json` is one local network-server foundation: pinned-version PostgreSQL 16.6, Redis 7.4.1, Mosquitto 2.0.20 and ChirpStack 4.10.0. It has an internal network, no database/Redis host ports, loopback MQTT/API publication, bounded logs and no automatic restart. Mosquitto requires TLS and per-service passwords, with no command topic writer. Redis requires a private password configuration. The stack is **not executed**: Docker is unavailable in this environment. Tags are fixed versions, not reviewed image digests or a claim of current vulnerability status. Container availability, ARM64 support, config acceptance and secure upgrades remain verification gates. A future authorized first start must replace ChirpStack's built-in initial administrator credentials before importing any real registry data; this template does not complete that bootstrap.

## Credential and certificate preparation

O1. Keep the application workspace and every backup on private local storage. The existing development key is global local-development admin, not a named production user. Scoped credentials are high-entropy tokens with hashes at rest, role/site/device checks, rotation and revocation. They are not OIDC, MFA, hardware attestation or production certificate enrollment. Do not expose the application on a public interface.

O2. For an authorized future Compose test, create `ops/compose/secrets/` with mode 0700. The nested `.gitignore` excludes it. Supply `postgres-password.txt`, `redis.conf`, `mqtt/{passwords,ca.crt,server.crt,server.key}` and `chirpstack/{chirpstack.toml,region_eu868.toml}`. Render from the checked-in `.example` files using a private secret store; every `REPLACE_` value must be replaced. Mosquitto password hashes must cover only the `chirpstack` and `aquilon` service users. Grant container users read access to only the required secrets without making private keys world-readable. No real key, certificate or hardware credential was created for these templates.

O3. `local-certificate.cnf.example` provides localhost/Mosquitto SANs, not a production trust policy. Verify certificate validity, SAN, file ownership, TLS chain and service permissions in an isolated test before accepting telemetry. The candidate EU868 receive-side region is not a gateway/radio transmission authorization; no gateway bridge service or downlink ACL is provisioned here. Onboarding a real gateway, device or regional RF profile requires separate approval.

Static inspection command:

```sh
python3 scripts/platform/check_ops.py
```

After private configuration and separate runtime authorization, the operator can validate Compose with `docker compose -f ops/compose/compose.json config --quiet` before starting any service. That command was not run here. Do not claim the stack is running from a JSON/TOML parse result. Back up PostgreSQL and Redis with their native consistent tools during the eventual infrastructure test; the workspace tool below does **not** back up Docker volumes.

## Workspace backup and restore

The tool requires an offline workspace. Its exclusive Hub lock rejects a workspace held by an application process; it never stops a service. Coordinate shutdown with the controller/operator. It opens and validates the Hub before copying, so normal interrupted-job recovery may occur before the backup snapshot. SQLite's backup API creates consistent database copies while the tool owns the workspace. Recordings/videos remain immutable; staging scratch is excluded and a clean staging directory is recreated at restore.

```sh
export PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/trident/src
python3 scripts/platform/backup_restore.py backup /owned/offline-workspace /new/private-backup
python3 scripts/platform/backup_restore.py verify /new/private-backup
python3 scripts/platform/backup_restore.py restore /new/private-backup /new/restored-workspace
```

Destinations must not exist and must be outside the source tree being copied. The tool never overwrites an existing backup/workspace. It verifies every manifest-listed file size/hash and rejects symlinks, traversal, unexpected entries and nonprivate backup directories before copying into a restore target. It then opens the restored Hub and validates source/database identities. Output includes counts only, never token contents or hashes.

Backups **contain credentials** and are not encrypted by this tool. Keep them on encrypted private storage with an operator-defined retention/access policy. SHA256 catalogs detect corruption, not a malicious rewrite by someone controlling the backup. Credential rotation after incident recovery is still required. A failed copy may leave an owned partial destination; inspect it, retain evidence and choose a new destination for retry. The tool does not delete partial or unknown files automatically.

The synthetic recovery drill covers a source-derived recording/candidate import, exact evidence counts after restore, private permissions, active-owner denial, corruption, traversal, unknown paths and overwrite refusal. It does not establish power-cut storage durability, backup media endurance, off-site disaster recovery or a live PostgreSQL restore.

## Failure and observability runbook

R1. API liveness is `/healthz`; authenticated `/api/v1/status` reports software jobs/evidence only. Use `/identity` to check actual auth mode/scope, `/audit` for authorized scope-specific security records, `/telemetry` for server receipt time and declared source/clock/calibration metadata, and per-target lifecycle history for local transitions. A registry row is not a connected device. Empty queries are valid. No-data/unknown-time cannot be interpreted as sensor health or zero events.

R2. Network loss: AQUILON's bounded durable spool and per-device credential resolver belong to the firmware adapter. The platform deduplicates exact `(device,boot,sequence)` receipts and rejects conflicting replay, older boot IDs and unknown older sequences. Sender `delivery_age_s` is a bounded claim, not trusted historical time. Do not clear sequence floors to get a replay accepted. Device reset/reprovisioning-generation semantics need a separately reviewed lifecycle before real use.

R3. Credential failure: distinguish revoked device, rotated/revoked principal, wrong role/site/device and unavailable API. Use a separate authorized admin session to rotate/revoke; device tokens cannot become fleet-wide publishers. Display new tokens once and store them outside source code. The local development key has no HTTP rotation endpoint; replacement/recovery needs controlled offline ownership, not a shortcut that bypasses current identity checks.

R4. Storage/job failure: preserve the workspace and inspect the safe job/error state. Do not remove evidence to make a test pass. Stop only owned processes through the approved launcher, make a private backup, then restart under the normal lock/recovery path. Capacity exhaustion is not permission for data deletion or unlimited queue growth. Define retention/quota operations with the owner before field acquisition.

R5. Update interruption: inspect the exact local target state after restart. Staged/trial state persists and never auto-confirms. Activate and confirm are separate; a confirmation is declared local test health, not hardware evidence. Recover/rollback can restore only a previous baseline satisfying the security floor; consumed sequence numbers stay consumed. A revoked signing key blocks further stage/activate/confirm. No image is executed, installed, flashed or sent to hardware. The firmware lane now supplies a separate host adapter for the approved manifest at `firmware/update/src/reef_update/platform_manifest.py`; the old private proposal format is not interchangeable with it. Interoperable hardware OTA and physical bootloader recovery remain open.

## Unexecuted paths

U1. Docker/ChirpStack/MQTT end-to-end runtime, credentials/certificate provisioning, network-server/gateway reception, service version/digest/ARM checks, actual backup volume restore and RF operation.

U2. Production identity provider, TLS ingress, independent security assessment, secret custody, key issuance/attestation, replay reset authority, fleet quotas/retention, incident support and qualified compliance review.

U3. Installed-image secure boot, physical A/B slots, fuse/security-floor behavior, interrupted flash, power loss/endurance, real calibration evidence, operating envelope and field permissions. Software tests do not close these gates.
