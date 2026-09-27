# Platform observation export to dataset evaluation

Wave 2, 2026-09-08. This is an executable integration with canonical Platform GET endpoints, the real Hub/FastAPI implementation, source-bound dataset sealing and the unchanged RMS evaluator. It does not use detector candidates as its population or infer negative coverage from their absence.

## Environment and real API demo

The integration uses the existing locked AEOLUS API environment for FastAPI/TestClient and HTTPX. It adds no root or API dependency file and starts no persistent server. Run from the repository root after the controller's normal API setup:

```sh
export PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src:apps/trident/src:apps/aeolus-api/src
apps/aeolus-api/.venv/bin/python -m unittest discover -s tests/research/integration -v
apps/aeolus-api/.venv/bin/python -m poseidon_acoustic.platform_dataset_cli demo --output-dir .local/platform-dataset-new
```

The demo creates a real Hub/FastAPI app in an owned temporary workspace with `start_worker=False`, imports a silent synthetic WAV, processes its job synchronously, creates independent observation rows and a second feeding-label revision, then reads actual authenticated API routes through TestClient. The app/client/workspace are closed and removed after export. No TCP listener, camera, hydrophone, playback or actuator is used. Only the new exported bundle remains; no access credential is written into it.

Its recording has **zero candidates and one independently declared synthetic feeding interval**. The resulting evaluation has one false negative and recall zero, not perfect performance. All labels, review-context claims and protocol acceptance in this demonstration are synthetic software fixtures, not human review or biological evidence. Server-generated audit times are real software timestamps, so a newly created demo has a new snapshot identity; unchanged exported source and snapshot bytes reproduce the same evaluation.

The API environment currently emits a Starlette deprecation warning about HTTPX TestClient. The warning is not suppressed; no dependency upgrade or other-lane repair is part of this work.

## Export from an existing authorized local API

This command sends GET requests only. It never starts, stops or configures the API. Do not point it at another operator's workspace or reuse a credential without authorization.

```sh
apps/aeolus-api/.venv/bin/python -m poseidon_acoustic.platform_dataset_cli export-api \
  --origin http://127.0.0.1:8181 --token-file /private/path/to/access.token \
  --plan /private/dataset-input/plan.json --acceptance /private/dataset-input/acceptance.json \
  --output-dir /private/dataset-export-new --threshold 0.2 --page-size 50
```

Only literal `http://127.0.0.1:PORT` origins are accepted. HTTPX uses no environment proxy and does not follow redirects. The credential file must be a bounded private regular file with no group/other permissions. Tokens are held by the client in memory and are not put into plans, snapshots, errors, results or logs. Transport errors are reported without echoing their exception URL/header text. The ASGI integration exercises real routes/storage/auth; no running operator API or persistent server was used during campaign validation.

## Explicit plan and protocol acceptance

The plan is a local JSON object:

```json
{
  "format": "poseidon-platform-dataset-plan-v1",
  "dataset_name": "declared-study-version",
  "protocol_ref": "explicit-protocol-id",
  "license": "Actual approved data terms; do not copy a fixture declaration",
  "site_holdout": false,
  "recordings": [
    {
      "recording_id": "declared-recording-id",
      "wav_path": "original.wav",
      "recording_manifest_path": "original.recording.json",
      "recording_group": "continuous-run-group",
      "local_date": "2026-09-08",
      "timezone": "Europe/Zagreb",
      "split": "validation"
    }
  ]
}
```

The paths are relative to the plan and must stay inside its directory. The original v1 manifest and WAV must match the authenticated Platform recording, including its source hash and site/device/source provenance. Source WAV bytes are copied unchanged into a new output, with streaming byte bounds and before/after checksum validation. No API raw-WAV download endpoint is assumed. The exporter does not read private Hub database tables or bypass route authorization.

`acceptance.json` uses the explicit policy from [dataset-evaluation.md](dataset-evaluation.md): protocol ID, acceptance reference, accepting reviewer declaration, positive/negative label-mapping decisions, limited-visibility decision, synchronization uncertainty limit and confidence grade. Nothing supplies an automatic human approval. `plan.protocol_ref` must equal the accepted protocol ID. A candidate review without independent reviewed coverage, matching protocol, evidence, usable visibility and accepted synchronization uncertainty remains excluded from scored exposure.

The selected recording list is explicit. The exporter proves response-level completeness for **all observations and revision histories of those selected recordings**, not that the user selected every recording in a deployment or every record visible to the account. Recording/day/site split validation still happens during sealing. Permissions, label truth and sampling sufficiency remain independent gates.

## Completeness and revision checks

| ID | Check | Failure behavior |
|---|---|---|
| PX1 | Every page must return exactly `{items,total,limit,offset}`, the requested offset/limit, stable total, and the full expected item count | Missing, duplicate, truncated or changing pages stop export. An explicit empty terminal page at offset `total` is retained. |
| PX2 | Each current observation is unique; every revision history is paginated through its terminal page | History must contain revisions `1..current_revision` in order with stable creation/source identity. Its latest full row must exactly equal the current row. |
| PX3 | Recording metadata is read before and after each complete observation/history walk | Source/context changes stop export. The original manifest and actual PCM properties are independently checked during dataset sealing. |
| PX4 | Two complete scans must match byte-canonically; authenticated identity must remain unchanged | Concurrent additions/revisions or identity changes stop export without hidden retry. The caller must review and explicitly restart in a new output directory. |
| PX5 | Historical and current rows pass canonical schema/source/revision validation; current intervals also pass the frozen protocol mapping | Unknown, not-visible, missing-context and rejected-protocol intervals never become negative evidence. Original rows and excluded reasons remain in the linked import artifact. |
| PX6 | Snapshot and import are hashed and bound to the dataset | Offline loading replays the saved page/history completeness checks, verifies the selected current export and explicit policy, and rejects changed or missing evidence. |

These checks establish a bounded stable export under the canonical API's immutable revision model. The API does **not** supply a server-atomic snapshot token. The artifact says `server_atomic_snapshot=false`; no simultaneous cross-recording transaction or cryptographic proof of server authenticity is claimed. A hash cannot prove that an actor who can rewrite/re-hash the entire bundle obtained it from the server.

## Bounds, publication and output

Default bounds are 50 rows/page, 1,000 current observations per recording, 100 revisions per observation, 5,000 requests, 1 MiB/response, 6 MiB total received JSON, 64 MiB total copied source media, 32 explicitly selected recordings, 120 seconds total and 10 seconds/request. They are software limits, not field sampling or safety requirements. `ExportLimits` supports explicit bounded alternatives. The CLI exposes page size only; all other defaults stay fixed. A larger study must select an explicit supported budget through the library or use a reviewed partition, not silently truncate.

The bundle contains unchanged WAV copies, compatible v1 manifests, complete Platform snapshot sidecars, source- and policy-preserving observation imports, the sealed dataset, data card and evaluation. Dataset rows add optional `platform_snapshot_path`/hash binding; old dataset and v1 recording records are unchanged. `export-complete.json` hashes all bundle files and publishes last through a synced, exclusive staging/link operation. A reported commit failure retracts only the receipt link for that owned staging inode; if the filesystem also refuses retraction, the error explicitly says not to use the output. Require both a zero exit and a valid completion receipt. Failed directories and staging bytes are retained; do not interpret a partial bundle as a completed export or overwrite it. Individual immutable records may already exist when evaluation or completion fails.

`load_dataset` rechecks source bytes, imported observations, snapshot hashes and captured pagination/history evidence. The original [scoring policy](dataset-evaluation.md#scoring-policy) still applies: independent intervals, excluded unusable/unreviewed time, one-to-one interval matching, explicit false negatives, descriptive Wilson intervals and no hidden holdout tuning.

## Root integration requirement

The controller must add this separate suite to root testing with the existing API environment and source roots above:

```sh
apps/aeolus-api/.venv/bin/python -m unittest discover -s tests/research/integration -v
```

It is separate from the dependency-free `tests/research` discovery, not silently skipped when FastAPI is absent. This lead does not change Makefile, pyproject, CI or API/Hub source. Hardware, local biological performance, acoustic calibration and permissions are not explanations for omitted software integration; the bounded digital path is implemented and exercised here.
