# Linux ARM64 no-device verification environment

This is a local development verification environment for the ALSA/V4L2 native shim. It is not a Raspberry Pi image, device-capture test, hardware qualification or field-release approval. Earlier accepted evidence remains unchanged.

## Recorded status

The first owned Lima/VZ session booted Debian13 ARM64, reported Linux6.12.107+deb13-cloud-arm64 and Python3.13.5 as UID1000, and stopped with no owned VM/control processes remaining. `boot-proof-001/result.json` records exit0 and `cleanup_ok: true`. This proves boot, identity and shutdown only.

`combined-002` returned exit0. Pinned guest provisioning, real-header compile/link smoke, the production native build and all four no-device ABI tests passed. UID/EUID remained1000 for compilation and tests; the VM stopped with `cleanup_ok: true`. Independent parent checks found no owned processes across either combined run or the earlier boot session.

`combined-001` remains a failed run: provisioning and smoke execution passed, but header evidence collection rejected Debian13's UAPI layout. A retained `linux-libc-dev6.12.107-1/all` package inspection justified admitting exactly five observed ARM64 headers, without a directory wildcard. The controller authorized that one correction and one confirmation run; original failed-run bytes remain unchanged. The package-layout observation is post-run host analysis, not guest output.

The final focused host helper command returned exit0:26 tests, zero skips:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tests/assurance -p test_linux_capture_env.py -v
```

Parent verification rechecked28 selected source hashes,5 frozen helper hashes,76 retained `.deb` files,1029 package-evidence artifacts and68 smoke/profile artifacts. The native library is ELF64 little-endian AArch64, artifact kind1. Build/smoke manifests retain their stage-local false flags for later stages; the subsequent four-test gate log supplies the ABI-test evidence.

## Pinned inputs

| Input | Identity |
| --- | --- |
| Lima | Official2.2.0 Darwin-arm64 archive,37586365bytes |
| Lima archive SHA256 | `bbdef91774885a0d05f7b048c4eb89ae2bcf3a0c252ae7ca7934e63df76d93c3` |
| Debian | Official13/trixie genericcloud ARM64 raw image, build20260831-2587,3221225472bytes |
| Debian published SHA512 | `d1217c88cd84a659686490fb206463138ca04dedcd4c061a6dae68eee1d3b288ad2bb2d096238b99e740d2557988cd24ce84df4c3a96a236d0d0a55c7297ecc1` |
| Image local SHA256 | `d22881efc5c04ea29a7e876eedc8f8817d884efd1c72a0decec2043accf99149` |
| Guest package repositories | Signed Debian and Debian-security snapshots at20260901T000000Z; no upgrade/dist-upgrade |
| GCC compiler / metapackage | `14.2.0-19` / `4:14.2.0-1` |
| libc6 / libc6-dev | `2.41-12+deb13u3`; glibc runtime2.41 |
| Kernel / linux-libc-dev | `6.12.107+deb13-cloud-arm64` / `6.12.107-1` |
| ALSA runtime / development | `libasound2t64` and `libasound2-dev`, both `1.2.14-1` |
| Python runtime / package | `3.13.5` / `python3.13=3.13.5-2+deb13u4` |
| Production library SHA256 | `30553cbd186f8dd55f0ecdc0045d226cdc8f6cda3c93e086baa1dd7ad83d831e` |
| Native profile SHA256 | `2d62f6a027fd35c70e0d19319307b73ff4df54c1bb21b7b6115bc61dc15f633b` |

Official inputs:

- [Lima archive](https://github.com/lima-vm/lima/releases/download/v2.2.0/lima-2.2.0-Darwin-arm64.tar.gz) and [SHA256SUMS](https://github.com/lima-vm/lima/releases/download/v2.2.0/SHA256SUMS).
- [Debian image](https://cloud.debian.org/images/cloud/trixie/20260831-2587/debian-13-genericcloud-arm64-20260831-2587.raw) and [SHA512SUMS](https://cloud.debian.org/images/cloud/trixie/20260831-2587/SHA512SUMS).

The image SHA256 was calculated locally after checking the published SHA512; it is not a Debian-published SHA256. Neither archive checksum verification nor the untouched Lima ad-hoc signature establishes publisher identity through an independently authenticated release signature. No Developer-ID/notarization claim is made.

## Bootstrap, run and stop

Run from the repository root. [`bootstrap.py`](../../scripts/assurance/linux_capture_env/bootstrap.py) accepts only a new absent cache, downloads the fixed HTTPS inputs once with deadlines, verifies their hashes and extracts checked entries. It refuses existing caches, quarantine or signature failures; it does not repair host settings. Its new downloader was tested offline, not rerun end-to-end over the network. Offline extraction matched198 files from the retained verified official archive. The actual VM runs used the previously verified cache.

```sh
# Optional new cache; do not overwrite the retained verification cache.
python3 -B scripts/assurance/linux_capture_env/bootstrap.py \
  --cache "$PWD/.local/linux-capture-env-new"

# Reuse the retained verified cache; output must not already exist.
PYTHONDONTWRITEBYTECODE=1 python3 -B scripts/assurance/linux_capture_env/runner.py \
  --cache "$PWD/.local/linux-capture-env-task18-2026-09-08" \
  --output "$PWD/.local/linux-capture-env-task18-tranche2-2026-09-08/new-run" \
  --native-inputs "$PWD/.local/acquisition-native-inputs.json"
```

A future run needs an owned acquisition input manifest with current matching hashes; private historical manifests are not checkout fixtures. The executed combined sessions also used a private launcher with a 9000-second aggregate deadline.

[`runner.py`](../../scripts/assurance/linux_capture_env/runner.py) requires Darwin arm64, supported VZ, at least12GiB free space and a verified project-local cache. It creates a new short private `/tmp` runtime and a new VM for every run. It never adopts a pre-existing instance.

The VM has2CPUs,2GiB RAM and an8GiB virtual disk. It mounts nothing and shares no host home, personal SSH keys, SSH agent, devices or proxy/secret environment. Its observed control listener must be loopback-only. Audio/video/USB passthrough, incidental port forwarding, container services, Rosetta, virtual capture-device modules and host privilege/security changes are outside this route.

Guest root is used only for setup and pinned package provisioning. Smoke, native build and ABI tests run unprivileged. Their allowed operations are real-header compilation, linking, library identity, layouts, constants and the reviewed no-device test calls. They must not enumerate, open or stream capture devices.

Every VM/control command has a deadline. The runner collects this run's guest evidence and stops the owned VM in `finally`; timeout/cancellation cannot turn a failed check into a pass. Shutdown checks the owned SSH socket and exact runtime-bound processes. `cleanup_ok: false` prevents success. Do not use broad process kills or control other Lima homes to recover this run.

## Acquisition input boundary

The final controller ruling selected the four-test native ABI gate with the real acoustic package import. Acquisition published28 selected file hashes in its amended operational input manifest, preserving its before-amend manifest. The executed manifest SHA256 is `676675c43cd1a96a7f1e7f433be650ffdf1add3ca474027893d73bc85eddd9be`. The selected acoustic closure includes its real `__init__.py` and dependencies; the selected `poseidon_proto` package is explicitly enumerated. Only the selected NEREID module uses a namespace package.

The runner copies only those listed files, checks guest transfer hashes, and checks host/staged/guest hashes after execution. Changing live-journal/supervisor/CLI files remain excluded. The cancelled acoustic namespace-only v2 proposal is not the selected run. Four ABI tests do not constitute broad application integration testing.

## Evidence locations

The verified cache and completed boot evidence are private, untracked development artifacts under `.local/linux-capture-env-task18-2026-09-08/`. New Task18 records belong under `.local/linux-capture-env-task18-tranche2-2026-09-08/`; earlier failed-download and accepted boot records are retained, not overwritten.

Within `combined-002/`, `result.json` retains every control command/exit/log; `guest-package-inputs/package-inputs.json` identifies all76 package/deb inputs; `guest-verification/native-profile.json` records152 file identities; `native-build/build.json` identifies the production artifact; `command-019.stderr.log` records the four passing tests; and `cleanup-process-proof.json` records stopped state. `independent-host-audit.json` records the child’s separate host checks.

Historical handoff and independent audit records are private and are not distributed in this repository. They do not authorize device capture, demonstrate bitwise rebuild reproducibility, close physical/safety/permission gates or qualify the full application.
