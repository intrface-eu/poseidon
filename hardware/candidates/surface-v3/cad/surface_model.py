"""Editable CadQuery solids. No frozen-model imports, active hardware or fin detail."""
from __future__ import annotations
from dataclasses import dataclass, field
import math
import cadquery as cq
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from surface_contract import values, layout, mechanics, require


def box(size):
    return cq.Workplane("XY").box(*size, centered=(True, True, False)).val()


def cylinder(radius, length, xyz=(0, 0, 0), axis=(0, 0, 1)):
    return cq.Solid.makeCylinder(radius, length, cq.Vector(*xyz), cq.Vector(*axis))


def ring(outer, inner, length):
    return cylinder(outer/2, length).cut(cylinder(inner/2, length)).clean()


def bbox(s):
    # Analytic bounds, independent of cached display triangulation and OCCT platform.
    bounds = Bnd_Box()
    BRepBndLib.AddOptimal_s(s.wrapped, bounds, False, False)
    lo = list(bounds.Get()[:3])
    hi = list(bounds.Get()[3:])
    return {"min_mm": lo, "max_mm": hi,
            "size_mm": [hi[i] - lo[i] for i in range(3)]}


def valid(s):
    return (bool(s.Solids()) and s.Volume() > 0 and BRepCheck_Analyzer(s.wrapped).IsValid()
            and all(shell.Closed() for solid in s.Solids() for shell in solid.Shells()))


def matrix_y(degrees, translation):
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s, translation[0]], [0, 1, 0, translation[1]],
            [-s, 0, c, translation[2]], [0, 0, 0, 1]]


@dataclass
class Part:
    name: str
    source_shape: cq.Shape
    shape: cq.Shape
    group: str
    variant: str
    kind: str
    material: str
    translation_mm: list
    rotation_y_deg: float
    parameter_keys: list
    note: str
    features: dict = field(default_factory=dict)

    @property
    def physical(self):
        return self.kind != "allocation"

    def metadata(self, surface_z):
        translation = list(self.translation_mm)
        if self.variant == "common":
            translation[2] += surface_z
        source_bounds, installed_bounds = bbox(self.source_shape), bbox(self.shape)
        volume = self.shape.Volume()
        if self.name == "SV3_MAST_SOCKET":
            # The fused, cross-drilled ring acquires OCCT-dependent sub-micron
            # bounds and sub-mm³ boolean volume noise. Preserve its engineered
            # dimensions to 1e-6 mm and mass volume to 1 mm³ in both archives.
            # Raw solids still undergo STEP, BRep, interference and fit checks.
            for bounds in (source_bounds, installed_bounds):
                bounds["min_mm"] = [round(x, 6) for x in bounds["min_mm"]]
                bounds["max_mm"] = [round(x, 6) for x in bounds["max_mm"]]
                bounds["size_mm"] = [hi-lo for lo, hi in zip(bounds["min_mm"], bounds["max_mm"])]
            volume = round(volume)
        return {"name": self.name, "group": self.group, "variant": self.variant, "kind": self.kind,
                "physical": self.physical, "material": self.material, "note": self.note,
                "volume_mm3": volume, "source_bbox_mm": source_bounds,
                "bbox": installed_bounds, "source_to_cad_matrix_mm": matrix_y(self.rotation_y_deg, translation),
                "source_to_group_matrix_mm": matrix_y(self.rotation_y_deg, self.translation_mm),
                "parameter_keys": self.parameter_keys, "features": self.features,
                "step": ("step/" if self.physical else "allocations/")+self.name+".step"}


@dataclass
class Model:
    interface: dict
    parts: list = field(default_factory=list)
    float_surface_z: float = 0

    def get(self, name):
        return next(p for p in self.parts if p.name == name)

    def add(self, name, source, group, keys, translation=(0, 0, 0), rotation=0,
            kind="physical_custom", material="aluminum", variant="common", note="Custom candidate; joints and physical suitability unqualified.", features=None):
        require(name not in {p.name for p in self.parts}, "Duplicate part name")
        s = source.rotate((0, 0, 0), (0, 1, 0), rotation).translate(translation)
        if variant == "common":
            s = s.translate((0, 0, values(self.interface)["freeboard_mm"]))
        self.parts.append(Part(name, source, s, group, variant, kind, material, list(translation), rotation, keys, note, features or {}))
        return self.parts[-1]

    def metadata(self):
        return [p.metadata(values(self.interface)["freeboard_mm"]) for p in self.parts]

    def installed(self, variant, include_allocations=True):
        shift = self.float_surface_z-values(self.interface)["freeboard_mm"]
        return [(p, p.shape.translate((0, 0, shift)) if variant == "float" and p.variant == "common" else p.shape)
                for p in self.parts if p.variant in ("common", variant) and (include_allocations or p.physical)]

    def compound(self, variant):
        return cq.Compound.makeCompound([s for _, s in self.installed(variant, False)])

    def native(self):
        # Common parts stay in tray-local coordinates under surface's placement.
        root = cq.Assembly(name="SURFACE_V3")
        surface = cq.Assembly(name="surface", loc=cq.Location(cq.Vector(0, 0, values(self.interface)["freeboard_mm"])))
        groups = {name: cq.Assembly(name=name) for name in ("tray", "hub", "panelA", "panelB", "mastSocket", "mountPole", "mountFloat")}
        colors = {"aluminum": (0.35, 0.42, 0.44, 1), "steel": (0.4, 0.44, 0.46, 1),
                  "foam": (0.20, 0.27, 0.24, 1), "panel": (0.025, 0.085, 0.14, 1),
                  "hub": (0.18, 0.22, 0.23, 1), "allocation": (0.35, 0.66, 0.7, 0.18)}
        for p in self.parts:
            shape = p.shape.translate((0, 0, -values(self.interface)["freeboard_mm"])) if p.variant == "common" else p.shape
            groups[p.group].add(shape, name=p.name, color=cq.Color(*colors[p.material]))
        for name in ("tray", "hub", "panelA", "panelB", "mastSocket"):
            surface.add(groups[name])
        root.add(surface)
        root.add(groups["mountPole"])
        root.add(groups["mountFloat"])
        return root


def build(p):
    v, d = values(p), layout(p)
    m = Model(p)
    panel_x, panel_y, panel_z = v["panel_xyz_mm"]
    tray = box([*v["tray_xy_mm"], v["tray_thickness_mm"]]).cut(cylinder(v["socket_id_mm"]/2, v["tray_thickness_mm"]))
    for y in d["panel_centres_y_mm"]:
        tray = tray.cut(cylinder(v["cable_hole_diameter_mm"]/2, v["tray_thickness_mm"], (v["cable_x_mm"], y, 0)))
    m.add("SV3_TRAY_PLATE", tray.clean(), "tray", ["tray_xy_mm", "tray_thickness_mm", "socket_id_mm", "cable_hole_diameter_mm", "cable_x_mm", "panel_xyz_mm", "panel_gap_mm"],
          note="Open central bore and two cable-clearance holes. Not a weather seal or released structural plate.")
    skirt_x, skirt_y = v["skirt_xy_mm"]
    skirt = box([skirt_x, skirt_y, v["skirt_depth_mm"]]).cut(box([skirt_x-2*v["skirt_wall_mm"], skirt_y-2*v["skirt_wall_mm"], v["skirt_depth_mm"]])).clean()
    m.add("SV3_OPEN_BOTTOM_SKIRT", skirt, "tray", ["skirt_xy_mm", "skirt_wall_mm", "skirt_depth_mm"], (0, 0, -v["skirt_depth_mm"]),
          note="Open-bottom skirt, no displaced sealed-air volume credited. Ventilation and splash ingress unresolved.")
    for label, y, group in zip(("A", "B"), d["panel_centres_y_mm"], ("panelA", "panelB")):
        m.add("SV3_PANEL_"+label, box(v["panel_xyz_mm"]), group,
              ["panel_xyz_mm", "panel_gap_mm", "panel_tilt_deg", "panel_low_clearance_mm", "tray_thickness_mm"],
              (0, y, d["panel_origin_z_mm"]), -v["panel_tilt_deg"], kind="purchased_envelope", material="panel",
              note="Victron SPM040401200 purchased envelope. 3.1 kg vendor nominal, not density-derived. Frame, cells, clamp zones and terminal positions unknown.",
              features={"mpn": "SPM040401200", "source_id": "panel-datasheet", "source_dimensions_mm": v["panel_xyz_mm"], "drainage_tilt_deg": v["panel_tilt_deg"]})
        length = v["wedge_length_mm"]
        bottom = v["tray_thickness_mm"]
        zlo = d["panel_origin_z_mm"]-length/2*math.tan(d["panel_angle_rad"])
        zhi = d["panel_origin_z_mm"]+length/2*math.tan(d["panel_angle_rad"])
        require(zlo > bottom, "Wedge must have positive low-end height")
        wedge = (cq.Workplane("XZ").polyline([(-length/2, bottom), (length/2, bottom), (length/2, zhi), (-length/2, zlo)])
                 .close().extrude(v["wedge_width_mm"]).val().translate((0, v["wedge_width_mm"]/2, 0)))
        for index, sign in enumerate((-1, 1), 1):
            m.add(f"SV3_WEDGE_{label}_{index}", wedge, group,
                  ["wedge_length_mm", "wedge_width_mm", "wedge_edge_inset_mm", "panel_xyz_mm", "panel_gap_mm", "panel_tilt_deg", "panel_low_clearance_mm", "tray_thickness_mm"],
                  (0, y+sign*(panel_y/2-v["wedge_edge_inset_mm"]), 0),
                  note="Solid custom wedge rail with a planar face tangent to the exact tilted panel underside; attachment/clamp design open.")
    hx, hy = v["hub_center_xy_mm"]
    m.add("SV3_HUB_HAMMOND_1550WJ", box(v["hub_xyz_mm"]), "hub",
          ["hub_xyz_mm", "hub_center_xy_mm", "shade_to_tray_mm", "shade_thickness_mm", "shade_hub_gap_mm"],
          (hx, hy, d["hub_bottom_mm"]), kind="purchased_envelope", material="hub",
          note="Flat Hammond 1550WJ overall envelope only. Vendor tapered interior, gasket, bosses, fasteners and actual mass unknown; do not treat this solid as metal or sealed buoyancy.",
          features={"mpn": "1550WJ", "source_id": "hub-drawing", "source_dimensions_mm": v["hub_xyz_mm"], "actual_mass_kg": None})
    shelf = box([v["hub_carrier_width_mm"], v["hub_xyz_mm"][1], v["hub_carrier_thickness_mm"]]).translate((hx, hy, d["hub_bottom_mm"]-v["hub_carrier_thickness_mm"]))
    for sign in (-1, 1):
        hanger = box([*v["hub_hanger_xy_mm"], -d["hub_bottom_mm"]]).translate((hx+sign*(v["hub_carrier_width_mm"]-v["hub_hanger_xy_mm"][0])/2, hy, d["hub_bottom_mm"]))
        shelf = shelf.fuse(hanger)
    m.add("SV3_HUB_CARRIER", shelf.clean(), "hub",
          ["hub_carrier_width_mm", "hub_carrier_thickness_mm", "hub_hanger_xy_mm", "hub_xyz_mm", "hub_center_xy_mm", "shade_to_tray_mm", "shade_thickness_mm", "shade_hub_gap_mm"],
          note="Shelf supports hub underside; two hanger tabs touch tray and clear shade ends. Welds/bolts, retention and loads not released.")
    m.add("SV3_SHADE_ROOF", box([*v["shade_xy_mm"], v["shade_thickness_mm"]]), "hub",
          ["shade_xy_mm", "shade_thickness_mm", "shade_to_tray_mm", "hub_xyz_mm", "hub_center_xy_mm", "sink_xyz_mm", "sink_hub_gap_mm"],
          (hx, d["shade_y_mm"], d["shade_bottom_mm"]),
          note="Inherited custom 375 x 275 x 1.5 mm shade roof and 75 mm hub gap. Directly under tray/panels now; no shade or thermal performance transferred.")
    for index, sign in enumerate((-1, 1), 1):
        m.add(f"SV3_SHADE_HANGER_{index}", box([*v["shade_support_xy_mm"], v["shade_to_tray_mm"]]), "hub",
              ["shade_support_xy_mm", "shade_support_x_mm", "shade_to_tray_mm", "hub_xyz_mm", "hub_center_xy_mm", "sink_xyz_mm", "sink_hub_gap_mm"],
              (hx+sign*v["shade_support_x_mm"], d["shade_y_mm"], d["shade_top_mm"]))
    sink_bottom = d["hub_mid_z_mm"]-v["sink_xyz_mm"][2]/2
    m.add("SV3_SINK_OCCUPANCY_NOT_FINS", box(v["sink_xyz_mm"]), "hub",
          ["sink_xyz_mm", "sink_base_mm", "sink_hub_gap_mm", "hub_xyz_mm", "hub_center_xy_mm", "shade_to_tray_mm", "shade_thickness_mm", "shade_hub_gap_mm"],
          (hx, d["sink_y_mm"], sink_bottom), kind="allocation", material="allocation",
          note="Wakefield 125460/XX4559 full occupancy, NOT solid metal or dimensioned fins. Beside the flat hub, no designed rear-base contact, no installed thermal or mass result.",
          features={"source_id": "sink-catalog", "source_dimensions_mm": v["sink_xyz_mm"], "profile_base_mm": v["sink_base_mm"], "fin_count": None, "fin_pitch_mm": None, "thermal_resistance_k_w": None})
    m.add("SV3_SINK_OUTLET_AIR_ALLOCATION", box([v["sink_xyz_mm"][0], v["sink_xyz_mm"][1], v["sink_vent_height_mm"]]), "hub",
          ["sink_xyz_mm", "sink_vent_height_mm", "sink_hub_gap_mm", "hub_xyz_mm", "hub_center_xy_mm", "shade_to_tray_mm", "shade_thickness_mm", "shade_hub_gap_mm"],
          (hx, d["sink_y_mm"], sink_bottom+v["sink_xyz_mm"][2]), kind="allocation", material="allocation",
          note="Open-air reservation above vertical sink occupancy. Skirt changes ventilation; this clearance is not a convection result.")
    socket = ring(v["socket_od_mm"], v["socket_id_mm"], v["socket_length_mm"]-v["socket_flange_thickness_mm"]).translate((0, 0, -v["socket_length_mm"]))
    flange = ring(v["socket_flange_od_mm"], v["socket_id_mm"], v["socket_flange_thickness_mm"]).translate((0, 0, -v["socket_flange_thickness_mm"]))
    socket = socket.fuse(flange)
    pole = ring(v["pole_od_mm"], v["pole_od_mm"]-2*v["pole_wall_mm"], d["pole_length_mm"]).translate((0, 0, -v["site_depth_mm"]))
    for index, depth in enumerate(v["bolt_centres_below_tray_mm"], 1):
        start = -v["bolt_allocation_length_mm"]/2
        hole = cylinder(v["bolt_hole_diameter_mm"]/2, v["bolt_allocation_length_mm"], (start, 0, -depth), (1, 0, 0))
        socket = socket.cut(hole)
        pole = pole.cut(hole.translate((0, 0, v["freeboard_mm"])))
        bolt = cylinder(v["bolt_allocation_diameter_mm"]/2, v["bolt_allocation_length_mm"], (start, 0, -depth), (1, 0, 0))
        m.add(f"SV3_CROSS_BOLT_ALLOCATION_{index}", bolt, "mastSocket",
              ["bolt_centres_below_tray_mm", "bolt_allocation_diameter_mm", "bolt_allocation_length_mm"],
              kind="allocation", material="allocation", note="Unpopulated cross-bolt space. Both socket and pole have larger clearance bores; no fastener/head/thread/locking design claimed.")
    m.add("SV3_MAST_SOCKET", socket.clean(), "mastSocket",
          ["socket_od_mm", "socket_id_mm", "socket_length_mm", "socket_flange_od_mm", "socket_flange_thickness_mm", "bolt_centres_below_tray_mm", "bolt_hole_diameter_mm", "bolt_allocation_length_mm"],
          features={"pole_interface_od_mm": v["pole_od_mm"], "bore_mm": v["socket_id_mm"], "cross_bolt_count": 2})
    m.add("SV3_POLE_60MM", pole.clean(), "mountPole",
          ["pole_od_mm", "pole_wall_mm", "site_depth_mm", "freeboard_mm", "bolt_centres_below_tray_mm", "bolt_hole_diameter_mm", "bolt_allocation_length_mm"],
          variant="pole", material="steel", note="Hollow, unsealed 60 mm pole. Length is water depth plus freeboard; ends at footing plate top. No embedment, foundation or load capacity inferred.",
          features={"length_mm": d["pole_length_mm"], "embedment_mm": None})
    m.add("SV3_SEABED_FOOTING_PLATE", box([*v["footing_xy_mm"], v["footing_thickness_mm"]]), "mountPole",
          ["footing_xy_mm", "footing_thickness_mm", "site_depth_mm"], (0, 0, -v["site_depth_mm"]-v["footing_thickness_mm"]),
          variant="pole", material="steel", note="Seabed-top plate allocation represented as custom physical plate. Not an engineered anchor, deadweight or embedment design.")
    for label, y in zip(("A", "B"), d["panel_centres_y_mm"]):
        low, high = v["cable_stub_z_mm"]
        m.add("SV3_CABLE_ROUTE_ALLOCATION_"+label, cylinder(v["cable_diameter_mm"]/2, high-low), "tray",
              ["cable_diameter_mm", "cable_x_mm", "cable_stub_z_mm", "panel_xyz_mm", "panel_gap_mm", "cable_bend_radius_mm"],
              (v["cable_x_mm"], y, low), kind="allocation", material="allocation",
              note="Unterminated route stub through tray clearance hole, not actual panel junction/gland geometry or a full harness. Inherited 56 mm bend allowance remains unresolved at ends.")
    collar = box([*v["float_outer_xy_mm"], v["float_height_mm"]]).cut(box([*v["skirt_xy_mm"], v["float_height_mm"]])).clean()
    f = m.add("SV3_FLOAT_COLLAR", collar, "mountFloat", ["float_outer_xy_mm", "skirt_xy_mm", "float_height_mm", "foam_density_kg_m3", "seawater_density_kg_m3", "hub_scenario_mass_kg", "sink_scenario_mass_kg", "unmodeled_payload_allowance_kg"],
              variant="float", material="foam", note="Closed-cell dry foam assumption, not a sourced buoy. Tray bears on collar top; skirt fits open centre. Conditional mass scenario sets waterline, no stability or wave result.")
    mass = mechanics(p, m.metadata())
    draft = mass["float_scenario"]["conditional_equilibrium_draft_m"]*1000
    require(0 < draft < v["float_height_mm"], "Mass scenario cannot float within collar height")
    m.float_surface_z = v["float_height_mm"]-draft
    f.translation_mm = [0, 0, -draft]
    f.shape = f.source_shape.translate(f.translation_mm)
    return m


def record(name, passed, **details):
    return {"id": name, "passed": bool(passed), **details}


def geometry_checks(m):
    v, d = values(m.interface), layout(m.interface)
    tol = v["brep_tolerance_mm"]
    checks = []
    for p in m.parts:
        checks.append(record("valid:"+p.name, valid(p.shape) and valid(p.source_shape), solids=len(p.shape.Solids()), volume_mm3=p.shape.Volume()))
        expected = p.source_shape.rotate((0, 0, 0), (0, 1, 0), p.rotation_y_deg).translate(p.translation_mm)
        if p.variant == "common":
            expected = expected.translate((0, 0, v["freeboard_mm"]))
        a, b = bbox(expected), bbox(p.shape)
        delta = max(abs(a[k][i]-b[k][i]) for k in ("min_mm", "max_mm") for i in range(3))
        checks.append(record("source_transform:"+p.name, delta <= tol and abs(expected.Volume()-p.shape.Volume()) <= v["interference_tolerance_mm3"], bbox_delta_mm=delta))
    for name, key in (("SV3_PANEL_A", "panel_xyz_mm"), ("SV3_PANEL_B", "panel_xyz_mm"), ("SV3_HUB_HAMMOND_1550WJ", "hub_xyz_mm"), ("SV3_SINK_OCCUPANCY_NOT_FINS", "sink_xyz_mm")):
        size = bbox(m.get(name).source_shape)["size_mm"]
        checks.append(record("sourced_dimensions:"+name, all(abs(a-b) <= tol for a, b in zip(size, v[key])), measured_mm=size, expected_mm=v[key]))
    checks.append(record("two_panel_gap", abs(m.get("SV3_PANEL_A").shape.distance(m.get("SV3_PANEL_B").shape)-v["panel_gap_mm"]) <= tol))
    socket = m.get("SV3_MAST_SOCKET").shape
    pole = m.get("SV3_POLE_60MM").shape
    checks.append(record("pole_length", abs(bbox(pole)["size_mm"][2]-d["pole_length_mm"]) <= tol, expected_mm=d["pole_length_mm"]))
    checks.append(record("pole_to_footing_contact", pole.distance(m.get("SV3_SEABED_FOOTING_PLATE").shape) <= tol))
    checks.append(record("socket_radial_clearance", abs(pole.distance(socket)-(v["socket_id_mm"]-v["pole_od_mm"])/2) <= tol))
    checks.append(record("shade_hub_gap", abs(m.get("SV3_SHADE_ROOF").shape.distance(m.get("SV3_HUB_HAMMOND_1550WJ").shape)-v["shade_hub_gap_mm"]) <= tol))
    for label in ("A", "B"):
        panel = m.get("SV3_PANEL_"+label).shape
        for i in (1, 2):
            checks.append(record(f"panel_wedge_contact:{label}:{i}", panel.distance(m.get(f"SV3_WEDGE_{label}_{i}").shape) <= tol))
    for variant in ("pole", "float"):
        installed = m.installed(variant)
        for i, (first, a) in enumerate(installed):
            aa = bbox(a)
            for second, b in installed[i+1:]:
                bb = bbox(b)
                broad = all(min(aa["max_mm"][k], bb["max_mm"][k])-max(aa["min_mm"][k], bb["min_mm"][k]) > tol for k in range(3))
                overlap = a.intersect(b).Volume() if broad else 0.0
                checks.append(record(f"interference:{variant}:{first.name}:{second.name}", overlap <= v["interference_tolerance_mm3"],
                                     volume_mm3=overlap, includes_nonphysical_allocation=not first.physical or not second.physical))
    collar = m.get("SV3_FLOAT_COLLAR").shape
    float_shapes = dict((p.name, s) for p, s in m.installed("float"))
    checks.append(record("float_tray_bearing_contact", collar.distance(float_shapes["SV3_TRAY_PLATE"]) <= tol))
    checks.append(record("float_hub_above_scenario_waterline", bbox(float_shapes["SV3_HUB_HAMMOND_1550WJ"])["min_mm"][2] > 0))
    checks.append(record("float_socket_above_scenario_waterline", bbox(float_shapes["SV3_MAST_SOCKET"])["min_mm"][2] > 0))
    checks.append(record("shallow_surface_envelope", v["skirt_depth_mm"]+v["tray_thickness_mm"]+v["panel_low_clearance_mm"]+v["panel_xyz_mm"][0]*math.sin(d["panel_angle_rad"])+v["panel_xyz_mm"][2]*math.cos(d["panel_angle_rad"]) < v["surface_height_limit_mm"],
                         limit_basis="Traced surface_height_limit_mm digital layout assumption, not physical load or suitability"))
    return checks
