# Local software inventory and secrets checks

Status: software assurance artefacts, not a release SBOM, license clearance, vulnerability audit or conformity decision. All commands below are local and install nothing. Use Python 3.11 or newer.

## Inventory inputs and outputs

`software_inventory.py` discovers current working-tree inputs, including untracked files. At initial generation none of these inputs appeared in `git ls-files`; do not describe them as committed locks.

| Input | Meaning |
|---|---|
| `apps/aeolus-api/uv.lock` | API Python lock, including its development records |
| `apps/nereid/uv.lock` | Recorded-codec Python lock |
| `apps/aeolus-ui/bun.lock` | Bun text lock; all package records, including optional non-host platforms |
| `apps/site/bun.lock` | Site Bun text lock; installed metadata is read from `apps/site/node_modules` |
| `firmware/toolchain/uv.lock` | PlatformIO Python toolchain lock |
| `firmware/update/uv.lock` | Update-reference Python lock, cryptography 46.0.3 |
| `firmware/toolchain/idf-python-constraints.txt` | Exact IDF environment freeze, cryptography 41.0.7; not the API/update environment and not an archive-content lock |
| `firmware/reference/platformio.ini`, `firmware/monitor-target/platformio.ini`, `Makefile` | Exact platform/tool package versions; Ninja's sole environment-variable pin resolves to the two literal `ESP_NINJA_VERSION` Makefile versions (macOS 1.13.2, Linux x86_64 1.7.1). The Makefile input hashes only that selector line and its exports in `compile-esp` and `compile-esp-monitor`; these are not complete transitive or archive-content locks. |

Every input has a path, kind, byte count and SHA256 in all inventory outputs. Adjacent `pyproject.toml`/`package.json` manifests are hashed too. New, deleted or changed locks, including whitespace changes, fail the stale-output gate. For the Makefile, only the three selected Ninja lines count as inventory bytes; unrelated target edits do not stale the inventory, while a missing or changed export fails closed. Unknown recognized lock formats and nonexact PlatformIO pins fail rather than disappear from coverage; only the exact Ninja interpolation at the two firmware projects resolves against the Makefile selector.

- `sbom.cdx.json`: CycloneDX 1.5 component inventory. The official schema defines `bomFormat`, `specVersion`, `version`, `metadata`, components, references, properties and named license choices. No timestamps or random serial numbers are added.
- `license-inventory.json`: each component's exact locked identity, every lock occurrence, raw locked dependency/marker/artifact details, declared license metadata, provenance, counts and coverage gaps.
- `metadata-snapshot.json`: reviewed installed metadata, bound to input hashes. Normal generation uses this snapshot, so an offline Linux checkout need not reproduce a Darwin install just to check the files.

Components deduplicate by ecosystem, normalized name, literal version and locked source identity. Different registries, unresolved constraint provenance, local-workspace roots and versions remain distinct. PlatformIO owner names remain in source identity; package metadata matches the exact unqualified package name and version, not a verified owner or content signature. The same Python name/version from a constraints-only source is not silently asserted to be the same locked registry artifact.

Raw lock dependency declarations remain in the license inventory. The SBOM omits the dependency graph rather than inventing resolved version edges from Bun ranges or conditional UV markers. It does not select a deployment target or claim every listed optional/dev/tool package ships in a product.

Initial inventory: 170 components from 190 lock/pin occurrences, across 8 inputs. Ecosystems: 85 npm, 75 Python source-qualified identities, 10 PlatformIO. Declared metadata exists for 115; 55 remain unresolved: 51 npm records absent from this host install and 4 local virtual Python projects. No license is guessed. Machine-readable counts are authoritative after regeneration.
Current generated inventory: 217 components from 244 occurrences across 10 inputs, including the site Bun lock, Makefile selector and separate macOS/Linux Ninja versions. The Linux 1.7.1 entry has no retained installed-package metadata and is marked unresolved; the existing macOS 1.13.2 declaration remains unchanged. After the site rebuild, a scoped metadata refresh kept 138 declared components; no locked component identities were removed.

Of the 51 absent npm records, 49 carry lock `os`/`cpu` conditions, such as `@next/swc-linux-arm64-gnu`, `@img/sharp-linux-x64` and `@typescript/typescript-win32-x64`. The other two are `@img/sharp-wasm32` and its dependency `@emnapi/runtime`; the lock places the former under the FreeBSD/webcontainers Sharp variants. A read-only search of the entire existing project `node_modules` found no matching metadata for any of the 51. There is no project `.bun` store or package-root symlink in this install; its seven symlinks are `.bin` executable links to in-project targets. These gaps are not an overlooked isolated Bun layout. The Bun workspace root has no locked version, so only actual locked package records become components.

## Metadata provenance and gaps

Python metadata comes from `*.dist-info/METADATA` in the existing root/app `.venv` environments and explicitly supplied firmware environments. JavaScript metadata comes from installed `node_modules` package roots, including nested versions. The generator reads data only; it never imports package code. PlatformIO metadata comes from the approved core's `platforms/*/platform.json` and `packages/*/package.json`.

Each observation retains exact name/version, declaration field/value, source-relative metadata path and file SHA256. `License-Expression`, `License`, license classifiers and package JSON `license`/`licenses` fields are verbatim declarations. They become **named** CycloneDX licenses, not inferred SPDX IDs. Classifiers and expressions are not legal conclusions. Conflicting declarations remain visible instead of being reconciled by guesswork. Empty/UNKNOWN declarations remain absent.

The root Python project has no adjacent lock. App/firmware directories without their own locks or pins are listed as gaps, including code using the shared root environment. Root/app metadata can help match an exact locked name/version but does not establish a separately installed firmware environment. Firmware source-tree `.venv` paths are absent; the approved external environments below provide their metadata. OS packages, bundled native libraries, SDK/toolchain subcomponents and release artifacts are not enumerated by these inputs. A package's top-level declaration does not license every bundled component or exception.

External metadata uses stable `metadata-source:` identities in generated files. A refresh requires four explicit read-only local sources; choose paths for your own installed, pinned environments. Private paths are not included in this repository.

| Source ID | Local source to provide |
|---|---|
| `firmware-toolchain` | `<toolchain-venv>` |
| `firmware-update` | `<update-venv>` |
| `firmware-idf` | `<platformio-core>/penv/.espidf-5.3.1` |
| `firmware-platformio` | `<platformio-core>` |

## Regenerate and check

Run from the repository root. Portable offline checks use the existing snapshot and do not require external metadata directories.

```sh
python3 -B scripts/assurance/software_inventory.py
python3 -B scripts/assurance/software_inventory.py --check
python3 -B -m unittest discover -s tests/assurance -p 'test_software_inventory.py' -v
```

After an input or installed-license metadata change, review the change and explicitly refresh. This replaces only the three generated JSON files, never the locks/environments. If only an app's lock or manifest changed, refresh that app's installed metadata and preserve all other reviewed sources:

```sh
python3 -B scripts/assurance/software_inventory.py --refresh-metadata --only apps/site
```

`--only` accepts a direct `apps/` directory with its lock and installed metadata. It rejects changes to inputs or manifests outside that directory and refuses missing installed metadata. It replaces metadata paths and environment records under the selected directory, retains matching metadata from all other sources for shared components, and drops identities removed from that app's lock. Check the generated diff before accepting it. A full refresh still requires all four approved firmware sources below; omitting them makes the coverage shrink visibly. No download or installation is performed to fill missing licenses.

```sh
python3 -B scripts/assurance/software_inventory.py --refresh-metadata \
  --metadata-source firmware-toolchain=.local/firmware-pio-venv \
  --metadata-source firmware-update=.local/firmware-update-venv \
  --metadata-source firmware-idf=.local/firmware-pio-core/penv/.espidf-5.3.1 \
  --metadata-source firmware-platformio=.local/firmware-pio-core
```

To recheck every installed metadata byte, use `--check --check-local-metadata` with those same four `--metadata-source` arguments. This stricter check fails if any captured file is unavailable or differs; ordinary `--check` checks the frozen snapshot, not current installations. Preserve the snapshot and provenance when temporary environments are retired.

`schema/` retains the official CycloneDX specification **1.5 tag** JSON schemas from `https://raw.githubusercontent.com/CycloneDX/specification/1.5/schema/`. The script pins each SHA256 and validates the emitted profile against those schemas with an offline evaluator. It supports the validation keywords reached by this output and **fails on unsupported applicable keywords**. It is not a general JSON Schema validator; draft-07 `format` remains an annotation. No standard `jsonschema`/`fastjsonschema` package was present in the inspected root/app/approved firmware environments, and none was installed. Tests reject bad component types, missing fields, invalid license choices/SPDX IDs, duplicate references, changed schemas and stale inputs. The schema files retain upstream notices; their `$comment` identifies Apache-2.0 terms.

## Fixed-pattern secrets scan

```sh
python3 -B scripts/assurance/secrets_scan.py
python3 -B -m unittest discover -s tests/assurance -p 'test_secrets_scan.py' -v
```

The scanner walks the project tree, including untracked files and `.env` source/config files. It ignores `.gitignore`; a new untracked matching credential blocks the check. It never traverses host home, `.git`, `.local` runtime credentials, virtual environments, dependency installations, caches or symlinks. Binary suffixes, NUL-containing files and generated `.log` outputs are excluded and counted; historical accepted logs remain untouched. Other unreadable, non-UTF-8, special or oversized files fail coverage rather than silently passing. Bounds: 8 MiB per file, 256 MiB read bytes, 30,000 files. Exclusions and counts appear in each report.

Patterns cover PEM private-key headers/bodies, AWS access IDs, GitHub/Slack/Google/Stripe-shaped keys, long quoted credential assignments and password-bearing service URLs. Reports expose only redacted location/pattern/fingerprint metadata, never candidate text. The pattern set is hashed. Credentials with unknown formats, short passwords, split/encoded values, binary or excluded content can evade this finite scan. A passing result is not proof that no possible secrets exist. Freeze sources before retaining scan evidence; the script cannot make concurrent repository edits atomic.

The allowlist rejects wildcards, global pattern suppression, traversal, duplicate identities, stale entries and changed occurrence counts. Synthetic exceptions require an exact path, pattern, fingerprint and specific justification. Three shipped `.toml.example` occurrences are uppercase REPLACE-prefixed synthetic placeholders. PEM fingerprints bind the body as well as the header.

### Retained third-party exceptions (closed 2026-09-09)

During software tranche 3 the two Wago vendor snapshots under `hardware/candidates/passive-v2/power/sources/` carried credential-like `smartMaps.apiKey` frontend values, and the scanner held two root-approved, publication-blocking exceptions for them. Hardware run B redacted both values to the literal `REDACTED`, rehashed the snapshots and their candidate locks, and removed the two allowlist entries. The scanner no longer has a non-synthetic exception category: every allowlist entry must be a synthetic fixture on a test, fixture or `.example` path, `publication_blocked` is always false, and any non-synthetic match blocks the check. The earlier ruling stays in the private tranche 3 evidence for history only.

## Freeze dependencies

Input/manifest edits require reviewed metadata refresh and regenerated JSON. Generator/schema edits require regeneration and both inventory tests/checks. Metadata-source removal does not invalidate portable checks, but prevents a live metadata recheck until the approved source is restored. Scanner/pattern/allowlist or any scanned source change requires a fresh redacted scan and test run. Root adoption of SECURITY.md, other leads' final edits and snapshot remediation all require another source scan. Keep earlier accepted evidence immutable; only new tranche3 evidence remains mutable until controller freeze.
