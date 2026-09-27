# REEF update and configuration reference

Status: host simulation with real Ed25519 verification, not an ESP secure-boot implementation. No image download, signing service, device flash, fuse change, radio transmission or production key provisioning occurs. The test image is labelled `SYNTHETIC-NOT-EXECUTABLE-IMAGE`; tests create ephemeral signing keys in memory.

## Run

From the repository root, using a private build environment:

```sh
export UV_CACHE_DIR="$PWD/.local/firmware-uv-cache"
export UV_PROJECT_ENVIRONMENT="$PWD/.local/firmware-update-venv"
uv sync --locked --project firmware/update
PYTHONPATH=apps/aquilon/src:libs/proto-py/src uv run --locked --project firmware/update python -m unittest discover -s tests/firmware -v
```

`firmware/update/uv.lock` pins the Python verification dependencies, including `cryptography==46.0.3`. The model lives in `firmware/update/src/reef_update/model.py`. This isolated environment does not modify the root project dependency graph. Tests use temporary SQLite stores and close them before removal. Choose a fresh owned directory for another run.

## Approved platform-manifest adapter

`reef_update.platform_manifest.PlatformImageVerifier` selects the approved `poseidon.signed-manifest.v1` envelope explicitly. It imports `poseidon_proto.signing.signing_bytes` and the shared schema/domain validator; it does not reproduce signing-byte construction or import the Hub. The signature covers the approved domain prefix, key ID and canonical payload. Transport input is bounded to 8192 bytes and must use the shared canonical JSON encoding; the detached-signature argument to `BootStore.stage` must be `b""` because the signature is inside this envelope.

```python
from reef_update import BootStore
from reef_update.platform_manifest import PlatformImageVerifier

# trusted_public_keys and installed_digest come from authenticated provisioning.
verifier = PlatformImageVerifier("reviewed-board-id", trusted_public_keys)
with BootStore(path, verifier, create=True, initial_version="installed-release",
               initial_sha256=installed_digest) as store:
    store.stage(canonical_envelope_bytes, b"", artifact_bytes, now=trusted_unix_seconds)
```

This example does not supply keys, claim a provisioned device, or permit factory recreation. `create=True` rejects an existing path. Existing stores must reopen with the same explicit verifier profile; switching profiles or encountering an old/incompatible store shape fails instead of clearing floors.

The adapter checks real Ed25519 signatures, canonical signature base64, `kind:update`, `target_kind:reef`, exact board compatibility, issuance/expiry against trusted UTC, security floor, monotonically increasing signed `sequence`, exact installed `previous_sha256`, image digest and size. Release `version` strings remain opaque: a lexically smaller name can be a newer signed sequence. The installed digest changes only on confirmed trial completion. The default image limit is 0x1f0000 bytes, matching each compile-only reference A/B slot, not a general ESP capacity claim. Firmware configuration embedded in the signed payload is validated and retained with the staged envelope but is not applied as an unacknowledged side effect.

The complete original signed envelope and image stay in the candidate record. Each schedule, trial boot and confirmation revalidates it; a derived candidate summary is not a substitute for signature verification. The known-good version/digest remain metadata in this host model, not an executable flash partition or a release audit archive.

`tests/firmware/test_platform_manifest.py` has 16 passing tests with ephemeral real signatures over the platform fixture shape. They cover exact shared signing bytes, invalid all-zero fixture signatures, signature-domain/key/field mutations, wrong targets, previous-digest chains, sequence wrap/replay, expiry, canonical JSON/base64, cross-profile rejection, staging/confirmation interruptions and revoked-key rollback. No production private key is written. The locked aggregate command above passed 147 tests after adding the canonical adapter, A/B reference checks, integer-digit parser rejection and repeated-version/different-image confirmation regression.

## Explicit private signing profile

The earlier `ImageVerifier` remains an explicitly selected, namespaced host proof. It is not the platform format, is never auto-detected, and cannot open a canonical-profile store. Its signed object is a canonical ASCII JSON manifest: lexicographically sorted keys, no insignificant whitespace, no duplicate/extra keys, no NaN, booleans in integer fields, or trailing data. Exactly these fields are present:

| Field | Contract |
|---|---|
| `schema` | `poseidon.reef.image.v1-proposal` |
| `board` | Exact allowlisted board compatibility ID, 1–64 ASCII letters/digits/underscore/dot/hyphen |
| `version` | Positive uint32 application version; strictly greater than installed version |
| `security_version` | Positive uint32; at least the device's confirmed security floor |
| `command_id` | Positive uint32 monotonic image authorization counter; never wraps |
| `expires_at` | uint32 Unix seconds, exclusive upper bound; trusted UTC required |
| `image_size` | Exact byte length; reference verifier limit is 2 MiB, not a chosen ESP partition size |
| `image_sha256` | Lowercase SHA-256 hex of the full image |
| `key_id` | Allowlisted verifier-key ID with the same character/length limits as `board` |

The detached Ed25519 signature is exactly 64 bytes over the complete canonical manifest bytes. The image digest and size are therefore signed. The manifest has a 1024-byte parser bound. No production private key is needed by the verifier. Unknown/revoked key IDs, missing/invalid signatures, wrong boards, expired/unsynchronized authorization, rollback attempts, counter replay, size mismatch and digest mismatch reject staging without consuming the counter.

This is a reference contract for review, not a new shared platform schema. The on-device signing format must be reconciled with the selected supported ESP bootloader; an Ed25519 host manifest alone does not establish compatibility with Espressif image signatures or secure boot.

## Boot state and interrupted commits

`BootStore` represents one known-good version and one candidate. It stores candidate bytes, signed metadata and the authorization counter in one SQLite transaction. `BEGIN IMMEDIATE` serializes validation and mutation; WAL and `synchronous=FULL` request SQLite's durable semantics. Fault callbacks interrupt after candidate/config writes, before state writes and before commit. These are logical storage-boundary tests, not power-cut measurements of flash or a filesystem.

| Operation/state | Reference behavior |
|---|---|
| Factory creation | Explicit new store only; existing stores are never overwritten or reset |
| Stage | Verify signature/board/digest/expiry/floors; persist candidate and consume image command ID |
| Staged reboot | Return the existing known-good version; staging alone does not activate an image |
| Schedule | Recheck the staged artifact and mark it pending |
| Pending boot | Recheck artifact; persist `trial` before returning a trial-boot decision |
| Candidate invalid/expired/time unavailable | Discard candidate and return the existing known-good version |
| Trial reboot without confirmation | Roll back to known-good; retain the consumed authorization counter |
| Confirm | Require matching running version **and `running_sha256`**, explicit health confirmation and still-valid signed artifact; advance confirmed version, digest and security floor atomically |
| Cancel before trial | Remove candidate but retain the consumed counter |
| Corrupt or missing provisioned store | Fail; do not silently recreate replay or version floors |

Boot decisions include `image_sha256`; confirmation must identify those exact bytes, not just a release label that may be reused. The private bootstrap may have a null digest if it was not supplied; the canonical profile requires an explicit installed digest. A commit interrupted during confirmation leaves the old confirmed version/digest and a trial state, so the next boot rolls back. Software-supplied health and running-digest reports are model inputs, not hardware attestation. Hardware integration must derive health from a bounded watchdog/self-test policy, retain actual A/B image slots, and verify the selected image before executing it. The reference's known-good bootstrap and immutable trust are assumptions; its persisted known-good metadata is not an executable partition. It does not protect SQLite state against an adversary who controls storage or against rollback of the whole storage device.

## Bounded configuration/downlink proposal

The device-side `ConfigurationController` accepts a private 21-byte big-endian binary message, not JSON over LoRaWAN:

| Offset | Type | Meaning |
|---|---|---|
| 0 | uint8 | Format version, exactly 1 |
| 1 | uint64 | Target boot/session identity, nonzero |
| 9 | uint32 | Nonzero monotonic command ID, no wrap within boot |
| 13 | uint32 | Expiry in Unix seconds; current trusted UTC must be earlier |
| 17 | uint32 | Sample interval in seconds, 60–86400 in this reference policy |

Only an authenticated trusted adapter may call `apply(..., authenticated=True)`. That flag is a precondition, not cryptographic validation of an untrusted payload field. No actuator-enable, wiper, radio setting or bulk image command exists. Unsynchronized devices reject configuration rather than pretending uptime is UTC. Accepted validity cannot exceed one day. The sample-interval bounds are simulation policy, not a reviewed RF airtime or sensor operating budget.

State stores the last boot as decimal text, command ID, exact payload digest and applied interval transactionally. JSON acknowledgements also carry `boot_id` as canonical decimal text, preserving the full uint64 range. The same command and exact payload return a `duplicate` acknowledgement without another state change; altered reuse, lower counters, earlier boots, wrap, expired requests and wrong target boots reject. Reprovisioning must explicitly migrate/reset lifecycle state under authenticated physical/service control; deleting the database is not the lifecycle protocol.

An acknowledgement contains boot ID, command ID, `applied`/`duplicate` status and the interval. This host model does not yet encode a LoRaWAN acknowledgement frame or call a ChirpStack downlink enqueue API. The 21-byte payload and proposed FPort 11 need platform review, regional airtime sizing and real modem integration before use. A lost acknowledgement does not imply application failure, and a network enqueue receipt does not imply device execution.

## Open gates

- **G1 — Configuration transport:** review/publish the compact downlink and acknowledgement encoding, implement authenticated network-server/modem transport, and integrate registry lifecycle and signing authority.
- **G2 — ESP integration:** ESP-IDF 5.3.1 compiled the reference A/B partition table and rollback bootloader with unused OTA API bindings; it did not execute an update. Connect approved envelope verification to bounded on-device image handling, supported bootloader signature verification and a reviewed trial watchdog before a real update test. Secure boot, fuse antirollback and flash encryption remain disabled in the compile-only profile.
- **G3 — Trust and recovery:** provision protected keys, test rotation/revocation and authenticated service recovery, reconcile security-floor advancement with an available recoverable image, and prove resistance to storage rollback.
- **G4 — Physical qualification:** authorized flash/power-cut/watchdog testing on real units; no secure-boot or electrical safety result follows from host tests.
- **G5 — Update transport:** use an authorized service cable or separately reviewed local high-bandwidth channel. Full image OTA over LoRaWAN is not implemented or assumed practical.
