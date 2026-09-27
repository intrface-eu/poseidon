"""Editable passive-v2 solids only. No baseline imports, mutation or live hardware."""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
from dataclasses import dataclass, field
import math
import cadquery as cq
from candidate_parameters import REVISION, STATUS, arithmetic

DENSITY = {"ALUMINIUM_ASSUMED": 2700, "SS316_ASSUMED": 8000, "THERMAL_PAD_ASSUMED": 2000,
           "VENDOR_ENVELOPE": None, "CABLE_ALLOCATION": None, "FR4_ASSUMED": 1850}


def box(size, xy=(0, 0), z=0):
    return cq.Workplane("XY").box(*size, centered=(True, True, False)).val().translate((*xy, z))


def cyl(r, length, xyz=(0, 0, 0), axis="z"):
    return cq.Solid.makeCylinder(r, length, cq.Vector(*xyz), cq.Vector(*{"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[axis]))


def ring(ro, ri, length, xyz=(0, 0, 0)):
    return cyl(ro, length, xyz).cut(cyl(ri, length, xyz)).clean()


def plate(size, xy=(0, 0), z=0, holes=(), diameter=6.6):
    shape = box(size, xy, z)
    for x, y in holes:
        if abs(x - xy[0]) + diameter / 2 >= size[0] / 2 or abs(y - xy[1]) + diameter / 2 >= size[1] / 2:
            raise ValueError("Off-plate mounting hole rejected")
        shape = shape.cut(cyl(diameter / 2, size[2] + 2, (x, y, z - 1)))
    return shape.clean()


def bbox(shape):
    b = shape.BoundingBox()
    return {"min_mm": [b.xmin, b.ymin, b.zmin], "max_mm": [b.xmax, b.ymax, b.zmax], "size_mm": [b.xlen, b.ylen, b.zlen]}


@dataclass
class Part:
    id: str
    shape: cq.Shape
    description: str
    bom_id: str
    material: str
    source_status: str
    features: dict = field(default_factory=dict)
    note: str = ""
    critical: bool = False

    def metadata(self):
        density = DENSITY[self.material]
        return {"id": self.id, "description": self.description, "bom_id": self.bom_id,
                "material": self.material, "density_assumed_kg_m3": density, "volume_mm3": self.shape.Volume(),
                "solid_equivalent_mass_kg": self.shape.Volume() * density / 1e9 if density else None,
                "mass_basis": "Assumed density times CAD solid volume; not measured. Vendor masses, if present, are separate feature fields.",
                "bbox": bbox(self.shape), "source_status": self.source_status, "features": self.features, "note": self.note,
                "critical_load": self.critical, "printable": False, "pressure_boundary": False, "revision": REVISION, "status": STATUS}


@dataclass
class Assembly:
    id: str
    description: str
    parts: list = field(default_factory=list)
    keepouts: dict = field(default_factory=dict)
    checks: list = field(default_factory=list)
    allowed: dict = field(default_factory=dict)

    def add(self, id, shape, description, bom_id=None, material="ALUMINIUM_ASSUMED", status="CUSTOM_PROVISIONAL_NOT_FABRICATION", features=None, note="", critical=False):
        if any(p.id == id for p in self.parts):
            raise ValueError("Duplicate part identity")
        self.parts.append(Part(id, shape, description, bom_id or id, material, status, features or {}, note, critical))
        return shape

    def get(self, id):
        return next(p.shape for p in self.parts if p.id == id)

    def reserve(self, id, shape, note, category="service_exclusion"):
        self.keepouts[id] = {"shape": shape, "note": note, "category": category}
        return shape

    def check(self, id, actual, minimum, unit="mm", note=""):
        self.checks.append({"id": id, "actual": float(actual), "minimum": float(minimum), "units": unit,
                            "passed": actual + 1e-6 >= minimum, "note": note})

    def gap(self, id, first, second, minimum, note=""):
        f = self.get(first) if isinstance(first, str) else first
        s = self.get(second) if isinstance(second, str) else second
        self.check(id, f.distance(s), minimum, note=note)

    def compound(self):
        return cq.Compound.makeCompound([p.shape for p in self.parts])

    def native(self):
        assembly = cq.Assembly(name=self.id)
        for p in self.parts:
            color = (0.65, 0.7, 0.6) if p.material == "VENDOR_ENVELOPE" else (0.4, 0.5, 0.6)
            assembly.add(p.shape, name=p.id, color=cq.Color(*color), metadata={"revision": REVISION, "status": STATUS, "bom_id": p.bom_id})
        return assembly


def tube(size, xy, z):
    x, y, h = size
    return box(size, xy, z).cut(box([x - 6, y - 6, h + 2], xy, z - 1)).clean()


def cable_xy(path, start, diameter):
    return cq.Workplane("XZ", origin=start).circle(diameter / 2).sweep(path).val()


def build_reef(p):
    a = Assembly("C2-REEF", "NON-ADOPTED two-series-panel 80W REEF frame, real cable routes and service allocations")
    sx, sy, sz = p["panel"]["size_mm"]
    panel_y = (sy + p["panel_gap_mm"]) / 2
    base_z, panel_z = 0, 1160
    for label, x in (("L", -270), ("R", 270)):
        holes = [(x, -430), (x, 430)]
        a.add("C2-REEF-BASE-" + label, plate([40, 900, 30], (x, 0), holes=holes, diameter=8.5), "Frame base rail with candidate anchor clearance", critical=True, features={"mount_holes_mm": holes, "hole_diameter_mm": 8.5})
        for j, y in enumerate((-430, 430), 1):
            a.add(f"C2-REEF-ANCHOR-{label}-{j}", cyl(4, 30, (x, y, 2)).fuse(cyl(7.5, 6, (x, y, 32))).clean(), "M8 candidate fastener simplified shank/head, unthreaded model", bom_id="C2-REEF-ANCHOR-M8", material="SS316_ASSUMED", critical=True, features={"nominal_thread_candidate": "M8", "head_envelope_diameter_mm": 15}, note="Generic envelope, not a verified ISO/supplier part. Embedment, tensile class, washer, locking and torque require structural/site review.")
            a.add(f"C2-REEF-WASHER-{label}-{j}", ring(9, 4.5, 2, (x, y, 30)), "Candidate M8 washer allocation", bom_id="C2-REEF-WASHER-M8", material="SS316_ASSUMED", critical=True)
    for i, (x, y) in enumerate([(-270, -360), (270, -360), (-270, 360), (270, 360)], 1):
        a.add(f"C2-REEF-POST-{i}", tube([40, 40, 1050], (x, y), 30), "40x40x3 aluminium post, structural review open", bom_id="C2-REEF-POST", critical=True,
              features={"section_mm": [40, 40, 3], "length_mm": 1050}, note="Generic section, not a sourced extrusion/bolt system; no joint or load release")
    for i, x in enumerate((-270, 270), 1):
        a.add(f"C2-REEF-PANEL-RAIL-{i}", box([40, 980, 40], (x, 0), 1080), "Longitudinal two-panel support rail", bom_id="C2-REEF-PANEL-RAIL", critical=True,
              features={"size_mm": [40, 980, 40]}, note="Panel rails carry twice the reference module face area; wind/fatigue/joint sizing not qualified")
    for i, y in enumerate((-360, 360), 1):
        a.add(f"C2-REEF-CROSS-TIE-{i}", box([500, 40, 30], (0, y), 30), "Frame bottom transverse tie", bom_id="C2-REEF-CROSS-TIE", critical=True)
    for index, y in enumerate((-panel_y, panel_y), 1):
        a.add(f"C2-REEF-PV-{index}", box([sx, sy, sz], (0, y), panel_z), "Victron SPM040401200 physical panel envelope", p["panel"]["bom_id"], "VENDOR_ENVELOPE", "SOURCE_VERIFIED_OVERALL_ENVELOPE_DETAIL_PROVISIONAL",
              features={"mpn": p["panel"]["mpn"], "size_mm": [sx, sy, sz], "instance": index, "electrical_series_position": index, "vendor_nameplate_w": 40, "vendor_nominal_mass_kg": 3.1,
                        "source_id": p["panel"]["source_id"], "centre_y_mm": y}, note="Two separate purchased references, not two quantities assigned to one solid. Clamp zones, frame profile, junction-box location and current availability unverified.")
        junction = a.add(f"C2-REEF-JUNCTION-ALLOC-{index}", box([90, 50, 20], (0, y), 1125), "Unverified panel junction/terminal allocation", p["panel"]["bom_id"], "VENDOR_ENVELOPE", "PROVISIONAL_TERMINAL_POSITIONS_NOT_VENDOR_GEOMETRY",
                        features={"allocation_only_not_extra_panel": True}, note="Datasheet does not locate junction terminals. Swept cables terminate at these assumed faces; not a released panel harness.")
        a.reserve(f"PV-{index}-TERMINAL-SERVICE", box([180, 160, 50], (0, y), 1070), "Terminal hand access below panel; assumed junction positions, no energized work")
        # Four metal support blocks/clamp ears per panel. No clamp load/torque from geometry.
        for j, (x, yy) in enumerate([(x, y + dy) for x in (-270, 270) for dy in (-155, 155)], 1):
            a.add(f"C2-REEF-PV-{index}-SUPPORT-{j}", box([40, 50, 40], (x, yy), 1120), "Metal panel support block", bom_id="C2-REEF-PV-SUPPORT", critical=True,
                  features={"size_mm": [40, 50, 40]}, note="Custom candidate support; actual permitted panel mounting/clamp zones and insulating pads unresolved")
        # End clamps sit beyond the X edges. Their horizontal lip touches panel top only.
        for j, x in enumerate((-sx / 2 - 7, sx / 2 + 7), 1):
            upright = box([8, 35, 35], (x, y), 1150)
            lip_x = -sx / 2 + 3 if x < 0 else sx / 2 - 3
            lip = box([20, 35, 5], (lip_x, y), 1185)
            clamp = upright.fuse(lip).clean()
            # Keep clamp pieces as a connected candidate, no corner-only loose solid.
            a.add(f"C2-REEF-PV-{index}-CLAMP-{j}", clamp, "Custom metal end-clamp study, no approved panel interface", bom_id="C2-REEF-PV-END-CLAMP", critical=True,
                  features={"nominal_fastener": "M6 candidate; thread/torque/rail attachment unresolved"}, note="Not a sourced complete clamp. Panel manufacturer mounting zones, edge crush, uplift and attachment remain open.")
            a.reserve(f"PV-{index}-CLAMP-{j}-TOOL", cyl(8, 80, (x, y, 1190)), "M6 driver envelope; fastener model is an allocation")
    a.gap("two_panel_edge_service_gap", "C2-REEF-PV-1", "C2-REEF-PV-2", p["panel_gap_mm"], "Exact distance between two distinct BRep panel envelopes")
    a.check("two_panel_face_area", 2 * sx * sy / 1e6, 0.5678, "m2", "Area only; drag and structural acceptance stay in parent calculations")
    # Actual continuous series jumper with four tangent quarter-circle bends.
    r, d = p["cable_radius_mm"], p["cable_diameter_mm"]
    k, x0, z = r / math.sqrt(2), -30, 1140
    x1, x2, x3 = x0 + r, x0 + r + 84, x0 + 2 * r + 84
    path = (cq.Workplane("XY").moveTo(x0, -panel_y + 25).lineTo(x0, -120)
            .threePointArc((x1 - k, -120 + k), (x1, -120 + r)).lineTo(x2, -120 + r)
            .threePointArc((x2 + k, -120 + 2*r - k), (x3, -120 + 2*r)).lineTo(x3, 120 - 2*r)
            .threePointArc((x2 + k, 120 - 2*r + k), (x2, 120-r)).lineTo(x1, 120-r)
            .threePointArc((x1-k, 120-k), (x0, 120)).lineTo(x0, panel_y-25).wire().translate((0, 0, z)))
    series = a.add("C2-REEF-SERIES-LINK", cable_xy(path, (x0, -panel_y + 25, z), d), "Physical swept P1-positive to P2-negative jumper", p["wiring"]["series_bom_id"], "CABLE_ALLOCATION", "PROVISIONAL_ROUTE_AND_TERMINATIONS",
                   features={"from": "PV1_POS", "to": "PV2_NEG", "centreline_radius_mm": r, "diameter_mm": d, "centreline_length_mm": path.val().Length(), "arc_count": 4},
                   note="Actual 3D route, but panel terminal coordinates, cable spec, glands and polarity qualification remain open; no energized hardware.")
    radii = [edge.radius() for edge in path.val().Edges() if edge.geomType() == "CIRCLE"]
    a.check("series_link_actual_centreline_min_radius", min(radii), 6 * d, note="Measured from actual path arcs; 6D is provisional, not a vendor cable limit")
    a.check("series_link_arc_count", len(radii), 4, "count")
    for i in (1, 2):
        a.gap(f"series_link_to_panel_{i}", series, f"C2-REEF-PV-{i}", 15, "Real cable-to-panel underside clearance")
        # Intended termination overlap: cylinder ends are tangent to the assumed junction face.
        a.allowed[frozenset(("C2-REEF-SERIES-LINK", f"C2-REEF-JUNCTION-ALLOC-{i}"))] = "Cable enters assumed terminal face; connector/overmould detail unresolved"
    # Separate free negative/positive leads with real vertical cable bend, ending above electronics.
    for i, sign in ((1, -1), (2, 1)):
        ystart = sign * (panel_y - 25)
        ybend = sign * 200
        endy = sign * (200 - r)
        ymid = sign * (200 - k)
        curve = (cq.Workplane("YZ").moveTo(ystart, z).lineTo(ybend, z)
                 .threePointArc((ymid, z-r+k), (endy, z-r)).lineTo(endy, 650).wire().translate((30, 0, 0)))
        lead = cq.Workplane("XZ", origin=(30, ystart, z)).circle(d/2).sweep(curve).val()
        a.add(f"C2-REEF-FREE-LEAD-{i}", lead, "Swept array free lead to unconnected power-service zone", p["wiring"]["series_bom_id"], "CABLE_ALLOCATION", "PROVISIONAL_ROUTE_AND_TERMINATIONS",
              features={"terminal": "ARRAY_NEG" if i == 1 else "ARRAY_POS", "from": "PV1_NEG" if i == 1 else "PV2_POS", "end_xyz_mm": [30, endy, 650], "centreline_radius_mm": r, "diameter_mm": d},
              note="Free ends stop at service boundary, not wired directly to an unselected MPPT/BMS connector. Requires disconnect, polarity, conductor and protection review.")
        a.allowed[frozenset((f"C2-REEF-FREE-LEAD-{i}", f"C2-REEF-JUNCTION-ALLOC-{i}"))] = "Cable enters provisional junction terminal face"
        a.gap(f"series_link_to_free_lead_{i}", series, lead, 5, "No physical series-to-output cable crossing")
        a.reserve(f"FREE-LEAD-{i}-CONNECTOR", box([60, 100, 80], (30, endy), 570), "Unselected touch-safe array output/disconnect connector and service approach")
    a.reserve("ARRAY-PANEL-LIFT", box([sx+80, 2*sy+p["panel_gap_mm"]+80, 220], z=1185), "Two-panel lift/service allocation, disconnect both source modules and follow approved electrical procedure")
    a.reserve("PANEL-UNDERVENT", box([500, 900, 30], z=1090), "Open underside ventilation allocation, not zero panel heat or thermal acceptance", "ventilation_allocation")
    for label, bottom in (("BATTERY", 70), ("ELECTRONICS", 450)):
        for i, x in enumerate((-260, 260), 1):
            a.add(f"C2-REEF-{label}-SUPPORT-RAIL-{i}", box([20, 680, 20], (x, 0), bottom), "Shelf support rail between posts", bom_id="C2-REEF-SHELF-RAIL", critical=True, note="Face-contact joint allocation only; welding/bolting, fatigue and corrosion review open")
    a.add("C2-REEF-BATTERY-SHELF", box([520, 250, 8], (0, -150), 90), "Metal battery shelf, restraint and weather compartment unresolved", critical=True)
    bx, by, bz = p["battery"]["size_mm"]
    a.add("C2-REEF-BATTERY", box([bx, by, bz], (0, -150), 110), "Victron BAT512050610 upright conservative envelope", p["battery"]["bom_id"], "VENDOR_ENVELOPE", "SOURCE_VERIFIED_OVERALL_ENVELOPE_DETAIL_PROVISIONAL",
          features={"size_mm": [bx, by, bz], "vendor_mass_kg": 7, "source_id": p["battery"]["source_id"], "thread": "M8"}, note="No inferred capacity or operating voltage from CAD. External BMS, isolation, weather guarding and approved straps required.")
    for i, x in enumerate((-115, 115), 1):
        a.add(f"C2-REEF-BATTERY-STOP-{i}", box([6, 180, 30], (x, -150), 98), "Provisional metal lateral stop", bom_id="C2-REEF-BATTERY-STOP", critical=True)
    bt = a.reserve("BATTERY-TERMINAL-SPACE", box([bx+20, by+20, p["battery_terminal_gap_mm"]], (0, -150), 110+bz), "At least40mm provisional terminal/lug/driver space; cable-vendor bend and boots not verified")
    a.add("C2-REEF-ELECTRONICS-SHELF", box([520, 280, 8], (0, 150), 470), "REEF electronics support shelf", critical=True)
    ex, ey, ez = p["reef_box"]["size_mm"]
    shell = box([ex, ey, ez-8], (0, 150), 478).cut(box([ex-30, ey-30, ez], (0, 150), 490)).clean()
    a.add("C2-REEF-ELECTRONICS-ALLOCATION", shell, "REEF enclosure allocation, exact purchased enclosure unselected", p["reef_box"]["bom_id"], "VENDOR_ENVELOPE", "PROVISIONAL_NOT_VENDOR_GEOMETRY",
          features={"size_mm": p["reef_box"]["size_mm"]}, note="Conservative cavity only. Component fit checked below; complete glands/terminals/charge-disable cable and cooling remain open.")
    lid = a.add("C2-REEF-ELECTRONICS-LID", box([ex, ey, 8], (0, 150), 478+ez-8), "Electronics lid allocation", p["reef_box"]["bom_id"], "VENDOR_ENVELOPE", "PROVISIONAL_NOT_VENDOR_GEOMETRY")
    a.add("C2-REEF-COMPONENT-TRAY", box([250, 170, 4], (0, 150), 494), "Reference electronics mounting tray, holes pending source freeze")
    locations = {"V2-MPPT-001": (65,105), "V2-BMS-001": (-65,105), "V2-LOADSW-001": (-60,200), "V2-REG5-001": (50,185), "V2-REG3-001": (95,185)}
    for component in p["power_components"]:
        id = component["id"]
        if id not in locations:
            continue
        xy = locations[id]
        sx2, sy2, sz2 = component["cad_envelope_xyz_mm"]
        shape = a.add("C2-REEF-" + id, box([sx2, sy2, sz2], xy, 502), component["mpn"] + " source-bound candidate envelope", id, "VENDOR_ENVELOPE", component["envelope_status"],
                      features={"size_mm": component["cad_envelope_xyz_mm"], "source_url": component["source_url"], "mpn": component["mpn"]}, note=component["notes"])
        a.gap(id + "_closed_lid_clearance", shape, lid, 5, "Packaging only, not cooling/terminal compatibility")
        if id == "V2-LOADSW-001":
            service = a.reserve("LOADSW-M6-TERMINAL-TOOL", box([sx2, sy2, 40], xy, 502+sz2), "Provisional40mm stud/lug/driver space above source-envelope46mm")
            a.gap("loadswitch_terminal_to_lid", service, lid, 15)
        elif id == "V2-BMS-001":
            service = a.reserve("BMS-CONNECTOR-ACCESS", box([sx2, sy2, 30], xy, 502+sz2), "30mm provisional connector approach; conflicting drawing/datasheet retained")
            a.gap("bms_connector_to_lid", service, lid, 20)
        elif id.startswith("V2-REG"):
            reserve = a.reserve(id + "-PLAN-ACCESS", box([sx2+10, sy2+10, 15], xy, 502), "5mm per plan side for headers/wires; height and actual wiring open", "component_access_allocation")
            a.gap(id + "_plan_access_to_shell", reserve, shell, 10)
    a.add("C2-REEF-MCU-ALLOCATION", box([55,28,14], (-65,150), 502), "ESP32-DevKitC-32E provisional envelope", "REEF-CPU-001", "VENDOR_ENVELOPE", "PROVISIONAL_NOT_VENDOR_GEOMETRY")
    a.add("C2-REEF-RADIO-ALLOCATION", box([40,30,15], (65,150), 502), "RAK3272S conservative provisional envelope", "REEF-RF-001", "VENDOR_ENVELOPE", "PROVISIONAL_BOARD_MODULE_HEADER_UNCERTAINTY")
    a.gap("battery_terminal_to_electronics_shelf", bt, "C2-REEF-ELECTRONICS-SHELF", 100, "True spatial clearance, not terminal-cable approval")
    a.reserve("REEF-ELECTRONICS-SERVICE", box([360, 280, 180], (0, 150), 618), "Electronics lid and driver access beneath panel frame")
    return a


def build_hub(p):
    a = Assembly("C2-HUB", "Vertical sourced enclosure, collector/TIM/rear sink and ventilated opaque shade candidate")
    h = p["hub"]
    x, depth, height = h["size_mm"]
    back, lid_t = h["base_thickness_mm"], h["lid_thickness_mm"]
    il, iw, ih = h["inside_reference_lwh_mm"]
    shell = box([x,depth-lid_t,height], (0,(depth-lid_t)/2)).cut(box([il,depth,iw], (0,back+depth/2), (height-iw)/2)).clean()
    a.add("C2-HUB-ENCLOSURE", shell, "Hammond1550WJ simplified vertical shell", h["bom_id"], "VENDOR_ENVELOPE", h["dimension_status"],
          features={"mpn":h["mpn"],"overall_xyz_mm":h["size_mm"],"source_id":h["source_id"],"base_reference_mm":back,"inside_reference_lwh_mm":h["inside_reference_lwh_mm"]},
          note="Source owns tapered walls/lips/bosses/gasket/fasteners; rectangular shell is a reference proxy. Do not fabricate, drill or transfer ingress/thermal qualification from this CAD.")
    lid = a.add("C2-HUB-LID", box([x,lid_t,height], (0,depth-lid_t/2)), "1550WJ lid reference", h["bom_id"], "VENDOR_ENVELOPE", "SOURCE_THICKNESS_SIMPLIFIED_GEOMETRY", features={"thickness_reference_mm":lid_t})
    t = p["tim"]["thickness_mm"]
    pw, ph = p["tim"]["patch_xz_mm"]
    patch_z = (height-ph)/2
    inner = a.add("C2-HUB-TIM-INNER", box([pw,t,ph], (0,back+t/2),patch_z), "SIL PAD TSP1600 nominal inner cut patch", p["tim"]["bom_id"], "THERMAL_PAD_ASSUMED", "SOURCE_MATERIAL_THICKNESS_CUSTOM_CUT_PROVISIONAL",
                  features={"source_id":p["tim"]["source_id"],"thickness_mm":t,"patch_xz_mm":[pw,ph]}, note="Large-area pressure, flatness, electrical isolation and contact resistance unqualified; density assumed only for mass bookkeeping")
    outer = a.add("C2-HUB-TIM-OUTER", box([pw,t,ph], (0,-t/2),patch_z), "SIL PAD TSP1600 nominal outer cut patch", p["tim"]["bom_id"], "THERMAL_PAD_ASSUMED", "SOURCE_MATERIAL_THICKNESS_CUSTOM_CUT_PROVISIONAL",
                  features={"source_id":p["tim"]["source_id"],"thickness_mm":t,"patch_xz_mm":[pw,ph]}, note="No clamping-pressure or installed thermal-interface resistance evidence")
    cx,cy,cz = p["collector"]["size_mm"]
    collector_y_front = back+t+cy
    collector = a.add("C2-HUB-COLLECTOR", box([cx,cy,cz], (0,back+t+cy/2),(height-cz)/2), "Custom aluminium collector against inside rear wall", p["collector"]["bom_id"], features={"size_mm":[cx,cy,cz],"contact_patch_xz_mm":[pw,ph]},
                      note="No component thermal-pickup pad map is invented. Actual enclosed-heat capture fraction, component-to-plate path, clamping, alloy and conductivity remain unknown.")
    sx,sd,sl = p["sink"]["size_mm"]
    base_d = p["sink"]["base_thickness_mm"]
    sink_z = (height-sl)/2
    sink_base = a.add("C2-HUB-SINK-BASE", box([sx,base_d,sl], (0,-t-base_d/2),sink_z), "Wakefield125460/XX4559 base of3in candidate cut", p["sink"]["bom_id"], "VENDOR_ENVELOPE", "SOURCE_PROFILE_BASE_AND_OUTLINE_ONLY",
                      features={"source_id":p["sink"]["source_id"],"stock_mpn":p["sink"]["mpn"],"stock_length_mm":304.8,"candidate_cut_length_mm":sl,"base_thickness_mm":base_d},
                      note="Cut/drill operations not authorized. Catalog0.5K/W is a3in reference, not installed thermal qualification; density/total fin surface not inferred.")
    a.add("C2-HUB-SINK-FINFIELD", box([sx,sd-base_d,sl], (0,-t-base_d-(sd-base_d)/2),sink_z), "Sink fin-field occupied volume, NOT a solid block or dimensioned fins", p["sink"]["bom_id"], "VENDOR_ENVELOPE", "SOURCE_OVERALL_OCCUPANCY_FIN_DETAILS_UNKNOWN",
          features={"source_id":p["sink"]["source_id"],"fin_channels_axis":"Z vertical","fin_count_pitch_taper":None,"not_solid_metal":True},
          note="Transparent-in-meaning occupancy proxy only. Fin pitch/taper/count unprovided; no fin detail, mass, conduction or convection area derived from this block.")
    for id,first,second in (("wall_to_inner_TIM",shell,inner),("inner_TIM_to_collector",inner,collector),("wall_to_outer_TIM",shell,outer),("outer_TIM_to_sink_base",outer,sink_base)):
        distance=first.distance(second)
        a.checks.append({"id":id,"distance_mm":distance,"maximum_mm":1e-5,"passed":distance<=1e-5,"patch_area_mm2":pw*ph,
                         "evidence":"BRep face contact and parameter-defined rectangular patch; not physical contact resistance or heat-capture proof"})
    # Source-backed PCB outline/hole pattern; no unsupported CPU thermal pad geometry.
    pi_x,pi_z=-50,85.5
    pcb_y=collector_y_front+10
    pcb=cq.Workplane("XY").box(85,1.6,56,centered=(True,True,False)).edges("|Y").fillet(3).val().translate((pi_x,pcb_y+0.8,pi_z-28))
    holes=[]
    for i,(hx,hz) in enumerate(((3.5,3.5),(61.5,3.5),(3.5,52.5),(61.5,52.5)),1):
        xx,zz=pi_x-42.5+hx,pi_z-28+hz
        holes.append([xx,zz])
        pcb=pcb.cut(cyl(1.35,3.6,(xx,pcb_y-1,zz),"y"))
        stand=cyl(3,10,(xx,collector_y_front,zz),"y").cut(cyl(1.35,10,(xx,collector_y_front,zz),"y")).clean()
        a.add(f"C2-HUB-PI-STANDOFF-{i}",stand,"Pi candidate M2.5 support, not a thermal pickup",bom_id="C2-HUB-PI-STANDOFF",material="SS316_ASSUMED",features={"height_mm":10,"nominal_thread":"M2.5 unthreaded reference"},note="Custom collector attachment, screw length and pad pressure require review; does not clamp CPU packages")
    a.add("C2-HUB-PI-PCB",pcb.clean(),"Pi4 PCB verified plan mounting features", "HUB-CPU-001","FR4_ASSUMED","SOURCE_PLAN_PATTERN_THICKNESS_PROVISIONAL",
          features={"source_id":"SRC-PI4-MECH","outline_xz_mm":[85,56],"hole_centres_xz_mm":holes,"hole_diameter_mm":2.7,"thickness_assumed_mm":1.6},note="Baseline Pi source retained byte-for-byte; connector/component and corner-detail thermal contact is not vendor CAD")
    components=a.add("C2-HUB-PI-COMPONENT-ALLOCATION",box([85,20,56],(pi_x,pcb_y+1.6+1+10),pi_z-28),"Pi component clearance allocation", "HUB-CPU-001","VENDOR_ENVELOPE","PROVISIONAL_COMPONENT_HEIGHT_NO_THERMAL_PAD_MAP",
                     note="No source-to-collector bridge is invented. Collector temperature is not Pi junction/local-air temperature.")
    a.add("C2-HUB-DAQ-ALLOCATION",box([95,30,60],(67.5,35),55),"Unselected receive DAQ fit allocation", "HUB-DAQ-001","VENDOR_ENVELOPE","PROVISIONAL_NOT_VENDOR_GEOMETRY")
    a.gap("pi_components_to_front_lid",components,lid,15,"Geometric service/cable allowance only")
    a.reserve("HUB-USBC-SOURCE-UNRESOLVED",box([95,30,25],(65,35),130),"Reserved packaging region, not a measured USB-C source/inline module and not proof of field DC power-path fit","unresolved_component_allocation")
    a.reserve("HUB-USABLE-ALLOCATION",box([245,48,145],(0,34),15),"Conservative container; not an exclusion and not a constant vendor cavity","usable_container")
    a.reserve("HUB-LID-REMOVAL",box([x,120,height],(0,depth+60)),"Lift lid toward+Y; seal/latch/fastener/cable-removal procedure unresolved")
    a.reserve("HUB-SINK-TOP-VENT",box([sx,sd,50],(0,-t-sd/2),sink_z+sl),"Keep vertical sink-channel outlet open by at least50mm; air/solar conditions remain unmeasured","ventilation_allocation")
    roof=p["shade"]
    roof_y=(-t-sd+depth)/2
    roof_z=height+roof["gap_mm"]
    shade=a.add("C2-HUB-SHADE",box([*roof["size_xy_mm"],roof["thickness_mm"]],(0,roof_y),roof_z),"Opaque aluminium roof with true overhang and open ventilation", roof["bom_id"], features={"roof_xy_mm":roof["size_xy_mm"],"gap_above_enclosure_mm":roof["gap_mm"],"overhang_x_mm":roof["overhang_mm"],"residual_solar_fraction":None}, critical=True,
                note="No side baffles are modelled.48W baseline potential absorbed sun remains in thermal comparison; roof geometry does not establish zero sun or thermal acceptance.")
    for i,xx in enumerate((-175,175),1):
        a.add(f"C2-HUB-SHADE-POST-{i}",box([12,12,268],(xx,-20),-18),"Outboard shade support, keeps sink channels unobstructed",bom_id="C2-HUB-SHADE-POST",critical=True,note="Custom bracket candidate, attachment and wind/corrosion loads unqualified")
    a.add("C2-HUB-MOUNT-CROSSBAR",box([370,20,8],(0,-20),-26),"Independent mounting-frame crossbar",critical=True)
    for i,xx in enumerate((-120,120),1):
        a.add(f"C2-HUB-SUPPORT-PAD-{i}",box([25,70,18],(xx,5),-18),"Enclosure support/attachment allocation",bom_id="C2-HUB-SUPPORT-PAD",critical=True,note="No enclosure wall holes or sink bolt positions invented; attachment and proof load still open")
    a.gap("shade_to_enclosure_vertical_gap",shade,shell,75)
    a.gap("shade_to_lid_service",shade,a.keepouts["HUB-LID-REMOVAL"]["shape"],50,"No roof obstruction of lid pull volume")
    a.check("shade_side_overhang_x",(roof["size_xy_mm"][0]-x)/2,50)
    a.check("shade_front_rear_overhang",(roof["size_xy_mm"][1]-(depth+sd+t))/2,50)
    a.gap("sink_outlet_to_roof",a.keepouts["HUB-SINK-TOP-VENT"]["shape"],shade,50)
    return a


def build_top(hub,reef,p):
    a=Assembly("C2-TOP","NON-ADOPTED changed HUB/REEF spatial study only; frozen WET/array/projector not replaced")
    placements={"C2-HUB":(-650,0,550),"C2-REEF":(500,0,0)}
    for source in (hub,reef):
        offset=placements[source.id]
        for part in source.parts:
            a.parts.append(Part(source.id+"__"+part.id,part.shape.translate(offset),part.description,part.bom_id,part.material,part.source_status,{**part.features,"assembly_translation_mm":list(offset)},part.note,part.critical))
        for id,ko in source.keepouts.items():
            a.reserve(source.id+"__"+id,ko["shape"].translate(offset),ko["note"],ko["category"])
        for pair,reason in source.allowed.items():
            a.allowed[frozenset(source.id+"__"+id for id in pair)]=reason
    a.gap("hub_shade_to_two_panel_array",a.get("C2-HUB__C2-HUB-SHADE"),cq.Compound.makeCompound([part.shape for part in a.parts if part.id in ("C2-REEF__C2-REEF-PV-1","C2-REEF__C2-REEF-PV-2")]),500,"Illustrative placement only; no farm attachment or shade-yield prediction")
    return a,placements


def geometry_checks(a):
    checks = list(a.checks)
    for p in a.parts:
        solids = p.shape.Solids()
        closed = bool(solids) and all(s.Closed() for solid in solids for s in solid.Shells())
        checks.append({"id": p.id + "_valid_closed_brep", "passed": bool(p.shape.isValid() and closed and p.shape.Volume() > 0),
                       "solid_count": len(solids), "closed_shells": closed, "volume_mm3": p.shape.Volume(), "evidence": "OCP_BRepCheck_and_shell_closure"})
    overlaps = []
    for i, first in enumerate(a.parts):
        b1 = bbox(first.shape)
        for second in a.parts[i+1:]:
            b2 = bbox(second.shape)
            if any(min(b1["max_mm"][k], b2["max_mm"][k]) - max(b1["min_mm"][k], b2["min_mm"][k]) <= 1e-5 for k in range(3)):
                continue
            vol = first.shape.intersect(second.shape).Volume()
            if vol > 1e-4:
                allowed = a.allowed.get(frozenset((first.id, second.id)))
                overlaps.append({"parts": [first.id, second.id], "volume_mm3": vol, "allowed_reason": allowed})
    checks.append({"id": a.id + "_physical_interference", "passed": all(o["allowed_reason"] for o in overlaps), "intersections": overlaps,
                   "evidence": "Exact OCP common volume after bbox broad phase; face contacts allowed, no structural qualification"})
    for id, ko in a.keepouts.items():
        checks.append({"id": id + "_keepout_valid", "passed": ko["shape"].isValid() and ko["shape"].Volume() > 0})
    return checks
