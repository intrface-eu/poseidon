# Tranche 3 digital backend

Digital simulation only. Nothing here drives hardware, publishes to a broker, dispatches a
command to a device, or holds production keys. Every calibration record produced by this
code carries `digital_only: true`, and synthetic evidence stays synthetic.

## What was built

Three seams sit behind the additive `/api/v1` routes described in `contracts/tranche3-api.md`.

**Command contract (K1).** `poseidon.command.v1` and `poseidon.command-ack.v1` are parsed by
`libs/proto-py/src/poseidon_proto/command.py` and `libs/proto-ts/src/command-v1.ts`. Both reuse
the existing `poseidon.signed-manifest.v1` signing scheme and poseidon-json-v1 canonical JSON;
neither reimplements them. The kind set is closed at seven: `inhibit`, `resume`, `rearm`,
`clear-fault`, `wiper-run`, `health-request`, `config-apply`. There is no emission or output
kind, and a parser rejects anything outside the set. uint64 sequence counters travel and are
stored as decimal text, never as SQLite integers. A byte-identical retry of an already accepted
command returns `duplicate` without executing or transitioning; the same `command_id` on
different bytes is rejected as `command_id_conflict`.

**Operating state (K2).** `apps/trident/src/poseidon_trident/operating.py` holds the state
machine and the watchdogs. States are `observe`, `armed`, `inhibited`, `fault`. `emit` is
reserved and `allowed_transition` refuses entry to it unconditionally — for commands, for
watchdog faults and for restart alike. Rearm needs an explicit scoped `operator` role; an admin
principal is refused, and no path rearms implicitly. Watchdogs cover storage bytes and inodes,
monotonic-versus-wall clock regression, loopback API liveness and live-journal heartbeat age.
Every transition writes an audit row with the causing command id or watchdog id, and the API
exposes the state plus the ten most recent transitions.

Restart never lands in `armed`. A clean close records `clean_shutdown`, so reopening restores
`observe`; anything else restores `inhibited` and says why. Neither path repairs a workspace: a
corrupt database, an invalid persisted state and an unreviewed watchdog configuration all fail
closed on open.

**Health, alarms, calibration, retention (K3).** Device health comes from accepted telemetry
age against a per-device profile, not from registry presence: `online`, `stale`, `offline`,
`revoked`, and `unprofiled` when no explicit zone profile exists. The hub binding is an explicit
immutable pin to one registered synthetic `kind: hub` device; it is never inferred from registry
order, and only that device's commands change workspace state. Calibration records are immutable,
signed, decimal-text valued, and restricted to the fixed 18-unit UCUM subset — a declared unit,
not physical calibration evidence. Retention is opt-in with no automatic worker: preview,
approve and execute are three separate admin steps bound to the preview sha256, and only newly
admitted completed synthetic recordings past the policy watermark are eligible.

**Contract registry.** `libs/proto-py/src/poseidon_proto/registry.py` names the whole published
`contracts/v1` set: the seven contracts frozen in `platform.py` plus `calibration-record`,
`command`, `command-ack` and `companion-read`. `platform.py` did not change. `registry.validate_contract`
passes the seven earlier names straight to `platform.validate_contract`, and checks each new name
against its published schema file before handing it to the parser that already owns its rules —
`command.parse_command`, `command.parse_command_ack`, `calibration.parse_calibration`, and for the
companion read DTO the transport constants `companion.py` exports. It verifies no signature, and no
schema file changed. Callers that need the full set, `tests/system/test_contract_boundary.py`
included, should import `poseidon_proto.registry` rather than `poseidon_proto.platform`.

Two `$id` forms are published side by side: the eight earlier schemas use
`https://poseidon.invalid/contracts/v1/<name>.schema.json`, while `calibration-record`,
`command` and `command-ack` carry the bare version string that is also their `schema_version`
const. The registry reads neither, so validation is unaffected. Reconciling the two forms is a
contract decision and is still open.

## Boundaries this code keeps

- No MQTT broker, no publication, no device dispatch, no C++ consumer stub. The broker ACL in
  `ops/compose/mosquitto.acl` is generated from `ops/compose/device-registry.json` and diffed by
  a test; it is output, not a deployed configuration.
- `X-Poseidon-Retained: true` is a loopback simulation of transport retain metadata. It is
  rejected before any state change or sequence advance.
- `config-apply` carries digital health configuration only. `health_interval_s` is not a
  physical sample rate or output setting, and applying it stores a validated document and
  nothing else.
- `wiper-run` returns `executed` with an explicit digital-simulation reason. It never operates
  a wiper.
- Command keys are principal-bound Ed25519 public keys. The private key is created in browser
  memory and never reaches the server; this is session custody, not production custody. The
  local-development key can neither sign commands nor rearm.
- API responses are `no-store`. No response body carries a credential hash, a token or a
  private key.
- Deleting evidence never manufactures evidence. Tombstones record what was removed and mark
  `complete_evidence: false`; manifests, source hashes and the evidence database are left
  untouched. A plan interrupted mid-deletion stays `executing` and the workspace refuses to
  reopen rather than repair itself or claim completion. Evidence predating the explicit opt-in
  is never eligible.

## Verifying it

```
PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/trident/src:apps/aeolus-api/src \
  .local/controller-final-digital-001/api/venv/bin/python scripts/assurance/run_pytest.py \
  tests/api tests/trident tests/proto tests/ops -q -ra -p no:cacheprovider
```

Paths must be absolute and the run must have zero skips. `tests/api/test_tranche3_http.py`
drives real loopback HTTP against `tests/api/tranche3_fixture.py`, which is the only way live
journal liveness and watchdog faults can be injected; the normal app factory never fabricates a
sensor heartbeat. Each test takes a fresh owned temporary workspace and a free port, and closes
its server process in a `finally`.

## Open items

- Hardware, live acquisition, physical calibration, safety, permits, field effectiveness and
  release remain unverified and out of scope.
- Firmware owns the device side of the `config-apply` ack.
- Assurance owns the ARM64 VM run, SBOM, license inventory and secrets scan.
