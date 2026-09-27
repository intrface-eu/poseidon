#!/usr/bin/env python3
"""Stdlib evidence audit by default. --geometry actually reexecutes CadQuery/OCP."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
from itertools import product
import json
import math
from pathlib import Path
import struct
from v3_contract import CANDIDATE, SCHEMA, STATUS, SOURCE_NAMES, baseline_check, digest, read_json, require, safe_file, source_bindings, stack_budget, validate


def close(a, b, tolerance=1e-7):
    return math.isfinite(a) and math.isfinite(b) and abs(a-b) <= tolerance


def matrix_multiply(a, b):
    return [[sum(a[r][k]*b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def node_matrix(node):
    if "matrix" in node:
        return [[node["matrix"][c*4+r] for c in range(4)] for r in range(4)]
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    rotation = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    scale, translation = node.get("scale", [1, 1, 1]), node.get("translation", [0, 0, 0])
    return [[rotation[r][c]*scale[c] for c in range(3)]+[translation[r]] for r in range(3)]+[[0, 0, 0, 1]]


def glb_audit(path, metadata):
    """Read actual binary POSITION accessors, TRS hierarchy and metre-scale bounds."""
    raw = path.read_bytes()
    require(len(raw) >= 20, "Truncated GLB")
    magic, version, length = struct.unpack_from("<4sII", raw)
    require(magic == b"glTF" and version == 2 and length == len(raw), "GLB header/length mismatch")
    chunks, offset = [], 12
    while offset < len(raw):
        require(offset+8 <= len(raw), "Truncated GLB chunk")
        count, kind = struct.unpack_from("<I4s", raw, offset)
        require(count % 4 == 0 and offset+8+count <= len(raw), "GLB chunk size mismatch")
        chunks.append((kind, raw[offset+8:offset+8+count]))
        offset += 8+count
    require(len(chunks) == 2 and chunks[0][0] == b"JSON" and chunks[1][0] == b"BIN\x00", "GLB must be self-contained JSON + BIN")
    doc, binary = json.loads(chunks[0][1]), chunks[1][1]
    require(doc["asset"]["version"] == "2.0" and doc["asset"]["extras"]["length_unit"] == "metre", "GLB units declaration drift")
    rights = doc["asset"]["extras"]
    require(rights["company"] == "Intrface" and rights["product"] == "Poseidon Trident"
            and rights["vendor_cad_reuse_rights"] == "UNVERIFIED_NOT_CC0"
            and rights["vendor_files_public_redistribution_authorized"] is False
            and rights["derived_assembly_wholly_original"] is True
            and rights["public_redistribution_authorized"] is True
            and rights["original_design_license"] == "CERN-OHL-S-2.0",
            "GLB company/product or vendor rights drift")
    require(len(doc["buffers"]) == 1 and "uri" not in doc["buffers"][0] and doc["buffers"][0]["byteLength"] <= len(binary), "External GLB buffer not allowed")
    nodes = doc["nodes"]
    named = {}
    for i, node in enumerate(nodes):
        if node.get("name") in metadata:
            require(node["name"] not in named, "Duplicate stable part node")
            named[node["name"]] = i
            expected = metadata[node["name"]]
            require(node.get("extras", {}).get("physical") is expected["physical"] and node["extras"]["material_class"] == expected["material"], "GLB physical/material classification drift")
    require(set(named) == set(metadata), "Missing stable GLB part names")
    accessors, views = doc["accessors"], doc["bufferViews"]
    position_bounds = {}
    for mesh in doc["meshes"]:
        for primitive in mesh["primitives"]:
            require(primitive.get("mode", 4) == 4, "Only triangle primitives supported")
            index = primitive["attributes"]["POSITION"]
            if index in position_bounds:
                continue
            acc = accessors[index]
            require(acc["componentType"] == 5126 and acc["type"] == "VEC3" and "sparse" not in acc, "Unexpected GLB POSITION accessor")
            view = views[acc["bufferView"]]
            stride = view.get("byteStride", 12)
            start = view.get("byteOffset", 0)+acc.get("byteOffset", 0)
            require(view.get("buffer", 0) == 0 and stride >= 12 and acc["count"] > 0 and start+(acc["count"]-1)*stride+12 <= view.get("byteOffset", 0)+view["byteLength"] <= len(binary), "GLB accessor outside binary buffer")
            vertices = [struct.unpack_from("<3f", binary, start+j*stride) for j in range(acc["count"])]
            require(all(math.isfinite(v) for q in vertices for v in q), "Nonfinite GLB vertex")
            low = [min(q[k] for q in vertices) for k in range(3)]
            high = [max(q[k] for q in vertices) for k in range(3)]
            require(all(close(x, y, max(1e-6, abs(y)*1e-7)) for x, y in zip(low+high, acc["min"]+acc["max"])), "GLB accessor bounds disagree with binary positions")
            position_bounds[index] = (low, high)
    identity = [[1 if r == c else 0 for c in range(4)] for r in range(4)]
    visited, bounds, triangles = set(), {}, 0

    def walk(index, parent, owner=None):
        nonlocal triangles
        require(index not in visited and 0 <= index < len(nodes), "GLB hierarchy cycle or repeated child")
        visited.add(index)
        node = nodes[index]
        world = matrix_multiply(parent, node_matrix(node))
        owner = node["name"] if node.get("name") in metadata else owner
        if "mesh" in node:
            require(owner is not None, "GLB mesh outside named part hierarchy")
            for primitive in doc["meshes"][node["mesh"]]["primitives"]:
                low, high = position_bounds[primitive["attributes"]["POSITION"]]
                points = [tuple(sum(world[r][k]*q[k] for k in range(3))+world[r][3] for r in range(3)) for q in product(*zip(low, high))]
                bounds.setdefault(owner, []).extend(points)
                acc = accessors[primitive["indices"]] if "indices" in primitive else accessors[primitive["attributes"]["POSITION"]]
                require(acc["count"] % 3 == 0, "GLB triangle index count")
                triangles += acc["count"]//3
        for child in node.get("children", []):
            walk(child, world, owner)
    for index in doc["scenes"][doc.get("scene", 0)]["nodes"]:
        walk(index, identity)
    require(len(visited) == len(nodes) and set(bounds) == set(metadata), "Unreachable or empty GLB part geometry")
    maximum = 0.0
    for name, points in bounds.items():
        b = metadata[name]["bbox"]
        expected_min = [b["min_mm"][0]/1000, b["min_mm"][2]/1000, -b["max_mm"][1]/1000]
        expected_max = [b["max_mm"][0]/1000, b["max_mm"][2]/1000, -b["min_mm"][1]/1000]
        measured_min = [min(q[k] for q in points) for k in range(3)]
        measured_max = [max(q[k] for q in points) for k in range(3)]
        delta = max(abs(x-y) for x, y in zip(expected_min+expected_max, measured_min+measured_max))
        maximum = max(maximum, delta)
        require(delta <= 0.001, "GLB metre-scale/source bbox mismatch: " + name + " delta="+str(delta))
    return {"nodes": len(nodes), "stable_part_nodes": len(named), "triangles": triangles, "bytes": len(raw), "max_bbox_delta_m": maximum, "binary_positions_read": True, "units": "m", "cad_to_glb": "(x,z,-y)/1000", "kernel_executed": False}


def mass_audit(m):
    result = m["mass_displacement"]
    require(result["actual_complete_dry_mass_kg"] is None and result["actual_unit_buoyancy_sign"] is None and result["sealed_boundary_present"] is False and result["physical_measurements_performed"] == 0, "Mass/displacement must not claim real sealed unit")
    parts = {p["name"]: p for p in m["parts"]}
    require({p["name"] for p in result["per_part"]} == set(parts), "Mass part coverage drift")
    for row in result["per_part"]:
        p = parts[row["name"]]
        mass = p["source_mass_kg"] if p["source_mass_kg"] is not None else p["volume_mm3"]*p["density_assumption_kg_m3"]/1e9 if p["density_assumption_kg_m3"] is not None else None
        require(row["modeled_mass_kg"] == p["modeled_mass_kg"] and ((mass is None and p["modeled_mass_kg"] is None) or (mass is not None and close(mass, p["modeled_mass_kg"]))), "Mass density/source arithmetic drift")
        require(close(row["geometric_volume_mm3"], p["volume_mm3"], 1e-5), "Mass geometric volume drift")
        require(0 <= row["flooded_external_solid_displacement_mm3"] <= p["volume_mm3"]+1e-3, "Flooded displacement exceeds part solid volume")
    subtotal = sum(r["modeled_mass_kg"] for r in result["per_part"] if r["modeled_mass_kg"] is not None)
    extra = sum(r["flooded_external_solid_displacement_mm3"] for r in result["per_part"])
    require(close(subtotal, result["known_or_assumed_mass_subtotal_kg"]) and close(extra, result["flooded_external_mount_and_stub_solid_volume_mm3"], 1e-3), "Mass subtotal drift")
    require(result["conditional_sealed_external_envelope_volume_mm3"] > result["pressure_shell_material_volume_mm3"] and extra > 0, "Sealed exterior must not equal hollow-shell volume; flooded mount contributions cannot vanish")
    displacement = (result["conditional_sealed_external_envelope_volume_mm3"]+extra)/1e9
    water = displacement*m["interface"]["allocations"]["mass_density_kg_m3"]["seawater"]
    difference = water-subtotal
    require(close(displacement, result["conditional_total_displacement_m3"]) and close(water, result["seawater_mass_displaced_kg"]) and close(difference, result["modeled_upward_mass_difference_kg"]), "Buoyancy arithmetic drift")
    require(result["modeled_buoyancy_sign"] == ("positive" if difference > 0 else "negative" if difference < 0 else "neutral"), "Modeled buoyancy sign drift")


def audit(output):
    output = Path(output)
    m = read_json(safe_file(output, "manifest.json"))
    require(m["schema"] == SCHEMA and m["product"] == "Poseidon Trident" and m["company"] == "Intrface" and m["configuration"] == "passive-v3" and m["revision"] == "HW-CAND-3.0" and m["status"] == STATUS, "Manifest candidate identity drift")
    require(all(m[k] is False for k in ("adopted", "build_authorized", "procurement_authorized", "active_emission_hardware_populated")) and m["physical_tests_performed"] == [], "Manifest authorization/physical boundary")
    validate(m["interface"])
    require(m["units"] == m["interface"]["units"], "Manifest units drift")
    require(m["reuse_rights"] == m["interface"]["reuse_rights"], "Manifest vendor CAD reuse-rights drift")
    require(m["baseline"] == baseline_check(), "Immutable baseline binding drift")
    require(set(m["source_files"]) == set(SOURCE_NAMES) and m["source_files"] == source_bindings(), "CAD/source changed since generation")
    require(m["stack_budget"] == stack_budget(m["interface"]), "Stack budget drift")
    require(m["open_gates"] == m["interface"]["open_gates"] and m["printable_whitelist"] == [], "Physical gates/printing boundary")
    artifacts = m["artifacts"]
    names = [a["path"] for a in artifacts]
    require(len(names) == len(set(names)), "Duplicate artifact path")
    for record in artifacts:
        path = safe_file(output, record["path"])
        require(path.stat().st_size == record["bytes"] > 0 and digest(path) == record["sha256"], "Artifact hash/size mismatch: " + record["path"])
        require(path.suffix.lower() not in (".stl", ".3mf"), "No fabrication mesh export")
        if path.suffix.lower() == ".step":
            text = path.read_text(errors="replace")
            require("MANIFOLD_SOLID_BREP" in text and "SI_UNIT(.MILLI.,.METRE.)" in text, "STEP lacks BRep/mm declaration")
        if path.suffix.lower() == ".dxf":
            text = path.read_text()
            require("DIMENSION" in text and "$INSUNITS" in text, "DXF is not dimensioned")
    actual = {str(f.relative_to(output)) for f in output.rglob("*") if f.is_file() and f.name != "manifest.json"}
    require(actual == set(names), "Missing/unlisted artifact")
    parts, empty = m["parts"], m["empty_nonphysical"]
    require(len(parts) == 25 and len(empty) == 3 and len({x["name"] for x in parts+empty}) == 28, "Physical/EMPTY part coverage drift")
    require(all(p["physical"] and not p["printable"] and not p["pressure_or_load_qualified"] for p in parts), "Physical classification drift")
    require(all(not p["physical"] and p["name"].startswith("EMPTY_") and p["modeled_mass_kg"] is None for p in empty), "EMPTY reserve counted as hardware/mass")
    for part in parts:
        require("step/"+part["name"]+".step" in names, "Missing per-part STEP")
        require(part["volume_mm3"] > 0 and all(v > 0 and math.isfinite(v) for v in part["bbox"]["size_mm"]), "Invalid archived BRep dimensions")
        require(all(close(part["bbox"]["max_mm"][k]-part["bbox"]["min_mm"][k], part["bbox"]["size_mm"][k]) for k in range(3)), "Inconsistent archived bbox")
    require("step/INTRFACE_PASSIVE_V3.step" in names and "keepouts/EMPTY_RESERVES_NOT_HARDWARE.step" in names and m["canonical_glb"] == "INTRFACE_PASSIVE_V3.glb" and m["canonical_glb"] in names, "Assembly/EMPTY/GLB exports missing")
    records = m["check_records"]
    require(len({r["id"] for r in records}) == len(records) and all(r["passed"] is True for r in records), "Archived kernel check failure or duplicate")
    pairs = [r for r in records if r["id"].startswith("interference:")]
    require(len(pairs) == len(parts)*(len(parts)-1)//2 and all("EMPTY_" not in r["id"] and r["overlap_mm3"] <= r["tolerance_mm3"] for r in pairs), "Physical pairwise check coverage drift")
    require(m["checks"] == {"kernel_executed": True, "total": len(records), "passed": len(records), "failed": 0, "physical_pair_checks": len(pairs)}, "Archived check counts drift")
    mass_audit(m)
    require(read_json(safe_file(output, "mass-displacement.json")) == m["mass_displacement"], "Mass artifact differs from manifest")
    hierarchy = read_json(safe_file(output, "hierarchy.json"))
    require(hierarchy["glb_sha256"] == digest(output / m["canonical_glb"]) and hierarchy["physical_parts"] == [p["name"] for p in parts] and hierarchy["empty_nonphysical_parts"] == [p["name"] for p in empty], "Hierarchy artifact binding drift")
    glb = glb_audit(output / m["canonical_glb"], {p["name"]: p for p in parts+empty})
    return {"mode": "stdlib_evidence_audit", "geometry_runtime_executed": False, "baseline_files_unchanged": m["baseline"]["files_checked"], "source_dimensions_traced": len(m["interface"]["dimensions"]), "physical_parts": len(parts), "empty_nonphysical": len(empty), "artifacts": len(artifacts), "archived_runtime_checks": len(records), "glb": glb, "note": "Hashes, source/trace bindings, archived check coverage, mass arithmetic and actual GLB binary positions checked. NO CadQuery/OCP or STEP importer executed in this audit."}


def geometry_audit(output):
    import cadquery as cq
    import v3_model
    from v3_export import step_roundtrip
    output = Path(output)
    m = read_json(output / "manifest.json")
    model = v3_model.build(m["interface"])
    checks = v3_model.geometry_checks(model)
    relative_tolerance = m["interface"]["allocations"]["step_relative_volume_tolerance"]
    for part in model.parts:
        checks.append(step_roundtrip(output / "step" / (part.name+".step"), part.shape, relative_tolerance))
    checks.append(step_roundtrip(output / "step/INTRFACE_PASSIVE_V3.step", model.compound(), relative_tolerance))
    checks.append(step_roundtrip(output / "keepouts/EMPTY_RESERVES_NOT_HARDWARE.step", cq.Compound.makeCompound([p.shape for p in model.empty]), relative_tolerance))
    current = v3_model.mass_displacement(model)
    for key in ("known_or_assumed_mass_subtotal_kg", "conditional_sealed_external_envelope_volume_mm3", "flooded_external_mount_and_stub_solid_volume_mm3", "conditional_total_displacement_m3"):
        require(close(current[key], m["mass_displacement"][key], max(1e-6, abs(current[key])*1e-8)), "Recomputed mass/displacement drift: " + key)
    stored = {p["name"]: p for p in m["parts"]}
    for part in model.parts:
        require(close(part.shape.Volume(), stored[part.name]["volume_mm3"], max(1e-3, part.shape.Volume()*1e-8)), "Rebuilt part volume differs from archived evidence")
        fresh_bbox = v3_model.bbox(part.shape)
        require(all(close(fresh_bbox[key][i], stored[part.name]["bbox"][key][i], 1e-4) for key in ("min_mm", "max_mm", "size_mm") for i in range(3)), "Rebuilt analytic BRep bbox differs from archived evidence: "+part.name)
    failed = [c for c in checks if not c["passed"]]
    require(not failed, "Runtime CAD checks failed: " + json.dumps(failed))
    require(baseline_check() == m["baseline"], "Immutable baseline changed during runtime")
    return {"mode": "cadquery_ocp_runtime_reexecution", "geometry_runtime_executed": True, "checks": len(checks), "passed": len(checks), "failed": 0, "physical_pair_checks": len(model.parts)*(len(model.parts)-1)//2, "step_files_reimported": len(model.parts)+2, "physical_parts": len(model.parts), "empty_excluded_from_physical_pairs": len(model.empty), "mass_displacement_recomputed": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--geometry", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(audit(args.directory), sort_keys=True), flush=True)
        if args.geometry:
            print(json.dumps(geometry_audit(args.directory), sort_keys=True), flush=True)
        return 0
    except Exception as error:
        print("Candidate audit failed: " + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
