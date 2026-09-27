#!/usr/bin/env python3
"""Offline lock inventory. No installs, package imports, timestamps or network calls.

Refresh metadata explicitly on the reviewed host; normal generation/check uses the
hashed snapshot so machines without those installed environments can verify it.
"""
from __future__ import annotations

import argparse
import configparser
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tomllib
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path("docs/compliance/software-supply-chain")
SCHEMA_HASHES = {
    "bom-1.5.schema.json": "067f7824b08653839ea050ae9e09ca48375eadc2652b0e2a299476e7db90335b",
    "spdx.schema.json": "4f6e2b05c05d26a4f2dc5879fbc2fca94b0a28db46289d0c51345621b71cfbfc",
    "jsf-0.82.schema.json": "8bae002c25e723db7ee1f26afde680ae1a2b1a8f6b4b4b0fd65dc3becb090aae",
}
SKIP_DIRS = {".git", ".local", ".venv", "node_modules", ".next", ".pio", "build", "dist", "__pycache__", ".cache"}
KNOWN_LOCKS = {"uv.lock", "bun.lock", "bun.lockb", "Cargo.lock", "dependencies.lock", "conan.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock"}
MAX_INPUT = 16 * 1024 * 1024


def encoded(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def read_bound(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular input: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise ValueError(f"input exceeds {MAX_INPUT} bytes: {path.name}")
    return data

def esp_ninja_pin_bytes(path: Path) -> bytes:
    """Hash only the selector and the exports that feed the two ESP builds."""
    lines = read_bound(path).splitlines()
    selectors = [line for line in lines if line.startswith(b"ESP_NINJA_VERSION")]
    if len(selectors) != 1:
        raise ValueError("missing or ambiguous ESP_NINJA_VERSION selector in Makefile")
    selected = [selectors[0]]
    expected = b'\t\tPOSEIDON_NINJA_VERSION="$(ESP_NINJA_VERSION)" \\'
    for target in (b"compile-esp", b"compile-esp-monitor"):
        headings = [index for index, line in enumerate(lines) if line.startswith(target + b":")]
        if len(headings) != 1:
            raise ValueError(f"missing or ambiguous {target.decode()} target in Makefile")
        exports = []
        for line in lines[headings[0] + 1:]:
            if not line.startswith(b"\t"):
                break
            if b"POSEIDON_NINJA_VERSION" in line:
                exports.append(line)
        if exports != [expected]:
            raise ValueError(f"missing or changed {target.decode()} Ninja export in Makefile")
        selected.append(exports[0])
    return b"\n".join(selected) + b"\n"


def normalize(name: str, ecosystem: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "pypi" else name


def jsonc(data: bytes) -> dict:
    """Bun text lock supports comments/trailing commas. Never alter strings."""
    text = data.decode("utf-8")
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/|,(?=\s*[}\]])')
    clean = tokens.sub(lambda m: m[0] if m[0].startswith('"') else ("\n" * m[0].count("\n") if m[0].startswith("/") else ""), text)
    # A comma before a comment is only removable after comments are stripped.
    clean = tokens.sub(lambda m: m[0] if m[0].startswith('"') else "", clean)
    return json.loads(clean)


def walk_files(base: Path):
    if not base.exists():
        return
    for directory, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            yield Path(directory) / name


def discover(root: Path) -> tuple[list[dict], list[dict]]:
    """Include untracked inputs; git status is deliberately not part of bytes."""
    inputs = []
    manifests = []
    candidates = [p for top in ("apps", "firmware", "libs") for p in walk_files(root / top)]
    candidates += [root / n for n in ("uv.lock", "bun.lock", "pyproject.toml", "package.json") if (root / n).exists()]
    for path in sorted(candidates):
        rel = path.relative_to(root).as_posix()
        name = path.name
        kind = None
        if name in KNOWN_LOCKS:
            if name not in {"uv.lock", "bun.lock"}:
                raise ValueError(f"unsupported dependency lock (not silently omitted): {rel}")
            kind = "uv" if name == "uv.lock" else "bun"
        elif rel.startswith("firmware/") and name == "idf-python-constraints.txt":
            kind = "pip-exact-constraints"
        elif rel.startswith("firmware/") and name == "platformio.ini":
            kind = "platformio-exact-pins"
        elif name in {"pyproject.toml", "package.json"}:
            raw = read_bound(path)
            manifests.append({"path": rel, "sha256": digest(raw), "bytes": len(raw), "adjacent_lock": next((str(path.with_name(n).relative_to(root)) for n in ("uv.lock", "bun.lock") if path.with_name(n).exists()), None)})
        if kind:
            raw = read_bound(path)
            inputs.append({"path": rel, "kind": kind, "sha256": digest(raw), "bytes": len(raw)})
    if not inputs:
        raise ValueError("no supported lock inputs found")
    # The one host-selected PlatformIO pin is defined in Make, not a registry range.
    if any(i["kind"] == "platformio-exact-pins" and b"${sysenv.POSEIDON_NINJA_VERSION}" in read_bound(root / i["path"]) for i in inputs):
        data = esp_ninja_pin_bytes(root / "Makefile")
        inputs.append({"path": "Makefile", "kind": "platformio-host-pins", "sha256": digest(data), "bytes": len(data)})
        inputs.sort(key=lambda i: i["path"])
    return inputs, manifests


def locked_components(root: Path, inputs: list[dict]) -> list[dict]:
    ninja_versions = None
    components: dict[str, dict] = {}

    def add(ecosystem, name, version, source, path, locator, details=None):
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise ValueError(f"missing exact package name/version in {path}")
        name = normalize(name, ecosystem)
        identity = {"ecosystem": ecosystem, "name": name, "version": version, "source": source}
        ref = "urn:poseidon:component:" + digest(canonical(identity).encode())
        record = components.setdefault(ref, {"bom-ref": ref, **identity, "occurrences": []})
        record["occurrences"].append({"path": path, "locator": locator, "locked_details": details or {}})

    for inp in inputs:
        path, kind = inp["path"], inp["kind"]
        data = esp_ninja_pin_bytes(root / path) if kind == "platformio-host-pins" else read_bound(root / path)
        if digest(data) != inp["sha256"]:
            raise ValueError(f"input changed while reading: {path}")
        if kind == "uv":
            lock = tomllib.loads(data.decode())
            if lock.get("version") != 1 or not isinstance(lock.get("package"), list):
                raise ValueError(f"unsupported uv structure: {path}")
            for index, package in enumerate(lock["package"]):
                source = package.get("source")
                if not isinstance(source, dict) or not source:
                    raise ValueError(f"missing locked source: {path}")
                # Relative workspace sources are local to the lock, not global.
                if any(key in source for key in ("virtual", "editable", "directory", "path")):
                    source = {"lock_directory": str(Path(path).parent), **source}
                add("pypi", package.get("name"), package.get("version"), source, path, f"package[{index}]", {k: v for k, v in package.items() if k not in {"name", "version", "source"}})
        elif kind == "bun":
            lock = jsonc(data)
            if lock.get("lockfileVersion") != 1 or not isinstance(lock.get("packages"), dict):
                raise ValueError(f"unsupported bun structure: {path}")
            for locator, package in sorted(lock["packages"].items()):
                if not isinstance(package, list) or len(package) != 4 or not isinstance(package[0], str):
                    raise ValueError(f"unsupported bun entry: {path} / {locator}")
                name, sep, version = package[0].rpartition("@")
                if not sep or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]+)?", version):
                    raise ValueError(f"non-registry/unpinned bun entry: {path} / {locator}")
                add("npm", name, version, {"registry": package[1] or "https://registry.npmjs.org", "integrity": package[3]}, path, locator, package[2])
        elif kind == "pip-exact-constraints":
            for number, line in enumerate(data.decode().splitlines(), 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+!-]+)", line)
                if not match:
                    raise ValueError(f"not an exact constraint: {path}:{number}")
                add("pypi", *match.groups(), {"constraint_only": True}, path, f"line:{number}")
        elif kind == "platformio-host-pins":
            matches = re.findall(
                r"^ESP_NINJA_VERSION := \$\(if \$\(filter Darwin,\$\(shell uname -s\)\),(\d+\.\d+\.\d+),(\d+\.\d+\.\d+)\)$",
                data.decode(), re.MULTILINE,
            )
            if len(matches) != 1:
                raise ValueError("missing or ambiguous exact ESP_NINJA_VERSION pair in Makefile")
            ninja_versions = (("darwin", matches[0][0]), ("linux_x86_64", matches[0][1]))
        else:
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(data.decode())
            for section in config.sections():
                for key in ("platform", "platform_packages"):
                    if key not in config[section]:
                        continue
                    for pin in config[section][key].splitlines():
                        pin = pin.strip()
                        if not pin:
                            continue
                        if pin == "platformio/tool-ninja@${sysenv.POSEIDON_NINJA_VERSION}" and path in {
                            "firmware/reference/platformio.ini", "firmware/monitor-target/platformio.ini"
                        } and key == "platform_packages":
                            if ninja_versions is None:
                                raise ValueError("missing exact ESP_NINJA_VERSION pair in Makefile")
                            for system, version in ninja_versions:
                                add("platformio", "tool-ninja", version,
                                    {"registry": "platformio", "owner": "platformio", "kind": key},
                                    path, f"{section}/{key}", {"system": system})
                            continue
                        match = re.fullmatch(r"([A-Za-z0-9_./-]+)@(\d+[A-Za-z0-9_.+-]*)", pin)
                        if not match:
                            raise ValueError(f"unpinned PlatformIO dependency: {path}/{section}/{key}")
                        qualified, version = match.groups()
                        owner, _, name = qualified.rpartition("/")
                        add("platformio", name or qualified, version, {"registry": "platformio", "owner": owner or None, "kind": key}, path, f"{section}/{key}")
    for record in components.values():
        record["occurrences"].sort(key=canonical)
    return sorted(components.values(), key=lambda r: (r["ecosystem"], r["name"], r["version"], r["bom-ref"]))


def capture_metadata(root: Path, inputs: list[dict], manifests: list[dict], components: list[dict], external: dict[str, Path] | None = None, only: str | None = None) -> dict:
    """Read declared metadata only; never import installed package code.

    External roots must be individually named by the caller, never discovered
    by walking host home or private .local trees. Snapshot paths use source IDs.
    """
    external = external or {}
    environments = []
    candidates = []

    def provenance_path(path, base, label):
        return (label + "/" + path.relative_to(base).as_posix()) if label else path.relative_to(root).as_posix()

    venvs = {root / ".venv"}
    venvs.update((root / m["path"]).parent / ".venv" for m in manifests if m["path"].endswith("pyproject.toml"))
    if only is not None:
        venvs = {env for env in venvs if env.relative_to(root).as_posix().startswith(only + "/")}
    env_specs = [(env, root, "") for env in sorted(venvs)]
    env_specs += [(env, env, "metadata-source:" + label) for label, env in sorted(external.items()) if label != "firmware-platformio"]
    for env, base, label in env_specs:
        paths = sorted(env.glob("lib/python*/site-packages/*.dist-info/METADATA")) if env.is_dir() and not env.is_symlink() else []
        environments.append({"path": label or env.relative_to(root).as_posix(), "kind": "python", "present": bool(paths), "metadata_files": len(paths)})
        for path in paths:
            if not path.resolve().is_relative_to(base.resolve()):
                continue
            raw = read_bound(path)
            headers = BytesParser().parsebytes(raw, headersonly=True)
            name, version = headers.get("Name"), headers.get("Version")
            if not name or not version:
                continue
            declarations = []
            for field in ("License-Expression", "License"):
                for value in headers.get_all(field, []):
                    if value.strip() and value.strip() not in {"UNKNOWN", "NOASSERTION"}:
                        declarations.append({"field": field, "value": value.strip()})
            for value in headers.get_all("Classifier", []):
                if value.startswith("License ::"):
                    declarations.append({"field": "Classifier", "value": value})
            candidates.append({"ecosystem": "pypi", "name": normalize(name, "pypi"), "version": version, "path": provenance_path(path, base, label), "sha256": digest(raw), "declarations": declarations})
    if "firmware-platformio" in external:
        base = external["firmware-platformio"]
        paths = sorted(base.glob("platforms/*/platform.json")) + sorted(base.glob("packages/*/package.json"))
        count = 0
        for path in paths:
            if not path.resolve().is_relative_to(base.resolve()):
                continue
            raw = read_bound(path)
            obj = json.loads(raw)
            if not isinstance(obj.get("name"), str) or not isinstance(obj.get("version"), str):
                continue
            candidates.append({"ecosystem": "platformio", "name": obj["name"], "version": obj["version"], "path": provenance_path(path, base, "metadata-source:firmware-platformio"), "sha256": digest(raw), "declarations": [{"field": f, "value": obj[f]} for f in ("license", "licenses") if obj.get(f)]})
            count += 1
        environments.append({"path": "metadata-source:firmware-platformio", "kind": "platformio", "present": bool(count), "metadata_files": count})
    for inp in inputs:
        if inp["kind"] != "bun":
            continue
        if only is not None and not inp["path"].startswith(only + "/"):
            continue
        env = (root / inp["path"]).parent / "node_modules"
        found = []
        # Include nested versions, not just the top-level install. No code runs.
        for path in walk_node_metadata(env):
            if not path.resolve().is_relative_to(root.resolve()):
                continue
            raw = read_bound(path)
            obj = json.loads(raw)
            if not isinstance(obj.get("name"), str) or not isinstance(obj.get("version"), str):
                continue
            declarations = [{"field": field, "value": obj[field]} for field in ("license", "licenses") if obj.get(field)]
            found.append({"ecosystem": "npm", "name": obj["name"], "version": obj["version"], "path": path.relative_to(root).as_posix(), "sha256": digest(raw), "declarations": declarations})
        candidates.extend(found)
        environments.append({"path": env.relative_to(root).as_posix(), "kind": "npm", "present": bool(found), "metadata_files": len(found)})
    records = []
    for component in components:
        sources = sorted((m for m in candidates if (m["ecosystem"], m["name"], m["version"]) == (component["ecosystem"], component["name"], component["version"])), key=lambda m: m["path"])
        records.append({"bom-ref": component["bom-ref"], "status": "declared" if any(m["declarations"] for m in sources) else ("absent-declaration" if sources else "unresolved-no-matching-installed-metadata"), "metadata": sources})
    return {"format": "poseidon.license-metadata.v1", "lock_inputs": inputs, "manifests": manifests, "environments": sorted(environments, key=lambda e: e["path"]), "components": records, "matching_rule": "Exact ecosystem, normalized name, literal locked version; installed declaration is not license verification or proof of artifact origin."}


def refresh_selected(root: Path, output: Path, inputs: list[dict], manifests: list[dict], components: list[dict], only: str) -> dict:
    """Replace one installed environment's observations without rereading retired sources."""
    prefix = only + "/"
    previous = json.loads(read_bound(output / "metadata-snapshot.json"))
    inventory = json.loads(read_bound(output / "license-inventory.json"))
    if (previous.get("format") != "poseidon.license-metadata.v1"
            or inventory.get("metadata_snapshot_sha256") != digest(encoded(previous))
            or inventory.get("lock_inputs") != previous.get("lock_inputs")
            or {r["bom-ref"] for r in inventory["components"]} != {r["bom-ref"] for r in previous["components"]}):
        raise ValueError("existing inventory and metadata snapshot disagree")
    for field, current in (("lock_inputs", inputs), ("manifests", manifests)):
        old_other = [item for item in previous[field] if not item["path"].startswith(prefix)]
        new_other = [item for item in current if not item["path"].startswith(prefix)]
        if old_other != new_other:
            raise ValueError(f"inputs outside {only} changed; full metadata refresh required")
    if not any(item["path"].startswith(prefix) for item in inputs):
        raise ValueError(f"no lock inputs under {only}")
    prior = {record["bom-ref"]: record for record in previous["components"]}
    old_components = {record["bom-ref"]: record for record in inventory["components"]}
    current = {record["bom-ref"]: record for record in components}
    for ref in old_components.keys() - current.keys():
        if any(not occurrence["path"].startswith(prefix) for occurrence in old_components[ref]["occurrences"]):
            raise ValueError(f"component outside {only} disappeared")
    for ref in current.keys() - old_components.keys():
        if any(not occurrence["path"].startswith(prefix) for occurrence in current[ref]["occurrences"]):
            raise ValueError(f"component outside {only} appeared")
    captured = capture_metadata(root, inputs, manifests, components, only=only)
    if not captured["environments"] or any(not env["present"] for env in captured["environments"]):
        raise ValueError(f"installed metadata under {only} is unavailable")
    selected = {record["bom-ref"]: record for record in captured["components"]}
    records = []
    for component in components:
        ref = component["bom-ref"]
        kept = [meta for meta in prior.get(ref, {}).get("metadata", []) if not meta["path"].startswith(prefix)]
        metadata = sorted(kept + selected[ref]["metadata"], key=lambda meta: meta["path"])
        status = "declared" if any(meta["declarations"] for meta in metadata) else ("absent-declaration" if metadata else "unresolved-no-matching-installed-metadata")
        records.append({"bom-ref": ref, "status": status, "metadata": metadata})
    return {**previous, "lock_inputs": inputs, "manifests": manifests,
            "environments": sorted([env for env in previous["environments"] if not env["path"].startswith(prefix)] + captured["environments"], key=lambda env: env["path"]),
            "components": records}

def refresh_root_manifest(output: Path, inputs: list[dict], manifests: list[dict], components: list[dict]) -> dict:
    """Rebind only root workspace metadata; installed declarations remain frozen."""
    previous = json.loads(read_bound(output / "metadata-snapshot.json"))
    inventory = json.loads(read_bound(output / "license-inventory.json"))
    if (previous.get("format") != "poseidon.license-metadata.v1"
            or inventory.get("metadata_snapshot_sha256") != digest(encoded(previous))
            or previous.get("lock_inputs") != inputs
            or inventory.get("lock_inputs") != inputs
            or {r["bom-ref"] for r in previous["components"]} != {r["bom-ref"] for r in components}
            or {r["bom-ref"] for r in inventory["components"]} != {r["bom-ref"] for r in components}):
        raise ValueError("existing inventory, inputs and metadata snapshot disagree")
    old = {item["path"]: item for item in previous["manifests"]}
    new = {item["path"]: item for item in manifests}
    if ("pyproject.toml" not in old or "pyproject.toml" not in new
            or old.keys() != new.keys()
            or any(old[path] != new[path] for path in old if path != "pyproject.toml")):
        raise ValueError("manifests outside pyproject.toml changed")
    return {**previous, "manifests": manifests}



def walk_node_metadata(env: Path):
    if not env.is_dir() or env.is_symlink():
        return
    for directory, dirs, files in os.walk(env, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in {".cache", ".bin", ".git"} and not (Path(directory) / d).is_symlink())
        path = Path(directory)
        # Only actual package roots under node_modules, not example/package.json.
        if "package.json" in files and (path.parent.name == "node_modules" or (path.parent.name.startswith("@") and path.parent.parent.name == "node_modules")):
            yield path / "package.json"


def validate_bom(bom: dict, schema_dir: Path) -> None:
    """Validate the emitted profile against pinned official draft-07 schemas.

    This small offline evaluator supports only keywords reached by this profile;
    an unsupported validation keyword fails closed. It is not advertised as a
    general JSON Schema validator. Draft-07 format remains an annotation.
    """
    if not isinstance(bom, dict) or bom.get("bomFormat") != "CycloneDX" or bom.get("specVersion") != "1.5":
        raise ValueError("expected CycloneDX 1.5 object")
    schemas = {}
    for name, expected in SCHEMA_HASHES.items():
        raw = read_bound(schema_dir / name)
        if digest(raw) != expected:
            raise ValueError(f"official schema hash mismatch: {name}")
        schemas[name] = json.loads(raw)
    annotations = {"title", "description", "$comment", "examples", "default", "deprecated", "readOnly", "writeOnly", "format", "$schema", "$id", "definitions", "$defs"}
    implemented = {"$ref", "type", "required", "properties", "additionalProperties", "items", "additionalItems", "enum", "const", "minLength", "maxLength", "pattern", "minimum", "maximum", "minItems", "maxItems", "uniqueItems", "oneOf", "anyOf", "allOf", "not"}

    def valid(value, schema, document, location):
        if isinstance(schema, bool):
            if not schema:
                raise ValueError(f"schema refusal at {location}")
            return
        if "$ref" in schema:
            filename, _, pointer = schema["$ref"].partition("#")
            doc = schemas[filename.rsplit("/", 1)[-1]] if filename else document
            target = doc
            for part in pointer.strip("/").split("/") if pointer else []:
                target = target[part.replace("~1", "/").replace("~0", "~")]
            valid(value, target, doc, location)
            return  # draft-07 ignores siblings of $ref
        unknown = set(schema) - annotations - implemented
        if unknown:
            raise ValueError(f"unsupported schema keyword {sorted(unknown)} at {location}")
        types = {"object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str), "integer": isinstance(value, int) and not isinstance(value, bool), "number": isinstance(value, (int, float)) and not isinstance(value, bool), "boolean": isinstance(value, bool), "null": value is None}
        if "type" in schema and not any(types[t] for t in ([schema["type"]] if isinstance(schema["type"], str) else schema["type"])):
            raise ValueError(f"schema type mismatch at {location}")
        if "const" in schema and value != schema["const"] or "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"schema value mismatch at {location}")
        if isinstance(value, dict):
            if set(schema.get("required", [])) - set(value):
                raise ValueError(f"schema missing required field at {location}")
            properties = schema.get("properties", {})
            for key, child in value.items():
                valid(child, properties.get(key, schema.get("additionalProperties", True)), document, location + "/" + key)
        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", sys.maxsize):
                raise ValueError(f"schema item bound at {location}")
            if schema.get("uniqueItems") and len({canonical(v) for v in value}) != len(value):
                raise ValueError(f"schema nonunique items at {location}")
            items = schema.get("items", True)
            for index, child in enumerate(value):
                child_schema = (items[index] if index < len(items) else schema.get("additionalItems", True)) if isinstance(items, list) else items
                valid(child, child_schema, document, location + "/*")
        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", sys.maxsize) or ("pattern" in schema and re.search(schema["pattern"], value) is None):
                raise ValueError(f"schema string constraint at {location}")
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
                raise ValueError(f"schema numeric bound at {location}")
        for branch in ("oneOf", "anyOf", "allOf", "not"):
            if branch not in schema:
                continue
            branches = [schema[branch]] if branch == "not" else schema[branch]
            successes = 0
            for candidate in branches:
                try:
                    valid(value, candidate, document, location)
                    successes += 1
                except ValueError as exc:
                    if str(exc).startswith("unsupported schema keyword"):
                        raise
            if (branch == "oneOf" and successes != 1) or (branch == "anyOf" and not successes) or (branch == "allOf" and successes != len(branches)) or (branch == "not" and successes):
                raise ValueError(f"schema {branch} mismatch at {location}")

    schema = schemas["bom-1.5.schema.json"]
    valid(bom, schema, schema, "bom")
    refs = [component["bom-ref"] for component in bom["components"]]
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate component bom-ref")


def generate(root: Path, snapshot: dict) -> tuple[dict, dict]:
    inputs, manifests = discover(root)
    components = locked_components(root, inputs)
    if snapshot.get("format") != "poseidon.license-metadata.v1" or snapshot.get("lock_inputs") != inputs or snapshot.get("manifests") != manifests:
        raise ValueError("metadata snapshot is stale; review changed inputs and run --refresh-metadata")
    metadata = {r["bom-ref"]: r for r in snapshot["components"]}
    if len(metadata) != len(snapshot["components"]) or set(metadata) != {c["bom-ref"] for c in components}:
        raise ValueError("metadata snapshot component identities differ from locks")
    bom_components, licenses = [], []
    for component in components:
        meta = metadata[component["bom-ref"]]
        declarations = []
        for provenance in meta["metadata"]:
            if (provenance["ecosystem"], provenance["name"], provenance["version"]) != (component["ecosystem"], component["name"], component["version"]):
                raise ValueError("metadata name/version mismatch")
            declarations.extend(provenance["declarations"])
        expected_status = "declared" if declarations else ("absent-declaration" if meta["metadata"] else "unresolved-no-matching-installed-metadata")
        if meta["status"] != expected_status:
            raise ValueError("metadata status mismatch")
        names = sorted({d["value"] if isinstance(d["value"], str) else canonical(d["value"]) for d in declarations})
        out = {"type": "library", "bom-ref": component["bom-ref"], "name": component["name"], "version": component["version"], "properties": [
            {"name": "poseidon:ecosystem", "value": component["ecosystem"]},
            {"name": "poseidon:locked-source", "value": canonical(component["source"])},
            {"name": "poseidon:lock-occurrences", "value": canonical([{k: o[k] for k in ("path", "locator")} for o in component["occurrences"]])},
            {"name": "poseidon:license-status", "value": expected_status},
            {"name": "poseidon:license-metadata-provenance", "value": canonical([{k: m[k] for k in ("path", "sha256")} for m in meta["metadata"]])},
        ]}
        if component["ecosystem"] in {"npm", "pypi"}:
            out["purl"] = "pkg:" + component["ecosystem"] + "/" + quote(component["name"], safe="/") + "@" + quote(component["version"], safe="")
        if names:
            # Verbatim declarations, including classifiers. No guessed SPDX IDs.
            out["licenses"] = [{"license": {"name": name}} for name in names]
        bom_components.append(out)
        licenses.append({**component, **meta})
    directories = []
    for top in ("apps", "firmware"):
        if not (root / top).is_dir():
            continue
        for directory in sorted((root / top).iterdir()):
            if directory.is_dir() and not directory.is_symlink() and directory.name not in SKIP_DIRS:
                relative = directory.relative_to(root).as_posix()
                owned_inputs = [i["path"] for i in inputs if i["path"].startswith(relative + "/")]
                directories.append({"path": relative, "inventory_inputs": owned_inputs, "status": "has-inputs-see-kind-and-gaps" if owned_inputs else "no-own-dependency-lock-or-pin-manifest-found"})
    coverage = {
        "software_directories": directories,
        "basis": "Current working-tree lock files and exact firmware pins, including untracked files; not a claim of committed or shipped dependencies.",
        "dependency_graph": "Not resolved. Raw lock dependency/marker/artifact records are retained in license-inventory.json; SBOM intentionally omits dependencies rather than inventing version edges.",
        "environments": snapshot["environments"],
        "manifests": manifests,
        "gaps": ["Missing adjacent locks remain listed per manifest; stdlib-only status is not inferred.", "PlatformIO manifests contain exact direct tool/platform pins, not a complete transitive firmware lock.", "OS packages, bundled native libraries, toolchain subcomponents and release artifacts are not enumerated by these locks.", "Metadata is an installed declaration matched by name/version, not a license audit or proof that an installed artifact matches a locked archive.", "Absent/non-host optional packages retain unresolved licenses; no packages were installed to fill gaps."],
    }
    inventory = {"format": "poseidon.license-inventory.v1", "lock_inputs": inputs, "metadata_snapshot_sha256": digest(encoded(snapshot)), "coverage": coverage, "components": licenses, "counts": {"components": len(components), "lock_inputs": len(inputs), "lock_occurrences": sum(len(c["occurrences"]) for c in components), **{status: sum(m["status"] == status for m in metadata.values()) for status in ("declared", "absent-declaration", "unresolved-no-matching-installed-metadata")}}}
    bom = {"$schema": "http://cyclonedx.org/schema/bom-1.5.schema.json", "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "metadata": {"properties": [
        {"name": "poseidon:inventory-kind", "value": "lock-derived source/build inventory; not a released artifact SBOM"},
        {"name": "poseidon:lock-inputs", "value": canonical(inputs)},
        {"name": "poseidon:metadata-snapshot-sha256", "value": digest(encoded(snapshot))},
        {"name": "poseidon:coverage", "value": canonical(coverage)},
    ]}, "components": bom_components}
    return bom, inventory


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Offline byte check of locks, frozen metadata and outputs")
    mode.add_argument("--refresh-metadata", action="store_true", help="Replace reviewed metadata snapshot from currently installed local environments, then regenerate")
    parser.add_argument("--check-local-metadata", action="store_true", help="Also require every captured metadata file still present with the same hash")
    parser.add_argument("--only", metavar="APP_DIR|pyproject.toml", help="With --refresh-metadata, replace metadata under one direct apps/ directory or rebind only the root pyproject.toml manifest")
    parser.add_argument("--metadata-source", action="append", default=[], metavar="ID=PATH", help="Explicit read-only firmware Python env, or firmware-platformio core; no host discovery")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.only and (not args.refresh_metadata or args.check_local_metadata or args.metadata_source):
        parser.error("--only requires --refresh-metadata without --check-local-metadata or --metadata-source")
    if args.only and args.only != "pyproject.toml" and (Path(args.only).is_absolute() or Path(args.only).as_posix() != args.only or not re.fullmatch(r"apps/[A-Za-z0-9_-]+", args.only)):
        parser.error("--only must name a direct apps/ directory or pyproject.toml")
    output = root / OUTPUT
    try:
        external = {}
        for item in args.metadata_source:
            label, sep, path = item.partition("=")
            if not sep or label not in {"firmware-toolchain", "firmware-update", "firmware-idf", "firmware-platformio"} or label in external:
                raise ValueError("invalid/duplicate metadata source ID")
            external[label] = Path(path).resolve()
            if not external[label].is_dir():
                raise ValueError(f"metadata source not present: {label}")
        inputs, manifests = discover(root)
        if args.refresh_metadata:
            components = locked_components(root, inputs)
            snapshot = (refresh_root_manifest(output, inputs, manifests, components) if args.only == "pyproject.toml"
                        else refresh_selected(root, output, inputs, manifests, components, args.only) if args.only
                        else capture_metadata(root, inputs, manifests, components, external))
        else:
            snapshot = json.loads(read_bound(output / "metadata-snapshot.json"))
        if args.check_local_metadata:
            for record in snapshot["components"]:
                for meta in record["metadata"]:
                    if meta["path"].startswith("metadata-source:"):
                        label, _, relative = meta["path"].removeprefix("metadata-source:").partition("/")
                        if label not in external:
                            raise ValueError(f"--check-local-metadata needs --metadata-source for {label}")
                        base = external[label]
                        path = base / relative
                    else:
                        base = root
                        path = root / meta["path"]
                    if not path.resolve().is_relative_to(base) or digest(read_bound(path)) != meta["sha256"]:
                        raise ValueError("captured local metadata changed or is outside source root")
        bom, inventory = generate(root, snapshot)
        validate_bom(bom, output / "schema")
        results = {"sbom.cdx.json": encoded(bom), "license-inventory.json": encoded(inventory), "metadata-snapshot.json": encoded(snapshot)}
        if args.check:
            stale = [name for name, raw in results.items() if read_bound(output / name) != raw]
            if stale:
                raise ValueError("stale generated output: " + ", ".join(stale))
        else:
            for name, raw in results.items():
                (output / name).write_bytes(raw)
        print(json.dumps({"ok": True, "mode": "check" if args.check else "generate", "counts": inventory["counts"], "sha256": {name: digest(raw) for name, raw in results.items()}}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, configparser.Error) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
