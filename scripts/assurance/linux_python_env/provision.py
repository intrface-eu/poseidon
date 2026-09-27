"""Provision exact Debian snapshot roots in a NEW marked guest, never the host.

Accepted Task18 planning/metadata helpers are imported read-only. This wrapper
adds Python regression tools, forbids retries and records the complete resolved
Depends/Pre-Depends artifact closure. It never runs a test as root.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import signal
import subprocess

from scripts.assurance.linux_capture_env import guest_prepare as shared
from scripts.assurance.linux_python_env import source


def validate_plan(plan: dict) -> dict:
    if set(plan) != {"schema_version", "snapshot", "roots", "indexes"} or plan["schema_version"] != "poseidon.linux-python-packages.v1" or plan["snapshot"] != shared.SNAPSHOT:
        raise ValueError("exact approved Debian snapshot package plan required")
    if type(plan["roots"]) is not dict or not plan["roots"] or len(plan["roots"]) > 64:
        raise ValueError("bounded exact package roots required")
    for name, version in plan["roots"].items():
        if type(name) is not str or not shared.PACKAGE_RE.fullmatch(name) or type(version) is not str or not shared.VERSION_RE.fullmatch(version):
            raise ValueError("invalid pinned Debian root")
        if name.startswith(("linux-image", "linux-headers", "linux-modules")) or name in {"dkms", "docker.io", "podman"}:
            raise ValueError("kernel/module/container package outside Python regression scope")
    if type(plan["indexes"]) is not dict or len(plan["indexes"]) != 3:
        raise ValueError("the three accepted ARM64 snapshot Packages digests are required")
    for name, digest in plan["indexes"].items():
        if not re.fullmatch(r"snapshot\.debian\.org_archive_debian(?:-security)?_20260901T000000Z_dists_trixie(?:-updates|-security)?_main_binary-arm64_Packages", name) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid exact snapshot index identity")
    return plan


def apt_options(work: Path) -> list[str]:
    """Reuse the reviewed Task18 options with acquisition retries disabled."""
    options = ["Acquire::Retries=0" if value.startswith("Acquire::Retries=") else value for value in shared.apt_options(work)]
    if options.count("Acquire::Retries=0") != 1:
        raise ValueError("APT acquisition must carry exactly one disabled retry option")
    return options


def install_arguments(roots: dict[str, str]) -> list[str]:
    """Exact pinned install with no upgrade, removal or recommended extras."""
    if not roots:
        raise ValueError("an install needs at least one pinned root")
    return ["--yes", "--no-remove", "--no-upgrade", "--no-install-recommends", "install",
            *[f"{name}={version}" for name, version in sorted(roots.items())]]


def verified_indexes(work: Path, expected: dict) -> dict:
    actual = {p.name: source.sha256(p) for p in (work / "apt/lists").glob("*Packages")}
    if actual != expected:
        raise ValueError("downloaded Packages indexes differ from accepted frozen Task18 identities")
    for suite in ("trixie", "trixie-updates", "trixie-security"):
        if not list((work / "apt/lists").glob(f"*_dists_{suite}_InRelease")):
            raise ValueError("missing authenticated snapshot InRelease")
    return actual


def prepare(args) -> dict:
    shared.guard_guest(args.run_id, root=True)
    if source.sha256(args.plan) != args.plan_sha256:
        raise ValueError("package plan differs from parent-frozen hash")
    plan = validate_plan(source.strict_json(args.plan.read_bytes()))
    if args.output != Path("/var/lib/poseidon-python-" + args.run_id):
        raise ValueError("guest package output must be the exact new owned /var/lib path")
    shared.new_directory(args.output, root=True)
    work = args.output
    result = {"schema_version": "poseidon.linux-python-preparation.v1", "run_id": args.run_id, "plan_sha256": args.plan_sha256,
              "roots": plan["roots"], "snapshot": shared.SNAPSHOT, "tests_executed_as_root": False,
              "device_access_occurred": False, "release_authorized": False}
    try:
        run = shared.Runner(work)
        before = shared.installed_packages(run)
        result["kernel_package"] = shared.check_base(before)
        for name, version in plan["roots"].items():
            if name in before and before[name]["Version"] != version:
                raise ValueError(f"pinned root would change existing package: {name}")
        result["automation"] = shared.freeze_automation(run)
        shared.preserve_sources(work)
        for name in ("apt", "apt/conf.d", "apt/lists", "apt/archives", "package-metadata"):
            (work / name).mkdir()
        (work / "apt/sources.list").write_text(shared.snapshot_sources())
        (work / "apt/apt.conf").write_text("Dir::Etc::main " + json.dumps(str(work / "apt/apt.conf")) + ";\nDir::Etc::parts " + json.dumps(str(work / "apt/conf.d")) + ";\n")
        run.env["APT_CONFIG"] = str(work / "apt/apt.conf")
        options = apt_options(work)
        apt = ["/usr/bin/apt-get", *options]
        cache = ["/usr/bin/apt-cache", *options]
        run.run([*apt, "update"], timeout=900)
        result["index_hashes"] = verified_indexes(work, plan["indexes"])
        install = install_arguments(plan["roots"])
        selected = shared.parse_install_plan(run.run([*apt, "--simulate", *install], timeout=120), before)
        shared.write_json(work / "resolved-install-plan.json", {"roots": plan["roots"], "new_packages": selected, "basis": "exact authenticated, hash-matched snapshot indexes; upgrades/removals forbidden"})
        run.run([*apt, "--download-only", *install], timeout=1200)
        if shared.parse_install_plan(run.run([*apt, "--simulate", *install], timeout=120), before) != selected:
            raise ValueError("APT plan changed after download")
        verified_indexes(work, plan["indexes"])
        run.run([*apt, "--no-download", *install], timeout=900)
        after = shared.installed_packages(run)
        for name, item in before.items():
            if after.get(name, {}).get("Version") != item["Version"]:
                raise ValueError(f"provisioning changed/removed existing package: {name}")
        if set(after) - set(before) - set(selected):
            raise ValueError("unplanned package installation")
        for name, version in (plan["roots"] | selected).items():
            if after.get(name, {}).get("Version") != version:
                raise ValueError(f"installed version differs from pin: {name}")
        shared.check_base(after)
        comparisons = {}

        def compare(actual, operator, wanted):
            key = (actual, operator, wanted)
            if key not in comparisons:
                run.run(["/usr/bin/dpkg", "--compare-versions", actual, operator, wanted], timeout=10, allowed=(0, 1))
                comparisons[key] = shared.load_json(run.logs / f"{run.counter:04d}.json")["returncode"] == 0
            return comparisons[key]

        closure, edges = shared.dependency_closure(set(plan["roots"]) | set(selected), after, compare)
        archives = work / "apt/archives"
        archived = {source.sha256(p): p for p in archives.glob("*.deb")}
        inputs = {}
        for name in closure:
            installed = after[name]
            text = run.run([*cache, "show", f"{name}={installed['Version']}"])
            metadata = shared.package_record(text, name, installed["Version"], installed["Architecture"])
            (work / "package-metadata" / (name + ".control")).write_text(text)
            expected = metadata["SHA256"]
            if expected not in archived:
                run.run([*apt, "download", f"{name}={installed['Version']}"], cwd=archives, timeout=300)
                archived = {source.sha256(p): p for p in archives.glob("*.deb")}
            artifact = archived.get(expected)
            if artifact is None or artifact.stat().st_size != int(metadata["Size"]):
                raise ValueError(f"package artifact SHA256/size mismatch: {name}")
            deb = shared.parse_control(run.run(["/usr/bin/dpkg-deb", "--field", artifact, "Package", "Version", "Architecture"]))
            if len(deb) != 1 or any(deb[0].get(field) != metadata[field] for field in ("Package", "Version", "Architecture")):
                raise ValueError("downloaded Debian archive identity mismatch")
            inputs[name] = {field: metadata[field] for field in ("Package", "Version", "Architecture", "Filename", "SHA256")}
            inputs[name].update({"Size": int(metadata["Size"]), "artifact": str(artifact.relative_to(work)), "dependencies": edges[name]})
        if set(archived) != {record["SHA256"] for record in inputs.values()}:
            raise ValueError("unidentified Debian archive in retained package closure")
        verified_indexes(work, plan["indexes"])
        result.update({"state": "prepared-no-tests-run", "installed_before": before, "installed_after": after,
                       "resolved_install_plan": selected, "package_artifacts": inputs})
        shared.write_json(work / "preparation.json", result)
        return result
    except BaseException as exc:
        shared.write_json(work / "failure.json", result | {"state": "failed", "error": f"{type(exc).__name__}: {exc}"})
        raise
    finally:
        shared.artifact_manifest(work)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def interrupted(signum, _):
        raise InterruptedError(f"guest package preparation interrupted: {signum}")

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    try:
        result = prepare(args)
        print(json.dumps({"state": result["state"], "output": str(args.output)}))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Guest package preparation refused/failed: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
