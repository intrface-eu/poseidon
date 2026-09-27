"""Translate parent-frozen tranche3 inputs into the exact artifacts validate_go accepts.

Host-only, stdlib-only and deterministic: the same inputs and the same working
tree always produce byte-identical artifacts. Nothing here starts a VM, opens a
socket, installs a package or writes a go record by default; `generate` only
reads the working tree and writes JSON into one new directory, and the separate
`go` subcommand needs an explicit parent expiry.

Every file a lane handoff declares must still hash exactly as that handoff says.
A drifted declaration stops generation unless the parent names the exact path as
an accepted rehearsal mismatch, and every accepted mismatch is recorded with
both digests in the artifact index.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from scripts.assurance.linux_capture_env import guest_prepare as debian
from scripts.assurance.linux_python_env import guest_checks, locked_checks, locked_env, provision, runner as lifecycle, source

SCHEMA = "poseidon.assurance-tranche3-freeze-index.v1"
PYTHON_VERSION = "3.13.5"
# The reviewed transferable closure: every directory a Stage1/Stage2 command
# reads, imports, compiles or hashes. Not a discovery of the host home; docs and
# other roots enter only as the exact files a lane handoff declares.
# "docs" is a full root: tests/assurance/test_dossier.py and test_evidence.py read
# manufacturing, qualification, requirements and roadmap documents (run lp3-stage1-004).
CLOSURE_ROOTS = (".github", ".taskmaster/tasks/production-v1", ".taskmaster/tasks/tasks.json", "apps", "contracts", "docs", "firmware", "hardware", "libs", "ops", "research", "scripts", "tests")
# HARDWARE.md is a frozen hardware baseline input (candidate CAD/power/preservation
# checks compare its hash; missing in run lp3-stage1-005 rehearsal).
CLOSURE_ROOT_FILES = ("DESIGN.md", "HARDWARE.md", "Makefile", "PRODUCT.md", "README.md", "SECURITY.md", "pyproject.toml")
# Root-frozen identities the parent published. Stage1 executes the Makefile in
# the guest, so a drifted root file stops generation instead of being frozen.
ROOT_FROZEN = {"Makefile": "b2fb095416d8a97130ea27f2586d01e65cf72b82fbee0de5598d6bab3cf09fc8",
               "SECURITY.md": "8eda96587ea2f3b566c270d4b6583fcd6a6838fe552ee17c87467b0fe264a273"}
FIRMWARE_INPUTS = ("firmware/monitor-target/platformio.ini", "firmware/reference/platformio.ini",
                   "firmware/toolchain/idf-python-constraints.txt", "firmware/toolchain/pyproject.toml",
                   "firmware/toolchain/uv.lock", "firmware/update/pyproject.toml", "firmware/update/uv.lock")
STAGE2_PYTHON_RE = re.compile(r"\{workspace\}/envs/([a-z]+)/bin/python\Z")
ARTIFACTS = ("firmware-inputs.json", "source-manifest.json", "handoffs.json", "stage1-packages.json",
             "stage2-tools.json", "stage1-checkset.json", "stage2-checkset.json", "index.json")


class FreezeError(ValueError):
    pass


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False).encode() + b"\n"


def load_json(path: Path, expected: str | None = None) -> dict:
    if not path.is_file() or path.is_symlink():
        raise FreezeError(f"input is not a regular file: {path}")
    if expected is not None and source.sha256(path) != expected:
        raise FreezeError(f"input differs from the parent-frozen digest: {path}")
    return source.strict_json(path.read_bytes())


def write_new(path: Path, value) -> dict:
    raw = canonical(value)
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": source.sha256(path)}


def scan_closure(root: Path, *, roots=CLOSURE_ROOTS, root_files=CLOSURE_ROOT_FILES, extra: tuple[str, ...] = ()) -> tuple[dict, list[dict]]:
    """Hash every transferable regular file under the reviewed roots, in order."""
    files: dict[str, dict] = {}
    skipped: list[dict] = []

    def add(name: str) -> None:
        path = root / name
        if path.is_symlink() or not path.is_file():
            skipped.append({"path": name, "reason": "not a regular file"})
            return
        try:
            source.safe_name(name)
        except source.SourceError as exc:
            skipped.append({"path": name, "reason": str(exc)})
            return
        files[name] = {"sha256": source.sha256(path), "size": path.stat().st_size}

    for entry in sorted(roots):
        base = root / entry
        if base.is_symlink() or not base.exists():
            raise FreezeError(f"missing reviewed closure root: {entry}")
        if base.is_file():
            add(entry)
            continue
        for directory, directories, names in os.walk(base):
            directories[:] = sorted(d for d in directories if d not in source.FORBIDDEN and not d.startswith(".env.")
                                    and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                add((Path(directory) / name).relative_to(root).as_posix())
    for name in sorted(set(root_files) | set(extra)):
        if (root / name).exists():
            add(name)
        elif name in extra:
            raise FreezeError(f"declared source is missing from the working tree: {name}")
    if not files:
        raise FreezeError("the reviewed closure is empty")
    return files, skipped


def check_root_files(files: dict, expected: dict) -> None:
    """Refuse a root-frozen file that is absent or no longer the frozen bytes."""
    wrong = [{"path": name, "declared_sha256": digest, "working_tree_sha256": files.get(name, {}).get("sha256")}
             for name, digest in sorted(expected.items()) if files.get(name, {}).get("sha256") != digest]
    if wrong:
        raise FreezeError(f"root-frozen files do not match the parent identities: {json.dumps(wrong, sort_keys=True)}")


def coverage_roots(files: dict) -> list[str]:
    """Directory roots plus any declared file that sits outside all of them."""
    roots = [name for name in CLOSURE_ROOTS]
    covered = {name for name in files if any(name.startswith(root + "/") for root in roots)}
    return sorted(set(roots) | (set(files) - covered))


def declared_lanes(inputs: dict, generated: dict) -> dict:
    """Normalize each published freeze into lane -> declared path digests."""
    platform = load_json(inputs["platform"])
    acquisition = load_json(inputs["acquisition"])
    native = load_json(inputs["native"])
    helpers = load_json(inputs["helpers"])
    lanes = {
        "platform": (inputs["platform"], {row["path"]: row["sha256"] for row in platform["sourceFiles"]}),
        "acquisition": (inputs["acquisition"], dict(acquisition["changedPathSha256"]) | dict(acquisition["selectedSourceAndTestSha256"])),
        "acquisition-native": (inputs["native"], dict(native["files"])),
        "assurance": (inputs["helpers"], {name: row["sha256"] for name, row in helpers["files"].items()}),
        "firmware": (generated["firmware"], dict(generated["firmware_files"])),
    }
    result = {}
    for lane, (path, digests) in lanes.items():
        if not digests:
            raise FreezeError(f"lane freeze declares no files: {lane}")
        for name, digest in digests.items():
            source.safe_name(name)
            if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise FreezeError(f"invalid declared digest in {lane}: {name}")
        result[lane] = {"manifest": str(path), "manifest_sha256": source.sha256(path), "files": dict(sorted(digests.items()))}
    return result


def reconcile(lanes: dict, files: dict, accepted: tuple[str, ...]) -> list[dict]:
    """Refuse any handoff whose declared file is missing or has changed."""
    accepted = set(accepted)
    mismatches, unresolved, unknown = [], [], []
    for lane, entry in sorted(lanes.items()):
        for name, digest in entry["files"].items():
            actual = files.get(name, {}).get("sha256")
            if actual == digest:
                continue
            row = {"lane": lane, "path": name, "declared_sha256": digest, "working_tree_sha256": actual}
            if actual is None:
                unresolved.append(row)
            elif name in accepted:
                mismatches.append(row)
                entry["files"][name] = actual
            else:
                unresolved.append(row)
    if unresolved:
        raise FreezeError(f"handoff inputs do not match the working tree: {json.dumps(unresolved[:8], sort_keys=True)}")
    for name in sorted(accepted):
        if not any(row["path"] == name for row in mismatches):
            unknown.append(name)
    if unknown:
        raise FreezeError(f"accepted rehearsal mismatch did not occur: {unknown}")
    return mismatches


def expand_coverage(entries: list[str], files: dict, *, python_only: bool = False, drop: bool = False) -> tuple[list[str], list[str]]:
    """Turn reviewed coverage paths into the exact frozen files they name."""
    selected, dropped = set(), set()
    for entry in entries:
        source.safe_name(entry)
        if entry in files:
            names = {entry}
        else:
            names = {name for name in files if name.startswith(entry + "/")}
            if python_only:
                names = {name for name in names if name.endswith(".py")}
        if not names:
            raise FreezeError(f"coverage path names no frozen file: {entry}")
        if drop:
            # Locked lanes are Stage2-only, and the labelled HIL guard command is
            # the single command that may claim the HIL file as its coverage.
            locked = {name for name in names if guest_checks.stage2_only(name) or name == guest_checks.HIL_COVERAGE}
            dropped |= locked
            names -= locked
        selected |= names
    if not selected:
        raise FreezeError(f"coverage names only locked-lane files: {sorted(entries)[:4]}")
    return sorted(selected), sorted(dropped)


def stage1_checkset(proposal: dict, files: dict, plan: dict, manifest_sha256: str) -> tuple[dict, list[str]]:
    """Executable Stage1 translation: no proposal fields, exactly one HIL label."""
    stage1 = proposal["stage1"]
    if stage1["interpreter"]["version"] != PYTHON_VERSION:
        raise FreezeError("the proposal does not pin the approved snapshot interpreter")
    if stage1["hil_label"] != guest_checks.HIL_LABEL:
        raise FreezeError("the proposal HIL label differs from the accepted evidence label")
    notes, commands, hil = [], [], []
    for command in stage1["commands"]:
        if command.get("expected_exit", 0) != 0:
            raise FreezeError(f"only a zero-exit check is executable: {command['id']}")
        argv = list(command["argv"])
        compileall = argv[:4] == ["/usr/bin/python3", "-m", "compileall", "-q"]
        if guest_checks.HIL_COVERAGE in command["coverage"]:
            hil.append(command)
            continue
        coverage, dropped = expand_coverage(command["coverage"], files, python_only=compileall, drop=True)
        if dropped:
            notes.append(f"{command['id']}: dropped locked-lane coverage {sorted(dropped)[:4]} (Stage2-only paths cannot be Stage1 coverage)")
        commands.append({"id": command["id"], "argv": argv, "timeout_seconds": command["timeout_seconds"],
                         "environment": dict(command.get("environment", {})), "coverage": coverage})
    if not hil:
        raise FreezeError("the proposal has no HIL guard command to label")
    merged = merge_hil(hil)
    notes.append("merged " + ", ".join(sorted(command["id"] for command in hil)) + f" into one labelled HIL command with --minimum {merged['argv'][8]}")
    position = len([command for command in stage1["commands"][:stage1["commands"].index(hil[0])] if guest_checks.HIL_COVERAGE not in command["coverage"]])
    commands.insert(position, merged)
    checkset = {"schema_version": "poseidon.linux-python-checkset.v1", "python_version": PYTHON_VERSION,
                "source_manifest_sha256": manifest_sha256, "package_pins": dict(plan["roots"]),
                "omissions": [dict(entry) for entry in stage1["omissions"]], "commands": commands}
    return guest_checks.validate_checkset(checkset), notes


def merge_hil(commands: list[dict]) -> dict:
    """One command, one label: the union of the reviewed HIL class selectors."""
    minimum, timeout = 0, 0
    root = pattern = None
    for command in commands:
        argv = command["argv"]
        if argv[:3] != ["/usr/bin/python3", "-m", "scripts.assurance.linux_python_env.suite"] or argv[3] != "--root" or argv[5] != "--pattern" or argv[7] != "--minimum":
            raise FreezeError(f"unexpected HIL guard command form: {command['id']}")
        if root not in (None, argv[4]) or pattern not in (None, argv[6]):
            raise FreezeError("HIL guard commands disagree about the selected module")
        root, pattern = argv[4], argv[6]
        minimum += int(argv[8])
        timeout = max(timeout, command["timeout_seconds"])
    return {"id": "tests-assurance-test_hil_gate", "timeout_seconds": timeout, "environment": {},
            "argv": ["/usr/bin/python3", "-m", "scripts.assurance.linux_python_env.suite",
                     "--root", root, "--pattern", pattern, "--minimum", str(minimum)],
            "coverage": [guest_checks.HIL_COVERAGE], "evidence_label": guest_checks.HIL_LABEL}


def stage2_argv(command: dict) -> list[str]:
    """Rewrite the proposal's lane interpreter paths into {python} placeholders."""
    argv = list(command["argv"])
    if argv[0] == "make":
        argv[0] = "/usr/bin/make"
    for index, value in enumerate(argv):
        prefix, _, tail = value.partition("=")
        match = STAGE2_PYTHON_RE.fullmatch(tail if prefix == "PYTHON" else value)
        if match is None:
            continue
        if match[1] != command["lane"]:
            raise FreezeError(f"command interpreter is not its own lane: {command['id']}")
        argv[index] = "PYTHON={python}" if prefix == "PYTHON" else "{python}"
    if any("{workspace}" in value for value in argv):
        raise FreezeError(f"unresolved workspace placeholder: {command['id']}")
    return argv


def stage2_checkset(proposal: dict, files: dict, manifest_sha256: str, tool_plan_sha256: str) -> tuple[dict, list[str]]:
    stage2 = proposal["stage2"]
    notes, commands = [], []
    for command in stage2["commands"]:
        coverage, _ = expand_coverage(command["coverage"], files)
        commands.append({"id": command["id"], "lane": command["lane"], "argv": stage2_argv(command),
                         "timeout_seconds": command["timeout_seconds"],
                         "environment": dict(command.get("environment", {})), "coverage": coverage})
    labels = {command.get("evidence_label") for command in stage2["commands"]} - {None}
    omissions = [{"paths": [entry], "reason": "explicitly out of scope for the locked Python check set"} for entry in stage2["explicit_exclusions"]]
    omissions.append({"paths": ["scope"], "reason": stage2["label_limits"]})
    for label in sorted(labels):
        omissions.append({"paths": ["scope"], "reason": label})
        notes.append("Stage2 schema has no evidence_label field; the proposal label was preserved as a scope omission")
    checkset = {"schema_version": "poseidon.linux-python-locked-checkset.v1", "source_manifest_sha256": manifest_sha256,
                "tool_plan_sha256": tool_plan_sha256, "omissions": omissions, "commands": commands}
    return locked_checks.validate_checkset(checkset), notes


def package_plan(proposal: dict, availability: dict) -> dict:
    """Exact snapshot pins, each proven by the retained availability metadata."""
    stage1 = proposal["stage1"]
    if availability["snapshot"] != debian.SNAPSHOT or availability.get("network_used") is not False:
        raise FreezeError("package availability proof is not the accepted offline snapshot record")
    roots = {}
    for name, version in stage1["apt_root_pins"].items():
        proven = [row["Version"] for row in availability["packages"].get(name, [])]
        if version not in proven:
            raise FreezeError(f"pinned root is not in the retained availability proof: {name}={version}")
        roots[name] = version
    indexes = {}
    for row in availability["indexes"]:
        if row.get("accepted_manifest_match") is False:
            raise FreezeError("snapshot index does not match the accepted Task18 manifest")
        indexes[Path(row["path"]).name] = row["sha256"]
    plan = {"schema_version": "poseidon.linux-python-packages.v1", "snapshot": debian.SNAPSHOT,
            "roots": dict(sorted(roots.items())), "indexes": dict(sorted(indexes.items()))}
    return provision.validate_plan(plan)


def tool_plan(root: Path, official: dict, files: dict) -> tuple[dict, list[str]]:
    """Official uv/CPython digests from the frozen pins; locks from frozen source."""
    plan = {"schema_version": "poseidon.linux-python-locked-tools.v1", "uv": dict(official["uv"]),
            "python": {version: dict(pin) for version, pin in official["python"].items()}, "locks": {}}
    notes = []
    for lane, (project, version) in sorted(locked_env.LANES.items()):
        entry = {"project": project, "python": version}
        for name, field in (("uv.lock", "lock_sha256"), ("pyproject.toml", "pyproject_sha256")):
            frozen = files.get(f"{project}/{name}")
            if frozen is None:
                raise FreezeError(f"lane dependency file is outside the frozen closure: {project}/{name}")
            if source.sha256(root / project / name) != frozen["sha256"]:
                raise FreezeError(f"lane dependency file changed while freezing: {project}/{name}")
            entry[field] = frozen["sha256"]
            declared = official["locks"].get(lane, {}).get(field)
            if declared != entry[field]:
                notes.append(f"{lane} {name} differs from the published tool plan: frozen={entry[field]} published={declared}")
        plan["locks"][lane] = entry
    return locked_env.validate_plan(plan), notes


def executed_commands(stage1: dict, stage2: dict) -> str:
    return hashlib.sha256(canonical([command["argv"] for command in stage1["commands"]] + [command["argv"] for command in stage2["commands"]])).hexdigest()


def generate(args) -> dict:
    root = args.root.resolve()
    inputs = {name: getattr(args, name).resolve() for name in ("platform", "acquisition", "native", "helpers", "proposal", "tools", "availability")}
    if args.accepted and args.label != "rehearsal":
        raise FreezeError("accepted input mismatches are only allowed in a labelled rehearsal generation")
    proposal = load_json(inputs["proposal"], args.proposal_sha256)
    official = load_json(inputs["tools"], args.tools_sha256)
    availability = load_json(inputs["availability"], args.availability_sha256)
    if args.output.is_symlink() or args.output.exists() or not args.output.parent.is_dir():
        raise FreezeError("artifacts need a new directory inside an existing parent")
    # Resolve the existing parent once, then keep the new leaf literal: a
    # symlinked artifacts directory is refused, a symlinked /tmp is not.
    args.output = args.output.parent.resolve() / args.output.name
    args.output.mkdir(mode=0o700)

    declared_extra = set()
    for name in ("platform", "acquisition", "native", "helpers"):
        declared_extra |= set(lane_paths(load_json(inputs[name])))
    files, skipped = scan_closure(root, extra=tuple(sorted(name for name in declared_extra if not any(name.startswith(entry + "/") for entry in CLOSURE_ROOTS))))
    for name in FIRMWARE_INPUTS:
        if name not in files:
            raise FreezeError(f"firmware freeze input is missing: {name}")
    check_root_files(files, dict(ROOT_FROZEN) | dict(args.expect))
    written = {"firmware-inputs.json": write_new(args.output / "firmware-inputs.json",
                                                 {"schema_version": "poseidon.linux-python-firmware-inputs.v1",
                                                  "files": {name: files[name] for name in FIRMWARE_INPUTS},
                                                  "note": "Firmware toolchain/update/target inputs frozen from the working tree; no external lane declared them."})}
    lanes = declared_lanes(inputs, {"firmware": args.output / "firmware-inputs.json",
                                    "firmware_files": {name: files[name]["sha256"] for name in FIRMWARE_INPUTS}})
    mismatches = reconcile(lanes, files, tuple(args.accepted))

    manifest = {"schema_version": "poseidon.linux-python-sources.v1", "files": dict(sorted(files.items())),
                "required_files": sorted(files), "coverage_roots": coverage_roots(files)}
    source.validate_manifest(manifest)
    written["source-manifest.json"] = write_new(args.output / "source-manifest.json", manifest)
    handoffs = {"schema_version": "poseidon.linux-python-handoffs.v1", "lanes": dict(sorted(lanes.items()))}
    written["handoffs.json"] = write_new(args.output / "handoffs.json", handoffs)
    plan = package_plan(proposal, availability)
    written["stage1-packages.json"] = write_new(args.output / "stage1-packages.json", plan)
    tools, notes = tool_plan(root, official, files)
    written["stage2-tools.json"] = write_new(args.output / "stage2-tools.json", tools)
    manifest_sha256 = written["source-manifest.json"]["sha256"]
    stage1, stage1_notes = stage1_checkset(proposal, files, plan, manifest_sha256)
    written["stage1-checkset.json"] = write_new(args.output / "stage1-checkset.json", stage1)
    stage2, stage2_notes = stage2_checkset(proposal, files, manifest_sha256, written["stage2-tools.json"]["sha256"])
    written["stage2-checkset.json"] = write_new(args.output / "stage2-checkset.json", stage2)
    notes += stage1_notes + stage2_notes

    for stage, checkset in ((1, stage1), (2, stage2)):
        required = lifecycle.required_sources(stage, checkset)
        missing = sorted(required - set(manifest["files"]))
        unenforced = sorted(required - set(manifest["required_files"]))
        if missing or unenforced:
            raise FreezeError(f"stage{stage} executable inputs are not frozen: missing={missing[:8]} unenforced={unenforced[:8]}")
    source.verify(root, manifest, exact=False)
    index = {"schema_version": SCHEMA, "label": args.label, "state": "artifacts-generated-no-go-record",
             "generated_at": datetime.now(timezone.utc).isoformat(), "root": str(root),
             "inputs": {name: {"path": str(path), "sha256": source.sha256(path)} for name, path in sorted(inputs.items())},
             "artifacts": dict(sorted(written.items())),
             "counts": {"files": len(manifest["files"]), "required_files": len(manifest["required_files"]),
                        "coverage_roots": len(manifest["coverage_roots"]), "closure_bytes": sum(item["size"] for item in manifest["files"].values()),
                        "handoff_lanes": len(lanes), "declared_files": sum(len(entry["files"]) for entry in lanes.values()),
                        "stage1_commands": len(stage1["commands"]), "stage2_commands": len(stage2["commands"]),
                        "package_roots": len(plan["roots"])},
             "root_frozen": dict(sorted((dict(ROOT_FROZEN) | dict(args.expect)).items())),
             "closure": {"roots": list(CLOSURE_ROOTS), "root_files": sorted(name for name in CLOSURE_ROOT_FILES if name in files),
                         "declared_files_outside_roots": sorted(name for name in files if name not in [*CLOSURE_ROOTS, *CLOSURE_ROOT_FILES] and not any(name.startswith(entry + "/") for entry in CLOSURE_ROOTS)),
                         "note": "Taskmaster inputs are limited to tasks.json and the production-v1 tag directory; other tags stay outside the closure."},
             "executed_command_list_sha256": executed_commands(stage1, stage2),
             "accepted_input_mismatches": mismatches, "excluded_paths": skipped,
             "translation_notes": sorted(set(notes)), "release_authorized": False,
             "physical_operations_performed": False, "vm_started": False, "network_used": False}
    written["index.json"] = write_new(args.output / "index.json", index)
    return {"label": index["label"], "state": index["state"], "artifacts": dict(sorted(written.items())),
            "counts": index["counts"], "executed_command_list_sha256": index["executed_command_list_sha256"],
            "accepted_input_mismatches": mismatches, "translation_notes": index["translation_notes"],
            "release_authorized": False}


def lane_paths(document: dict) -> list[str]:
    for field in ("sourceFiles", "changedPathSha256", "selectedSourceAndTestSha256", "files"):
        if field in document:
            value = document[field]
            names = [row["path"] for row in value] if type(value) is list else list(value)
            if field == "changedPathSha256":
                names += list(document.get("selectedSourceAndTestSha256", {}))
            return names
    raise FreezeError("lane freeze has no recognized path map")


def go(args) -> dict:
    """Written only when the parent asks, with an explicit parent expiry."""
    index = load_json(args.artifacts / "index.json")
    if index["schema_version"] != SCHEMA:
        raise FreezeError("artifacts directory has no freeze index")
    if not re.fullmatch(r"lp3-[a-zA-Z0-9-]{1,40}", args.run_id) or not args.workspace.name.startswith("linux-python-env-tranche3-"):
        raise FreezeError("a go needs a new tranche3 run identity and workspace")
    if args.expires_unix <= int(args.now):
        raise FreezeError("the parent expiry is already past")
    digests = {name: index["artifacts"][name]["sha256"] for name in ("source-manifest.json", "handoffs.json", "stage1-packages.json", "stage2-tools.json", "stage1-checkset.json", "stage2-checkset.json")}
    record = {"schema_version": "poseidon.linux-python-go.v1", "stage": args.stage, "run_id": args.run_id,
              "output": str(args.workspace), "source_manifest_sha256": digests["source-manifest.json"],
              "checkset_sha256": digests["stage1-checkset.json" if args.stage == 1 else "stage2-checkset.json"],
              "package_plan_sha256": digests["stage1-packages.json"],
              "tool_plan_sha256": None if args.stage == 1 else digests["stage2-tools.json"],
              "handoffs_sha256": digests["handoffs.json"], "expires_unix": args.expires_unix,
              "release_authorized": False, "stage1_result": None}
    if args.stage == 2:
        if args.stage1_result is None or not args.stage1_result_sha256:
            raise FreezeError("Stage2 go needs the stopped Stage1 result path and digest")
        record["stage1_result"] = {"path": str(args.stage1_result), "sha256": args.stage1_result_sha256}
    written = write_new(args.output, record)
    return {"go": written, "stage": args.stage, "run_id": args.run_id, "release_authorized": False}


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    build = actions.add_parser("generate", help="write the frozen manifest, handoffs, check sets and plans")
    build.add_argument("--root", type=Path, default=lifecycle.ROOT)
    build.add_argument("--output", type=Path, required=True)
    for name in ("platform", "acquisition", "native", "helpers", "proposal", "tools", "availability"):
        build.add_argument("--" + name, type=Path, required=True)
    for name in ("proposal", "tools", "availability"):
        build.add_argument("--" + name + "-sha256")
    build.add_argument("--label", choices=("final", "rehearsal"), default="final")
    build.add_argument("--accept-mismatch", dest="accepted", action="append", default=[],
                       help="exact path a rehearsal may take from the working tree instead of its handoff")
    build.add_argument("--expect", metavar="PATH=SHA256", action="append", default=[],
                       help="replace a root-frozen identity, e.g. Makefile=<sha256>")
    build.set_defaults(handler=generate)
    consent = actions.add_parser("go", help="write the parent go record; never written by generate")
    consent.add_argument("--artifacts", type=Path, required=True)
    consent.add_argument("--output", type=Path, required=True)
    consent.add_argument("--stage", type=int, choices=(1, 2), required=True)
    consent.add_argument("--run-id", required=True)
    consent.add_argument("--workspace", type=Path, required=True)
    consent.add_argument("--expires-unix", type=int, required=True)
    consent.add_argument("--now", type=float, default=None)
    consent.add_argument("--stage1-result", type=Path)
    consent.add_argument("--stage1-result-sha256")
    consent.set_defaults(handler=go)
    args = parser.parse_args(argv)
    if args.action == "generate":
        expect = {}
        for value in args.expect:
            name, separator, sha = value.partition("=")
            if not separator or not re.fullmatch(r"[0-9a-f]{64}", sha):
                parser.error("--expect needs PATH=<sha256>")
            expect[name] = sha
        args.expect = expect
    if args.action == "go" and args.now is None:
        args.now = time.time()
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    try:
        print(json.dumps(args.handler(args), sort_keys=True))
        return 0
    except (FreezeError, source.SourceError, ValueError, OSError) as exc:
        print(f"tranche3 freeze refused/failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
