"""Editable candidate using original fit proxies for bought parts.

Published dimensions and local allocations determine the envelopes. The proxy
shapes cannot establish a supplier's internal geometry or pressure rating.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import combinations
import math
import cadquery as cq
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from v3_contract import CANDIDATE, read_json, require, stack_budget
from v3_proxy import build as build_bought_proxies

COLORS = {
    "aluminium_6061": (0.13, 0.17, 0.20, 1),
    "aluminium_7075": (0.22, 0.25, 0.28, 1),
    "aluminium_alloy_unconfirmed": (0.13, 0.17, 0.20, 1),
    "stainless_316": (0.67, 0.72, 0.76, 1),
    "peek": (0.64, 0.56, 0.38, 1),
    "polycarbonate": (0.61, 0.82, 0.90, 0.30),
    "polyurethane": (0.09, 0.11, 0.13, 1),
    "camera_unknown_internals": (0.10, 0.27, 0.20, 1),
    "vendor_unknown_internals": (0.20, 0.24, 0.27, 1),
    "fathom_bulk_effective": (0.98, 0.62, 0.09, 1),
    "lanyard_polyester": (0.90, 0.27, 0.10, 1),
    "EMPTY": (0.96, 0.42, 0.10, 0.12),
}


def bbox(shape):
    # CadQuery BoundingBox() may use cached display triangulation and inflate its
    # gap after GLTF meshing. Always evaluate the analytic BRep, without a mesh
    # or shape-tolerance enlargement, so web export cannot change CAD dimensions.
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, bounds, False, False)
    values = bounds.Get()
    low, high = list(values[:3]), list(values[3:])
    return {"min_mm": low, "max_mm": high, "size_mm": [high[i]-low[i] for i in range(3)]}


def valid(shape):
    return bool(BRepCheck_Analyzer(shape.wrapped).IsValid())


def cylinder(radius, height, origin=(0, 0, 0), axis=(0, 0, 1)):
    return cq.Solid.makeCylinder(radius, height, cq.Vector(*origin), cq.Vector(*axis))


def box(size, center):
    return cq.Workplane("XY").box(*size).val().translate(center)


def ring(ro, ri, height, origin):
    return cylinder(ro, height, origin).cut(cylinder(ri, height, origin))


def union(*shapes):
    return shapes[0].fuse(*shapes[1:]).clean() if len(shapes) > 1 else shapes[0]


def cable(points, radius, arc):
    """A straight lead, tangent three-point quarter circle, then straight tail."""
    start, bend, end, final = points
    edges = []
    if math.dist(start, bend) > 1e-8:
        edges.append(cq.Edge.makeLine(cq.Vector(*start), cq.Vector(*bend)))
    mid = (bend[0], bend[1] + arc*(1-1/math.sqrt(2)), bend[2]-arc/math.sqrt(2))
    edges += [cq.Edge.makeThreePointArc(cq.Vector(*bend), cq.Vector(*mid), cq.Vector(*end)), cq.Edge.makeLine(cq.Vector(*end), cq.Vector(*final))]
    wire = cq.Wire.assembleEdges(edges)
    plane = cq.Plane(origin=start, normal=(0, 0, -1), xDir=(1, 0, 0))
    shape = cq.Workplane(plane).circle(radius).sweep(cq.Workplane("XY").newObject([wire]), transition="round").val()
    return shape, wire


@dataclass
class Part:
    name: str
    shape: cq.Shape
    material: str
    group: str
    source: str
    physical: bool = True
    source_model: str | None = None
    density: float | None = None
    source_mass: float | None = None
    mass_note: str = ""
    wetted: bool = True
    transforms: list = field(default_factory=list)
    features: dict = field(default_factory=dict)

    def mass(self):
        return self.source_mass if self.source_mass is not None else (self.shape.Volume()*self.density/1e9 if self.density is not None else None)

    def metadata(self):
        return {"name": self.name, "group": self.group, "physical": self.physical, "material": self.material,
                "source": self.source, "source_model": self.source_model, "transforms": self.transforms,
                "bbox": bbox(self.shape), "volume_mm3": self.shape.Volume(), "solid_count": len(self.shape.Solids()),
                "density_assumption_kg_m3": self.density, "source_mass_kg": self.source_mass, "modeled_mass_kg": self.mass(),
                "mass_note": self.mass_note, "wetted": self.wetted, "features": self.features,
                "pressure_or_load_qualified": False, "printable": False}


@dataclass
class Model:
    parts: list
    empty: list
    source_shapes: dict
    routes: dict
    interface: dict
    source_register: dict

    def compound(self):
        return cq.Compound.makeCompound([p.shape for p in self.parts])

    def native(self, include_empty=True):
        root = cq.Assembly(name="INTRFACE_PASSIVE_V3")
        for group in ("PRESSURE_BOUNDARY", "CAMERA_AND_INTERNAL_MOUNT", "PASSIVE_RECEIVE", "FARM_CLAMP", "SURFACE_ROUTE_CONCEPT", "EMPTY_RESERVES_NOT_HARDWARE"):
            members = [p for p in self.parts + (self.empty if include_empty else []) if p.group == group]
            if not members:
                continue
            node = cq.Assembly(name=group)
            for p in members:
                node.add(p.shape, name=p.name, color=cq.Color(*COLORS[p.material]))
            root.add(node)
        return root


def build(p, candidate=CANDIDATE):
    a, d = p["allocations"], p["dimensions"]
    density = a["mass_density_kg_m3"]
    register = read_json(candidate / "sources/source-register.json")
    source_shapes = build_bought_proxies(d, register)
    parts, empty, routes = [], [], {}
    L = d["tube.length"]
    flange_insert = d["flange.piston_length"]
    flange_face = d["flange.length"] - flange_insert
    front_face = L + flange_face
    tube_clear = d["tube.od"]/2 + a["mount_tube_radial_gap_mm"]

    def sourced(name, key, group, material, rotations=(), translation=(0, 0, 0), known_mass=None, note="", wetted=True, geometric_density=True):
        shape = source_shapes[key]
        transforms = []
        for axis, angle in rotations:
            shape = shape.rotate((0, 0, 0), axis, angle)
            transforms.append({"rotate_axis": list(axis), "degrees": angle})
        shape = shape.translate(translation)
        transforms.append({"translate_mm": list(translation)})
        part = Part(name, shape, material, group, "cad/v3_proxy.py:" + key, source_model=key,
                    density=density.get(material) if geometric_density else None, source_mass=known_mass, mass_note=note,
                    wetted=wetted, transforms=transforms)
        parts.append(part)
        part.features["vendor_part_number"] = register["vendor_models"][key]["part_number"]
        return part

    def custom(name, shape, group="FARM_CLAMP", material="peek", features=None, wetted=True, known_mass=None):
        part = Part(name, shape, material, group, "sources/design-inputs.json: allocations; all dimensions hash traced",
                    density=density.get(material), source_mass=known_mass, mass_note="Geometric solid with explicit nominal density assumption; not measured mass", wetted=wetted, features=features or {})
        parts.append(part)
        return part

    sourced("V3_TUBE_AL6061_BR106279_300", "tube", "PRESSURE_BOUNDARY", "aluminium_6061", [((0, 1, 0), 90)], note="Original enclosure tube fit proxy; compare catalog nominal 1.066 kg, not as-built mass.")
    sourced("V3_FLANGE_AFT_SOURCE_ID_CONFLICT", "flange", "PRESSURE_BOUNDARY", "aluminium_6061", [((1, 0, 0), 180)], (0, 0, flange_insert), note="Flange supplier identity conflicts with archive filename; proxy models the envelope and fit bore.")
    sourced("V3_FLANGE_FORWARD_SOURCE_ID_CONFLICT", "flange", "PRESSURE_BOUNDARY", "aluminium_6061", translation=(0, 0, L-flange_insert), note="Same unresolved supplier identity as aft flange; original fit proxy.")
    cap = sourced("V3_AFT_CAP_5_M10_AL6061", "aft_cap", "PRESSURE_BOUNDARY", "aluminium_6061", [((1, 0, 0), 180)], (0, 0, -flange_face), note="Five traced penetrator bore positions; four remain OPEN. Original fit proxy, not a sealed boundary.")
    cap.features["penetrator_centers_source_xy_mm"] = register["vendor_models"]["aft_cap"]["penetrator_centers_xy_mm"]
    sourced("V3_DOME_POLYCARBONATE_BR107201", "dome", "PRESSURE_BOUNDARY", "polycarbonate", [((1, 0, 0), 90)], (0, 0, front_face), note="Hollow polycarbonate optical fit proxy; spherical surface allocation, not supplier design.")
    retaining_ring = sourced("V3_DOME_RETAINING_RING_ALUMINIUM", "dome_ring", "PRESSURE_BOUNDARY", "aluminium_alloy_unconfirmed", [((1, 0, 0), 90)], (0, 0, front_face), note="Original retaining-ring fit proxy; supplier alloy unconfirmed.", geometric_density=False)
    retaining_ring.density = density["aluminium_6061"]
    hole = next(xy for xy in cap.features["penetrator_centers_source_xy_mm"] if abs(xy[0]) < 1e-6)
    port = (hole[0], -hole[1])
    wetlink = sourced("V3_WETLINK_M10_7P5_SOURCE_REVISION_CONFLICT", "wetlink", "PRESSURE_BOUNDARY", "vendor_unknown_internals", [((1, 0, 0), -90)], (port[0], port[1], a["penetrator_origin_z_mm"]), note="Source revision measures 16 mm OD, current PDF states 18 mm. Original fit proxy; seal and compression unresolved.", geometric_density=False)
    wetlink.features["current_candidate"] = "BR-100875-175 HC tested Fathom row; not verified exact CAD revision"

    board_z = L-a["camera_board_from_front_mm"]
    sourced("V3_CAMERA_BR_LOW_LIGHT_USB_VENDOR_INTERNALS", "camera", "CAMERA_AND_INTERNAL_MOUNT", "camera_unknown_internals", [((1, 0, 0), 90)], (-d["camera.pcb_width"]/2, -d["camera.pcb_height"]/2, board_z), note="Original camera PCB and optical envelope; internals and mass unknown.", wetted=False, geometric_density=False)
    tray_z = board_z-a["camera_mount_depth_mm"]
    tray = box([a["camera_tray_width_mm"], a["camera_tray_width_mm"], a["camera_tray_thickness_mm"]], (0, 0, tray_z+a["camera_tray_thickness_mm"]/2))
    tray = tray.cut(box([a["camera_tray_opening_mm"], a["camera_tray_opening_mm"], a["camera_tray_thickness_mm"]], (0, 0, tray_z+a["camera_tray_thickness_mm"]/2)))
    custom("V3_CAMERA_TRAY_PEEK_ALLOCATION", tray, "CAMERA_AND_INTERNAL_MOUNT", wetted=False)
    for ix, x in enumerate((-d["camera.mount_pitch"]/2, d["camera.mount_pitch"]/2)):
        for iy, y in enumerate((-d["camera.mount_pitch"]/2, d["camera.mount_pitch"]/2)):
            support = ring(a["camera_support_od_mm"]/2, a["camera_support_hole_mm"]/2, a["camera_mount_depth_mm"]-a["camera_tray_thickness_mm"], (x, y, tray_z+a["camera_tray_thickness_mm"]))
            custom(f"V3_CAMERA_STANDOFF_{ix}{iy}_PEEK", support, "CAMERA_AND_INTERNAL_MOUNT", wetted=False)

    hx = a["hydrophone_center_x_mm"]
    hydro_front = L-a["hydrophone_front_from_tube_front_mm"]
    hydro_rear = hydro_front-d["as1.length"]
    hp = Part("V3_AS1_RECEIVE_ONLY_SOURCE_ENVELOPE", cylinder(d["as1.diameter"]/2, d["as1.length"], (hx, 0, hydro_rear)), "polyurethane", "PASSIVE_RECEIVE", "sources/dimension-traces.json:as1.diameter,as1.length", source_mass=d["as1.mass"], mass_note="8 g distributor mass without cable. Outer encapsulated envelope is NOT solid-metal mass.", features={"source_envelope_mm": [d["as1.diameter"], d["as1.diameter"], d["as1.length"]], "transmit_connected": False})
    parts.append(hp)
    collar_z = hydro_rear+a["hydrophone_collar_from_rear_mm"]
    saddle = ring(a["saddle_outer_radius_mm"], tube_clear, a["saddle_width_mm"], (0, 0, collar_z))
    collar = ring(a["hydrophone_collar_outer_radius_mm"], d["as1.diameter"]/2+a["hydrophone_collar_radial_gap_mm"], a["saddle_width_mm"], (hx, 0, collar_z))
    arm_start = a["saddle_outer_radius_mm"]-a["hydrophone_arm_overlap_mm"]
    arm_end = hx-a["hydrophone_collar_outer_radius_mm"]+a["hydrophone_arm_overlap_mm"]
    arm = box([arm_end-arm_start, a["hydrophone_arm_width_mm"], a["saddle_width_mm"]], ((arm_start+arm_end)/2, 0, collar_z+a["saddle_width_mm"]/2))
    custom("V3_AS1_NONMETAL_STANDOFF_BRACKET", union(saddle, collar, arm), "PASSIVE_RECEIVE", features={"stand_off_skin_to_sensor_mm": hx-d["as1.diameter"]/2-d["tube.od"]/2, "fit_and_acoustic_self_noise": "unperformed"})

    cx, cy, cz = a["clamp_center_mm"]
    sx, sy, sz = a["clamp_size_mm"]
    gap = a["clamp_split_gap_mm"]
    half_h = (sz-gap)/2
    lower = box([sx, sy, half_h], (cx, cy, cz-gap/2-half_h/2))
    upper = box([sx, sy, half_h], (cx, cy, cz+gap/2+half_h/2))
    line_hole = cylinder(a["longline_hole_radius_mm"], sy, (cx, cy-sy/2, cz), (0, 1, 0))
    lower, upper = lower.cut(line_hole), upper.cut(line_hole)
    band = ring(a["saddle_outer_radius_mm"], tube_clear, a["saddle_width_mm"], (0, 0, cz-a["saddle_width_mm"]/2))
    bridge = box(a["clamp_bridge_size_mm"], (a["clamp_bridge_center_x_mm"], 0, cz-a["saddle_width_mm"]/2))
    lx, ly, lz = a["lanyard_lug_center_mm"]
    lug = ring(a["lanyard_lug_outer_radius_mm"], a["lanyard_lug_inner_radius_mm"], a["lanyard_lug_thickness_mm"], (lx, ly, lz))
    fixed = union(lower, band, bridge, lug, box(a["lanyard_lug_bridge_size_mm"], a["lanyard_lug_bridge_center_mm"]))
    fixed = fixed.cut(cylinder(tube_clear, L, (0, 0, 0)))
    for x in a["pin_centers_x_mm"]:
        tool = cylinder(a["pin_sleeve_outer_radius_mm"], sz, (x, cy, cz-sz/2))
        fixed, upper = fixed.cut(tool), upper.cut(tool)
    custom("V3_LONGLINE_FIXED_JAW_SADDLE_LANYARD_LUG", fixed, features={"farm_rope_diameter_unknown": True, "allocated_opening_diameter_mm": 2*a["longline_hole_radius_mm"]})
    custom("V3_DIVER_RELEASE_MOVING_JAW", upper, features={"release": "Withdraw two concept pull pins, lift jaw; detent/captive-pin retention unqualified"})
    for i, x in enumerate(a["pin_centers_x_mm"]):
        sleeve = ring(a["pin_sleeve_outer_radius_mm"], a["pin_sleeve_inner_radius_mm"], sz, (x, cy, cz-sz/2))
        custom(f"V3_PIN_{i+1}_PEEK_ISOLATION_SLEEVE", sleeve)
        bottom = cz-sz/2
        pin = cylinder(a["pin_radius_mm"], a["pin_length_mm"], (x, cy, bottom))
        head = cylinder(a["pin_head_radius_mm"], a["pin_head_height_mm"], (x, cy, bottom+a["pin_length_mm"]))
        pull = cq.Solid.makeTorus(a["pin_pull_ring_major_radius_mm"], a["pin_pull_ring_minor_radius_mm"], cq.Vector(x, cy, bottom+a["pin_length_mm"]+a["pin_head_height_mm"]+a["pin_pull_ring_major_radius_mm"]-a["pin_head_height_mm"]), cq.Vector(0, 1, 0))
        custom(f"V3_DIVER_PULL_PIN_{i+1}_ISOLATED_316", union(pin, head, pull), material="stainless_316", features={"nominal_shank_diameter_mm": 2*a["pin_radius_mm"], "threads_and_detent": None, "isolation": "PEEK sleeve and PEEK clamp; no conductive aluminium contact modeled"})
    lanyard_z = lz+a["lanyard_lug_thickness_mm"]+a["lanyard_visual_gap_mm"]+a["lanyard_diameter_mm"]/2
    custom("V3_LANYARD_ROUTE_CONCEPT_UNTERMINATED", cylinder(a["lanyard_diameter_mm"]/2, a["lanyard_length_mm"], (lx, ly, lanyard_z), (0, 1, 0)), material="lanyard_polyester", features={"end_termination": None, "load_rating": None})

    r = a["tether_bend_radius_mm"]
    z = a["tether_route_start_z_mm"]
    points = [(port[0], port[1], z), (port[0], port[1], z), (port[0], port[1]+r, z-r), (port[0], a["tether_surface_endpoint_y_mm"], z-r)]
    tether_shape, wire = cable(points, d["tether.diameter"]/2, r)
    custom("V3_FATHOM_TETHER_SURFACE_ROUTE_CONCEPT", tether_shape, "SURFACE_ROUTE_CONCEPT", "fathom_bulk_effective", features={"path_length_mm": wire.Length(), "bend_radius_mm": r, "jacket_diameter_mm": d["tether.diameter"], "full_30m_route_modeled": False, "communications_verified": False})
    routes["tether"] = {"wire": wire, "diameter_mm": d["tether.diameter"], "radius_mm": r, "part": parts[-1].name}
    clearance, _ = cable(points, d["tether.diameter"]/2+a["strain_relief_radial_gap_mm"], r)
    relief = union(box(a["strain_relief_size_mm"], a["strain_relief_center_mm"]), box(a["strain_relief_support_size_mm"], a["strain_relief_support_center_mm"]), box(a["strain_relief_riser_size_mm"], a["strain_relief_riser_center_mm"]), ring(a["saddle_outer_radius_mm"], tube_clear, a["saddle_width_mm"], (0, 0, a["strain_relief_saddle_z_mm"])))
    cap_min = bbox(cap.shape)["min_mm"][2]
    relief = relief.cut(clearance).cut(cylinder(tube_clear, L, (0, 0, 0)))
    # The aft flange and cap are wider than the tube: clear their source-sized
    # rim as well, rather than accepting an 'intended' pressure-part collision.
    relief = relief.cut(cylinder(d["flange.od"]/2+a["mount_tube_radial_gap_mm"], -cap_min, (0, 0, cap_min)))
    custom("V3_TETHER_NONMETAL_STRAIN_RELIEF_CONCEPT", relief, "SURFACE_ROUTE_CONCEPT", features={"pull_limit_N": None, "termination": "No verified cable load transfer or fastener sizing"})
    r = a["analog_bend_radius_mm"]
    bz = a["analog_bend_start_z_mm"]
    analog_shape, wire = cable([(hx, 0, hydro_rear), (hx, 0, bz), (hx, r, bz-r), (hx, a["analog_surface_endpoint_y_mm"], bz-r)], d["as1.cable_diameter"]/2, r)
    custom("V3_AS1_ANALOG_CABLE_DRY_HUB_ROUTE_CONCEPT", analog_shape, "PASSIVE_RECEIVE", "polyurethane", known_mass=wire.Length()/1000*d["as1.cable_mass_per_m"], features={"path_length_mm": wire.Length(), "jacket_diameter_mm": d["as1.cable_diameter"], "bend_radius_mm": r, "standard_cable_m": 9, "30m_analog_front_end": "UNRESOLVED, preamp remains dry"})
    parts[-1].density = None
    parts[-1].mass_note = "28 g/m distributor linear cable mass for this modeled stub only; no full 30 m cable mass invented"
    routes["analog"] = {"wire": wire, "diameter_mm": d["as1.cable_diameter"], "radius_mm": r, "part": parts[-1].name}

    for name, size, center in [
        ("EMPTY_PREAMP_RESERVE_NONPOPULATED_DRY_PREAMP_ONLY", a["empty_preamp_reserve_size_mm"], (0, 0, a["empty_preamp_reserve_z_mm"])),
        ("EMPTY_CAMERA_CABLE_SERVICE_ALLOCATION", a["camera_service_envelope_size_mm"], a["camera_service_envelope_center_mm"]),
        ("EMPTY_FUTURE_PROJECTOR_MOUNT_ENVELOPE", a["future_projector_envelope_size_mm"], a["future_projector_envelope_center_mm"]),
    ]:
        empty.append(Part(name, box(size, center), "EMPTY", "EMPTY_RESERVES_NOT_HARDWARE", "sources/design-inputs.json", physical=False, wetted=False, mass_note="EMPTY, not hardware; excluded from physical mass, displacement and interference", features={"populated": False}))
    return Model(parts, empty, source_shapes, routes, p, register)


def check_record(name, passed, **details):
    return {"id": name, "passed": bool(passed), **details}


def geometry_checks(model):
    p = model.interface
    tol = p["allocations"]["geometry_linear_tolerance_mm"]
    vt = p["allocations"]["interference_volume_tolerance_mm3"]
    checks = []
    for part in model.parts + model.empty:
        checks.append(check_record("brep:"+part.name, valid(part.shape) and part.shape.Volume() > 0 and all(valid(s) for s in part.shape.Solids()), evidence="OCP BRepCheck_Analyzer; EMPTY validity is not physical membership", solids=len(part.shape.Solids())))
    # Check every positioned physical pair; proxy clearances are not supplier
    # pressure, seal, or internal-fit qualifications.
    for left, right in combinations(model.parts, 2):
        intersection = left.shape.intersect(right.shape)
        overlap = sum(abs(s.Volume()) for s in intersection.Solids())
        checks.append(check_record("interference:"+left.name+":"+right.name, overlap <= vt, overlap_mm3=overlap, tolerance_mm3=vt, evidence="Fresh OCP Boolean common of positioned part pair"))
    for key, raw in model.source_shapes.items():
        b = bbox(raw)
        expected = model.source_register["vendor_models"][key]
        measured = expected["bbox_size_mm"]
        delta = max(abs(b["size_mm"][i]-measured[i]) for i in range(3))
        checks.append(check_record("source_bbox:"+key, valid(raw) and delta <= expected["proxy_envelope_tolerance_mm"], max_delta_mm=delta, source_file=expected["file"], evidence="Fresh parametric proxy versus recorded purchased-part envelope"))
    for part in model.parts:
        if part.source_model:
            raw = model.source_shapes[part.source_model]
            for transform in part.transforms:
                raw = raw.rotate((0, 0, 0), transform["rotate_axis"], transform["degrees"]) if "rotate_axis" in transform else raw.translate(transform["translate_mm"])
            delta = max(abs(bbox(raw)[k][i]-bbox(part.shape)[k][i]) for k in ("min_mm", "max_mm") for i in range(3))
            checks.append(check_record("placed_source_bbox:"+part.name, delta <= tol and abs(raw.Volume()-part.shape.Volume()) <= vt, max_delta_mm=delta))
    # Independently evaluate published dimensions from actual analytic surfaces,
    # not just the stored CAD bounding-box records.
    for trace, key, diameter in [
        ("tube.od", "tube", p["dimensions"]["tube.od"]),
        ("tube.id", "tube", p["dimensions"]["tube.id"]),
        ("flange.od", "flange", p["dimensions"]["flange.od"]),
        ("flange.piston_diameter", "flange", p["dimensions"]["flange.piston_diameter"]),
        ("aft_cap.penetrator_hole_diameter", "aft_cap", p["dimensions"]["aft_cap.penetrator_hole_diameter"]),
    ]:
        diameters = [2*f._geomAdaptor().Cylinder().Radius() for f in model.source_shapes[key].Faces() if f.geomType() == "CYLINDER"]
        error = min(abs(value-diameter) for value in diameters)
        checks.append(check_record("traced_surface_dimension:"+trace, error <= tol, source_trace=trace, target_mm=diameter, minimum_surface_delta_mm=error))
    radii = sorted({round(f._geomAdaptor().Sphere().Radius(), 6) for f in model.source_shapes["dome"].Faces() if f.geomType() == "SPHERE"})
    checks.append(check_record("traced_surface_dimension:dome.internal_radius", abs(radii[0]-p["dimensions"]["dome.internal_radius"]) <= tol, actual_mm=radii[0]))
    wall = radii[-1]-radii[0]
    checks.append(check_record("traced_surface_dimension:dome.wall", abs(wall-p["dimensions"]["dome.wall"]) <= p["dimensions"]["dome.wall_tolerance"], actual_mm=wall, published_nominal_mm=p["dimensions"]["dome.wall"], published_tolerance_mm=p["dimensions"]["dome.wall_tolerance"]))
    camera_size = bbox(model.source_shapes["camera"])["size_mm"]
    checks.append(check_record("traced_surface_dimension:camera_envelope", all(abs(v-e) <= tol for v, e in zip(camera_size, [p["dimensions"]["camera.pcb_width"], p["dimensions"]["camera.front_depth"]+p["dimensions"]["camera.rear_depth"], p["dimensions"]["camera.pcb_height"]])), actual_mm=camera_size))
    by_name = {x.name: x for x in model.parts}
    checks.append(check_record("source_as1_outer_dimensions", max(abs(v-e) for v, e in zip(bbox(by_name["V3_AS1_RECEIVE_ONLY_SOURCE_ENVELOPE"].shape)["size_mm"], [p["dimensions"]["as1.diameter"]]*2+[p["dimensions"]["as1.length"]])) <= tol))
    for key, route in model.routes.items():
        arcs = [e for e in route["wire"].Edges() if e.geomType() == "CIRCLE"]
        radii = [e.radius() for e in arcs]
        checks.append(check_record("route_arc:"+key, len(radii) == 1 and abs(radii[0]-route["radius_mm"]) <= tol, actual_radii_mm=radii, centerline_length_mm=route["wire"].Length(), note="Geometric bend only, not vendor cable acceptance"))
    # Empty internal allocations must fit and remain empty. They are not tested as
    # physical pairs; separate spatial occupancy checks catch a camera moved into one.
    for reserve in model.empty[:2]:
        intrusions = [part.name for part in model.parts if sum(abs(s.Volume()) for s in reserve.shape.intersect(part.shape).Solids()) > vt]
        checks.append(check_record("empty_reserve_clear:"+reserve.name, not intrusions, intrusions=intrusions))
    pins = [part for part in model.parts if part.material == "stainless_316"]
    metals = [part for part in model.parts if part.material.startswith("aluminium")]
    for pin in pins:
        gap = min(pin.shape.distance(m.shape) for m in metals)
        checks.append(check_record("316_aluminium_separation:"+pin.name, gap > tol, minimum_gap_mm=gap, note="Geometric noncontact only; corrosion and wet isolation untested"))
    checks.append(check_record("internal_stack_budget", stack_budget(p)["margin_mm"] >= 0, **stack_budget(p)))
    return checks


def mass_displacement(model):
    p, d = model.interface, model.interface["dimensions"]
    a = p["allocations"]
    # Closed exterior comparison, conditional on a future complete sealed boundary.
    # Tube/flange/cap cylinders approximate the exterior; dome proxy is hollow
    # with an independently filled internal sphere for conditional displacement.
    L, lip = d["tube.length"], d["flange.length"]-d["flange.piston_length"]
    cap = next(q.shape for q in model.parts if q.name == "V3_AFT_CAP_5_M10_AL6061")
    cap_min = bbox(cap)["min_mm"][2]
    tube_outer = cylinder(d["tube.od"]/2, L)
    aft_outer = cylinder(d["flange.od"]/2, -cap_min, (0, 0, cap_min))
    fore_outer = cylinder(d["flange.od"]/2, lip, (0, 0, L))
    dome = next(q.shape for q in model.parts if q.name == "V3_DOME_POLYCARBONATE_BR107201")
    dome_ring = next(q.shape for q in model.parts if q.name == "V3_DOME_RETAINING_RING_ALUMINIUM")
    # The internal proxy sphere defines the conditional hollow envelope.
    spheres = [f._geomAdaptor().Sphere() for f in dome.Faces() if f.geomType() == "SPHERE"]
    inner = min(spheres, key=lambda s: s.Radius())
    center = inner.Location()
    inner_fill = cq.Solid.makeSphere(inner.Radius(), cq.Vector(center.X(), center.Y(), center.Z()), angleDegrees1=0, angleDegrees2=90)
    base_fill = cylinder(inner.Radius(), center.Z()-(L+lip), (0, 0, L+lip))
    dome_closed = union(dome, dome_ring, inner_fill, base_fill)
    # Nominal cap cylinder omits the two small lifting ears. Do not Boolean-union
    # an overlapping imported cap into that proxy: coincident source faces can
    # produce a valid-looking but volume-losing Boolean result in OCCT.
    exterior = union(tube_outer, aft_outer, fore_outer, dome_closed)
    exterior_volume = exterior.Volume()
    require(valid(exterior) and len(exterior.Solids()) == 1 and exterior_volume > tube_outer.Volume()+aft_outer.Volume(), "Conditional displacement exterior lost volume or is not closed")
    pressure_names = {q.name for q in model.parts if q.group == "PRESSURE_BOUNDARY" and "WETLINK" not in q.name}
    contributions = []
    for part in model.parts:
        external = part.shape.cut(exterior).Volume() if part.wetted and part.name not in pressure_names else 0.0
        contributions.append({"name": part.name, "geometric_volume_mm3": part.shape.Volume(), "modeled_mass_kg": part.mass(), "mass_basis": "source_mass" if part.source_mass is not None else "geometric_density_assumption" if part.density is not None else "unknown_omitted_not_solid_metal", "density_assumption_kg_m3": part.density, "flooded_external_solid_displacement_mm3": max(0, external), "internal_or_pressure_shell_no_double_count": external <= 0, "note": part.mass_note})
    mass = sum(x["modeled_mass_kg"] for x in contributions if x["modeled_mass_kg"] is not None)
    extra = sum(x["flooded_external_solid_displacement_mm3"] for x in contributions)
    displaced = (exterior_volume+extra)/1e9
    buoyant_mass = displaced*a["mass_density_kg_m3"]["seawater"]
    delta = buoyant_mass-mass
    return {"density_assumptions_kg_m3": a["mass_density_kg_m3"], "per_part": contributions, "known_or_assumed_mass_subtotal_kg": mass,
            "actual_complete_dry_mass_kg": None, "unknown_mass_parts": [x["name"] for x in contributions if x["modeled_mass_kg"] is None],
            "other_omitted_mass": p["pressure_boundary"]["missing_items"]+["Full length 30 m transport, surface hub and farm rope, fouling and water ingress"],
            "pressure_shell_material_volume_mm3": sum(q.shape.Volume() for q in model.parts if q.name in pressure_names),
            "conditional_sealed_external_envelope_volume_mm3": exterior_volume, "flooded_external_mount_and_stub_solid_volume_mm3": extra,
            "conditional_total_displacement_m3": displaced, "seawater_mass_displaced_kg": buoyant_mass, "modeled_upward_mass_difference_kg": delta,
            "modeled_buoyancy_sign": "positive" if delta > 0 else "negative" if delta < 0 else "neutral",
            "sign_basis": "Conditional closed nominal exterior minus modeled mass subtotal only; incomplete real mass and open boundary prevent an actual unit buoyancy conclusion",
            "actual_unit_buoyancy_sign": None, "sealed_boundary_present": False,
            "displacement_method": "OCP union of source-sized tube/flange/nominal cap cylinders with original hollow dome fit proxy and inner-sphere fill. Cap lifting ears omitted; chamfers/slots approximated. This conditional envelope is checked for BRep validity, one solid and volume retention. Flooded mounts contribute only their solids outside it, never bounding boxes. Internal camera/tray and EMPTY reserves add no sealed displacement.",
            "source_mass_comparisons_kg": {"tube": d["tube.mass"], "each_flange_identity_unresolved": d["flange.mass"], "aft_cap": d["aft_cap.mass"], "dome_and_ring_combined": d["dome_and_ring.mass"]},
            "physical_measurements_performed": 0}
