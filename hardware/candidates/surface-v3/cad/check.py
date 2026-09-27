#!/usr/bin/env python3
"""Audit <dir> using stdlib; --geometry independently rebuilds and imports STEP with CadQuery."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
import argparse
import math
from pathlib import Path
from surface_contract import (CAD, CANDIDATE, ROOT, STATUS, GLB_NAME, SENTENCE, read_json, digest,
                              validate, values, layout, baseline_check, mechanics, require, repo_file)
from surface_glb import Parsed, expected_bounds, point

PART_SPECS = {
    "SV3_TRAY_PLATE": ("tray", "common", "physical_custom", "aluminum"),
    "SV3_OPEN_BOTTOM_SKIRT": ("tray", "common", "physical_custom", "aluminum"),
    "SV3_PANEL_A": ("panelA", "common", "purchased_envelope", "panel"),
    "SV3_PANEL_B": ("panelB", "common", "purchased_envelope", "panel"),
    "SV3_HUB_HAMMOND_1550WJ": ("hub", "common", "purchased_envelope", "hub"),
    "SV3_HUB_CARRIER": ("hub", "common", "physical_custom", "aluminum"),
    "SV3_SHADE_ROOF": ("hub", "common", "physical_custom", "aluminum"),
    "SV3_SINK_OCCUPANCY_NOT_FINS": ("hub", "common", "allocation", "allocation"),
    "SV3_SINK_OUTLET_AIR_ALLOCATION": ("hub", "common", "allocation", "allocation"),
    "SV3_MAST_SOCKET": ("mastSocket", "common", "physical_custom", "aluminum"),
    "SV3_POLE_60MM": ("mountPole", "pole", "physical_custom", "steel"),
    "SV3_SEABED_FOOTING_PLATE": ("mountPole", "pole", "physical_custom", "steel"),
    "SV3_FLOAT_COLLAR": ("mountFloat", "float", "physical_custom", "foam"),
}
for label in ("A", "B"):
    for i in (1, 2):
        PART_SPECS[f"SV3_WEDGE_{label}_{i}"] = ("panel"+label, "common", "physical_custom", "aluminum")
    PART_SPECS["SV3_CABLE_ROUTE_ALLOCATION_"+label] = ("tray", "common", "allocation", "allocation")
for i in (1, 2):
    PART_SPECS[f"SV3_SHADE_HANGER_{i}"] = ("hub", "common", "physical_custom", "aluminum")
    PART_SPECS[f"SV3_CROSS_BOLT_ALLOCATION_{i}"] = ("mastSocket", "common", "allocation", "allocation")
SOURCE_FILES = ["interface.json", "baseline-lock.json", "sources/source-register.json"] + ["cad/"+n for n in (
    "generate.py", "check.py", "surface_contract.py", "surface_model.py", "surface_export.py", "surface_glb.py")]


def close(a, b, tol=1e-8):
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(close(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isfinite(a) and math.isfinite(b) and abs(a-b) <= tol*max(1, abs(b))
    return a == b


def metadata_differences(archived, rebuilt, tol=1e-7, key=""):
    """Name every out-of-tolerance leaf; the acceptance predicate remains close()."""
    if close(archived, rebuilt, tol):
        return []
    if isinstance(archived, dict) and isinstance(rebuilt, dict):
        differences = []
        for field in sorted(archived.keys() | rebuilt.keys()):
            path = f"{key}.{field}" if key else field
            if field not in archived or field not in rebuilt:
                differences.append(f"{path}: archived={archived.get(field, '<missing>')!r}, "
                                   f"rebuilt={rebuilt.get(field, '<missing>')!r}, absolute_delta=n/a, relative_delta=n/a")
            else:
                differences.extend(metadata_differences(archived[field], rebuilt[field], tol, path))
        return differences
    if isinstance(archived, list) and isinstance(rebuilt, list):
        differences = []
        if len(archived) != len(rebuilt):
            differences.append(f"{key}.length: archived={len(archived)!r}, rebuilt={len(rebuilt)!r}, "
                               "absolute_delta=n/a, relative_delta=n/a")
        for index in range(max(len(archived), len(rebuilt))):
            path = f"{key}[{index}]"
            if index >= len(archived) or index >= len(rebuilt):
                differences.append(f"{path}: archived={archived[index] if index < len(archived) else '<missing>'!r}, "
                                   f"rebuilt={rebuilt[index] if index < len(rebuilt) else '<missing>'!r}, "
                                   "absolute_delta=n/a, relative_delta=n/a")
            else:
                differences.extend(metadata_differences(archived[index], rebuilt[index], tol, path))
        return differences
    if type(archived) in (int, float) and type(rebuilt) in (int, float):
        absolute = abs(archived-rebuilt)
        scale = max(abs(archived), abs(rebuilt))
        return [f"{key}: archived={archived!r}, rebuilt={rebuilt!r}, "
                f"absolute_delta={absolute!r}, relative_delta={(absolute/scale if scale else 0)!r}"]
    return [f"{key}: archived={archived!r}, rebuilt={rebuilt!r}, absolute_delta=n/a, relative_delta=n/a"]


def safe_artifact(out, relative):
    rel = Path(relative)
    require(not rel.is_absolute() and ".." not in rel.parts, "Unsafe artifact path")
    target = out/rel
    require(target.is_file() and not target.is_symlink() and target.resolve().is_relative_to(out.resolve()), "Artifact escape/missing: "+relative)
    return target


def audit(out, geometry=False):
    out = Path(out)
    manifest = read_json(out/"manifest.json")
    require(manifest["schema"] == "poseidon.surface-v3.manifest.v1" and manifest["status"] == STATUS, "Manifest identity")
    require(manifest["boundary"] == SENTENCE, "Manifest authority boundary")
    p = manifest["interface"]
    validate(p)
    baseline = baseline_check()
    require(manifest["baseline"] == baseline, "Baseline evidence changed")
    require(read_json(out/"interface-used.json") == p, "Used parameter snapshot mismatch")
    expected_sources = {str((CANDIDATE/f).relative_to(ROOT)): digest(CANDIDATE/f) for f in SOURCE_FILES}
    require(manifest["construction_sources"] == expected_sources, "Construction source hashes changed")
    v, d = values(p), layout(p)
    parts = {r["name"]: r for r in manifest["parts"]}
    require(set(parts) == set(PART_SPECS) and len(parts) == len(manifest["parts"]), "Part inventory/duplicate drift")
    expected_paths = {GLB_NAME, "hierarchy.json", "mass-displacement.json", "interface-used.json"}
    for name, part in parts.items():
        spec = PART_SPECS[name]
        require(tuple(part[k] for k in ("group", "variant", "kind", "material")) == spec, "Part classification: "+name)
        require(part["physical"] == (spec[2] != "allocation"), "Allocation population: "+name)
        expected_step = ("allocations/" if spec[2] == "allocation" else "step/")+name+".step"
        require(part["step"] == expected_step, "Wrong STEP classification/path")
        expected_paths.update((expected_step, "drawings/"+name+".dxf"))
        require(part["parameter_keys"] and set(part["parameter_keys"]) <= set(p["parameters"]), "Part dimension trace coverage: "+name)
        require(math.isfinite(part["volume_mm3"]) and part["volume_mm3"] > 0, "Part volume")
        for box in (part["bbox"], part["source_bbox_mm"]):
            require(all(math.isfinite(x) for k in ("min_mm", "max_mm", "size_mm") for x in box[k]), "Finite BRep metadata")
            require(all(abs(box["max_mm"][k]-box["min_mm"][k]-box["size_mm"][k]) < 1e-6 and box["size_mm"][k] > 0 for k in range(3)), "BRep bbox arithmetic")
        transform = part["source_to_cad_matrix_mm"]
        corners = [point(transform, [part["source_bbox_mm"][k][i] for i, k in enumerate(keys)])
                   for keys in __import__("itertools").product(("min_mm", "max_mm"), repeat=3)]
        transformed = {"min_mm": [min(q[i] for q in corners) for i in range(3)], "max_mm": [max(q[i] for q in corners) for i in range(3)]}
        require(all(abs(transformed[k][i]-part["bbox"][k][i]) < 0.0001 for k in transformed for i in range(3)), "Source transform/bbox drift: "+name)
    for variant in ("POLE", "FLOAT"):
        expected_paths.update((f"step/SURFACE_V3_{variant}.step", f"drawings/SURFACE_V3_{variant}.dxf"))
    artifacts = {r["path"]: r for r in manifest["artifacts"]}
    require(set(artifacts) == expected_paths and len(artifacts) == len(manifest["artifacts"]), "Artifact inventory")
    actual = {str(f.relative_to(out)) for f in out.rglob("*") if f.is_file()}
    require(actual == expected_paths | {"manifest.json"}, "Unexpected/missing generated files")
    for name, rec in artifacts.items():
        file = safe_artifact(out, name)
        require(digest(file) == rec["sha256"] and file.stat().st_size == rec["bytes"], "Artifact hash/size mismatch: "+name)
        if name.endswith(".step"):
            require("SI_UNIT(.MILLI.,.METRE.)" in file.read_text(errors="replace"), "STEP mm declaration")
        if name.endswith(".dxf"):
            text = file.read_text(errors="replace")
            require(all(marker in text for marker in ("$INSUNITS", "LWPOLYLINE", "DIMENSION", "XY", "XZ", "YZ")), "DXF structure")
    hierarchy = read_json(out/"hierarchy.json")
    require(hierarchy["glb_sha256"] == digest(out/GLB_NAME), "Hierarchy/GLB hash mismatch")
    require(hierarchy["cad_units"] == "mm" and hierarchy["glb_units"] == "m", "Hierarchy units")
    hparts = {q["name"]: q for q in hierarchy["parts"]}
    require(set(hparts) == set(parts) and len(hparts) == len(hierarchy["parts"]), "Hierarchy part inventory")
    require(set(hierarchy["physical_parts"]) == {n for n, r in parts.items() if r["physical"]} and
            set(hierarchy["nonphysical_allocations"]) == {n for n, r in parts.items() if not r["physical"]}, "Hierarchy physical/allocation split")
    for name, row in parts.items():
        require(all(close(hparts[name][k], val) for k, val in row.items()), "Hierarchy source metadata mismatch: "+name)
        require(hparts[name]["step_sha256"] == digest(out/row["step"]), "Hierarchy STEP hash")
        require(close(hierarchy["source_geometry_bboxes_mm"][name], row["bbox"]), "Hierarchy source bbox")
    mass = read_json(out/"mass-displacement.json")
    recomputed = mechanics(p, list(parts.values()))
    require(close(mass, recomputed), "Mass/displacement arithmetic or unknown-mass boundary")
    require(close(mass, manifest["mass_displacement"]), "Manifest mass mismatch")
    require(mass["actual_complete_mass_kg"] is None and mass["actual_buoyancy_sign"] == "UNKNOWN", "Actual buoyancy not known")
    require(mass["float_scenario"]["fully_submerged_buoyancy_sign"] == "POSITIVE", "Conditional collar buoyancy sign")
    surface_float = mass["float_scenario"]["float_surface_y_m"]
    require(close(hierarchy["surface_origin_float_mm"], [0, 0, surface_float*1000]), "Float placement mass mismatch")
    # Independent core envelope checks, not values copied from the generated PASS flag.
    for name, key in (("SV3_PANEL_A", "panel_xyz_mm"), ("SV3_PANEL_B", "panel_xyz_mm"),
                      ("SV3_HUB_HAMMOND_1550WJ", "hub_xyz_mm"), ("SV3_SINK_OCCUPANCY_NOT_FINS", "sink_xyz_mm")):
        require(close(parts[name]["source_bbox_mm"]["size_mm"], v[key], 1e-7), "Purchased source bbox mismatch: "+name)
        require(close(parts[name]["volume_mm3"], math.prod(v[key])), "Purchased solid-envelope volume mismatch")
    a, b = parts["SV3_PANEL_A"]["bbox"], parts["SV3_PANEL_B"]["bbox"]
    require(abs(b["min_mm"][1]-a["max_mm"][1]-v["panel_gap_mm"]) < 1e-6, "Panel gap changed")
    require(abs(parts["SV3_POLE_60MM"]["bbox"]["size_mm"][2]-d["pole_length_mm"]) < 1e-6, "Pole source length changed")
    require(close(parts["SV3_POLE_60MM"]["bbox"]["size_mm"][:2], [60, 60], 1e-6), "Pole diameter")
    require(abs(parts["SV3_POLE_60MM"]["bbox"]["min_mm"][2]+v["site_depth_mm"]) < 1e-6, "Pole seabed endpoint")
    for name in ("SV3_PANEL_A", "SV3_PANEL_B"):
        # z component of rotated local +X fixes the drainage slope independently.
        require(abs(parts[name]["source_to_cad_matrix_mm"][2][0]-math.sin(d["panel_angle_rad"])) < 1e-9, "Panel tilt transform")
    glb = Parsed(out/GLB_NAME)
    groups = {"SURFACE_V3", "surface", "tray", "hub", "panelA", "panelB", "mastSocket", "mountPole", "mountFloat"}
    require(set(glb.names) == set(parts) | groups, "GLB stable names/hierarchy inventory")
    nodes = glb.doc["nodes"]
    def parent_name(name):
        index = glb.parents.get(glb.names[name])
        return nodes[index]["name"] if index is not None else None
    for group in ("tray", "hub", "panelA", "panelB", "mastSocket"):
        require(parent_name(group) == "surface", "Contract surface ancestry")
    for group in ("surface", "mountPole", "mountFloat"):
        require(parent_name(group) == "SURFACE_V3", "Root contract ancestry")
    root = nodes[glb.names["SURFACE_V3"]]
    require(root.get("scale") == [0.001]*3, "Exactly one mm-to-m root scale")
    require(root["extras"]["contract"] == "poseidon.site.assets.v3" and
            close(root["extras"]["seabedTopY"], -v["site_depth_mm"]/1000) and
            close(root["extras"]["trayTopY"], (v["freeboard_mm"]+v["tray_thickness_mm"])/1000), "Root water/height metadata")
    fnode = nodes[glb.names["mountFloat"]]
    require(fnode["extras"]["defaultHidden"] is True and close(fnode["extras"]["floatSurfaceY"], surface_float), "Float variant visibility/height")
    max_delta, triangles = 0.0, 0
    for name, part in parts.items():
        node = nodes[glb.names[name]]
        require(parent_name(name) == part["group"], "Part group mapping: "+name)
        require(node["extras"]["physical"] == part["physical"] and node["extras"]["kind"] == part["kind"], "GLB allocation classification")
        require(node["extras"]["source_step_sha256"] == digest(out/part["step"]), "GLB STEP binding")
        actual_geometry = glb.geometry(name)
        expected = expected_bounds(part["bbox"])
        delta = max(abs(actual_geometry[k][i]-expected[k][i]) for k in expected for i in range(3))
        require(delta <= (v["glb_deflection_mm"]+0.001)/1000, "GLB scale/binary bbox: "+name)
        actual_volume = actual_geometry["enclosed_mesh_volume_m3"]*1e9
        require(abs(actual_volume-part["volume_mm3"]) <= max(1, part["volume_mm3"]*0.015), "GLB binary geometry volume: "+name)
        require(close(actual_geometry, hparts[name]["gltf_geometry"], 1e-7), "Hierarchy binary geometry drift: "+name)
        max_delta = max(max_delta, delta)
        triangles += actual_geometry["triangle_count"]
    mapping = hierarchy["contract_groups"]
    for group in ("tray", "hub", "panelA", "panelB", "mastSocket", "mountPole", "mountFloat"):
        actual_members = mapping["surface"][group] if group in mapping["surface"] else mapping[group]
        require(set(actual_members) == {n for n, r in parts.items() if r["group"] == group}, "Hierarchy contract mapping")
    result = {"result": "PASS", "kernel_executed": False, "parts": len(parts),
              "physical_parts": sum(r["physical"] for r in parts.values()), "allocations": sum(not r["physical"] for r in parts.values()),
              "traced_parameters": len(v), "source_files_checked": len(validate(p)), "baseline_files_checked": baseline["files_checked"],
              "artifacts_hashed": len(artifacts), "glb_triangles": triangles, "max_glb_bbox_delta_m": max_delta,
              "saved_pass_flag_trusted": False, "physical_tests_performed": 0}
    if geometry:
        import cadquery as cq
        import surface_model as model
        from surface_export import step_check, drawing_check
        fresh = model.build(p)
        checks = model.geometry_checks(fresh)
        fresh_parts = {r["name"]: r for r in fresh.metadata()}
        for name, r in parts.items():
            if not close(r, fresh_parts[name], 1e-7):
                require(False, "Rebuilt source metadata differs: "+name+"; "+
                        "; ".join(metadata_differences(r, fresh_parts[name], 1e-7)))
            shape = fresh.get(name).shape
            checks.append(step_check(out/r["step"], shape))
            checks.append(drawing_check(out/"drawings"/(name+".dxf"), shape))
            # Binary vertices and face centroids must remain on the regenerated BRep
            # within tessellation tolerance. This catches same-bbox mesh tampering.
            samples = set()
            for tri in glb.triangles(name):
                for q in [*tri, [sum(q[k] for q in tri)/3 for k in range(3)]]:
                    samples.add(tuple(round(x, 9) for x in q))
            maximum = 0.0
            for x, z, negy in samples:
                distance = shape.distance(cq.Vertex.makeVertex(x*1000, -negy*1000, z*1000))
                maximum = max(maximum, distance)
            checks.append(model.record("binary_mesh_on_brep:"+name, maximum <= v["glb_deflection_mm"]+0.001,
                                       max_distance_mm=maximum, samples=len(samples)))
        for variant in ("pole", "float"):
            checks.append(step_check(out/"step"/("SURFACE_V3_"+variant.upper()+".step"), fresh.compound(variant)))
            checks.append(drawing_check(out/"drawings"/("SURFACE_V3_"+variant.upper()+".dxf"), fresh.compound(variant)))
        failures = [r for r in checks if not r["passed"]]
        require(not failures, "Independent kernel checks failed: "+str(failures))
        result.update(kernel_executed=True, kernel_checks=len(checks), kernel_failed=0,
                      coinstalled_pair_checks=sum(r["id"].startswith("interference:") for r in checks))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--geometry", action="store_true")
    args = parser.parse_args(argv)
    try:
        import json
        print(json.dumps(audit(args.directory, args.geometry), indent=2))
        return 0
    except Exception as error:
        print("FAIL: "+str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
