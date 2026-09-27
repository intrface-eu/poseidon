# Development tranche 001: verification record

Date: 2026-09-07. Reviewed working tree on `dev`, based on `da5b22c`; no commit or deployment was made.

## Accepted scope

This tranche delivers the P0 baseline, P1 desk-preparation documents, a validated production backlog, and the P2-dev synthetic/offline replay slice. It does not complete field feasibility, hardware, CAD, acoustic intervention, or production qualification.

| Evidence | Result | Boundary |
|---|---|---|
| Production baseline | 25 unique requirements, named owner roles, verification methods, explicit unknowns, passive-first ADR, and revised historical claims. | Requirement documentation is not field or scientific acceptance. |
| Research preparation | Site/permission register, unapproved collection protocol, initial hazards, and unsent prior-trial request drafts exist. | No site access, permission, quote, spending approval, or expert sign-off was obtained. |
| Backlog | 31 production tasks, IDs 101–131, with valid same-tag dependencies and deterministic generated records. | The old `master` and `crack-attack` records remain unchanged historical objects; their known defects were not silently rewritten. |
| Passive replay | Strict v1 provenance models; PCM16 per-channel amplitude analysis; deterministic candidates; hash-bound input; atomic, idempotent SQLite storage; JSONL export; synthetic demo. | Candidate events are not confirmed feeding, species identification, calibrated SPL, or deterrence evidence. |

## Commands run by the integration reviewer

| Command | Observed result |
|---|---|
| `make check PYTHON=python3.11` | Exit 0: production graph, generated-file consistency, and Python compilation passed. Interpreter: Python 3.11.15. |
| `PYTHONWARNINGS=always::ResourceWarning make test PYTHON=python3.11` | Exit 0: 11 tooling tests and 31 acoustic tests passed. No resource warning appeared in the final run. |
| `make check PYTHON=python3` | Exit 0 on Python 3.14.7. |
| `PYTHONWARNINGS=always::ResourceWarning make test PYTHON=python3` | Exit 0: the same 42 tests passed on Python 3.14.7. No resource warning appeared in the final run. |
| `make sim OUTPUT_DIR=<temporary-directory>/demo` | Exit 0; produced `synthetic.wav`, `recording-manifest.json`, `evidence.sqlite3`, and `events.ndjson`, containing two synthetic candidates with emissions disabled. |
| `git diff --check` | Exit 0 after changed-line whitespace corrections. |

The test count is 42 distinct tests, run on two interpreters, not 84 distinct tests. Local validation ran on macOS; the GitHub Actions Linux matrix is configured for Python 3.11 and 3.14 but was not run remotely. No Raspberry Pi execution is claimed.

## Independent integration checks

- **V1 — Input and channel handling:** a separately constructed opposite-phase stereo WAV yielded exactly two candidates, with frame intervals `[320, 640)` and `[960, 1120)`. The last interval verified partial-window/EOF handling without channel cancellation.
- **V3 — Replay and persistence:** the CLI demo, replay, and event export returned exit 0. Replaying the same manifest/config reported `already_present=true` and exported identical JSONL without duplicate events.
- **V4 — File preservation:** repeating the demo in its nonempty directory returned exit 2. Modifying the WAV while retaining its original hash caused replay to return exit 2; the existing database's SHA-256 remained unchanged.
- **V4 — Generator isolation:** independent temporary-directory tests confirmed refusal of generated-file symlinks, namespace symlinks into the legacy root, and unexpected generated-name files. Outside sentinels and unknown files were preserved.
- **V1 — Malformed input:** oversized numeric JSON is rejected without an uncaught traceback. Tooling tests also cover nesting limits, malformed JSON, invalid UTF-8, ID/schema errors, and graph cycles. The interpreter's numeric safety limit was not raised.
- **V1 — Repository records:** the root historical PRD and `.taskmaster/docs/prd.txt` were byte-identical at this historical checkpoint. The tracked `.taskmaster/config.json` is now a regular file; the obsolete broken local symlink was removed.

The first review found unsafe generator cleanup, stale test expectations, an uncaught numeric JSON error, and test-only SQLite connection leaks. Those issues were corrected before the final passing runs. A delegated worker also deleted a newly created roadmap outside its scope; the document owner restored it from the approved plan. No pre-existing user document was lost.

## Requirement and task acceptance

This record supplies local software evidence for `REQ-SW-001` and `REQ-SW-003` in the [requirements matrix](../requirements/production-requirements.md). It does not verify `REQ-DET-001`, field capture, synchronization with real cameras, physical safety, biological efficacy, or any compliance requirement.

Production backlog tasks 101, 102, 107, and 131 may be marked done for their bounded documentation/preparation/tooling deliverables. Task 102 means a preparation packet exists, not that P1 research or permissions are complete. All field, expenditure, measurement, active-output, manufacturing, and release gates remain open.

## Research update affecting the next phase

The [official ARIEL Croatian regional pilot report](https://ariel.adrioninterreg.eu/wp-content/uploads/2020/07/ARIEL_D.T2.4.1_Pilot_Activities_-regional_Report_HRVate.docx) describes a 2019 DDD03L pinger trial at two Lim Bay concessions. Initial protection did not persist; severe predation was reported by mid-July, and the July repeat failed after about two weeks. This negative result was added to the [site evidence register](../research/site-permissions-evidence-register.md). It does not establish another safe/effective treatment or prove every acoustic approach ineffective.

## Not performed

No dependency installation, remote CI run, cloud deployment, hardware purchase, fabricated CAD/PCB, device operation, physical safety test, live recording, acoustic playback, animal exposure, field deployment, regulatory filing, external contact, shipment, commit, or push occurred. Source screening and software tests do not replace the qualified reviews and permissions named in the [production roadmap](../production-roadmap.md).
