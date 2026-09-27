"""STEP/DXF exports and a named, metre-correct source GLB. Kernel-only module."""
from __future__ import annotations
import math
import cadquery as cq
import ezdxf
from surface_contract import CAD, ROOT, CANDIDATE, GLB_NAME, STATUS, values, digest, write_json, require
from surface_model import bbox, valid, record
from surface_glb import unpack, encode, Parsed, expected_bounds


def step_check(path, shape):
    imported = cq.importers.importStep(str(path)).val()
    a, b = bbox(shape), bbox(imported)
    delta = max(abs(a[k][i]-b[k][i]) for k in ("min_mm", "max_mm") for i in range(3))
    vd = abs(shape.Volume()-imported.Volume())
    # Socket metadata is archived to whole mm³; compare raw STEP volume within
    # that 1 mm³ quantum, even if the two values straddle a rounding boundary.
    # Other parts retain their tighter raw-volume limit.
    volume_agrees = (vd <= 1.0 if path.name == "SV3_MAST_SOCKET.step"
                     else vd < max(0.001, shape.Volume()*1e-6))
    return record("step_roundtrip:"+path.name,
                  valid(imported) and len(imported.Solids()) == len(shape.Solids()) and delta < 0.0001
                  and volume_agrees and "SI_UNIT(.MILLI.,.METRE.)" in path.read_text(errors="replace"),
                  bbox_delta_mm=delta, volume_delta_mm3=vd, solids=len(imported.Solids()))


def drawing(path, shape, p):
    v = values(p)
    d = ezdxf.new("R2018")
    d.units = ezdxf.units.MM
    d.header["$MEASUREMENT"] = 1
    for layer in ("XY", "XZ", "YZ", "DIMENSIONS", "NOTES"):
        d.layers.new(layer)
    space, b = d.modelspace(), bbox(shape)
    for axes, layer, offset in [((0, 1), "XY", (0, 0)), ((0, 2), "XZ", (0, -b["size_mm"][2]-v["dxf_view_gap_mm"])),
                                ((1, 2), "YZ", (b["size_mm"][0]+v["dxf_view_gap_mm"], 0))]:
        u, w = axes
        for edge in shape.Edges():
            count = 2 if edge.geomType() == "LINE" else max(16, min(180, int(edge.Length()/v["dxf_curve_spacing_mm"])+2))
            pts = [edge.positionAt(i/(count-1)).toTuple() for i in range(count)]
            pts = [(q[u]-b["min_mm"][u]+offset[0], q[w]-b["min_mm"][w]+offset[1]) for q in pts]
            if any(math.dist(pts[0], q) > 1e-6 for q in pts[1:]):
                space.add_lwpolyline(pts, dxfattribs={"layer": layer})
        ox, oy = offset
        a = {"dimtxt": v["dxf_text_height_mm"], "dimasz": v["dxf_text_height_mm"], "dimdec": 3}
        space.add_linear_dim(base=(ox, oy-v["dxf_text_height_mm"]*8), p1=(ox, oy), p2=(ox+b["size_mm"][u], oy), override=a, dxfattribs={"layer": "DIMENSIONS"}).render()
        space.add_linear_dim(base=(ox-v["dxf_text_height_mm"]*8, oy), p1=(ox, oy), p2=(ox, oy+b["size_mm"][w]), angle=90, override=a, dxfattribs={"layer": "DIMENSIONS"}).render()
    space.add_text("SURFACE-V3 / mm / NON-ADOPTED DIGITAL CANDIDATE / NOT FOR FABRICATION", dxfattribs={"height": v["dxf_text_height_mm"], "layer": "NOTES"})
    space.add_text("Orthographic wireframe; curves sampled. Source STEP owns geometry. Allocations are not hardware.", dxfattribs={"height": v["dxf_text_height_mm"], "layer": "NOTES", "insert": (0, -v["dxf_text_height_mm"]*2)})
    d.saveas(path)
    return drawing_check(path, shape)


def drawing_check(path, shape):
    doc = ezdxf.readfile(path)
    dims = list(doc.modelspace().query("DIMENSION"))
    sizes = bbox(shape)["size_mm"]
    expected = [sizes[0], sizes[1], sizes[0], sizes[2], sizes[1], sizes[2]]
    measures = [float(d.get_measurement()) for d in dims]
    layers = {e.dxf.layer for e in doc.modelspace().query("LWPOLYLINE")}
    return record("dxf_roundtrip:"+path.name,
                  doc.units == ezdxf.units.MM and len(measures) == 6 and {"XY", "XZ", "YZ"} <= layers
                  and all(abs(a-b) < 0.0001 for a, b in zip(measures, expected)), measurements_mm=measures)


def export(m, out, metadata, mass):
    checks = []
    by_name = {p.name: p for p in m.parts}
    for part in metadata:
        p = by_name[part["name"]]
        path = out / part["step"]
        cq.Assembly(p.shape, name=p.name).save(str(path), exportType="STEP")
        checks.append(step_check(path, p.shape))
        checks.append(drawing(out / "drawings" / (p.name+".dxf"), p.shape, m.interface))
    for variant in ("pole", "float"):
        assembly = cq.Assembly(name="SURFACE_V3_"+variant.upper())
        for p, shape in m.installed(variant, False):
            assembly.add(shape, name=p.name)
        path = out / "step" / ("SURFACE_V3_"+variant.upper()+".step")
        assembly.save(str(path), exportType="STEP")
        checks.append(step_check(path, m.compound(variant)))
        checks.append(drawing(out / "drawings" / ("SURFACE_V3_"+variant.upper()+".dxf"), m.compound(variant), m.interface))
    path = out / GLB_NAME
    v = values(m.interface)
    m.native().save(str(path), exportType="GLTF", tolerance=v["glb_deflection_mm"], angularTolerance=v["glb_angular_deflection_rad"])
    doc, chunks = unpack(path)
    root = next(n for n in doc["nodes"] if n["name"] == "SURFACE_V3")
    require("scale" not in root, "Unexpected pre-scaled CadQuery export")
    # Verify the pinned OCCT writer emitted millimetres before applying one unit conversion.
    raw = Parsed(path)
    for part in metadata:
        got = raw.geometry(part["name"])
        expected = expected_bounds(part["bbox"])
        require(all(abs(got[k][i]-expected[k][i]*1000) <= v["glb_deflection_mm"]+0.001
                    for k in ("min_m", "max_m") for i in range(3)), "Unexpected raw GLB units/axes: "+part["name"])
    root["scale"] = [0.001]*3
    root["extras"] = {"contract": "poseidon.site.assets.v3", "seabedTopY": -v["site_depth_mm"]/1000,
                      "trayTopY": (v["freeboard_mm"]+v["tray_thickness_mm"])/1000,
                      "waterSurfaceGltfY": 0, "sourceCadUnits": "mm", "length_unit": "metre", "status": STATUS}
    source_code = {str((CAD/n).relative_to(ROOT)): digest(CAD/n) for n in ("surface_model.py", "surface_contract.py", "surface_export.py", "surface_glb.py", "generate.py", "check.py")}
    group_map = {name: [] for name in ("tray", "hub", "panelA", "panelB", "mastSocket", "mountPole", "mountFloat")}
    meta = {r["name"]: r for r in metadata}
    for node in doc["nodes"]:
        name = node["name"]
        if name in meta:
            p = meta[name]
            group_map[p["group"]].append(name)
            node["extras"] = {"cad_part_id": name, "physical": p["physical"], "kind": p["kind"],
                              "material_class": p["material"], "variant": p["variant"], "contract_group": p["group"],
                              "source_step": p["step"], "source_step_sha256": digest(out/p["step"]),
                              "source_bbox_mm": p["source_bbox_mm"], "source_to_cad_matrix_mm": p["source_to_cad_matrix_mm"],
                              "note": p["note"], "included_in_mass": p["physical"] and name != "SV3_HUB_HAMMOND_1550WJ",
                              "qualified": False}
        elif name == "mountFloat":
            node["extras"] = {"defaultHidden": True, "floatSurfaceY": m.float_surface_z/1000,
                              "exclusiveWith": "mountPole", "actualBuoyancySign": "UNKNOWN", "massScenarioOnly": True,
                              "conditionalEquilibriumDraftM": mass["float_scenario"]["conditional_equilibrium_draft_m"]}
        elif name == "mountPole":
            node["extras"] = {"defaultHidden": False, "exclusiveWith": "mountFloat"}
    doc["asset"]["extras"] = {"configuration": "surface-v3", "length_unit": "metre", "status": STATUS,
                              "coordinate_map": "CAD (x,y,z) mm -> glTF (x,z,-y)/1000 m", "unitCorrectionAppliedExactlyOnce": True,
                              "geometry_source": "CadQuery envelope reconstruction and custom candidate BRep, not vendor internal CAD",
                              "allocations_are_not_hardware": True, "new_downloads": 0}
    # This is this call's new file, never a previous export.
    path.write_bytes(encode(doc, chunks))
    parsed = Parsed(path)
    entries = []
    for p in metadata:
        geometry = parsed.geometry(p["name"])
        entries.append({**p, "step_sha256": digest(out/p["step"]), "gltf_geometry": geometry,
                        "source_model": {"path": str((CAD/"surface_model.py").relative_to(ROOT)), "sha256": source_code[str((CAD/"surface_model.py").relative_to(ROOT))]},
                        "variant_pose": {"pole": p["source_to_cad_matrix_mm"] if p["variant"] != "float" else None,
                                         "float_common_translation_delta_mm": [0, 0, m.float_surface_z-v["freeboard_mm"]] if p["variant"] == "common" else None}})
    hierarchy = {"schema": "poseidon.surface-v3.hierarchy.v1", "root": "SURFACE_V3", "canonical_glb": GLB_NAME,
                 "glb_sha256": digest(path), "cad_units": "mm", "glb_units": "m", "coordinate_map": "CAD (x,y,z) mm -> glTF (x,z,-y)/1000 m",
                 "contract_groups": {"surface": {g: group_map[g] for g in ("tray", "hub", "panelA", "panelB", "mastSocket")},
                                     "mountPole": group_map["mountPole"], "mountFloat": group_map["mountFloat"]},
                 "surface_origin_pole_mm": [0, 0, v["freeboard_mm"]], "surface_origin_float_mm": [0, 0, m.float_surface_z],
                 "surface_origin_meaning": "Tray underside; set surface world glTF Y to floatSurfaceY for float variant, do not resize or move its children independently.",
                 "source_geometry_bboxes_mm": {p["name"]: p["bbox"] for p in metadata},
                 "source_local_bboxes_mm": {p["name"]: p["source_bbox_mm"] for p in metadata},
                 "parts": entries, "source_code": source_code,
                 "nodes": [{"index": i, **n} for i, n in enumerate(doc["nodes"])],
                 "physical_parts": [p["name"] for p in metadata if p["physical"]],
                 "nonphysical_allocations": [p["name"] for p in metadata if not p["physical"]],
                 "variant_rule": "Pole and collar never co-installed. Common surface translates rigidly for float mode. The exported source GLB carries both variants for downstream visibility handling.",
                 "geometry_rule": "Source BRep is the record. No Blender resizing; use source transforms, part STEP hashes and per-part binary GLB bounds/volumes. Keep allocation materials visibly provisional.",
                 "rights": m.interface["reuse_rights"]}
    write_json(out/"hierarchy.json", hierarchy)
    return checks
