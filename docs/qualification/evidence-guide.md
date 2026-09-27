# Assurance evidence and gate evaluation

Date: 2026-09-08. Status: software assurance tooling; external qualification blocked.

The [gate policy](gate-policy-v1.json) is the machine-readable requirements-to-evidence trace matrix. Each of its 15 rows names the exact requirement IDs, roadmap phases and V-gates, owner role, dependencies, tangible artifact, method, criterion, current status and missing proof. It covers the current production requirements and P0–P9/V1–V9 without changing those root-owned records. `G-EFFICACY` is conditional on an active/deterrence claim; a failed efficacy result does not invalidate the local passive monitor. `G-SCOPE` keeps flora research separate. Neither branch grants a release by omission.

## Evidence levels are not interchangeable

| Level | What it means here | What it cannot establish |
|---|---|---|
| `software-complete` | Scope-limited software work accepted by its responsible reviewer, such as the prior local tranche | Physical behavior, lawful field work, efficacy or whole-product completion |
| `simulated` | Executed real software with explicitly synthetic or simulated inputs and recorded source hashes | Real sensor calibration, deployed radio behavior, pressure integrity, HIL, ecology or CE conformity |
| `source-verified-vendor-data` | Identified manufacturer source, retrieval date, exact part/revision and extracted fact reviewed against that source | Supplied-unit identity, actual assembly fit/performance or current procurement availability |
| `independently-reviewed` | Identified competent reviewer accepts a specific method/configuration/result and residual risk; evidence held for manual verification | A computer-created signature or an agent's assertion of professional approval |
| `physically-tested` | Actual unit/instrument/environment/method/raw-result records against frozen criteria | Approval by file existence, a CAD result or simulation labeled as a measurement |
| `authority-decision` | Genuine dated written decision matched to site/activity/conditions and checked for expiry | Permission derived from guidance, a draft request, historic trial or farm consent alone |
| `documented-plan` | Prepared procedure, technical-file material, applicability research or unperformed template | Any performed test or passed external gate |

The manifest deliberately classifies desk dossiers as `documented-plan`, even when they cite genuine official/vendor sources. Machine-readable dossier data (the SBOM, license inventory, metadata snapshot and their schemas) is recorded as kind `inventory` at `software-complete`: hashed and parsed, never a gate closure; a JSON template that declares `is_template` stays a plan. The precise source verification is in those dossiers. The evaluator does not certify that a citation was read or that a claimed reviewer exists.

## Commands and exit meanings

Run from the repository root, with Python 3.11 or later and the repository source present:

```sh
python3 -m unittest discover -s tests/assurance -v
python3 -m unittest discover -s tests/system -v
python3 scripts/assurance/run_system_checks.py --output-dir docs/qualification/evidence
python3 scripts/assurance/snapshot.py --output docs/qualification/evidence-manifest-v1.json
python3 scripts/assurance/evidence.py validate
python3 scripts/assurance/evidence.py evaluate
```

The recording commands refuse an existing output directory/file. They must not overwrite the published snapshot or user files. The first wave uses the names above. A later evidence revision needs a new named evidence directory, an explicitly reviewed gate-policy artifact-path update and a new manifest, not silent replacement. `validate --manifest <repo-relative-path>` selects that new manifest. The current runner names its files `system-checks-v1.json` and `.log` inside the chosen new directory.

`validate` exits **0** when integrity and structure checks pass, **1** on invalid/missing/stale evidence. `evaluate` exits **2** for the expected blocked product, **1** for corrupt/incomplete evidence. Both return `release_authorized:false`. Exit 0 from integrity validation is not release approval. A shell/CI integration must preserve this distinction; do not write `evaluate || true` and label the gate passed. Full root `make check`, `make test` and `make build-ui` remain controller-owned and are not invoked by these tools.

The system runner invokes exactly `python3 -m unittest discover -s tests/system -v` with a 120-second timeout. It records a report only for a nonempty, entirely passing, unskipped run whose verbose test identities/count agree with the log. It hashes source before and after execution and refuses to accept a run that races a source edit. A failed/incomplete run keeps its original log in the newly owned directory but produces no accepted report. It never executes a command from an evidence document.

## Manifest and record rules

The v1 manifest has an exact schema implemented by `scripts/assurance/evidence.py`: version, policy/configuration identity, timezone-aware creation time, artifacts, all gate claims and `release_authorized:false`. Artifact entries contain a canonical relative path, SHA-256, byte length, kind, evidence level, applicable gate IDs and configuration. Missing, duplicate, malformed, extra-field, nonfinite, future-dated or inconsistent records fail. Absolute/traversing paths and symlinks fail; the tools neither follow them into unknown data nor overwrite them.

A `plan` must have substantive content and disclose its open/unperformed state. This catches empty or obvious placeholder dossiers, not scientific or legal correctness. A `test-report` must match the exact supported synthetic system command, test identities/count, passing log, configuration and current non-cache file inventory in the selected source/contract/test directories, including binary fixtures, plus the root Python manifest and API Python manifest/lock. Added, removed or changed inputs invalidate it. The inventory does not attest installed packages, interpreter binaries or code outside those declared paths; selected-device/reproducible-environment qualification remains separate. The manifest hashes all supplied dossier bytes too. Source changes in other workstreams during this wave can therefore invalidate a previously correct snapshot; report that staleness rather than suppress it.

An `external-candidate` is an optional JSON wrapper for future genuine external evidence. It requires version 1, `is_template:false`, configuration, evidence level, performed timestamp, author, method, frozen criterion revision, result, a nonempty mapping of local raw-file paths to SHA-256, and limitations. Even a structurally valid candidate stays blocked. Verification of identity, qualifications, authority, scope, calibration, sample selection, measurement uncertainty and accepted result remains a human review. Do not wrap an unperformed template as actual evidence.

## What the result means

Only `G-LOCAL` may report `software-checks-passed`. That status refers to the named synthetic real-component scenarios, not every possible local behavior. All other gates remain `blocked` with owner and missing-proof text, regardless of external self-attestations or filenames. The policy forbids automation of those gates, checks dependency cycles/missing references, and checks that no root requirement or roadmap verification category is omitted.

The tool is a conservative evidence intake and release guard, not a signature/attestation system or final release engine. A passing report can be forged by someone able to rewrite the report and log; hashes detect changes, not truth. Reviewers must inspect provenance and actual execution records. Automatic physical/regulatory closure is intentionally absent. A later professionally reviewed release mechanism requires its own authorized design; this wave cannot declare production complete.

The tests use temporary directories and synthetic data. Hub tests preserve unknown file bytes, inode, mode, size and modification time; a stable `.hub.lock` coordination inode may remain after rejected initialization. No hardware operation, live capture, service listener, browser, firmware flash or field activity is part of the assurance suite.
