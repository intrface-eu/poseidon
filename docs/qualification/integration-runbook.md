# Digital integration verification

Date: 2026-09-08. Historical `make verify-digital` run exited 0, including browser, CAD, reference and monitor-target gates. The removed historical evidence bundle does not attest the current source state. Cold-build monitor hashes differed despite matching SDK configurations; bit-for-bit reproducibility was not established. This runbook does not accept a field, physical, regulatory or commercial gate.

The current Make targets and GitHub Actions workflows are authoritative; rerun them on the checked-out revision rather than using historical run logs as current evidence.

## Environments and discovery boundaries

Every command runs from the repository root. Source imports include `libs/proto-py/src`, `apps/acoustic/src`, `apps/nereid/src`, `apps/siren/src`, `libs/dsp/src`, `apps/aquilon/src`, `apps/trident/src` and `apps/aeolus-api/src` as needed. Use explicit `PYTHONPATH`, not an unrelated editable install.

| ID | Digital coverage | Required environment | Execution boundary |
|---|---|---|---|
| D1 | `tests/tooling`, `tests/dev` and original Hub regression files | Source Python ≥3.11; original Hub `test_hub.py`, `test_media_and_limits.py`, `test_recovery_and_safety.py` remain separately runnable | Source-only tooling, file/loopback supervisor mocks; not production service deployment |
| D2 | `tests/acoustic`, `tests/siren`, top-level `tests/research` | Source Python and acquisition source roots | WAV replay/segment export, synthetic scheduler/wiper/data methods; no capture, acoustic emission, biology or calibrated SPL |
| D3 | All `tests/nereid`, plus explicit nonempty `test_codec.py` gate | `apps/nereid/uv.lock`, Python ≥3.12,<3.13, `av==16.1.0` | Recorded MP4/H264 software path, not live camera. Native worker uses selected `sys.executable`; no codec/interpreter fallback. The old 32 tests alone do not establish codec coverage. |
| D4 | `tests/api`, full `tests/trident`, `tests/proto`, `tests/ops` | `apps/aeolus-api/uv.lock`, including pytest/FastAPI/httpx and cryptography 46.0.3 | Full local platform and signature simulations. Plain Python can skip lifecycle tests and is not this gate. Static service checks are not Docker execution. |
| D5 | `tests/research/integration` | API lock and acquisition/Hub/API source roots, without adding `av` | Real Hub/FastAPI TestClient pagination/export/evaluation; `start_worker=False`, no TCP service. Independent observer coverage is not all noncandidate time. |
| D6 | Standalone `tests/aquilon` | Source Python, `apps/aquilon/src` and `libs/proto-py/src` | SQLite/CBOR/bridge and owned loopback mocks. Missing canonical source path or fixture must fail, not skip. |
| D7 | Additive `tests/aquilon/integration` / `test_real_api.py` | API lock plus `apps/aquilon/src:libs/proto-py/src:apps/acoustic/src:apps/trident/src:apps/aeolus-api/src` | Firmware lead verified 12 real-API tests without skips. They own prebound loopback port-zero Uvicorn/webhook processes and bounded shutdown; no live ChirpStack or radio. `test-aquilon-api` is bound in R2 and passed12 cases in parent/root checks; do not mix API dependencies into standalone discovery. |
| D8 | `tests/firmware` host runtime, update, canonical signing, actual NVS and monitor-task fake-ABI tests | `firmware/update/uv.lock`, cryptography 46.0.3 and C++17 host compiler | Wave3 full suite280 includes original147 plus NVS100 and monitor33. The separate native sanitizer gate sets both `REEF_SANITIZE=1` and `MONITOR_SANITIZE=1`, with disjoint minimums100 and33. No flash, real NVS power-cut/wear, sensors or RF. |
| D9 | `tests/hardware`, reference validator, archived CAD audit, deterministic electrical/mechanical/refinement comparisons | Source Python ≥3.11 | Source/manifest/arithmetic consistency. A failed thermal/solar screen remains a failed design assumption even if its regression test passes. Archived CAD audit does not run the geometry kernel. |
| D10 | Fresh CAD generation and `check_manifest.py --geometry` | `hardware/cad/uv.lock`, Python3.12, pinned CadQuery/OCP/VTK stack | Actual native solids/STEP/STL recomputation in a new owned directory; no pressure/strength/marine qualification |
| D11 | ESP compile-only `platformio run --project-dir firmware/reference -e reef_reference` | `firmware/toolchain/uv.lock`, Python ≥3.11,<3.14, PlatformIO6.1.18, pinned platform/tool packages and scoped IDF constraints | Fresh environment/build/sdkconfig/cache; no `upload`, flashing, fuse changes or target operation. IDF cryptography41.0.7 constraints must not contaminate API/update46.0.3. |
| D12 | `tests/assurance`, `tests/system` | Source Python; suite-specific locked environments remain separate | Evidence false-claim guards and synthetic real-component checks; no automatic release approval |
| D13 | UI tests, typecheck and build | Bun and `apps/aeolus-ui/bun.lock` | Use `bun run --cwd apps/aeolus-ui test`, `typecheck`, `build`; retain `NEXT_TELEMETRY_DISABLED=1`. Platform holds the current local frontend slot; assurance has not run these commands. |

Hardware baseline remains `HW-REF-1.1`. The later `passive-v2 / HW-CAND-2.0` work is a **NON-ADOPTED candidate**; its additive tests may join source discovery, but no baseline dossier is automatically rebound and no design/physical gate passes by inclusion. `check-hardware-candidate` checks archived exports, preservation and deterministic calculations; `verify-cad-candidate` separately runs the published candidate generator and fresh geometry checker. Root reports230 generation/230 fresh geometry checks and179 source tests with144 baseline files unchanged; no thermal/autonomy/physical acceptance follows.

## Non-skipping and process controls

`run_unittest.py` discovers one explicit root and reports actual test counts. Zero tests, a count below `--min-tests`, any skip, expected failure, unexpected success, failure or error gives a nonzero exit. The default minimum is1; acquisition explicitly requires `--min-tests 31` for the dedicated codec gate, not merely one surviving test. `run_pytest.py` invokes pytest from the chosen locked environment and rejects collection/runtime skips, xfail/xpass, empty or collect-only runs while preserving other nonzero exits. Subtests are call reports, not extra collected test functions; do not sum them into a product-completion count.

`run_bun_tests.py` requests a fresh JUnit report from the existing Bun package test script and checks nonempty testcases, reconciled counts and no represented skips/failures/todo/incomplete outcomes. Real temporary Bun1.3.14 fixtures confirmed rejection of mixed pass/skip and pass/todo even when Bun itself exits0. Malformed, absent, oversized, entity-bearing, symlink or non-regular reports fail. Bun1.3.14 does not distinguish `test.failing(...)` from an ordinary pass in JUnit; the guard cannot detect that unrepresented expected outcome and does not claim to parse JavaScript semantics.

`run_command.py --timeout <seconds> -- <command...>` executes without a shell in a new owned process group. Timeout returns124; signal termination follows shell-style status; ordinary nonzero exits remain nonzero. Normal completion also stops surviving descendants in that owned group. Cancellation is deferred during spawn registration without giving children blocked signals, and protected during cleanup until escalation/reaping finish. Browser gates select `--term-grace 20` because the inner runner may need15 seconds to clean three groups; ordinary checks default to3 seconds. No broad process, browser, port or project kill is used.

`prepare_workspace.py --directory <repo>/.local/<name>` accepts a new/empty workspace or its exact typed ownership marker. It rejects traversal, symlink parents/markers, foreign or malformed markers and nonempty unowned data. Isolated verification environments must not replace a lane's active `.venv` or write another lane's lockfile. CAD and ESP use fresh owned output/build environments, not shared active caches or stale generated sdkconfig.

The source-only `make sim` behavior, local API/UI port/data/readiness overrides, `setup/dev/serve/token` behavior and legacy local app commands must remain intact. New all-digital checks add explicit gates rather than treating optional dependency skips as success. CI describes proposed execution only until a remote run actually occurs; no remote job, push or deployment was triggered by this work.

## Actual assurance-runner evidence

Assurance executed:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/assurance/run_command.py --timeout 180 -- \
  python3 -B scripts/assurance/run_unittest.py -s tests/assurance
```

Historical local assurance runner: 104 tests passed with zero failures, errors or skips; subprocess success/failure/skip/error fixtures, cleanup and cache isolation were exercised. A separate 24-case runner suite passed under the locked API interpreter. These checks do not count all product suites.

Historical `test-assurance test-python check-ops` run exited 0, with assurance71, tooling11, acoustic109, legacy Hub6+7+12 and dev20; static ops stated `docker_executed:false`.

The subsequent `make verify-host` run exited 0 with reported NEREID64, platform173 plus60 subtests, AQUILON67, firmware147, hardware117, assurance98, system9, codec31 and observation/API18. Source changed during that run, so it is not a current source-freeze attestation. A separate historical `make verify-cad compile-esp` run exited 0; counts from that run were not independently extracted here.

## Applied Make targets (R1–R3)

| Target | Meaning and scope |
|---|---|
| `setup` / `setup-api` / `setup-ui` | Existing local app dependency setup, split into reusable targets; preserves default app environments |
| `setup-digital` | Separate locked API/NEREID/firmware-update environments under owned `VERIFY_ROOT` |
| `check-python` / `check` | Task graph/generated consistency and Python compilation; `check` also includes UI typecheck |
| `test-python` | Source-only tooling, acoustic, original Hub and dev regressions |
| `test-acquisition` / `test-acquisition-integration` | Acoustic/NEREID/SIREN/research; explicit codec plus real observation/API integration |
| `test-platform` / `check-ops` | Locked full API/Hub/proto/ops tests; static service validation remains separate from Docker |
| `test-aquilon` / `test-firmware` / `test-firmware-sanitized` | Standalone gateway, locked host/update/canonical firmware and separate ASan/UBSan mode |
| `test-hardware` / `check-hardware-reference` / `check-hardware-calculations` | Source/reference tests, archived manifest audit and fresh deterministic calculation comparisons |
| `test-assurance` / `test-system` | Non-skipping assurance fixtures and synthetic real-component scenarios |
| `verify-host` | Bound non-UI host gates, including separate actual AQUILON/API and candidate consistency checks |
| `verify-ui` | Guarded Bun tests, typecheck, build and all three separate browser suites |
| `verify-browser` / `verify-browser-auth` / `verify-browser-legacy` | Full new workflows / strict native auth / original candidate-review-video; each clears other mode flags and uses a fresh retained artifact directory |
| `verify-cad` / `verify-cad-candidate` / `compile-esp` | Separate baseline and NON-ADOPTED candidate native geometry, plus unchanged reference ESP compile-only; isolated caches |
| `verify-digital` | Bound host/sanitizer/UI/browser/native gates; the separate later monitor-target descriptor is still pending, not silently counted |

Make targets use separate verification roots and caches. GitHub Actions permits `runner.temp` in step-level `env`, not job-level `env`; YAML parsing alone does not validate workflow contexts. Each revision needs its own executed checks.

Historical UI checks passed Bun tests, typecheck, build, QA runner and three browser modes. The legacy gate used a silent synthetic MP4 with its declared hash, muted playback and protected ranges; it did not claim service restart, live capture or speaker operation. `.NOTPARALLEL` serializes one Make process only: concurrent processes need distinct `VERIFY_ROOT` values and cannot share the active Next cache. CI now runs on every push; local checks and historical outcomes are not substitutes for its results.

## R4 monitor extension

`test-firmware-native-sanitized` uses the locked update environment, enables both sanitizer flags and runs the disjoint NVS100 and monitor33 test minimums. Historical runs of those recipes passed without skips. A separate historical assurance suite recorded 177 tests, including 73 monitor-checker regressions; rerun it for current evidence.

`compile-esp-monitor` is separate from unchanged `compile-esp`. It builds `firmware/monitor-target` profiles `monitor_disabled` and `monitor_persisted` in distinct fresh absolute build/sdkconfig roots, with isolated pinned toolchain caches. Verbose compiler output is retained through `tee` with Bash pipefail. No upload or target execution occurs. CI passes the selected host Python into sanitizer gates, and IDF crypto41 constraints remain scoped to target builds rather than the crypto46 host environments.

`scripts/assurance/check_monitor_build.py` checks actual verbose `src/main.cpp` compile records with exactly0/1 persistence flags, regular bounded ELF/bin/sdkconfig files, Xtensa metadata, eight required defined text symbols per profile and distinct binaries. It does not use `compile_commands.json`. Bounded read-only nm/objdump calls have cancellation-safe registration and cleanup. Parent independently checked the existing paired controller builds: exit0, all stated checks passed, and20 diagnostic records were retained. Nonfatal bootloader git-version and unused `LEGACY_INCLUDE_COMMON_HEADERS` diagnostics are not suppressed or called warning-free.

The checker emits `initializer_semantics_verified:false`, `manual_initializer_review_required:true` and `fresh_build_provenance_verified:false`. Make establishes fresh build execution; the parser does not attest it from filenames or hashes. Raw initializer and `app_main` disassembly, command/output hashes and matching ELF hashes survive in the JSON before temporary native directories are removed. Those bytes require separate manual review, not a register/address heuristic. The controller's earlier manual review at `root-monitor-builds.SS46tL/root-manual-initializer-review.json` applies only to its named ELF hashes; it is not silently transferred to new images. This compile/link evidence cannot close physical NVS wear/power-cut, runtime timing/resource, sensor/radio, secure-update or field gates.

## One final evidence refresh after controller freeze

Do not execute this sequence while any lane or root integration file is still changing.

- **A1 — Freeze and retain.** Controller identifies the accepted source/environment/reference state and authorizes the refresh. Preserve wave1 `gate-policy-v1.json`, `evidence-manifest-v1.json`, report/log and its recorded stale exit1. Do not overwrite them or suppress the failure.
- **A2 — Prepare a new policy.** Create a separately reviewed policy such as `docs/qualification/gate-policy-w2.json` with a new policy ID and the new G-LOCAL/G-SOFTWARE report path. Preserve all external-gate rules, exact requirement coverage and explicit HW-REF-1.1 binding unless a separately reviewed change says otherwise. This policy file is not yet created by this preparation step.
- **A3 — Execute once against new paths.** Run the commands below after the policy exists and the source is frozen. Output directories/files must be new; writers refuse existing user data. `--policy` selects the new record without modifying the old policy.
- **A4 — Interpret exits.** Integrity validation exit0 means bytes/structure/source inputs agree. Evaluation exit2 means valid evidence but externally blocked product; exit1 means invalid/stale/incomplete evidence. Neither is release authorization. If sources change during or after execution, stop and report the mismatch; do not churn snapshots without another reviewed freeze.

```sh
python3 scripts/assurance/run_system_checks.py \
  --policy docs/qualification/gate-policy-w2.json \
  --output-dir docs/qualification/evidence-w2
python3 scripts/assurance/snapshot.py \
  --policy docs/qualification/gate-policy-w2.json \
  --output docs/qualification/evidence-manifest-w2.json
python3 scripts/assurance/evidence.py validate \
  --policy docs/qualification/gate-policy-w2.json \
  --manifest docs/qualification/evidence-manifest-w2.json
python3 scripts/assurance/evidence.py evaluate \
  --policy docs/qualification/gate-policy-w2.json \
  --manifest docs/qualification/evidence-manifest-w2.json
```

The source-bound system report covers its named synthetic scenarios, not the entire native/UI/platform matrix. Full digital verification logs and the controller's acceptance remain separate evidence. Site, scientific, hardware, conformity, manufacturing, support and commercial decisions stay open where actual qualified evidence is missing.
