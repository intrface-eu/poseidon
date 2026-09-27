"""Exact STEP, sampled dimensioned DXF and named cq.Assembly.save(GLTF) exports."""
from __future__ import annotations
import json
import math
import struct
import cadquery as cq
import ezdxf
from v3_contract import require, write_json, digest
from v3_model import bbox, valid, check_record


def step_roundtrip(path, original, relative_tolerance=1e-6):
    imported = cq.importers.importStep(str(path)).val()
    b1, b2 = bbox(original), bbox(imported)
    delta = max(abs(b1[k][i]-b2[k][i]) for k in ("min_mm", "max_mm") for i in range(3))
    vd = abs(original.Volume()-imported.Volume())
    tolerance = max(0.001, original.Volume()*relative_tolerance)
    count = len(imported.Solids())
    return check_record("step_roundtrip:"+path.name,
                        valid(imported) and count == len(original.Solids()) and delta <= 0.0001 and vd <= tolerance and "SI_UNIT(.MILLI.,.METRE.)" in path.read_text(errors="replace"),
                        bbox_max_delta_mm=delta, volume_delta_mm3=vd, volume_tolerance_mm3=tolerance,
                        imported_solids=count, expected_solids=len(original.Solids()), evidence="Fresh STEP import, OCP BRepCheck_Analyzer, bbox, volume, count and mm units")


def drawing(shape, name, path, p, note):
    dxf = ezdxf.new("R2018")
    dxf.units = ezdxf.units.MM
    dxf.header["$MEASUREMENT"] = 1
    space = dxf.modelspace()
    for layer in ("XY_AFT", "XZ_SIDE", "YZ_SIDE", "DIMENSIONS", "NOTES"):
        dxf.layers.new(layer)
    b = bbox(shape)
    a = p["allocations"]
    xgap = b["size_mm"][0]+a["dxf_view_gap_mm"]
    ygap = b["size_mm"][1]+a["dxf_view_gap_mm"]
    for axes, offset, layer in [((0, 1), (0, 0), "XY_AFT"), ((0, 2), (0, -ygap-b["size_mm"][2]), "XZ_SIDE"), ((1, 2), (xgap, 0), "YZ_SIDE")]:
        u, v = axes
        for edge in shape.Edges():
            count = 2 if edge.geomType() == "LINE" else max(12, min(96, int(edge.Length()/a["dxf_curve_sample_spacing_mm"])+2))
            pts = [edge.positionAt(i/(count-1)).toTuple() for i in range(count)]
            xy = [(q[u]-b["min_mm"][u]+offset[0], q[v]-b["min_mm"][v]+offset[1]) for q in pts]
            if any(math.dist(xy[0], q) > 1e-6 for q in xy[1:]):
                space.add_lwpolyline(xy, dxfattribs={"layer": layer})
        ox, oy = offset
        text = a["dxf_text_height_mm"]
        override = {"dimtxt": text, "dimasz": text, "dimdec": 3}
        space.add_linear_dim(base=(ox, oy-a["dxf_dimension_offset_mm"]), p1=(ox, oy), p2=(ox+b["size_mm"][u], oy), override=override, dxfattribs={"layer": "DIMENSIONS"}).render()
        space.add_linear_dim(base=(ox-a["dxf_dimension_offset_mm"], oy), p1=(ox, oy), p2=(ox, oy+b["size_mm"][v]), angle=90, override=override, dxfattribs={"layer": "DIMENSIONS"}).render()
    for i, line in enumerate([name+" / Poseidon Trident by Intrface / HW-CAND-3.0 / mm", "NON-ADOPTED DIGITAL CANDIDATE; NO BUILD OR PRESSURE RELEASE", "Three orthographic wireframe projections; sampled curves. STEP is exact. Do not scale a render.", note, "Dimension origins use modeled bounds; vendor BRep details keep source authority and revision conflicts.", "All physical gates unperformed. Dome material is POLYCARBONATE, not acrylic."]):
        space.add_text(line, dxfattribs={"height": a["dxf_text_height_mm"], "layer": "NOTES", "insert": (0, -ygap-b["size_mm"][2]-70-i*7)})
    dxf.saveas(path)
    reopened = ezdxf.readfile(path)
    dimensions = list(reopened.modelspace().query("DIMENSION"))
    return check_record("dxf:"+path.name, reopened.units == ezdxf.units.MM and len(dimensions) == 6, dimension_entities=len(dimensions), evidence="Fresh ezdxf read with three dimensioned mm views")


def annotate_glb(path, model):
    data = path.read_bytes()
    magic, version, size = struct.unpack_from("<4sII", data)
    require(magic == b"glTF" and version == 2 and size == len(data), "CadQuery GLB header invalid")
    chunks, offset = [], 12
    while offset < len(data):
        length, kind = struct.unpack_from("<I4s", data, offset)
        chunks.append((kind, data[offset+8:offset+8+length]))
        offset += 8+length
    require(chunks[0][0] == b"JSON", "GLB first chunk must be JSON")
    doc = json.loads(chunks[0][1])
    parts = {q.name: q for q in model.parts+model.empty}
    roots = [node for node in doc["nodes"] if node.get("name") == "INTRFACE_PASSIVE_V3"]
    require(len(roots) == 1 and "scale" not in roots[0], "Unexpected CadQuery GLTF root transform")
    # CadQuery 2.6.1 rotates Z-up to Y-up but this pinned OCCT writer emits
    # millimetre vertex values. An explicit root transform makes glTF metres.
    # This was checked against binary POSITION values, not inferred from metadata.
    roots[0]["scale"] = [0.001, 0.001, 0.001]
    for node in doc["nodes"]:
        if node.get("name") in parts:
            part = parts[node["name"]]
            node["extras"] = {"intrface_part_id": part.name, "physical": part.physical, "material_class": part.material, "source": part.source, "populated": part.physical, "digital_candidate_not_build_authorized": True}
    rights = model.interface["reuse_rights"]
    doc["asset"]["extras"] = {"product": "Poseidon Trident", "company": "Intrface",
                              "vendor_cad_reuse_rights": rights["vendor_cad"],
                              "vendor_files_public_redistribution_authorized": rights["vendor_files_public_redistribution_authorized"],
                              "derived_assembly_wholly_original": rights["derived_assembly_wholly_original"],
                              "public_redistribution_authorized": rights["public_redistribution_authorized"],
                              "original_design_license": rights["original_design_license"],
                              "configuration": "passive-v3", "status": "NON_ADOPTED_NOT_BUILD_AUTHORIZED",
                              "length_unit": "metre", "cad_to_glb": "(x,y,z) mm -> (x,z,-y)/1000 m; standard CadQuery GLTF exporter",
                              "polycarbonate_not_acrylic": True,
                              "geometry_exporter": "cq.Assembly.save(exportType='GLTF'); JSON provenance extras and explicit root mm-to-m scale added afterwards",
                              "assembly_rating_verified": False}
    encoded = json.dumps(doc, separators=(",", ":"), allow_nan=False).encode()
    encoded += b" "*((-len(encoded)) % 4)
    chunks[0] = (b"JSON", encoded)
    body = b"".join(struct.pack("<I4s", len(blob), kind)+blob for kind, blob in chunks)
    # Only touches this run's newly created GLB, never an existing output package.
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, len(body)+12)+body)
    return doc


def export(model, output):
    checks = []
    relative_tolerance = model.interface["allocations"]["step_relative_volume_tolerance"]
    for part in model.parts:
        path = output / "step" / (part.name+".step")
        cq.Assembly(part.shape, name=part.name).save(str(path), exportType="STEP")
        checks.append(step_roundtrip(path, part.shape, relative_tolerance))
    path = output / "step" / "INTRFACE_PASSIVE_V3.step"
    model.native(include_empty=False).save(str(path), exportType="STEP")
    checks.append(step_roundtrip(path, model.compound(), relative_tolerance))
    keepout = cq.Assembly(name="EMPTY_RESERVES_NOT_HARDWARE")
    for part in model.empty:
        keepout.add(part.shape, name=part.name)
    keepout.save(str(output / "keepouts/EMPTY_RESERVES_NOT_HARDWARE.step"), exportType="STEP")
    checks.append(step_roundtrip(output / "keepouts/EMPTY_RESERVES_NOT_HARDWARE.step", cq.Compound.makeCompound([x.shape for x in model.empty]), relative_tolerance))
    checks.append(drawing(model.compound(), "INTRFACE_PASSIVE_V3", output / "drawings/INTRFACE_PASSIVE_V3.dxf", model.interface, "Physical assembly only; EMPTY reserves excluded from dimensions and mass."))
    for part in model.parts:
        if part.name in {"V3_AFT_CAP_5_M10_AL6061", "V3_AS1_NONMETAL_STANDOFF_BRACKET", "V3_LONGLINE_FIXED_JAW_SADDLE_LANYARD_LUG", "V3_DIVER_RELEASE_MOVING_JAW", "V3_TETHER_NONMETAL_STRAIN_RELIEF_CONCEPT", "V3_CAMERA_TRAY_PEEK_ALLOCATION"}:
            checks.append(drawing(part.shape, part.name, output / "drawings" / (part.name+".dxf"), model.interface, part.source))
    glb = output / "INTRFACE_PASSIVE_V3.glb"
    a = model.interface["allocations"]
    model.native(include_empty=True).save(str(glb), exportType="GLTF", tolerance=a["glb_linear_deflection_mm"], angularTolerance=a["glb_angular_deflection_rad"])
    document = annotate_glb(glb, model)
    names = {node.get("name") for node in document["nodes"]}
    checks.append(check_record("glb_named_hierarchy", {q.name for q in model.parts+model.empty}.issubset(names), nodes=len(document["nodes"]), exporter="cq.Assembly.save(GLTF)"))
    write_json(output / "hierarchy.json", {
        "schema": "intrface.passive-v3.hierarchy.v1", "company": "Intrface", "product": "Poseidon Trident", "reuse_rights": model.interface["reuse_rights"], "canonical_glb": "INTRFACE_PASSIVE_V3.glb", "glb_sha256": digest(glb),
        "root": "INTRFACE_PASSIVE_V3", "cad_units": "mm", "glb_units": "m", "coordinate_map": "CAD (x,y,z) -> glTF (x,z,-y)/1000",
        "physical_parts": [p.name for p in model.parts], "empty_nonphysical_parts": [p.name for p in model.empty],
        "nodes": [{"index": i, "name": n.get("name"), "children": n.get("children", []), "extras": n.get("extras", {})} for i, n in enumerate(document["nodes"])],
        "material_rule": "V3_DOME_POLYCARBONATE_BR107201 stays polycarbonate, not acrylic; unknown vendor interiors are not solid metal",
        "boundary": "No underwater preamp, no active projector; EMPTY nodes must never become physical parts or mass",
        "source_geometry_bboxes_mm": {p.name: bbox(p.shape) for p in model.parts+model.empty},
    })
    return checks
