# Independent dataset evaluation

Status: executable offline reference, 2026-09-08. No local biological dataset, species classifier, field performance or permission is supplied. Source PCM16 WAV files and existing `RecordingManifest` v1 records remain unchanged; the dataset is a separate provisional versioned sidecar, not a shared Platform contract.

Wave 2 adds [actual canonical Platform pagination/history export through dataset evaluation](platform-dataset-wave2.md), with real Hub/FastAPI tests. The `import-platform` file converter below remains available; it is not the new API export command.

## Reproduce

From the repository root, Python 3.11+ and the standard library are sufficient:

```sh
export PYTHONPATH=libs/proto-py/src:apps/acoustic/src:apps/nereid/src:apps/siren/src:libs/dsp/src
python3 -m unittest discover -s tests/research -v
python3 -m poseidon_acoustic.dataset_cli demo .local/dataset-example-new
python3 -m poseidon_acoustic.dataset_cli validate .local/dataset-example-new/dataset.json
python3 -m poseidon_acoustic.dataset_cli card .local/dataset-example-new/dataset.json
python3 -m poseidon_acoustic.dataset_cli evaluate .local/dataset-example-new/dataset.json .local/threshold-result-new.json --threshold 0.2 --threshold 0.4 --window-ms 10
```

Use new output paths. Existing evidence and partial outputs are never overwritten. The demo writes two synthetic WAV files, old v1 recording manifests, a source specification, a checksummed dataset manifest, evaluation JSON and a data card. The example includes independent positive intervals in a recording with **zero detector candidates**. Its false negative must remain in recall. The extremely short fixture creates a large false-alerts/hour value; that tests the exposure denominator, not a plausible field rate.

The checked-in example is `datasets/synthetic-independent-v1/`. Recreate it at a fresh path with `demo`; source and result identities are path-independent and deterministic.

## Source and observation contract

Start from the demo's `spec.json`. `seal SPEC OUTPUT` requires both paths in the same directory so relative sources stay valid. It verifies the exact v1 recording manifest, PCM framing and SHA-256, then binds duration, frame count, sample rate, channel count, source/manifest digests, site, provenance and local covered dates into the sidecar. The `dataset_id` hashes the canonical full content, including split assignment and observations. `validate` and `evaluate` recheck actual source bytes rather than trusting the saved hash string.

Files are immutable by workflow and hash identity, not by filesystem write protection or a signature. Any corrected observation requires a new dataset version and output path. Content hashes cannot prove permission, true identity, correct annotation, or detect re-encoded duplicates. The caller owns a stable local workspace while the command runs; this is not a multi-user adversarial filesystem service. No device path or symlink source is accepted.

| ID | Record requirement | Meaning |
|---|---|---|
| DS1 | `recording_group`, local date/timezone, `split` | Same recording group or covered local calendar date cannot appear in different partitions. Date is checked against the source timestamp, including midnight crossings. With `site_holdout=true`, whole sites also stay in one split. |
| DS2 | `observations` | Ordered, non-overlapping half-open recording-relative seconds. Reviewed intervals may exist without any candidate. Gaps are unreviewed, not negatives. |
| DS3 | `observer_id`, `evidence_ref`, `confidence`, `visibility`, `timing_uncertainty_s` | Independent annotation provenance, visible/limited/not_visible/not_applicable status, and alignment uncertainty. Evidence reference is an opaque reference, not proof of human review or a verified external-media checksum. |
| DS4 | `protocol_ref`, `license`, provenance | Dated/frozen analysis and access terms. `field` remains a declaration, not proof of a permit. Synthetic and field recordings cannot be aggregated in one evaluation split. |
| DS5 | Bounds | At most 8 MiB JSON, 2,000 recordings, 10,000 observations or predictions per recording, 32 thresholds and two million prediction/truth comparisons per recording. Long WAV reads stream; detector event limits still need a target-platform resource study. |

The local label `observed_predation` means **independently observed feeding under the declared protocol**, not proof of predator species, number of mussels lost, prevented loss or financial benefit. The name is retained within this provisional sidecar and must not be exposed as a stock-loss claim.

### Accepted Platform mapping

The controller accepted `contracts/v1/interop.md` during this wave. The offline `import-platform` adapter now validates canonical stored rows and records an explicit protocol-acceptance decision. No live API connector was added and no old evidence database was migrated.

| ID | Platform observation | Local evaluation treatment |
|---|---|---|
| MAP1 | `feeding_observed` | `observed_predation` only when the protocol's feeding evidence rule is met, visibility is visible/limited and timing uncertainty is accepted. Generic fish presence is insufficient. |
| MAP2 | `no_feeding_observed` | `hard_negative` only for an independently reviewed, usable interval with adequate visibility. Missing candidates or missing video cannot generate this label. |
| MAP3 | `uncertain` | `unknown`, excluded from primary scoring. |
| MAP4 | `not_visible` | `unusable` and `visibility=not_visible`, excluded. Original reason and visibility stay in the source observation record. |

Platform candidate reviews alone do not establish exhaustive coverage. Before translation, independent coverage and evidence must be recorded even for zero-candidate recordings. The provisional dataset uses one disjoint interval list: positive event spans plus independently reviewed negative spans; unknown/unusable spans and uncovered gaps are separate from predictions. A future adjudication UI can retain richer overlapping annotation histories, but must resolve one frozen disjoint scoring view with lineage rather than overwrite this version.

### Offline import command and retained metadata

```sh
python3 -m poseidon_acoustic.dataset_cli import-platform datasets/synthetic-platform-import-v1/export.json datasets/synthetic-platform-import-v1/acceptance.json .local/observation-import-new.json
```

The retained example is entirely synthetic, including its actor, declared observer, reviewed-coverage claim and acceptance record. It is not a human-approved research protocol, permission or authenticated API session. `export.json` wraps one explicitly selected current stored revision per observation in `{format:"poseidon-platform-observation-export-v1", recording_id, recording_sha256, source_kind, observations:[...]}`. A real exporter must gather all pages and choose revisions explicitly; this CLI does not fetch the API or prove export completeness.

The acceptance file requires `protocol_id`, `acceptance_ref`, `accepted_by`, `accept_feeding_observed_as_feeding`, `accept_no_feeding_observed_as_reviewed_negative`, `allow_limited_visibility`, `max_sync_uncertainty_s` and a declared `confidence` grade. No acceptance defaults are filled in. Missing review context, unreviewed coverage, unaccepted protocol, missing evidence, rejected visibility or unknown/excess timing uncertainty excludes the interval from mapped observations and records each reason. Uncertain/not-visible labels remain unknown/unusable masks when their context is present. Overlaps, including overlaps with excluded masks, require adjudication rather than priority by label. Multiple revisions of one observation cannot be scored twice.

The conversion artifact retains the **entire original export and acceptance record**, plus their content hashes and mapped/excluded records. Actor and declared observer remain separate; mapped `observer_id` hashes the display name only as a local identifier, not as authenticated identity. All notes, original evidence references, review context, source hash, timestamps, auth mode and revision remain in the source object. Unknown future fields are rejected rather than dropped. Conversion checks the canonical shared observation validator. Checksums do not authenticate a file export or verify the truth of its source claims.

To bind the conversion into a dataset, put it inside the dataset directory, set the recording's optional `observation_import_path`, copy the artifact's mapped `observations`, and set dataset `protocol_ref` to the explicitly accepted `protocol_id`. Sealing validates the conversion again, matches recording ID/hash/provenance, checks every original interval against duration, compares mapped observations exactly and binds `observation_import_sha256`. Any later source, policy, actor, note, mask or mapping change invalidates that dataset version. Empty mappings leave unreviewed time, not negative exposure.

Clock relation fixtures are verified by the session suite. Canonical relations omit an epoch: `ClockMap.from_relation` therefore requires an explicit sidecar `reference_epoch` and retains it locally. No implicit UTC or synchronization claim is created. Source/chunk/frame/drop/storage metadata also remains in the immutable acquisition sidecar; current Platform association is not a full chunk ingestion API.

## Scoring policy

| ID | Rule | Consequence |
|---|---|---|
| EV1 | Score only observed-feeding/hard-negative intervals with visible/limited evidence and accepted timing uncertainty | Unknown, unusable, not-visible, not-applicable, excess-uncertainty and unreviewed time do not become absence evidence. Confidence grades are reported, not silently converted into probability weights. |
| EV2 | A prediction must lie entirely within the union of scorable coverage | Predictions touching excluded time are listed as excluded, not silently counted as true or false. Ground-truth positives are not removed merely because a candidate straddles a boundary. This conservative policy must be frozen before field scoring. |
| EV3 | Maximum-cardinality one-to-one matching at a configurable interval IoU | Half-open touching intervals do not match. One candidate cannot explain two feeding intervals, and duplicate predictions cannot count one observation twice. No hidden timestamp dilation. |
| EV4 | Precision = TP/(TP+FP); recall = TP/(TP+FN) | Undefined denominators return JSON null, never perfect scores. Each unmatched independent positive is a false negative, including in zero-candidate recordings. |
| EV5 | False alerts/hour = FP × 3600 / independently scorable seconds | Exposure includes positive and negative scorable time; all source/reviewed/scorable/excluded time is reported. This is not the rate per entire deployment hour. |
| EV6 | 95% Wilson event-binomial confidence intervals | Descriptive software calculation only. Correlated events within a day/site violate independent-binomial assumptions; a statistics reviewer must define cluster-aware field uncertainty and sample sufficiency. No false-alert-rate confidence interval is claimed. |
| EV7 | Threshold comparisons on validation; one threshold per holdout call | No automatic best-threshold selection. Repeated holdout calls cannot be prevented by an offline CLI; label access and preregistration remain process gates. Report hashes bind evaluator version, dataset, thresholds, split and matching policy. |

Reports include per-recording/site/start-day counts, excluded predictions, matched IDs, false-negative IDs, coverage, label/visibility durations and confidence counts. Midnight-spanning recordings retain all `covered_dates`; start-day strata do not divide events at midnight. Range, condition-specific biological performance and on-Pi CPU/memory/power measurements remain unmeasured. The old normalized-RMS detector is reused without changing its semantics or writing to the old evidence database.
