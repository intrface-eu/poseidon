#!/usr/bin/env python3
"""Audit archived CAD evidence using stdlib; --geometry reexecutes CAD checks.

Manifest-only success means files, arithmetic and stored evidence agree. It does
NOT mean CadQuery, OCP, STEP import or STL manifold checks ran in this process.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from parameters import (CAD_ROOT, ROOT, CONFIGURATION, REVISION, STATUS, arithmetic_checks,
                        interface_evidence, sha256, validate_parameters)

REQUIRED_ASSEMBLIES = {"HUB", "WET", "ARRAY", "WIPER", "PROJECTOR", "REEF", "FARM",
                       "ASSEMBLY_FIXTURE", "CALIBRATION_FIXTURE", "PRESSURE_POSITIONING_FIXTURE", "TOP_PASSIVE"}
PRINTABLE_IDS = {"PRINT-HUB-GUIDE-01", "PRINT-PI-TEMPLATE-01", "PRINT-CABLE-RADIUS-GAUGE-01", "PRINT-CAL-TARGET-HOLDER-01"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def safe_artifact(directory, name):
    relative = Path(name)
    require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe artifact path")
    path = directory / relative
    require(path.is_file() and not path.is_symlink(), f"Artifact missing or symlink: {name}")
    require(path.resolve().is_relative_to(directory.resolve()), "Artifact escapes output directory")
    return path


def audit(directory: Path, verify_current_sources=True):
    manifest = json.loads((directory / "manifest.json").read_text())
    require(manifest.get("schema") == "poseidon.cad.manifest.v1", "Wrong CAD manifest schema")
    require(manifest.get("configuration") == CONFIGURATION and manifest.get("revision") == REVISION, "Wrong configuration or revision")
    require(manifest.get("status") == STATUS, "Missing provisional status")
    require(manifest.get("units") == {"length": "mm", "volume": "mm3", "mass": "kg"}, "Wrong model units")
    require(manifest.get("passive_default") is True and manifest.get("default_top_assembly") == "TOP_PASSIVE", "Passive default lost")
    require(manifest.get("no_pressure_boundary_designed") is True and manifest.get("fabrication_authorized") is False, "Pressure or fabrication boundary violated")
    require(manifest.get("physical_tests_performed") == [], "CAD evidence must not invent physical tests")
    parameters = manifest["parameters"]
    validate_parameters(parameters)
    require(manifest["checks"] == arithmetic_checks(parameters), "Stored arithmetic checks disagree with recomputation")
    if verify_current_sources:
        for name, digest in manifest["source_files"].items():
            require(Path(name).name == name, "Unsafe source path")
            require(sha256(CAD_ROOT / name) == digest, f"CAD source changed since generation: {name}")
        current = interface_evidence(parameters)
        require(current == manifest["interface_evidence"], "Controlled interface changed since generation")
    vendor_records = {r["path"]: r for r in json.loads((ROOT / "hardware/vendor-sources.json").read_text())["files"]}
    for evidence in manifest["primary_source_evidence"]:
        path = evidence["local_path"]
        require(path.startswith("hardware/.vendor-cache/cad/"), "Evidence path outside private cache")
        key = path.removeprefix("hardware/.vendor-cache/")
        record = vendor_records.get(key)
        require(record is not None and record["sha256"] == evidence["sha256"]
                and record["url"] == evidence["url"], "Primary evidence provenance mismatch")
        require(evidence["retrieved_date"] == "2026-09-08" and evidence["url"].startswith("https://"), "Missing source provenance")
    records = manifest["assemblies"]
    ids = [a["id"] for a in records]
    require(len(ids) == len(set(ids)), "Duplicate assembly IDs")
    require(REQUIRED_ASSEMBLIES <= set(ids), "Missing major CAD assembly")
    require(set(ids) <= REQUIRED_ASSEMBLIES | {"TOP_RESEARCH"}, "Unknown assembly")
    artifacts = manifest["artifacts"]
    artifact_names = [a["path"] for a in artifacts]
    require(len(artifact_names) == len(set(artifact_names)), "Duplicate artifact paths")
    for artifact in artifacts:
        path = safe_artifact(directory, artifact["path"])
        require(path.stat().st_size == artifact["bytes"] > 0, f"Artifact size mismatch: {path.name}")
        require(sha256(path) == artifact["sha256"], f"Artifact digest mismatch: {path.name}")
        if path.suffix == ".svg":
            require(ET.parse(path).getroot().tag.endswith("svg"), "Invalid SVG drawing")
    actual_names = {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file() and path.name != "manifest.json"}
    require(actual_names == set(artifact_names), "Unlisted or missing output artifacts")
    external_ids = {part["id"] for part in json.loads((ROOT / manifest["external_bom"]["path"]).read_text())["parts"]}
    mechanical = json.loads((directory / "mechanical-bom.json").read_text())
    mechanical_ids = {part["id"] for part in mechanical["parts"]}
    printed = set()
    checks = list(manifest["checks"])
    for assembly in records:
        require(assembly["parts"], "Empty assembly does not count")
        for field in ("min_mm", "max_mm", "size_mm"):
            require(len(assembly["bbox"][field]) == 3 and all(math.isfinite(v) for v in assembly["bbox"][field]), "Invalid assembly bbox")
        require(all(v > 0 for v in assembly["bbox"]["size_mm"]), "Degenerate assembly bbox")
        for name in (assembly["step"], assembly["drawing_svg"], assembly["drawing_dxf"], f"views/{assembly['id']}_assembly.svg", f"views/{assembly['id']}_exploded.svg"):
            require(name in artifact_names, f"Missing assembly export {name}")
        step = safe_artifact(directory, assembly["step"]).read_text(errors="replace")
        require("ISO-10303-21" in step and "SI_UNIT(.MILLI.,.METRE.)" in step, "STEP is missing explicit mm units")
        require("MANIFOLD_SOLID_BREP" in step or "BREP_WITH_VOIDS" in step, "STEP does not contain BRep solids")
        require(len({part["id"] for part in assembly["parts"]}) == len(assembly["parts"]), "Duplicate part IDs")
        for part in assembly["parts"]:
            require(part["bom_id"] in external_ids | mechanical_ids, f"Unresolved BOM link {part['bom_id']}")
            require(part["status"] == STATUS and part["revision"] == REVISION, "Part revision/status mismatch")
            require(part["pressure_boundary"] is False, "No custom pressure-boundary parts allowed")
            require(part["solids"] >= 1 and part["volume_mm3"] > 0, "Part has no positive solid volume")
            b = part["bbox"]
            for i in range(3):
                require(math.isfinite(b["size_mm"][i]) and b["size_mm"][i] > 0, "Invalid part bbox")
                require(abs(b["max_mm"][i] - b["min_mm"][i] - b["size_mm"][i]) < 1e-5, "Inconsistent part bbox")
                require(assembly["bbox"]["min_mm"][i] - 1e-4 <= b["min_mm"][i] <= b["max_mm"][i] <= assembly["bbox"]["max_mm"][i] + 1e-4, "Part outside assembly bbox")
            density = manifest["materials"][part["material_id"]]["density_kg_m3"]
            if density is None:
                require(part["solid_equivalent_mass_kg"] is None, "Envelope must not infer density mass")
            else:
                require(abs(part["solid_equivalent_mass_kg"] - density * part["volume_mm3"] / 1e9) <= 1e-6, "Mass calculation mismatch")
            if part["printable"]:
                require(part["id"] in PRINTABLE_IDS and part["material_id"] == "PETG" and not part["critical_load"], "Unsafe printable classification")
                require(f"printable/{part['id']}.stl" in artifact_names, "Missing printable STL")
                printed.add(part["id"])
        checks.extend(assembly["checks"])
        require(any(c["id"] == assembly["id"] + "_step_roundtrip" for c in assembly["checks"]), "Missing archived STEP roundtrip")
        require(any(c["id"] == assembly["id"] + "_physical_interference" for c in assembly["checks"]), "Missing archived interference check")
    require(printed == PRINTABLE_IDS, "Printable whitelist mismatch")
    require({Path(name).stem for name in artifact_names if name.endswith(".stl")} == PRINTABLE_IDS, "STL exported for non-whitelisted part")
    require(all(c.get("passed") is True for c in checks), "Stored runtime checks include failure")
    require(manifest["check_summary"]["total"] == len(checks) and manifest["check_summary"]["passed"] == len(checks) and manifest["check_summary"]["failed"] == 0, "Check-summary count mismatch")
    top = next(a for a in records if a["id"] == "TOP_PASSIVE")
    require(not any(part["id"].startswith(("WIPER__", "PROJECTOR__", "ARRAY__")) for part in top["parts"]), "Optional active/research hardware leaked into passive top")
    return {"mode": "stdlib_manifest_audit", "geometry_runtime_executed": False,
            "assemblies": len(records), "artifacts": len(artifacts), "archived_runtime_and_arithmetic_checks": len(checks),
            "note": "Verified hashes, arithmetic, source/BOM links and stored CAD evidence; did NOT execute OCP, STEP import or STL manifold checks."}


def geometry_audit(directory: Path):
    # Import only on explicit CAD-runtime path, so stdlib unit tests need no CAD dependency.
    import cadquery as cq
    import trimesh
    import generate as g
    m = json.loads((directory / "manifest.json").read_text())
    p = m["parameters"]
    assemblies = [g.build_hub(p), g.build_wet(p), g.build_array(p), g.build_wiper(p), g.build_projector(p), g.build_reef(p),
                  g.build_farm(p), g.build_assembly_fixture(p), g.build_calibration_fixture(p), g.build_pressure_positioning(p)]
    top, _ = g.build_top(assemblies, p, False)
    if m["research_layout_exported"]:
        research, _ = g.build_top(assemblies, p, True)
        assemblies.extend([top, research])
    else:
        assemblies.append(top)
    checks = []
    for a in assemblies:
        checks.extend(g.geometry_checks(a))
        checks.append(g.step_roundtrip(directory / "step" / f"{a.id}.step", a.compound()))
        if a.keepouts:
            checks.append(g.step_roundtrip(directory / "keepouts" / f"{a.id}_keepouts.step", cq.Compound.makeCompound([shape for shape, _ in a.keepouts.values()])))
        for part in a.parts:
            if part.printable:
                mesh = trimesh.load_mesh(directory / "printable" / f"{part.id}.stl", process=True)
                require(mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0, "STL is not a closed consistently oriented solid")
                require(abs(mesh.volume - part.shape.Volume()) / part.shape.Volume() < 0.01, "STL volume diverges from BRep")
                checks.append({"id": part.id + "_mesh_recheck", "passed": True})
    failures = [c for c in checks if not c["passed"]]
    require(not failures, "CAD runtime recheck failed: " + json.dumps(failures))
    return {"mode": "cad_runtime_reexecution", "geometry_runtime_executed": True, "checks": len(checks), "passed": len(checks), "failed": 0,
            "note": "Rebuilt parametric solids, reran BRep/interference/clearances, freshly imported every STEP and rechecked actual STL meshes."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--geometry", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(audit(args.directory), sort_keys=True))
        if args.geometry:
            print(json.dumps(geometry_audit(args.directory), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, ImportError, json.JSONDecodeError) as error:
        print(f"CAD audit failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
