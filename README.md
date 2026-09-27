# Poseidon Trident

Poseidon Trident investigates fish predation on shellfish farms in Limski kanal, Istria. The project starts with passive acoustic monitoring to gather evidence and assess what can be detected; whether acoustic deterrence can be safe or effective is a research question, not a product feature.

Software has been tested with synthetic data, and digital hardware designs exist. No physical hardware has been built or deployed. We are looking for pilot shellfish farms, marine biology and bioacoustics partners, acoustic and embedded engineers, and funding collaborators. See [the public project page](https://poseidon.intrface.eu), [contribution guide](CONTRIBUTING.md), [licenses and ownership notice](NOTICE), or email basic@intrface.eu.

## Run the monitor application

Requires Python 3.11 or later, uv, Bun, and Make. From the repository root:

```sh
make setup
make dev API_PORT=8181 UI_PORT=3100 DATA_DIR=.local/monitor-app
```

Open `http://127.0.0.1:3100`. In another terminal, retrieve this workspace's private access key:

```sh
make token DATA_DIR=.local/monitor-app
```

The workspace key is generated once and stored with private permissions; it grants local-development admin access. Do not commit or share it. Browser sessions use HttpOnly, SameSite=Strict cookies. Separate scoped principals restrict local access by role, site and device; this is not production identity management or physical device provisioning.

`make dev` without overrides uses API port 8080, UI port 3000, and `.local/monitor`. Occupied ports are rejected rather than cleared. Ctrl+C stops the services owned by that launcher. Existing recordings, reviews, and queued jobs survive restart.

Once unlocked, load the explicitly synthetic demo or import a WAV plus its provenance manifest. Select a recording and candidate to inspect its waveform, attach optional MP4 evidence, and save an operator observation. Synthetic provenance and uncalibrated amplitude remain visible. Video alignment is operator-declared, not verified synchronization.

See the [runtime guide](docs/development/monitor-runtime.md), [original monitor API](docs/development/monitor-api-contract.md) and [additive platform API](contracts/platform-v1-api.md) for limits, endpoints and operations.

## Checks

```sh
make check
make test
```

After stopping the dev server, verify the production UI bundle:

```sh
make build-ui
make serve API_PORT=8181 UI_PORT=3100 DATA_DIR=.local/monitor-app
```

`make serve` runs the built UI locally with the same API and workspace. It is not an Internet deployment or a production-readiness claim.

The [digital integration runbook](docs/qualification/integration-runbook.md) covers locked environments, non-skipping test runners, browser suites, CAD reconstruction and compile-only ESP targets. CI runs on GitHub Actions on every push; local checks alone do not establish Linux/ARM64 or hardware qualification.

## Standalone passive replay

The original source-only replay path still requires no Python package installation:

```sh
make sim
make test-python
```

The demo creates a WAV, manifest, SQLite evidence store, and two synthetic candidates under `.local/demo`. It produces no audio playback and refuses to overwrite a nonempty directory. Use `make sim OUTPUT_DIR=.local/demo-2` for another run. The [replay guide](docs/development/passive-replay.md) describes direct replay and JSONL export.

## What remains

Candidate events are not species identification, confirmed feeding, calibrated SPL or prevented stock loss. Operator-entered observations do not change those limits. The application does not capture from live sensors/cameras or operate radios, actuators, projectors or acoustic hardware.

Live capture adapters, complete acquisition-sidecar ingestion, production identity/hosting/security controls and installed update execution remain unfinished software. Hardware operating design still has thermal, autonomy, field-power/protection and mounting/sealing gaps; CAD validity does not close them.

Field permissions, local detection performance, acoustic safety and sustained deterrence efficacy, physical qualification, conformity, manufacturing and funded support remain open. No purchase, field activity, emission or commercial claim is authorized by this repository.

## Project records

- [Hardware reference](HARDWARE.md) and [non-adopted passive candidate](hardware/candidates/passive-v2/README.md)
- [Production roadmap and historical audit](docs/production-roadmap.md)
- [Requirements and verification matrix](docs/requirements/production-requirements.md)
- [Passive-first architecture decision](docs/decisions/0001-passive-first-system-boundary.md)
- [Passive collection protocol](docs/research/passive-audio-video-collection-protocol.md)
- [Site and permissions evidence](docs/research/site-permissions-evidence-register.md)
- [Initial hazard register](docs/safety/initial-hazard-register.md)
- [Monitor application verification](docs/validation/development-tranche-002.md)
- [First replay-tranche verification](docs/validation/development-tranche-001.md)

The root v0.1 PRD, funding brief, and old hardware estimate are preserved as labeled historical records. They do not define current readiness or approved claims.
