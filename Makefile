PYTHON ?= python3
UV ?= uv
BUN ?= bun
UV_PYTHON ?= 3.11
API_PORT ?= 8080
UI_PORT ?= 3000
DATA_DIR ?= .local/monitor
READINESS_TIMEOUT ?= 30
export NEXT_TELEMETRY_DISABLED := 1
SOURCE_PYTHONPATH := libs/proto-py/src:apps/acoustic/src:apps/trident/src:apps/aeolus-api/src
OUTPUT_DIR ?= .local/demo

# One Make invocation owns its caches. Separate invocations must not share them.
.NOTPARALLEL:
.DEFAULT_GOAL := help
VERIFY_ROOT ?= $(CURDIR)/.local/assurance-integration-v1
NEREID_PYTHON ?= 3.12
FIRMWARE_PYTHON ?= $(UV_PYTHON)
CAD_PYTHON ?= 3.12
ESP_PYTHON ?= 3.12
ESP_NINJA_VERSION := $(if $(filter Darwin,$(shell uname -s)),1.13.2,1.7.1)
ACQUISITION_PYTHONPATH := $(SOURCE_PYTHONPATH):apps/nereid/src:apps/siren/src:libs/dsp/src
FIRMWARE_PYTHONPATH := apps/aquilon/src:libs/proto-py/src
RUN := $(PYTHON) scripts/assurance/run_command.py
UNITTEST := scripts/assurance/run_unittest.py
API_VERIFY_ENV = UV_PROJECT_ENVIRONMENT="$(VERIFY_ROOT)/api/venv" UV_CACHE_DIR="$(VERIFY_ROOT)/api/uv-cache"
NEREID_VERIFY_ENV = UV_PROJECT_ENVIRONMENT="$(VERIFY_ROOT)/nereid/venv" UV_CACHE_DIR="$(VERIFY_ROOT)/nereid/uv-cache"
FIRMWARE_VERIFY_ENV = UV_PROJECT_ENVIRONMENT="$(VERIFY_ROOT)/firmware-update/venv" UV_CACHE_DIR="$(VERIFY_ROOT)/firmware-update/uv-cache"

.PHONY: help setup setup-api setup-ui setup-digital prepare-verification check check-python \
	test test-python test-tooling test-dev test-hub-legacy test-acoustic test-nereid test-siren \
	test-research test-acquisition test-acquisition-integration test-codec test-acquisition-api test-platform check-ops \
	test-aquilon test-aquilon-api log-host-compiler test-firmware test-firmware-sanitized test-firmware-native-sanitized test-hardware test-hardware-kernel check-hardware-reference \
	check-hardware-calculations check-hardware-candidate verify-cad-candidate fetch-vendor-sources check-vendor-fit test-assurance test-system test-ui typecheck-ui build-ui \
	prepare-browser-api test-browser-runner verify-browser verify-browser-auth verify-browser-legacy \
	verify-host verify-ui verify-cad compile-esp compile-esp-monitor verify-digital dev serve token sim build test-hil

help:
	@printf '%s\n' \
		'Poseidon Trident local targets:' \
		'  make setup                 Install locked API and UI dependencies for the local app' \
		'  make setup-digital         Prepare isolated API, NEREID and update Python environments' \
		'  make check                 Validate generated files, compile Python, and typecheck the UI' \
		'  make test                  Run host digital suites and UI unit tests' \
		'  make test-python           Run source-only tooling, acoustic, original Hub and dev suites' \
		'  make verify-host           Run Python/source/host gates; no UI or heavy native build' \
		'  make verify-ui             Run guarded UI tests/types/build and all three browser suites' \
		'  make verify-browser        Full browser workflow against the existing built bundle' \
		'  make verify-browser-auth   Strict browser-native auth/audit workflow in a new workspace' \
		'  make verify-browser-legacy Candidate/review/video workflows in a separate new workspace' \
		'  make verify-cad            Recompute actual CAD in a fresh owned native workspace' \
		'  make verify-cad-candidate  Recompute NON-ADOPTED passive-v2 and passive-v3 plus kernel tests' \
		'  make test-hardware-kernel  Live CadQuery negative tests against hardware/cad/.venv' \
		'  make compile-esp           Compile/link ESP reference only; NEVER upload or flash' \
		'  make compile-esp-monitor   Compile/check separate disabled and persisted monitor images' \
		'  make test-firmware-native-sanitized  Sanitize actual NVS/task fake-ABI code (100+33 minimum)' \
		'  make verify-digital        Run all bound host/browser/CAD/reference and monitor compile gates' \
		'  make test-acquisition-integration  Run exact codec and real Hub/API observation gates' \
		'  make test-codec            Require real MP4/H264 tests in the locked PyAV environment' \
		'  make test-acquisition-api  Run the separate API integration root; no av or TCP listener' \
		'  make test-aquilon-api       Run real local API integration in the separate locked environment' \
		'  make test-firmware-sanitized       Extra ASan/UBSan host runtime check' \
		'  make build-ui              Create the Next.js production build' \
		'  make dev                   Run the local API and Next development server' \
		'  make serve                 Run the local API and built Next bundle' \
		'    API_PORT=8181 UI_PORT=3100 DATA_DIR=.local/monitor-app override defaults' \
		'  make token                 Print the private local workspace access key' \
		'  make sim                   Create a passive synthetic replay in .local/demo' \
		'  make sim OUTPUT_DIR=PATH   Use a new or empty output directory' \
		'Digital checks do not authorize equipment, field operation or release.' \
		'Source-freeze evidence is separate; stale/externally blocked evaluation is not a green gate.'

# Preserve the app default environments; verification environments are scoped separately.
setup: setup-api setup-ui

setup-api:
	$(RUN) --timeout 600 -- $(UV) sync --project apps/aeolus-api --python $(UV_PYTHON) --frozen

setup-ui:
	$(RUN) --timeout 900 -- $(BUN) install --cwd apps/aeolus-ui --frozen-lockfile

prepare-verification:
	$(RUN) --timeout 30 -- $(PYTHON) scripts/assurance/prepare_workspace.py --directory "$(VERIFY_ROOT)"

setup-digital: prepare-verification
	$(API_VERIFY_ENV) $(RUN) --timeout 600 -- $(UV) sync --locked --project apps/aeolus-api --python "$(UV_PYTHON)"
	$(NEREID_VERIFY_ENV) $(RUN) --timeout 600 -- $(UV) sync --locked --project apps/nereid --python "$(NEREID_PYTHON)"
	$(FIRMWARE_VERIFY_ENV) $(RUN) --timeout 600 -- $(UV) sync --locked --project firmware/update --python "$(FIRMWARE_PYTHON)"

# Compile/bundle aggregation only; never upload, flash or run physical checks.
build: check-python build-ui compile-esp compile-esp-monitor

# This gate only validates authorization. No hardware implementation is linked.
# Guard exit 3 becomes GNU make exit 2 on recipe failure; no physical run follows.
HIL_AUTHORIZATION ?=
HIL_CONTROLLER_KEYS ?=
test-hil:
	@test -n "$(HIL_AUTHORIZATION)" && test -n "$(HIL_CONTROLLER_KEYS)" || { \
		echo "HIL refused: HIL_AUTHORIZATION and HIL_CONTROLLER_KEYS must name a controller-signed authorization file and a separate trusted key file; no hardware test ran" >&2; exit 2; }
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" $(RUN) --timeout 30 -- \
		$(PYTHON) scripts/assurance/hil_gate.py --authorization "$(HIL_AUTHORIZATION)" --trusted-controller-keys "$(HIL_CONTROLLER_KEYS)"

check: check-python typecheck-ui

check-python:
	$(RUN) --timeout 120 -- $(PYTHON) scripts/task_graph.py validate --tag production-v1
	$(RUN) --timeout 120 -- $(PYTHON) scripts/task_graph.py generate --tag production-v1 --check
	@set -eu; tmp=$$(mktemp -d) || exit 1; \
	trap 'rm -rf -- "$$tmp"' 0; trap 'exit 130' INT; trap 'exit 143' TERM; \
	PYTHONPYCACHEPREFIX="$$tmp" PYTHONPATH="$(ACQUISITION_PYTHONPATH):apps/aquilon/src:firmware/update/src" \
		$(RUN) --timeout 180 -- $(PYTHON) -m compileall -q \
		libs/proto-py/src libs/dsp/src apps/acoustic/src apps/nereid/src apps/siren/src \
		apps/trident/src apps/aeolus-api/src apps/aquilon/src firmware/update/src \
		scripts/assurance scripts/platform tests/tooling tests/acoustic tests/trident tests/dev \
		tests/api tests/proto tests/ops tests/nereid tests/siren tests/research tests/aquilon \
		tests/firmware tests/hardware tests/assurance tests/system

# No optional crypto discovery here: the full Hub suite belongs to test-platform.
test-python: test-tooling test-acoustic test-hub-legacy test-dev

test-tooling:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" $(RUN) --timeout 180 -- $(PYTHON) $(UNITTEST) -s tests/tooling

test-dev:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" $(RUN) --timeout 300 -- $(PYTHON) $(UNITTEST) -s tests/dev

test-hub-legacy:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" $(RUN) --timeout 120 -- $(PYTHON) $(UNITTEST) -s tests/trident -p test_hub.py
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" $(RUN) --timeout 120 -- $(PYTHON) $(UNITTEST) -s tests/trident -p test_media_and_limits.py
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" $(RUN) --timeout 120 -- $(PYTHON) $(UNITTEST) -s tests/trident -p test_recovery_and_safety.py

test-acoustic:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ACQUISITION_PYTHONPATH)" $(RUN) --timeout 180 -- $(PYTHON) $(UNITTEST) -s tests/acoustic

# The original 32 PGM/wiper tests are NOT MP4/H264 decoder evidence.
test-nereid: prepare-verification
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ACQUISITION_PYTHONPATH)" $(NEREID_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project apps/nereid --python "$(NEREID_PYTHON)" python $(UNITTEST) -s tests/nereid

test-siren:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ACQUISITION_PYTHONPATH)" $(RUN) --timeout 180 -- $(PYTHON) $(UNITTEST) -s tests/siren

test-research:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ACQUISITION_PYTHONPATH)" $(RUN) --timeout 180 -- $(PYTHON) $(UNITTEST) -s tests/research

test-acquisition: test-acoustic test-nereid test-siren test-research

# Full NEREID also runs these tests; the acquisition-owned floor is31 cases.
# Their removal must not become a green PGM-only or partial codec result.
test-codec: prepare-verification
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ACQUISITION_PYTHONPATH)" $(NEREID_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project apps/nereid --python "$(NEREID_PYTHON)" python $(UNITTEST) -s tests/nereid -p test_codec.py --min-tests 31

# The source-only acoustic suite includes the segment-to-v1 bridge tests.
# Real Hub/FastAPI observation integration has its own non-codec dependency root.
test-acquisition-api: prepare-verification
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(ACQUISITION_PYTHONPATH)" $(API_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project apps/aeolus-api --python "$(UV_PYTHON)" python $(UNITTEST) -s tests/research/integration

test-acquisition-integration: test-codec test-acquisition-api

test-platform: prepare-verification
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" $(API_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project apps/aeolus-api --python "$(UV_PYTHON)" \
		python scripts/assurance/run_pytest.py tests/api tests/trident tests/proto tests/ops -q -ra -p no:cacheprovider

check-ops:
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 60 -- $(PYTHON) scripts/platform/check_ops.py

# Standalone discovery remains dependency-free; the real API suite is separate.
test-aquilon:
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(FIRMWARE_PYTHONPATH)" $(RUN) --timeout 180 -- $(PYTHON) $(UNITTEST) -s tests/aquilon

# Actual Uvicorn/webhook loopback processes use owned port-zero sockets and cleanup.
test-aquilon-api: prepare-verification
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(FIRMWARE_PYTHONPATH):apps/acoustic/src:apps/trident/src:apps/aeolus-api/src" $(API_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project apps/aeolus-api --python "$(UV_PYTHON)" python $(UNITTEST) -s tests/aquilon/integration

log-host-compiler:
	$(RUN) --timeout 30 -- $(PYTHON) -c 'import os, subprocess; subprocess.run([os.environ.get("CXX", "c++"), "--version"], check=True)'

# Includes C++ host/runtime, private-update and canonical signed-manifest tests.
test-firmware: prepare-verification log-host-compiler
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(FIRMWARE_PYTHONPATH)" REEF_TEST_TMPDIR="$(VERIFY_ROOT)" $(FIRMWARE_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project firmware/update --python "$(FIRMWARE_PYTHON)" python $(UNITTEST) -s tests/firmware

test-firmware-sanitized: prepare-verification log-host-compiler
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(FIRMWARE_PYTHONPATH)" REEF_TEST_TMPDIR="$(VERIFY_ROOT)" REEF_SANITIZE=1 \
		$(RUN) --timeout 600 -- $(PYTHON) $(UNITTEST) -s tests/firmware -p test_runtime.py

# New adapters execute actual NVS/task/app_main code against fake ABI. These
# disjoint floors require all133 delivered cases; both sanitizer flags are set.
test-firmware-native-sanitized: prepare-verification log-host-compiler
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(FIRMWARE_PYTHONPATH)" REEF_TEST_TMPDIR="$(VERIFY_ROOT)" \
		REEF_SANITIZE=1 MONITOR_SANITIZE=1 $(FIRMWARE_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project firmware/update --python "$(FIRMWARE_PYTHON)" python $(UNITTEST) -s tests/firmware -p test_nvs_boot_identity.py --min-tests 100
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(FIRMWARE_PYTHONPATH)" REEF_TEST_TMPDIR="$(VERIFY_ROOT)" \
		REEF_SANITIZE=1 MONITOR_SANITIZE=1 $(FIRMWARE_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project firmware/update --python "$(FIRMWARE_PYTHON)" python $(UNITTEST) -s tests/firmware -p test_monitor_task.py --min-tests 33

test-hardware:
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 180 -- $(PYTHON) $(UNITTEST) -s tests/hardware

# Live CadQuery/OCP negative tests; needs a kernel interpreter (default hardware/cad/.venv).
# Kept outside tests/hardware discovery so test-hardware never records a skip.
test-hardware-kernel:
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 1200 -- $(PYTHON) $(UNITTEST) -s tests/hardware/kernel

# Archived hashes/arithmetic only; verify-cad separately executes the CAD kernel.
check-hardware-reference:
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 120 -- $(PYTHON) hardware/validation/check_reference.py
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 120 -- $(PYTHON) hardware/cad/check_manifest.py hardware/cad/generated/reference-v1

check-hardware-calculations: prepare-verification
	@set -eu; work=$$(mktemp -d "$(VERIFY_ROOT)/calculations.XXXXXX") || exit 1; \
	trap 'rm -rf -- "$$work"' 0; trap 'exit 130' INT; trap 'exit 143' TERM; \
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 180 -- sh -ec '\
		"$$1" hardware/electronics/calculate.py --output "$$2/electrical.json"; \
		cmp hardware/electronics/reference-evidence.json "$$2/electrical.json"; \
		"$$1" hardware/analysis/mechanical.py --output "$$2/mechanical.json"; \
		cmp hardware/analysis/calculated-reference.json "$$2/mechanical.json"; \
		"$$1" hardware/electronics/refine_power.py > "$$2/refinement.json"; \
		cmp hardware/electronics/refinement-evidence.json "$$2/refinement.json"' sh "$(PYTHON)" "$$work"

# NON-ADOPTED candidate checks preserve the frozen HW-REF-1.1 bytes and failed screens.
check-hardware-candidate: prepare-verification
	@set -eu; work=$$(mktemp -d "$(VERIFY_ROOT)/candidate-checks.XXXXXX") || exit 1; \
	trap 'rm -rf -- "$$work"' 0; trap 'exit 130' INT; trap 'exit 143' TERM; \
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 180 -- sh -ec '\
		"$$1" hardware/candidates/passive-v2/cad/check.py hardware/candidates/passive-v2/cad/generated/passive-v2; \
		"$$1" hardware/candidates/passive-v2/thermal/model.py --output "$$2/thermal.json"; \
		cmp hardware/candidates/passive-v2/thermal/results.json "$$2/thermal.json"; \
		"$$1" hardware/candidates/passive-v2/power/calculate.py > "$$2/power.json"; \
		cmp hardware/candidates/passive-v2/power/evidence.json "$$2/power.json"; \
		"$$1" hardware/candidates/passive-v2/check_candidate.py --output "$$2/review.json"; \
		cmp hardware/candidates/passive-v2/review-results.json "$$2/review.json"' sh "$(PYTHON)" "$$work"

# HIL authorization fixtures verify real Ed25519 signatures with existing crypto.
# uv run --locked prepares/reuses only this owned API verification environment.
test-assurance: prepare-verification
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" $(API_VERIFY_ENV) \
		$(RUN) --timeout 600 -- $(UV) run --locked --project apps/aeolus-api --python "$(UV_PYTHON)" python $(UNITTEST) -s tests/assurance

test-system:
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 180 -- $(PYTHON) $(UNITTEST) -s tests/system

test-ui:
	$(PYTHON) scripts/assurance/run_bun_tests.py --bun "$(BUN)" --cwd apps/aeolus-ui --timeout 180

typecheck-ui:
	$(RUN) --timeout 300 -- $(BUN) run --cwd apps/aeolus-ui typecheck

build-ui:
	$(RUN) --timeout 900 -- $(BUN) run --cwd apps/aeolus-ui build

test: verify-host test-ui

verify-host: check-python test-python test-acquisition test-platform check-ops test-aquilon test-aquilon-api \
	test-firmware test-hardware check-hardware-reference check-hardware-calculations check-hardware-candidate \
	test-assurance test-system test-acquisition-integration

# Browser installation is never automatic here. CI provisions the project-pinned
# Chromium executable in its own runner cache; local missing executables fail.
prepare-browser-api: prepare-verification
	$(API_VERIFY_ENV) $(RUN) --timeout 600 -- $(UV) sync --locked --project apps/aeolus-api --python "$(UV_PYTHON)"

test-browser-runner:
	PYTHONDONTWRITEBYTECODE=1 $(RUN) --timeout 180 --term-grace 20 -- $(PYTHON) $(UNITTEST) -s apps/aeolus-ui/qa -p test_run_platform_qa.py

# Keep each fresh artifact directory, including failed-run logs; runner removes
# only its private application workspace and closes every owned process group.
verify-browser: prepare-browser-api test-browser-runner
	@set -eu; artifacts=$$(mktemp -d "$(abspath $(VERIFY_ROOT))/browser-full.XXXXXX") || exit 1; \
	printf '%s\n' "Full browser artifacts: $$artifacts"; \
	bun=$$($(PYTHON) -c 'import pathlib,shutil,sys; p=shutil.which(sys.argv[1]); assert p, "Bun executable missing"; print(pathlib.Path(p).resolve())' "$(BUN)"); \
	env -u PLATFORM_QA_LEGACY_ONLY -u PLATFORM_QA_RESIDUAL_ONLY -u PLATFORM_QA_REMAINING_ONLY \
		PYTHONDONTWRITEBYTECODE=1 PLATFORM_QA_ARTIFACTS="$$artifacts" PLATFORM_QA_BUN="$$bun" \
		PLATFORM_QA_API_PYTHON="$(abspath $(VERIFY_ROOT))/api/venv/bin/python" \
		$(RUN) --timeout 600 --term-grace 20 -- $(PYTHON) apps/aeolus-ui/qa/run-platform-qa.py

verify-browser-auth: prepare-browser-api test-browser-runner
	@set -eu; artifacts=$$(mktemp -d "$(abspath $(VERIFY_ROOT))/browser-auth.XXXXXX") || exit 1; \
	printf '%s\n' "Native-auth browser artifacts: $$artifacts"; \
	bun=$$($(PYTHON) -c 'import pathlib,shutil,sys; p=shutil.which(sys.argv[1]); assert p, "Bun executable missing"; print(pathlib.Path(p).resolve())' "$(BUN)"); \
	env -u PLATFORM_QA_LEGACY_ONLY -u PLATFORM_QA_REMAINING_ONLY PLATFORM_QA_RESIDUAL_ONLY=1 \
		PYTHONDONTWRITEBYTECODE=1 PLATFORM_QA_ARTIFACTS="$$artifacts" PLATFORM_QA_BUN="$$bun" \
		PLATFORM_QA_API_PYTHON="$(abspath $(VERIFY_ROOT))/api/venv/bin/python" \
		$(RUN) --timeout 600 --term-grace 20 -- $(PYTHON) apps/aeolus-ui/qa/run-platform-qa.py

# Distinct legacy suite: original candidate/review/video proof is not inferred
# from full new-platform or native-auth checks. Other diagnostic modes are cleared.
verify-browser-legacy: prepare-browser-api test-browser-runner
	@set -eu; artifacts=$$(mktemp -d "$(abspath $(VERIFY_ROOT))/browser-legacy.XXXXXX") || exit 1; \
	printf '%s\n' "Legacy browser artifacts: $$artifacts"; \
	bun=$$($(PYTHON) -c 'import pathlib,shutil,sys; p=shutil.which(sys.argv[1]); assert p, "Bun executable missing"; print(pathlib.Path(p).resolve())' "$(BUN)"); \
	env -u PLATFORM_QA_RESIDUAL_ONLY -u PLATFORM_QA_REMAINING_ONLY PLATFORM_QA_LEGACY_ONLY=1 \
		PYTHONDONTWRITEBYTECODE=1 PLATFORM_QA_ARTIFACTS="$$artifacts" PLATFORM_QA_BUN="$$bun" \
		PLATFORM_QA_API_PYTHON="$(abspath $(VERIFY_ROOT))/api/venv/bin/python" \
		$(RUN) --timeout 480 --term-grace 20 -- $(PYTHON) apps/aeolus-ui/qa/run-platform-qa.py

verify-ui: test-ui typecheck-ui build-ui verify-browser verify-browser-auth verify-browser-legacy

# Fresh env/cache/output every run. Never overwrite canonical CAD or another run.
verify-cad: prepare-verification
	@set -eu; work=$$(mktemp -d "$(VERIFY_ROOT)/cad.XXXXXX") || exit 1; \
	trap 'rm -rf -- "$$work"' 0; trap 'exit 130' INT; trap 'exit 143' TERM; \
	PYTHONDONTWRITEBYTECODE=1 UV_PROJECT_ENVIRONMENT="$$work/venv" UV_CACHE_DIR="$$work/uv-cache" \
		$(RUN) --timeout 2700 -- sh -ec '\
		"$$1" run --locked --project hardware/cad --python "$$2" python -c "import sys, importlib.metadata as m; print(sys.version); print({n: m.version(n) for n in [\"cadquery\", \"cadquery-ocp\", \"vtk\", \"ezdxf\", \"trimesh\", \"numpy\"]})"; \
		"$$1" run --locked --project hardware/cad --python "$$2" python hardware/cad/generate.py --output "$$3/generated" --research-layout; \
		"$$1" run --locked --project hardware/cad --python "$$2" python hardware/cad/check_manifest.py "$$3/generated" --geometry' sh "$(UV)" "$(CAD_PYTHON)" "$$work"

# Separate digital candidate gate; this never adopts or rebinds HW-REF-1.1.
verify-cad-candidate: prepare-verification
	@set -eu; work=$$(mktemp -d "$(VERIFY_ROOT)/cad-candidate.XXXXXX") || exit 1; \
	trap 'rm -rf -- "$$work"' 0; trap 'exit 130' INT; trap 'exit 143' TERM; \
	printf '%s\n' 'Recomputing NON-ADOPTED passive-v2 / HW-CAND-2.0; no physical approval'; \
	PYTHONDONTWRITEBYTECODE=1 UV_PROJECT_ENVIRONMENT="$$work/venv" UV_CACHE_DIR="$$work/uv-cache" \
		$(RUN) --timeout 2700 -- sh -ec '\
		"$$1" run --locked --project hardware/cad --python "$$2" python -c "import sys, importlib.metadata as m; print(sys.version); print({n: m.version(n) for n in [\"cadquery\", \"cadquery-ocp\", \"vtk\"]})"; \
		"$$1" run --locked --project hardware/cad --python "$$2" python hardware/candidates/passive-v2/cad/generate.py --output "$$3/generated"; \
		"$$1" run --locked --project hardware/cad --python "$$2" python hardware/candidates/passive-v2/cad/check.py "$$3/generated" --geometry; \
		printf "%s\n" "Recomputing NON-ADOPTED passive-v3 / HW-09; no physical approval"; \
		"$$1" run --locked --project hardware/cad --python "$$2" python hardware/candidates/passive-v3/cad/generate.py --output "$$3/generated-v3"; \
		"$$1" run --locked --project hardware/cad --python "$$2" python hardware/candidates/passive-v3/cad/check.py "$$3/generated-v3" --geometry; \
		POSEIDON_CAD_PYTHON="$$3/venv/bin/python" "$$4" $(UNITTEST) -s tests/hardware/kernel' sh "$(UV)" "$(CAD_PYTHON)" "$$work" "$(PYTHON)"
# Optional private supplier fit check; never part of the offline hardware gates.
fetch-vendor-sources:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) scripts/hardware/fetch_vendor_sources.py

check-vendor-fit:
	PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python scripts/hardware/check_vendor_fit.py


# The IDF pip constraints apply ONLY here, never to API/update cryptography.
# Fresh sdkconfig avoids older generated settings overriding new defaults.
compile-esp: prepare-verification
	@set -eu; work=$$(mktemp -d "$(VERIFY_ROOT)/esp.XXXXXX") || exit 1; \
	trap 'rm -rf -- "$$work"' 0; trap 'exit 130' INT; trap 'exit 143' TERM; \
	PIP_CONSTRAINT="$(CURDIR)/firmware/toolchain/idf-python-constraints.txt" PIP_CACHE_DIR="$$work/pip-cache" \
		POSEIDON_NINJA_VERSION="$(ESP_NINJA_VERSION)" \
		UV_PROJECT_ENVIRONMENT="$$work/venv" UV_CACHE_DIR="$$work/uv-cache" \
		PLATFORMIO_CORE_DIR="$$work/pio-core" PLATFORMIO_PACKAGES_DIR="$$work/pio-core/packages" \
		PLATFORMIO_BUILD_DIR="$$work/pio-build" PLATFORMIO_BUILD_CACHE_DIR="$$work/pio-build-cache" \
		$(RUN) --timeout 2700 -- sh -ec '\
		"$$1" run --locked --project firmware/toolchain --python "$$2" python -c "import sys, importlib.metadata as m; print(sys.version); print(\"platformio=\" + m.version(\"platformio\"))"; \
		"$$1" run --locked --project firmware/toolchain --python "$$2" platformio run --project-dir firmware/reference -e reef_reference; \
		"$$1" run --locked --project firmware/toolchain --python "$$2" platformio pkg list --project-dir firmware/reference -e reef_reference; \
		"$$3/pio-core/packages/toolchain-xtensa-esp-elf/bin/xtensa-esp32-elf-g++" --version; \
		"$$3/pio-core/packages/tool-cmake/bin/cmake" --version; \
		"$$3/pio-core/packages/tool-ninja/ninja" --version' sh "$(UV)" "$(ESP_PYTHON)" "$$work"

# Additive monitor project only. Original reference compile and partition layout
# stay separate. Each profile gets a new explicit build/sdkconfig root; verbose
# compiler commands, nonfatal diagnostics and actual linked ELF evidence survive
# in stdout. No CMake compile_commands inference, upload, flash or target run.
compile-esp-monitor: prepare-verification
	@set -eu; work=$$(mktemp -d "$(abspath $(VERIFY_ROOT))/esp-monitor.XXXXXX") || exit 1; \
	trap 'rm -rf -- "$$work"' 0; trap 'exit 130' INT; trap 'exit 143' TERM; \
	PIP_CONSTRAINT="$(CURDIR)/firmware/toolchain/idf-python-constraints.txt" PIP_CACHE_DIR="$$work/pip-cache" \
		POSEIDON_NINJA_VERSION="$(ESP_NINJA_VERSION)" \
		UV_PROJECT_ENVIRONMENT="$$work/venv" UV_CACHE_DIR="$$work/uv-cache" \
		PLATFORMIO_CORE_DIR="$$work/pio-core" PLATFORMIO_PACKAGES_DIR="$$work/pio-core/packages" \
		PLATFORMIO_BUILD_CACHE_DIR="$$work/pio-build-cache" \
		$(RUN) --timeout 2700 --term-grace 20 -- bash -o pipefail -ec '\
		"$$1" run --locked --project firmware/toolchain --python "$$2" python -c "import sys, importlib.metadata as m; print(sys.version); print(\"platformio=\" + m.version(\"platformio\"))"; \
		PLATFORMIO_BUILD_DIR="$$3/disabled-build" "$$1" run --locked --project firmware/toolchain --python "$$2" platformio run --project-dir firmware/monitor-target -e monitor_disabled -v 2>&1 | tee "$$3/disabled.log"; \
		PLATFORMIO_BUILD_DIR="$$3/persisted-build" "$$1" run --locked --project firmware/toolchain --python "$$2" platformio run --project-dir firmware/monitor-target -e monitor_persisted -v 2>&1 | tee "$$3/persisted.log"; \
		"$$4" scripts/assurance/check_monitor_build.py --disabled-build "$$3/disabled-build" --persisted-build "$$3/persisted-build" --disabled-log "$$3/disabled.log" --persisted-log "$$3/persisted.log" --packages "$$3/pio-core/packages"; \
		"$$3/pio-core/packages/toolchain-xtensa-esp-elf/bin/xtensa-esp32-elf-g++" --version; \
		"$$3/pio-core/packages/tool-cmake/bin/cmake" --version; \
		"$$3/pio-core/packages/tool-ninja/ninja" --version' bash "$(UV)" "$(ESP_PYTHON)" "$$work" "$(PYTHON)"

# Bound digital gates include each accepted lane; no physical release follows.
# No evidence evaluator here: digital success cannot close external release gates.
verify-digital: verify-host test-firmware-sanitized test-firmware-native-sanitized verify-ui verify-cad verify-cad-candidate compile-esp compile-esp-monitor

dev:
	$(PYTHON) scripts/dev.py start --ui-mode dev --data-dir "$(DATA_DIR)" --api-port "$(API_PORT)" --ui-port "$(UI_PORT)" --readiness-timeout "$(READINESS_TIMEOUT)"

serve:
	$(PYTHON) scripts/dev.py start --ui-mode production --data-dir "$(DATA_DIR)" --api-port "$(API_PORT)" --ui-port "$(UI_PORT)" --readiness-timeout "$(READINESS_TIMEOUT)"

token:
	@$(PYTHON) scripts/dev.py token --data-dir "$(DATA_DIR)"

sim:
	@if [ "$(OUTPUT_DIR)" = ".local/demo" ]; then \
		if [ -L .local ]; then printf '%s\n' 'error: .local must not be a symbolic link' >&2; exit 2; fi; \
		mkdir -p .local; \
	fi
	PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$(SOURCE_PYTHONPATH)" \
		$(PYTHON) -m poseidon_acoustic demo --output-dir "$(OUTPUT_DIR)"
