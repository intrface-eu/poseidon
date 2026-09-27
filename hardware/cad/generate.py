#!/usr/bin/env python3
"""Regenerate reference assemblies in a NEW/EMPTY owned directory.

CadQuery is the editable/native source. STEP files contain named assembly parts,
not triangle facsimiles. All dimensions in mm. No pressure boundary is designed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import html
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import sys
import xml.etree.ElementTree as ET

import cadquery as cq
import ezdxf
import trimesh

from parameters import (CAD_ROOT, ROOT, CONFIGURATION, REVISION, STATUS, arithmetic_checks,
                        additional_source_evidence, interface_evidence, read_parameters, sha256, source_evidence)

BOM_ALIASES = {
    "CPU-01": "HUB-CPU-001", "ENC-HUB-01": "HUB-ENC-001", "DAQ-01": "HUB-DAQ-001",
    "PWR-HUB-01": "HUB-DC5-001", "STORAGE-01": "HUB-STORE-001", "CAM-01": "WET-PRESSURE-001",
    "HYD-01": "WET-HYD-001", "HYD-ARRAY-01": "ARRAY-DAQ-OPT-001", "WIPER-MOTOR-01": "WIPER-DRIVE-OPT-001",
    "WIPER-PIVOT-01": "WIPER-DRIVE-OPT-001", "WIPER-BLADE-01": "WIPER-DRIVE-OPT-001",
    "ACT-PROJECTOR-01": "PROJECTOR-XDCR-OPT-001",
    "SOLAR-01": "REEF-PV-001", "BAT-01": "REEF-BAT-001", "ENC-REEF-01": "REEF-ENC-001",
    "MCU-01": "REEF-CPU-001", "RADIO-01": "REEF-RF-001", "CHARGER-01": "REEF-MPPT-001",
    "ANT-REEF-01": "REEF-ANT-001", "PROBE-01": "REEF-PROBE-001", "H-05": "REEF-PROBE-001",
    "H-02": "WET-HARNESS-001",
}

MATERIALS = {
    "AL6061": {"description": "6061-T6 aluminium assumption; marine finish/isolation review open", "density_kg_m3": 2700, "finish": "Candidate hard anodize, isolate stainless couples; coating thickness not modelled"},
    "SS316L": {"description": "316L stainless assumption; crevice corrosion and weld review open", "density_kg_m3": 8000, "finish": "Deburr and passivate after machining/welding; process not qualified"},
    "PETG": {"description": "PETG, dry bench/internal non-pressure non-critical-load prototype only", "density_kg_m3": 1270, "finish": "Remove support, deburr; 100% solid-equivalent mass, print settings not qualified"},
    "ELASTOMER": {"description": "Generic elastomer assumption; grade/durometer/immersion compatibility open", "density_kg_m3": 1150, "finish": "Purchased/moulded candidate, not printed; damping unmeasured"},
    "FR4": {"description": "Generic FR4 PCB solid-equivalent assumption; excludes all mounted parts", "density_kg_m3": 1850, "finish": "Purchased PCB; do not drill board"},
    "VENDOR_ENVELOPE": {"description": "Simplified integration volume; feature/source metadata identifies verified overall dimensions versus provisional allocations; not detailed vendor CAD", "density_kg_m3": None, "finish": "No fabrication allowed from envelope"},
    "CABLE_ENVELOPE": {"description": "Cable routing envelope; exact cable/connector/overmould unresolved", "density_kg_m3": None, "finish": "No material or strain/pressure rating inferred"},
}
COLORS = {"AL6061": (0.64, 0.68, 0.72), "SS316L": (0.48, 0.53, 0.57),
          "PETG": (0.15, 0.42, 0.58), "ELASTOMER": (0.18, 0.20, 0.22),
          "FR4": (0.16, 0.42, 0.22), "VENDOR_ENVELOPE": (0.68, 0.74, 0.60),
          "CABLE_ENVELOPE": (0.28, 0.28, 0.30)}


def box(x, y, z, centre=(0, 0), bottom=0):
    return cq.Workplane("XY").box(x, y, z, centered=(True, True, False)).val().translate((centre[0], centre[1], bottom))


def cylinder(radius, length, origin=(0, 0, 0), axis="z"):
    shape = cq.Workplane("XY").circle(radius).extrude(length).val()
    if axis == "x":
        shape = shape.rotate((0, 0, 0), (0, 1, 0), 90)
    elif axis == "y":
        shape = shape.rotate((0, 0, 0), (1, 0, 0), -90)
    return shape.translate(origin)


def ring(ro, ri, length, origin=(0, 0, 0), axis="z"):
    return cylinder(ro, length, origin, axis).cut(cylinder(ri, length, origin, axis)).clean()


def drilled_plate(x, y, z, holes=(), diameter=6.6, centre=(0, 0), bottom=0):
    result = box(x, y, z, centre, bottom)
    for hx, hy in holes:
        if abs(hx - centre[0]) + diameter / 2 >= x / 2 or abs(hy - centre[1]) + diameter / 2 >= y / 2:
            raise ValueError(f"Mount hole {(hx, hy)} is not fully inside plate centred {centre}")
        result = result.cut(cylinder(diameter / 2, z + 2, (hx, hy, bottom - 1)))
    return result.clean()


def collar_x(x, y, z, inner, outer, width, foot_bottom=8):
    # One machined/welded metal collar concept, bore cut AFTER combining the foot.
    result = cylinder(outer, width, (x, y, z), "x")
    foot = box(width, 44, z - outer + 8 - foot_bottom, (x + width / 2, y), foot_bottom)
    result = result.fuse(foot).cut(cylinder(inner, width + 2, (x - 1, y, z), "x"))
    return result.clean()


def bbox(shape):
    b = shape.BoundingBox()
    return {"min_mm": [b.xmin, b.ymin, b.zmin], "max_mm": [b.xmax, b.ymax, b.zmax],
            "size_mm": [b.xlen, b.ylen, b.zlen]}


def rounded(values):
    if isinstance(values, float):
        return round(values, 7)
    if isinstance(values, list):
        return [rounded(v) for v in values]
    if isinstance(values, dict):
        return {k: rounded(v) for k, v in values.items()}
    return values


@dataclass
class Part:
    id: str
    bom_id: str
    description: str
    shape: cq.Shape
    material: str = "AL6061"
    role: str = "custom_reference_part"
    printable: bool = False
    critical_load: bool = False
    features: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def metadata(self):
        density = MATERIALS[self.material]["density_kg_m3"]
        volume = self.shape.Volume()
        return rounded({"id": self.id, "bom_id": self.bom_id, "description": self.description,
                        "role": self.role, "status": STATUS, "revision": REVISION,
                        "bom_reference": ("hardware/bom/reference-v1.json#" if self.bom_id in BOM_ALIASES.values() else "mechanical-bom.json#") + self.bom_id,
                        "material_id": self.material, "volume_mm3": volume,
                        "solid_equivalent_mass_kg": volume * density / 1e9 if density else None,
                        "mass_basis": "geometric solid times assumed density, not measured assembly mass" if density else "No density-derived hardware mass; see sourced vendor_mass_kg where present",
                        "centre_of_volume_mm": list(self.shape.Center().toTuple()),
                        "bbox": bbox(self.shape), "features": self.features, "notes": self.notes,
                        "printable": self.printable, "critical_load": self.critical_load,
                        "pressure_boundary": False, "solids": len(self.shape.Solids())})


@dataclass
class Assembly:
    id: str
    description: str
    optional: bool = False
    parts: list[Part] = field(default_factory=list)
    keepouts: dict[str, tuple[cq.Shape, str]] = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)
    allowed_intersections: dict[frozenset, str] = field(default_factory=dict)

    def add(self, id, description, shape, material="AL6061", *, bom_id=None,
            role="custom_reference_part", printable=False, critical=False, features=None, notes=None):
        if any(part.id == id for part in self.parts):
            raise ValueError(f"Duplicate part id {id}")
        if printable and (critical or material != "PETG" or role != "custom_reference_part"):
            raise ValueError("Only designated PETG non-critical, non-pressure prototype parts may export STL")
        bom_id = BOM_ALIASES.get(bom_id, bom_id) if bom_id else id
        part = Part(id, bom_id, description, shape, material, role, printable, critical, features or {}, notes or [])
        self.parts.append(part)
        return shape

    def get(self, id):
        return next(part.shape for part in self.parts if part.id == id)

    def reserve(self, id, shape, note):
        self.keepouts[id] = (shape, note)
        return shape

    def gap(self, id, first, second, minimum, note):
        a = self.get(first) if isinstance(first, str) else first
        b = self.get(second) if isinstance(second, str) else second
        distance = a.distance(b)
        self.checks.append({"id": id, "actual": round(distance, 6), "minimum": minimum,
                            "units": "mm", "passed": distance + 1e-6 >= minimum,
                            "evidence": "OCP_BRep_minimum_distance", "note": note})

    def allow(self, first, second, note):
        self.allowed_intersections[frozenset((first, second))] = note

    def compound(self):
        return cq.Compound.makeCompound([p.shape for p in self.parts])

    def native(self, exploded=False):
        result = cq.Assembly(name=self.id, metadata={"revision": REVISION, "status": STATUS})
        for i, p in enumerate(self.parts):
            # Sequential assembly-local +Z separation is a visual aid, not an assembly sequence.
            loc = cq.Location((0, 0, i * 32)) if exploded else cq.Location()
            result.add(p.shape, name=p.id, color=cq.Color(*COLORS[p.material]), loc=loc,
                       metadata={"bom_id": p.bom_id, "status": STATUS})
        return result


def build_hub(p):
    a = Assembly("HUB", "Above-water hub lift-off enclosure and removable electronics tray")
    x, y, z = p["hub_exterior_mm"]
    ix, iy, iz = p["hub_usable_mm"]
    shell = box(x, y, z - 8).cut(box(ix, iy, z, bottom=20)).clean()
    a.add("HUB-ENV-01", "Purchased enclosure allocation, open-shell proxy", shell, "VENDOR_ENVELOPE", bom_id="ENC-HUB-01", role="purchased_envelope", notes=["Wall thickness/cavity are conservative allocation, NOT an enclosure design. No seals, vents, latches or penetrators selected."])
    lid = a.add("HUB-ENV-02", "Lift-off lid allocation", box(x, y, 8, bottom=z - 8), "VENDOR_ENVELOPE", bom_id="ENC-HUB-01", role="purchased_envelope")
    mounts = [(-155, -105), (155, -105), (-155, 105), (155, 105)]
    tx, ty, tz = p["tray_mm"]
    tray = drilled_plate(tx, ty, tz, mounts, 6.6, bottom=24)
    pi_origin = (-147.5, -88)
    pi_holes = [(pi_origin[0] + hx, pi_origin[1] + hy) for hx, hy in p["pi_hole_centres_from_lower_left_mm"]]
    for hx, hy in pi_holes:
        tray = tray.cut(cylinder(1.6, tz + 2, (hx, hy, 23)))
    a.add("CAD-HUB-TRAY-01", "Removable machined electronics tray", tray.clean(), features={"size_mm": p["tray_mm"], "tray_mount_holes_mm": mounts, "tray_mount_diameter_mm": 6.6, "pi_support_holes_mm": pi_holes, "pi_support_hole_diameter_mm": 3.2}, notes=["M6 candidate tray hardware and M2.5 Pi fasteners; thread engagement, washer stack, torque and captive nut retention open."])
    for i, (hx, hy) in enumerate(mounts, 1):
        a.add(f"HUB-SPACER-{i}", "Tray spacer, M6 clearance", ring(6, 3.3, 4, (hx, hy, 20)), "SS316L", bom_id="FAST-HUB-M6-SPACER", role="fastener_reference")
        access = a.reserve(f"TOOL-TRAY-{i}", cylinder(p["hand_tool_diameter_mm"] / 2, p["tool_access_height_mm"], (hx, hy, 29)), "Driver approach with lid removed; tray mounting fastener not yet specified")
        a.gap(f"tool_{i}_to_shell", access, shell, 5, "Driver radius to enclosure allocation; no claim about unselected latch geometry")
    pcb = cq.Workplane("XY").box(85, 56, p["pi_pcb_thickness_mm"], centered=(True, True, False)).edges("|Z").fillet(3).val().translate((-105, -60, 36))
    for i, (hx, hy) in enumerate(pi_holes, 1):
        pcb = pcb.cut(cylinder(p["pi_hole_diameter_mm"] / 2, 4, (hx, hy, 35)))
        a.add(f"HUB-PI-STANDOFF-{i}", "8 mm Pi support, M2.5 clearance assumption", ring(3, 1.35, 8, (hx, hy, 28)), "SS316L", bom_id="FAST-PI-M2P5-STANDOFF", role="fastener_reference", features={"height_mm": 8, "nominal_fastener": "M2.5", "location_mm": [hx, hy]}, notes=["Not threaded geometry; PCB maximum screw/head envelope and torque review open"])
    a.add("HUB-CPU-01", "Pi 4 PCB verified plan features only", pcb.clean(), "FR4", bom_id="CPU-01", role="purchased_simplified_part", features={"source_id": "SRC-PI4-MECH", "verified_outline_mm": [85, 56], "verified_corner_radius_mm": 3, "verified_hole_diameter_mm": 2.7, "verified_hole_centres_local_mm": p["pi_hole_centres_from_lower_left_mm"], "placement_lower_left_mm": list(pi_origin), "thickness_assumed_mm": p["pi_pcb_thickness_mm"]})
    a.add("HUB-CPU-COMPONENT-ENV", "Pi connectors/components conservative envelope", box(85, 56, 21, (-105, -60), 38), "VENDOR_ENVELOPE", bom_id="CPU-01", role="purchased_envelope", notes=["NOT connector geometry. Separate USB-C/cable access allocations below."])
    a.add("HUB-DAQ-ENV", "Unselected receive DAQ allocation", box(95, 60, 30, (20, -60), 28), "VENDOR_ENVELOPE", bom_id="DAQ-01", role="purchased_envelope")
    a.add("HUB-POWER-ENV", "Mean Well SD-50A-5 converter reference envelope", box(*p["converter_mm"], centre=(70, 50), bottom=28), "VENDOR_ENVELOPE", bom_id="PWR-HUB-01", role="purchased_envelope", features={"size_mm": p["converter_mm"], "source_id": "SRC-SD50", "verification": "Lead electrical source evidence; terminal geometry unresolved"})
    a.reserve("CONVERTER-TERMINAL-ACCESS", box(159, 28, 40, (70, -13), 28), "Provisional converter terminal approach between DAQ and converter, wiring selection open")
    a.add("HUB-STORAGE-ENV", "Storage allocation", box(80, 55, 15, (-90, 30), 28), "VENDOR_ENVELOPE", bom_id="STORAGE-01", role="purchased_envelope")
    guide = box(55, 22, 12, (-105, 105), 28)
    for xx in (-120, -105, -90):
        guide = guide.cut(cylinder(5, 24, (xx, 93, 40), "y"))
    a.add("PRINT-HUB-GUIDE-01", "Internal loose cable comb, no strain or retention duty", guide.clean(), "PETG", printable=True, features={"groove_diameter_mm": 10, "groove_pitch_mm": 15}, notes=["Internal dry fit prototype only; never substitute for bolted tether strain relief"])
    usb = a.reserve("USB-C-PLUG-ACCESS", box(35, 32, 24, (-127, -106), 34), "Provisional USB-C mating plug and hand access, not verified port outline")
    a.gap("usb_c_allocation_to_shell", usb, shell, 5, "Checks cavity fit of plug allocation, not connector compatibility")
    a.reserve("LID-LIFT", box(x, y, p["hub_lid_lift_mm"], bottom=z), "Keep this volume clear for lift-off lid removal")
    usable = a.reserve("USABLE-INTERIOR", box(ix, iy, iz, bottom=20), "Allocation container, NOT an exclusion volume; exported for review only")
    a.reserve("TRAY-EXTRACTION", box(tx, ty, 220, bottom=z), "Remove lid, disconnect harness and remove tray vertically; wiring slack unverified")
    for part_id in ("HUB-CPU-COMPONENT-ENV", "HUB-DAQ-ENV", "HUB-POWER-ENV", "HUB-STORAGE-ENV"):
        a.gap(f"{part_id}_lid_headroom", part_id, lid, 80, "BRep headroom below closed lid")
    return a


def build_wet(p):
    a = Assembly("WET", "Passive camera and single receive head; non-pressure metal support")
    base_holes = [(-5, -120), (255, -120), (-5, 180), (255, 180)]
    a.add("CAD-WET-BASE-01", "Perforated wet support plate", drilled_plate(300, 350, 8, base_holes, 8.5, (125, 30)), "SS316L", critical=True, features={"size_mm": [300, 350, 8], "mount_holes_mm": base_holes, "mount_hole_diameter_mm": 8.5}, notes=["M8 candidate fasteners; farm loads, galvanic isolation and lifting proof open"])
    a.add("WET-CAMERA-ENV", "FICTIONAL purchased camera/housing integration envelope", cylinder(p["camera_diameter_mm"] / 2, p["camera_length_mm"], (0, 0, 100), "x"), "VENDOR_ENVELOPE", bom_id="CAM-01", role="purchased_envelope", features={"diameter_mm": p["camera_diameter_mm"], "length_mm": p["camera_length_mm"], "related_bom_ids": ["WET-CAM-001", "WET-PRESSURE-001"]}, notes=["Blue Robotics 4in watertight enclosure is a pressure-boundary CANDIDATE only, not selected exact SKU. This 110 mm cylinder is not vendor geometry, a tube, a seal, or a pressure design."])
    for i, xx in enumerate((47, 187), 1):
        a.add(f"CAD-WET-CAMERA-COLLAR-{i}", "Metal clearance collar with integral support foot", collar_x(xx, 0, 100, p["camera_clamp_bore_mm"] / 2, 65, 16), "SS316L", bom_id="CAD-WET-CAMERA-COLLAR-01", critical=True, features={"bore_mm": p["camera_clamp_bore_mm"], "outside_diameter_mm": 130, "width_mm": 16, "axis_x_mm": xx}, notes=["Retention/liner and split-clamp fasteners unresolved; clearance collar is NOT a proven restraint"])
        a.gap(f"camera_collar_{i}_radial_gap", "WET-CAMERA-ENV", f"CAD-WET-CAMERA-COLLAR-{i}", 1.3, "Nominal measured radial gap, worst-case tolerance checked separately")
    a.add("WET-HYDROPHONE-ENV", "Unselected receive hydrophone envelope", cylinder(p["hydrophone_diameter_mm"] / 2, p["hydrophone_length_mm"], (75, 140, 60), "x"), "VENDOR_ENVELOPE", bom_id="HYD-01", role="purchased_envelope")
    for i, xx in enumerate((90, 145), 1):
        a.add(f"CAD-WET-HYD-COLLAR-{i}", "Receive collar and stand, no acoustic isolation claim", collar_x(xx, 140, 60, p["hydrophone_clamp_bore_mm"] / 2, 23, 12), "SS316L", bom_id="CAD-WET-HYD-COLLAR-01", critical=True, features={"bore_mm": p["hydrophone_clamp_bore_mm"], "width_mm": 12})
        a.gap(f"hydrophone_collar_{i}_radial_gap", "WET-HYDROPHONE-ENV", f"CAD-WET-HYD-COLLAR-{i}", 0.9, "Mechanical clearance only; cable microphonics/calibration open")
    a.reserve("OPTICAL-AXIS", cylinder(42, 160, (p["camera_length_mm"], 0, 100), "x"), "Illustrative clear optical axis cylinder, NOT calibrated field of view")
    a.reserve("CAMERA-AXIAL-REMOVAL", cylinder(68, 300, (p["camera_length_mm"] + 1, 0, 100), "x"), "Unclamp and withdraw purchased boundary along +X; remove optional wiper first")
    a.reserve("REAR-CONNECTOR-ACCESS", box(90, 150, 130, (-60, 0), 35), "Cable/connector bend and removal allocation; exact penetrator configuration unresolved")
    a.gap("camera_receive_surface_spacing", "WET-CAMERA-ENV", "WET-HYDROPHONE-ENV", 65, "Geometric spacing only, not acoustic isolation")
    return a


def build_array(p):
    a = Assembly("ARRAY", "Optional four-hydrophone square research fixture; synchronized DAQ not selected", True)
    pitch = p["array_pitch_mm"]
    h = pitch / 2
    for side in (-1, 1):
        a.add(f"CAD-ARRAY-X-{side:+d}".replace("+", "P").replace("-1", "N1"), "Square array cross rail", box(pitch + 40, 20, 20, (0, side * h)), critical=True, bom_id="CAD-ARRAY-X-RAIL", features={"length_mm": pitch + 40, "section_mm": [20, 20]})
        a.add(f"CAD-ARRAY-Y-{side:+d}".replace("+", "P").replace("-1", "N1"), "Square array side rail", box(20, pitch - 20, 20, (side * h, 0)), critical=True, bom_id="CAD-ARRAY-Y-RAIL", features={"length_mm": pitch - 20, "section_mm": [20, 20]})
    locations = [(-h, -h), (h, -h), (h, h), (-h, h)]
    for i, (xx, yy) in enumerate(locations, 1):
        a.add(f"CAD-ARRAY-SENSOR-COLLAR-{i}", "Unloaded collar geometry, restraint hardware unresolved", ring(24, p["hydrophone_clamp_bore_mm"] / 2, 18, (xx, yy, 22)), "SS316L", bom_id="CAD-ARRAY-SENSOR-COLLAR-01", critical=True, features={"bore_mm": p["hydrophone_clamp_bore_mm"], "centre_xy_mm": [xx, yy]})
        a.add(f"ARRAY-HYD-{i}", "Research-only hydrophone envelope", cylinder(p["hydrophone_diameter_mm"] / 2, p["hydrophone_length_mm"], (xx, yy, 24)), "VENDOR_ENVELOPE", bom_id="HYD-ARRAY-01", role="purchased_envelope")
        a.gap(f"array_collar_{i}_gap", f"CAD-ARRAY-SENSOR-COLLAR-{i}", f"ARRAY-HYD-{i}", 0.9, "Channel centres parameterized; no synchronization accuracy implied")
    for i, j in ((1, 2), (2, 3), (3, 4), (4, 1)):
        a.gap(f"array_hyd_{i}_{j}_surface_gap", f"ARRAY-HYD-{i}", f"ARRAY-HYD-{j}", pitch - p["hydrophone_diameter_mm"] - 1e-6, "BRep verifies configured square side pitch minus sensor diameter")
    a.reserve("ARRAY-CABLE-OVERHEAD", box(pitch + 100, pitch + 100, 100, bottom=150), "Research cable breakout space; each channel must share the selected acquisition clock")
    return a


def build_wiper(p):
    a = Assembly("WIPER", "Optional unpowered wiper geometry, parked arm and guarding study", True)
    a.add("CAD-WIPER-GUARD-01", "Metal annular optical guard", ring(74, 64, 8, (260, 0, 100), "x"), "SS316L", critical=True, features={"outer_diameter_mm": 148, "inner_diameter_mm": 128, "axial_width_mm": 8}, notes=["Guard does not prove finger/debris safety; unpowered reference only"])
    # The guard mount is a single reference bridge above the camera envelope.
    bridge = box(45, 24, 6, (247.5, 0), 177)
    a.add("CAD-WIPER-MOTOR-BRIDGE-01", "Motor and guard mounting bridge", bridge, "SS316L", critical=True, notes=["Fastener interfaces and housing-side attachment require selected motor and support design"])
    a.add("WIPER-MOTOR-ENV", "Unselected sealed motor allocation, not populated", box(40, 35, 30, (240, 0), 185), "VENDOR_ENVELOPE", bom_id="WIPER-MOTOR-01", role="purchased_envelope")
    a.add("WIPER-PIVOT-ENV", "Axis-X pivot allocation at parked angle", cylinder(6, 12, (269, 0, 170), "x"), "VENDOR_ENVELOPE", bom_id="WIPER-PIVOT-01", role="purchased_envelope")
    arm = box(6, 70, 8, (284, 35), 166).cut(cylinder(2.75, 8, (280, 5, 170), "x"))
    a.add("CAD-WIPER-ARM-01", "Parked 70 mm metal wiper arm", arm.clean(), "SS316L", critical=True, features={"reach_mm": 70, "section_mm": [6, 8], "pivot_hole_mm": 5.5}, notes=["Unpowered pose study. Motor torque, shaft seal, hard stops, blade force, snagging and independent inhibit open"])
    a.add("WIPER-BLADE-01", "Purchased/moulded elastomer blade allocation", box(8, 5, 34, (285, 72.5), 136), "ELASTOMER", bom_id="WIPER-BLADE-01", role="purchased_simplified_part")
    optical = a.reserve("OPTICAL-CLEAR", cylinder(42, 50, (250, 0, 100), "x"), "Optical axis cylinder in parked pose only; NOT field of view")
    a.reserve("WIPER-SWEEP", cylinder(82, 18, (274, 0, 170), "x"), "Full circular sweep envelope conservative for any commanded angle. Must inhibit for service; not a motion simulation")
    a.gap("parked_arm_to_optical_axis", "CAD-WIPER-ARM-01", optical, 20, "Only parked arm clearance; sweeping blade intentionally crosses optics")
    a.gap("guard_to_optical_axis", "CAD-WIPER-GUARD-01", optical, 20, "Annular optical clearance")
    return a


def build_projector(p):
    a = Assembly("PROJECTOR", "Optional inhibited projector mount and elastomer isolation geometry", True)
    a.add("CAD-PROJECTOR-BASE-01", "Projector support plate, not a pressure part", drilled_plate(230, 200, 8, [(-15, -80), (175, -80), (-15, 80), (175, 80)], 8.5, (80, 0)), "SS316L", critical=True)
    a.add("PROJECTOR-ENV", "Unselected projector envelope, electrically absent by default", cylinder(60, 160, (0, 0, 100), "x"), "VENDOR_ENVELOPE", bom_id="ACT-PROJECTOR-01", role="purchased_envelope", features={"diameter_assumed_mm": 120, "length_assumed_mm": 160}, notes=["No frequency, power, depth, source-level or biological-safe claim. Not a historical pinger selection."])
    for i, xx in enumerate((28, 118), 1):
        a.add(f"CAD-PROJECTOR-COLLAR-{i}", "Metal support collar", collar_x(xx, 0, 100, 70, 80, 16), "SS316L", bom_id="CAD-PROJECTOR-COLLAR-01", critical=True, features={"bore_mm": 140, "outside_diameter_mm": 160})
        a.add(f"PROJECTOR-ISOLATOR-{i}", "Generic elastomer isolation annulus, uncompressed", ring(69.5, 60.8, 14, (xx + 1, 0, 100), "x"), "ELASTOMER", bom_id="ACT-ISOLATOR-01", role="purchased_simplified_part", notes=["0.8 mm inner/0.5 mm outer clearance is a geometry study, not assembled preload. Durometer, compression, restraint, creep and modal/transmissibility tests open."])
        a.gap(f"projector_isolator_{i}_inner_gap", "PROJECTOR-ENV", f"PROJECTOR-ISOLATOR-{i}", 0.75, "Clearance reference before actual isolation selection")
        a.gap(f"projector_isolator_{i}_outer_gap", f"PROJECTOR-ISOLATOR-{i}", f"CAD-PROJECTOR-COLLAR-{i}", 0.45, "Clearance reference, not a compressed retention assembly")
    a.reserve("PROJECTOR-AXIAL-SERVICE", cylinder(85, 230, (165, 0, 100), "x"), "Reserved extraction space only; mechanical distance is not an acoustic safety boundary")
    return a


def build_reef(p):
    a = Assembly("REEF", "Above-water REEF frame with solar, battery, electronics and wired probe allocation")
    for i, (xx, yy) in enumerate([(-250, -150), (250, -150), (-250, 150), (250, 150)], 1):
        # Hollow sections are actual CAD solids; welds/bolts are not claimed designed.
        post = box(40, 40, 970, (xx, yy), 20).cut(box(34, 34, 972, (xx, yy), 19))
        a.add(f"CAD-REEF-POST-{i}", "40x40x3 hollow frame post", post.clean(), critical=True, bom_id="CAD-REEF-POST-01", features={"section_mm": [40, 40, 3], "length_mm": 970}, notes=["Marine frame load/buckling/wind/wave/fatigue and joining design open; never print"])
    for z, label in ((0, "BASE"), (990, "SOLAR")):
        for i, yy in enumerate((-150, 150), 1):
            a.add(f"CAD-REEF-{label}-RAIL-{i}", "Frame cross rail", box(570, 40, 20, (0, yy), z), critical=True, bom_id=f"CAD-REEF-{label}-RAIL-01", features={"size_mm": [570, 40, 20]})
    for i, xx in enumerate((-250, 250), 1):
        a.add(f"CAD-REEF-BASE-TIE-{i}", "Base side tie", box(40, 260, 20, (xx, 0)), critical=True, bom_id="CAD-REEF-BASE-TIE-01")
    sx, sy, sz = p["solar_mm"]
    a.add("REEF-SOLAR-ENV", "Victron SPM040401200 40W historical reference envelope", box(sx, sy, sz, bottom=1010), "VENDOR_ENVELOPE", bom_id="SOLAR-01", role="purchased_envelope", features={"size_mm": p["solar_mm"], "source_id": "SRC-VICTRON-SOLAR", "vendor_mass_kg": 3.1, "tilt_degrees_assumed": 0, "panel_overhang_from_support_y_mm": sy / 2 - 170}, notes=["Primary PDF p1 verifies 425x668x25, rotated here. Historical drawing reference; current availability/obsolescence unresolved. No purchase approval.", "Horizontal packaging pose only, not an energy-optimal or wind-qualified installation. Clamp zones and junction box unresolved. Nominal support overhang 42.5 mm each Y side."])
    # Trays span to the structural posts but do not invent battery or box mounting holes.
    a.add("CAD-REEF-BATTERY-SHELF-01", "Battery shelf, edge stops and rated restraint needed", box(460, 210, 5, (0, -70), 90), critical=True, features={"size_mm": [460, 210, 5]})
    bx, by, bz = p["battery_mm"]
    a.add("REEF-BATTERY-ENV", "Victron BAT512050610 conservative manual envelope", box(bx, by, bz, (0, -70), 100), "VENDOR_ENVELOPE", bom_id="BAT-01", role="purchased_envelope", features={"size_mm": p["battery_mm"], "source_id": "SRC-VICTRON-BATTERY", "vendor_mass_kg": 7.0, "terminal_thread": "M8"}, notes=["Manual HxWxD199x188x147, mapped XYZ188x147x199. Drawing Rev01 and manual differ in detail; reconcile selected revision before fabrication.", "Upright pose. Terminal/lug positions, fuse, isolation, ventilation and rated restraint remain open. 7 kg vendor nominal mass, not geometry-derived."])
    terminal = a.reserve("BATTERY-TERMINAL-TOOL-BEND", box(bx + 20, by + 20, p["battery_terminal_service_mm"], (0, -70), 100 + bz), "40 mm provisional terminal/lug/driver allowance above battery; exact M8 lug and selected cable radius require review")
    for i, xx in enumerate((-114, 114), 1):
        a.add(f"CAD-REEF-BATTERY-STOP-{i}", "Metal battery lateral stop", box(5, 170, 35, (xx, -70), 95), "SS316L", critical=True, bom_id="CAD-REEF-BATTERY-STOP-01")
        a.gap(f"battery_stop_{i}_gap", f"CAD-REEF-BATTERY-STOP-{i}", "REEF-BATTERY-ENV", 10, "Space for selected isolation pad; not a proven restraint")
    a.reserve("BATTERY-REMOVAL", box(bx + 30, 320, bz + 30, (0, -270), 95), "Disconnect/fuse-safe battery withdrawal toward -Y; strap and connector selection pending")
    a.add("CAD-REEF-BOX-SHELF-01", "Electronics enclosure shelf", box(460, 240, 8, (0, 80), 412), critical=True)
    ex, ey, ez = p["reef_box_mm"]
    shell = box(ex, ey, ez - 8, (0, 80), 420).cut(box(ex - 30, ey - 30, ez, (0, 80), 432)).clean()
    a.add("REEF-BOX-ENV", "Electronics enclosure shell allocation", shell, "VENDOR_ENVELOPE", bom_id="ENC-REEF-01", role="purchased_envelope", notes=["Conservative cavity proxy; no ingress protection or fabrication claim"])
    a.add("REEF-BOX-LID-ENV", "Electronics lift-off lid allocation", box(ex, ey, 8, (0, 80), 420 + ez - 8), "VENDOR_ENVELOPE", bom_id="ENC-REEF-01", role="purchased_envelope")
    a.add("CAD-REEF-ELECTRONICS-TRAY-01", "REEF controller/radio tray", drilled_plate(250, 170, 4, [(-110, 10), (110, 10), (-110, 150), (110, 150)], 4.5, (0, 80), 436), features={"size_mm": [250, 170, 4], "mount_hole_diameter_mm": 4.5})
    a.add("REEF-MCU-ENV", "ESP32-DevKitC-32E provisional board envelope", box(*p["esp32_envelope_mm"], centre=(-60, 65), bottom=448), "VENDOR_ENVELOPE", bom_id="MCU-01", role="purchased_envelope", features={"size_mm": p["esp32_envelope_mm"], "mount_holes_verified": False})
    a.add("REEF-RADIO-ENV", "RAK3272S EU868 candidate, provisional envelope", box(*p["rak3272s_envelope_mm"], centre=(40, 65), bottom=448), "VENDOR_ENVELOPE", bom_id="RADIO-01", role="purchased_envelope", features={"size_mm": p["rak3272s_envelope_mm"], "mount_holes_verified": False, "source_id": "SRC-RAK", "documented_plan_mm": [25.4, 32.3]}, notes=["40x30x15 mm is a conservative provisional allocation. Source board/module wording and header/antenna height are unresolved; not detailed vendor CAD."])
    a.add("REEF-CHARGE-ENV", "Victron SCC075010060R MPPT 75/10 reference envelope", box(*p["mppt_mm"], centre=(25, 120), bottom=444), "VENDOR_ENVELOPE", bom_id="CHARGER-01", role="purchased_envelope", features={"size_mm": p["mppt_mm"], "source_id": "SRC-MPPT", "verification": "Lead electrical source evidence; terminal and mounting holes unresolved"})
    a.reserve("MPPT-TERMINAL-APPROACH", box(113, 30, 70, (25, 155), 444), "Provisional terminal/driver approach beside controller; exact wire exits and 3D cable bends remain open")
    a.add("REEF-ANTENNA-ENV", "Above-water antenna and support allocation", cylinder(8, 230, (290, 310, 1000)), "VENDOR_ENVELOPE", bom_id="ANT-REEF-01", role="purchased_envelope", notes=["RF clearance only; gain, cable loss, solar shading and range unverified"])
    a.add("REEF-PROBE-ENV", "Wired submerged environmental probe envelope", cylinder(15, 180, (300, 310, -450)), "VENDOR_ENVELOPE", bom_id="PROBE-01", role="purchased_envelope")
    a.add("REEF-PROBE-CABLE-ENV", "Straight probe cable route allocation", cylinder(4, 1070, (300, 310, -270)), "CABLE_ENVELOPE", bom_id="H-05", role="routing_envelope", notes=["Not a terminated harness; add drip loop, gland, conditioning and minimum bend review after selection"])
    service = a.reserve("REEF-BOX-LID-LIFT", box(ex, ey, 180, (0, 80), 420 + ez), "Vertical electronics service volume below panel")
    a.gap("reef_lid_service_to_solar", service, "REEF-SOLAR-ENV", 200, "BRep clearance for lid lift under panel")
    a.gap("reef_battery_to_electronics_shelf", "REEF-BATTERY-ENV", "CAD-REEF-BOX-SHELF-01", 80, "Battery terminal/tool headroom assumption")
    a.gap("reef_battery_terminal_keepout_to_shelf", terminal, "CAD-REEF-BOX-SHELF-01", 60, "40 mm terminal/tool volume plus residual physical shelf clearance")
    a.gap("reef_mppt_to_closed_lid", "REEF-CHARGE-ENV", "REEF-BOX-LID-ENV", 5, "Packaging only, not ventilation or cooling qualification")
    a.gap("reef_mcu_to_radio", "REEF-MCU-ENV", "REEF-RADIO-ENV", 30, "Cable/header and tool allocation, pin/hole locations unresolved")
    return a


def build_farm(p):
    a = Assembly("FARM", "Farm pipe attachment study, metal strain relief and independent retrieval allocation")
    a.add("FARM-PIPE-ENV", "Fictional 60 mm farm rail, NOT surveyed infrastructure", cylinder(30, 300, (0, -150, 100), "y"), "VENDOR_ENVELOPE", bom_id="SITE-PIPE-01", role="site_envelope")
    a.add("CAD-FARM-BACKPLATE-01", "Attachment backplate", drilled_plate(180, 250, 8, [(-70, -100), (70, -100), (-70, 100), (70, 100)], 10.5), "SS316L", critical=True, features={"size_mm": [180, 250, 8], "mount_hole_diameter_mm": 10.5})
    for i, yy in enumerate((-80, 60), 1):
        saddle = ring(42, 31, 20, (0, yy, 100), "y")
        lower = saddle.intersect(box(100, 22, 50, (0, yy + 10), 49)).clean()
        upper = saddle.intersect(box(100, 22, 50, (0, yy + 10), 102)).clean()
        foot = box(30, 20, 54, (0, yy + 10), 8)
        lower = lower.fuse(foot).clean()
        a.add(f"CAD-FARM-LOWER-SADDLE-{i}", "Split lower metal saddle, 4 mm split gap", lower, "SS316L", critical=True, bom_id="CAD-FARM-LOWER-SADDLE-01", features={"bore_mm": 62, "pipe_assumed_diameter_mm": 60, "split_gap_mm": 4}, notes=["Through-bolt ears, purchased U-bolt/strap choice and slip/crush/load calculations remain open"])
        a.add(f"CAD-FARM-UPPER-SADDLE-{i}", "Split upper metal saddle, fastening unresolved", upper, "SS316L", critical=True, bom_id="CAD-FARM-UPPER-SADDLE-01")
        a.gap(f"farm_pipe_saddle_{i}_gap", "FARM-PIPE-ENV", f"CAD-FARM-LOWER-SADDLE-{i}", 0.95, "Pipe diameter is a site assumption, not mounting approval")
    lug = box(65, 8, 65, (55, 0), 8).cut(cylinder(8, 10, (55, -5, 54), "y"))
    a.add("CAD-FARM-RETRIEVAL-LUG-01", "Metal secondary retrieval eye concept", lug.clean(), "SS316L", critical=True, features={"eye_diameter_mm": 16, "plate_thickness_mm": 8, "eye_centre_z_mm": 54}, notes=["No safe working load. Independent rated retrieval hardware, eye edge distance, joint and corrosion review required; never print"])
    # Cable held in metal clamp; 0.5 mm radial design clearance is not compression/preload.
    a.add("FARM-TETHER-ENV", "8 mm tether allocation", cylinder(p["cable_diameter_mm"] / 2, 180, (-60, -90, 23), "y"), "CABLE_ENVELOPE", bom_id="H-02", role="routing_envelope")
    for i, yy in enumerate((-55, 35), 1):
        clamp = box(25, 20, 30, (-60, yy), 8).cut(cylinder(4.5, 22, (-60, yy - 11, 23), "y")).clean()
        a.add(f"CAD-FARM-STRAIN-RELIEF-{i}", "Bolted metal tether clamp geometry", clamp, "SS316L", critical=True, bom_id="CAD-FARM-STRAIN-RELIEF-01", features={"bore_mm": 9, "block_mm": [25, 20, 30]}, notes=["Compression sleeve, split, bolt pattern, cable crush and pullout test open; not a qualified strain relief"])
        a.gap(f"tether_clamp_{i}_gap", "FARM-TETHER-ENV", f"CAD-FARM-STRAIN-RELIEF-{i}", 0.45, "Nominal envelope gap, not a strain-retention proof")
    a.reserve("FARM-HAND-ACCESS", box(240, 300, 180, bottom=160), "Assumed hand/driver space above farm mounting; survey required")
    return a


def build_assembly_fixture(p):
    a = Assembly("ASSEMBLY_FIXTURE", "Dry-bench Pi pattern template and cable bend-check fixture")
    holes = [(x - 42.5, y - 28) for x, y in p["pi_hole_centres_from_lower_left_mm"]]
    template = drilled_plate(95, 66, 4, holes, p["fixture_hole_mm"])
    a.add("PRINT-PI-TEMPLATE-01", "Pi support-pattern alignment template, not drill tooling", template, "PETG", printable=True, features={"size_mm": [95, 66, 4], "hole_centres_mm": holes, "hole_diameter_mm": p["fixture_hole_mm"], "verified_pattern_source": "SRC-PI4-MECH"}, notes=["Do not drill a PCB. Verify print scale with callipers; no hardened guide bushings or process accuracy claim"])
    r = p["cable_bend_radius_mm"]
    radius = p["cable_diameter_mm"] / 2
    # A true curved sweep: straight, tangent 90-degree circular arc, straight.
    path = (cq.Workplane("XY").moveTo(120, 0).lineTo(180, 0)
            .threePointArc((180 + r / math.sqrt(2), r - r / math.sqrt(2)), (180 + r, r))
            .lineTo(180 + r, r + 80).wire())
    cable = cq.Workplane("YZ", origin=(120, 0, 12)).circle(radius).sweep(path.translate((0, 0, 12))).val()
    a.add("FIXTURE-CABLE-BEND-ENV", "Synthetic cable sweep at assumed radius", cable, "CABLE_ENVELOPE", bom_id="H-02", role="routing_envelope", features={"centreline_arc_radius_mm": r, "diameter_mm": p["cable_diameter_mm"], "arc_angle_degrees": 90, "straight_lengths_mm": [60, 80]})
    # The mandrel surface is at R - cable radius, so centreline allowance matches the arc.
    mandrel = cylinder(r - radius - 0.5, 16, (180, r, 0))
    a.add("PRINT-CABLE-RADIUS-GAUGE-01", "Bench bend-radius mandrel; never structural or pressure tooling", mandrel, "PETG", printable=True, features={"mandrel_radius_mm": r - radius - 0.5, "cable_centreline_radius_mm": r, "radial_test_gap_mm": 0.5, "height_mm": 16}, notes=["Assumed 6D minimum plus tolerance margin; check selected cable datasheet before use"])
    a.gap("bend_gauge_to_cable", "PRINT-CABLE-RADIUS-GAUGE-01", "FIXTURE-CABLE-BEND-ENV", 0.45, "BRep distance from actual swept cable to radius gauge")
    return a


def build_calibration_fixture(p):
    a = Assembly("CALIBRATION_FIXTURE", "Passive sensor positioning rail and optical scale target holder, no calibration claim")
    a.add("CAD-CAL-RAIL-01", "600 mm bench spacing rail", box(600, 35, 20), features={"length_mm": 600, "section_mm": [35, 20]}, notes=["Datum marks defined in drawing; straightness, distance and alignment require measurement"])
    for i, xx in enumerate((-200, 200), 1):
        a.add(f"CAD-CAL-SLIDER-{i}", "Bench positioning slider", drilled_plate(60, 70, 10, [(xx - 20, 0), (xx + 20, 0)], 6.6, (xx, 0), 20), bom_id="CAD-CAL-SLIDER-01", features={"centre_x_mm": xx, "mount_hole_diameter_mm": 6.6})
        a.add(f"CAD-CAL-COLLAR-{i}", "Sensor position collar", ring(24, 17, 18, (xx, 0, 32)), "SS316L", bom_id="CAD-CAL-COLLAR-01")
        a.add(f"CAL-SENSOR-ENV-{i}", "Receive sensor positioning envelope only", cylinder(16, 100, (xx, 0, 34)), "VENDOR_ENVELOPE", bom_id="HYD-01", role="purchased_envelope")
    a.gap("calibration_surface_separation", "CAL-SENSOR-ENV-1", "CAL-SENSOR-ENV-2", 368 - 1e-6, "400 mm centre spacing; no certified distance or acoustic calibration")
    holder = box(100, 22, 16, (0, 110)).cut(box(82, 4, 14, (0, 110), 4))
    a.add("PRINT-CAL-TARGET-HOLDER-01", "Dry-bench optical target card holder", holder.clean(), "PETG", printable=True, features={"slot_mm": [82, 4, 12]}, notes=["Holds a separately measured passive target; target artwork and calibration not supplied"])
    return a


def build_pressure_positioning(p):
    a = Assembly("PRESSURE_POSITIONING_FIXTURE", "Open handling/positioning cradle for an independently approved pressure-test facility")
    mount_holes = [(-15, -85), (265, -85), (-15, 85), (265, 85)]
    base = drilled_plate(360, 220, 8, mount_holes, 10.5, (125, 0))
    for xx in (-10, 60, 125, 190, 260):
        base = base.cut(box(14, 150, 10, (xx, 0), -1))
    a.add("CAD-PRESS-POS-BASE-01", "Open drained positioning plate, NOT containment", base.clean(), "SS316L", critical=True, features={"size_mm": [360, 220, 8], "drain_slot_width_mm": 14, "mount_holes_mm": mount_holes, "mount_hole_diameter_mm": 10.5}, notes=["No lid, seals, pressure fittings, pressure reaction frame or containment. Facility must approve materials, venting, buoyancy, restraints and clearance. No pressure rating."])
    for i, (hx, hy) in enumerate(mount_holes, 1):
        probe = cylinder(5.20, 8, (hx, hy, 0))
        rim = ring(6.25, 5.30, 8, (hx, hy, 0))
        void_intersection = base.intersect(probe).Volume()
        rim_fraction = base.intersect(rim).Volume() / rim.Volume()
        a.checks.append({"id": f"pressure_base_mount_hole_{i}_present", "passed": void_intersection < 1e-6 and rim_fraction > 0.99,
                         "evidence": "OCP_exact_cylindrical_void_and_surrounding_material", "centre_xy_mm": [hx, hy],
                         "nominal_hole_diameter_mm": 10.5, "probe_overlap_mm3": void_intersection, "retained_rim_fraction": rim_fraction})
    for i, xx in enumerate((37, 197), 1):
        full = collar_x(xx, 0, 100, 57.5, 68, 16)
        lower = full.intersect(box(20, 160, 92, (xx + 8, 0), 8)).clean()
        a.add(f"CAD-PRESS-POS-SADDLE-{i}", "Open-top metal cradle, no pressure reaction duty", lower, "SS316L", critical=True, bom_id="CAD-PRESS-POS-SADDLE-01", features={"bore_mm": 115, "width_mm": 16, "support_axis_z_mm": 100})
    a.add("PRESS-POS-CAMERA-ENV", "Fictional housing positioning allocation", cylinder(p["camera_diameter_mm"] / 2, p["camera_length_mm"], (0, 0, 100), "x"), "VENDOR_ENVELOPE", bom_id="CAM-01", role="purchased_envelope")
    a.reserve("FACILITY-CHAMBER-REQUIRED-SPACE", box(500, 360, 320, (125, 0), -20), "Minimum packaging request only, NOT a pressure chamber or authorization. Actual certified facility/chamber not selected.")
    for i in (1, 2):
        a.gap(f"pressure_positioning_saddle_{i}_gap", "PRESS-POS-CAMERA-ENV", f"CAD-PRESS-POS-SADDLE-{i}", 2.45, "Clearance for chosen pad; pressure resistance is NOT tested or calculated")
    return a


def build_top(assemblies, p, research):
    a = Assembly("TOP_RESEARCH" if research else "TOP_PASSIVE", "Illustrative spatial arrangement, water datum Z=0; NOT a farm installation drawing", research)
    placements = {"HUB": (-700, 0, 700), "WET": (0, 0, -600), "REEF": (800, 0, 0), "FARM": (0, 0, 500)}
    if research:
        placements.update({"ARRAY": (0, 800, -650), "PROJECTOR": (-450, 600, -650), "WIPER": (0, 0, -600)})
    for source in assemblies:
        if source.id not in placements:
            continue
        offset = placements[source.id]
        for part in source.parts:
            a.parts.append(Part(source.id + "__" + part.id, part.bom_id, part.description,
                                part.shape.translate(offset), part.material, part.role, False,
                                part.critical_load, {"local_part_id": part.id, "assembly_translation_mm": list(offset)}, part.notes))
        for name, (shape, note) in source.keepouts.items():
            a.reserve(source.id + "__" + name, shape.translate(offset), note)
    a.reserve("WATER-DATUM-NOT-SURVEY", box(2100, 1100, 0.5, (250, 200), -0.25), "Z=0 schematic water datum only; tides/waves/freeboard/site unselected")
    a.reserve("WET-HUB-TETHER-CORRIDOR", box(160, 130, 1400, (-260, -220), -650), "Reserved route, NOT terminated cable geometry; use >= assumed cable bend radius, drip loop and independent strain relief")
    a.reserve("RETRIEVAL-CORRIDOR", box(80, 80, 1150, (100, -100), -580), "Independent rated secondary retrieval allocation; line, shackle and load path not yet specified")
    hub_service = a.keepouts["HUB__LID-LIFT"][0]
    reef_parts = cq.Compound.makeCompound([part.shape for part in a.parts if part.id.startswith("REEF__")])
    a.gap("top_hub_lid_service_to_reef", hub_service, reef_parts, 700, "True 3D distance for illustrative placement, not a surveyed service route")
    wet_removal = a.keepouts["WET__CAMERA-AXIAL-REMOVAL"][0]
    a.gap("top_camera_removal_to_reef", wet_removal, reef_parts, 100, "Camera service corridor to passive REEF; optional wiper must be removed first")
    a.checks.append({"id": "top_rf_above_water_datum", "actual": a.get("REEF__REEF-ANTENNA-ENV").BoundingBox().zmin,
                     "minimum": 500, "units": "mm", "passed": a.get("REEF__REEF-ANTENNA-ENV").BoundingBox().zmin >= 500,
                     "evidence": "OCP_BRep_bbox", "note": "Schematic water datum only, not minimum real-world freeboard"})
    return a, placements


def geometry_checks(a):
    results = []
    for part in a.parts:
        solids = part.shape.Solids()
        shell_closed = all(shell.Closed() for solid in solids for shell in solid.Shells())
        ok = bool(solids) and part.shape.isValid() and part.shape.Volume() > 1e-6 and shell_closed
        results.append({"id": f"{part.id}_brep_valid_closed_solids", "passed": ok,
                        "solid_count": len(solids), "closed_shells": shell_closed,
                        "volume_mm3": round(part.shape.Volume(), 6), "evidence": "OCP_BRepCheck_and_topological_shell_closure"})
    # BBox broad phase followed by exact intersection volume. Face contacts do not fail.
    intersections = []
    for i, first in enumerate(a.parts):
        fb = bbox(first.shape)
        for second in a.parts[i + 1:]:
            sb = bbox(second.shape)
            if any(min(fb["max_mm"][k], sb["max_mm"][k]) - max(fb["min_mm"][k], sb["min_mm"][k]) <= 1e-5 for k in range(3)):
                continue
            volume = first.shape.intersect(second.shape).Volume()
            if volume > 1e-4:
                reason = a.allowed_intersections.get(frozenset((first.id, second.id)))
                intersections.append({"parts": [first.id, second.id], "volume_mm3": round(volume, 6), "allowed_reason": reason})
    results.append({"id": f"{a.id}_physical_interference", "passed": all(x["allowed_reason"] for x in intersections),
                    "evidence": "OCP_pairwise_exact_common_volume_after_bbox_broad_phase", "intersections": intersections,
                    "note": "Keepout/reference allocation volumes excluded; touching faces allowed; not structural joint validation"})
    for name, (shape, _) in a.keepouts.items():
        results.append({"id": f"{name}_keepout_brep_valid", "passed": shape.isValid() and shape.Volume() > 0,
                        "evidence": "OCP_BRepCheck", "volume_mm3": round(shape.Volume(), 6)})
    return results + a.checks


def step_roundtrip(path, original):
    text = path.read_text(errors="replace")
    mm_unit = "SI_UNIT(.MILLI.,.METRE.)" in text
    imported = cq.importers.importStep(str(path)).val()
    before, after = bbox(original), bbox(imported)
    max_delta = max(abs(before[key][i] - after[key][i]) for key in ("min_mm", "max_mm") for i in range(3))
    delta_volume = abs(original.Volume() - imported.Volume())
    tolerance = max(1e-3, original.Volume() * 1e-8)
    expected_solids = len(original.Solids())
    actual_solids = len(imported.Solids())
    result = {"id": path.stem + "_step_roundtrip", "passed": mm_unit and imported.isValid() and max_delta <= 1e-4 and delta_volume <= tolerance and expected_solids == actual_solids,
              "evidence": "Fresh_STEP_import_OCP_BRepCheck_bbox_volume_solid_count", "units_mm_in_step": mm_unit,
              "bbox_max_delta_mm": max_delta, "volume_delta_mm3": delta_volume,
              "volume_tolerance_mm3": tolerance, "expected_solids": expected_solids, "imported_solids": actual_solids}
    return rounded(result)


def projected_edges(shape, view):
    # Drawing-only wireframe polylines; original solids stay exact in STEP.
    output = []
    for edge in shape.Edges():
        count = 2 if edge.geomType() == "LINE" else max(16, min(100, int(edge.Length() / 3) + 2))
        coords = [edge.positionAt(i / (count - 1)).toTuple() for i in range(count)]
        if view == "TOP":
            pts = [(x, y) for x, y, z in coords]
        elif view == "FRONT":
            pts = [(x, z) for x, y, z in coords]
        else:
            pts = [(y, z) for x, y, z in coords]
        if any(math.dist(pts[0], point) > 1e-5 for point in pts[1:]):
            output.append(pts)
    return output


def write_drawing(a, destination):
    shape = a.compound()
    bounds = bbox(shape)
    sizes = bounds["size_mm"]
    # Engineering orthographic sheet, 3 wireframe views, matching CAD-space DXF.
    width, height = 1500, 1100
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="1500" height="1100" fill="white"/>',
           '<style>text{font-family:Arial,sans-serif;fill:#172d39}.edge{fill:none;stroke:#314651;stroke-width:1}.dim{stroke:#53636b;stroke-width:1;fill:none}.small{font-size:14px}.label{font-size:19px}</style>',
           f'<text x="45" y="42" font-size="27">POSEIDON / {a.id} / {REVISION}</text>',
           f'<text x="45" y="73" class="label">{html.escape(a.description)}</text>',
           '<text x="45" y="101" class="label">PROVISIONAL — NOT FOR FABRICATION — mm — orthographic wireframe</text>']
    dxf = ezdxf.new("R2018")
    dxf.units = ezdxf.units.MM
    dxf.header["$MEASUREMENT"] = 1
    space = dxf.modelspace()
    for layer in ("TOP", "FRONT", "RIGHT", "DIMENSIONS", "NOTES"):
        dxf.layers.new(layer)
    views = [("TOP", 45, 140, 690, 355, (0, 1)), ("FRONT", 45, 550, 690, 355, (0, 2)),
             ("RIGHT", 800, 140, 635, 760, (1, 2))]
    dxf_offsets = {"TOP": (0, 0), "FRONT": (0, -(sizes[2] + 150)), "RIGHT": (sizes[0] + 150, 0)}
    for view, ox, oy, w, h, (u, v) in views:
        edges = projected_edges(shape, view)
        scale = min((w - 100) / sizes[u], (h - 80) / sizes[v])
        min_u, min_v = bounds["min_mm"][u], bounds["min_mm"][v]
        sx, sy = ox + 40, oy + h - 45
        svg.append(f'<text x="{ox}" y="{oy + 18}" class="label">{view} (display {scale:.3f} px/mm; do not scale print)</text>')
        dx, dy = dxf_offsets[view]
        for points in edges:
            xy = " ".join(f"{sx + (x-min_u)*scale:.3f},{sy - (y-min_v)*scale:.3f}" for x, y in points)
            svg.append(f'<polyline class="edge" points="{xy}"/>')
            space.add_lwpolyline([(x - min_u + dx, y - min_v + dy) for x, y in points], dxfattribs={"layer": view})
        x2, y2 = sx + sizes[u] * scale, sy - sizes[v] * scale
        svg.extend([f'<path class="dim" d="M {sx} {sy+8} V {sy+27} M {x2} {sy+8} V {sy+27} M {sx} {sy+20} H {x2}"/>',
                    f'<text x="{(sx+x2)/2}" y="{sy+39}" text-anchor="middle" class="small">{sizes[u]:.2f} mm</text>',
                    f'<path class="dim" d="M {sx-8} {sy} H {sx-28} M {sx-8} {y2} H {sx-28} M {sx-20} {sy} V {y2}"/>',
                    f'<text x="{sx-25}" y="{(sy+y2)/2}" transform="rotate(-90 {sx-25} {(sy+y2)/2})" text-anchor="middle" class="small">{sizes[v]:.2f} mm</text>'])
        dimstyle = {"dimtxt": max(2.5, max(sizes) / 130), "dimasz": max(2.5, max(sizes) / 180), "dimclrd": 7, "dimclre": 7, "dimclrt": 7, "dimdec": 2}
        space.add_linear_dim(base=(dx, dy - 35), p1=(dx, dy), p2=(dx + sizes[u], dy), angle=0, override=dimstyle, dxfattribs={"layer": "DIMENSIONS"}).render()
        space.add_linear_dim(base=(dx - 35, dy), p1=(dx, dy), p2=(dx, dy + sizes[v]), angle=90, override=dimstyle, dxfattribs={"layer": "DIMENSIONS"}).render()
        space.add_text(view, dxfattribs={"height": max(4, max(sizes) / 100), "layer": "NOTES", "insert": (dx, dy + sizes[v] + 20)})
    notes = ["Datum: right-handed assembly-local X/Y/Z; plan XY, front XZ, right YZ. Overall dimensions derive from exact BRep.",
             "Curved drawing edges are sampled; wireframe includes hidden/back edges. STEP is the geometry authority; DXF units mm.",
             "Source-tagged Pi features and battery/panel/converter/MPPT overall sizes are verified references; other geometry is provisional.",
             "Default machining allowance +/-0.30 mm; clamp bore +/-0.20 mm; envelope dia +/-0.50 mm: assumptions, not release tolerances.",
             "Metal parts: deburr/passivate or isolate/anodize per material record; fastener torque, coating, corrosion and loads remain open.",
             "No pressure containment, rating, calibration, safe working load or fabrication release. See manifest.json part/BOM/feature notes."]
    for i, note in enumerate(notes):
        svg.append(f'<text x="45" y="{948+i*23}" class="small">{html.escape(note)}</text>')
        space.add_text(note, dxfattribs={"height": 4, "layer": "NOTES", "insert": (0, -(sizes[2] + 250 + i * 9))})
    # Local feature callouts are machine-readable and also visible on a second sheet below.
    svg.append("</svg>")
    (destination / f"{a.id}.svg").write_text("\n".join(svg))
    dxf.saveas(destination / f"{a.id}.dxf")
    feature_sheet(a, destination)


def feature_sheet(a, destination):
    parts = [part for part in a.parts if part.features or part.notes]
    lines = []
    for part in parts:
        lines.append((part.id + " / BOM " + part.bom_id, True))
        for key, value in part.features.items():
            lines.append((f"{key}: {json.dumps(value, separators=(',', ':'))}", False))
        for note in part.notes:
            # Wrap long notes for a printable engineering schedule, not a raster chart.
            import textwrap
            lines.extend((line, False) for line in textwrap.wrap(note, 135))
    h = max(400, 180 + len(lines) * 23)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="{h}" viewBox="0 0 1500 {h}">', f'<rect width="1500" height="{h}" fill="white"/>',
           '<g font-family="monospace" fill="#172d39">', f'<text x="35" y="40" font-size="25">{a.id} / {REVISION} / FEATURE AND FASTENER SCHEDULE</text>',
           '<text x="35" y="72" font-size="18">PROVISIONAL / mm / NOT FOR FABRICATION / features in assembly-local coordinates unless labelled local</text>',
           '<text x="35" y="100" font-size="16">Source-tagged Pi features and battery/panel/converter/MPPT envelopes have vendor evidence; other details/tolerances are assumptions.</text>']
    for i, (text, bold) in enumerate(lines):
        svg.append(f'<text x="{35 if bold else 50}" y="{140+i*23}" font-size="15" font-weight="{"bold" if bold else "normal"}">{html.escape(text)}</text>')
    svg.extend(["</g>", "</svg>"])
    (destination / f"{a.id}_features.svg").write_text("\n".join(svg))


def write_views(a, destination):
    for exploded, label in ((False, "assembly"), (True, "exploded")):
        shapes = [part.shape.translate((0, 0, i * 32 if exploded else 0)) for i, part in enumerate(a.parts)]
        image = cq.exporters.getSVG(cq.Compound.makeCompound(shapes), {
            "width": 1200, "height": 900, "marginLeft": 60, "marginTop": 80,
            "projectionDir": (1, -1, 0.75), "showHidden": False, "showAxes": True,
            "strokeWidth": 0.8, "strokeColor": (35, 55, 66)})
        root = ET.fromstring(image)
        ns = "http://www.w3.org/2000/svg"
        # OCP's automatic camera frame projects +Z down for this direction.
        # Rotate the drawing (not the model) 180 degrees to present +Z upward.
        projection = ET.Element(f"{{{ns}}}g", {"transform": "rotate(180 600 450)"})
        for child in list(root):
            root.remove(child)
            projection.append(child)
        root.append(projection)
        root.insert(0, ET.Element(f"{{{ns}}}rect", {"width": "100%", "height": "100%", "fill": "white"}))
        text = ET.SubElement(root, f"{{{ns}}}text", {"x": "25", "y": "28", "font-family": "Arial", "font-size": "19", "fill": "#172d39"})
        text.text = f"{a.id} / {REVISION} / {label.upper()} / PROVISIONAL NOT FOR FABRICATION"
        text = ET.SubElement(root, f"{{{ns}}}text", {"x": "25", "y": "52", "font-family": "Arial", "font-size": "14"})
        text.text = "Exploded sequential +Z spacing is a review aid, not installation order; part names/BOM mapping in manifest." if exploded else "Exact CAD projection; unselected purchased components are fictional envelopes, not vendor models."
        (destination / f"{a.id}_{label}.svg").write_text(ET.tostring(root, encoding="unicode"))


def write_keepout_view(a, destination):
    if not a.keepouts:
        return
    # Separate SVG+STEP prevents allocation volumes from being mistaken for physical BOM.
    all_shapes = [part.shape for part in a.parts] + [shape for shape, _ in a.keepouts.values()]
    image = cq.exporters.getSVG(cq.Compound.makeCompound(all_shapes), {"width": 1400, "height": 1000, "marginLeft": 80, "marginTop": 85,
                    "projectionDir": (1, -1, 0.7), "showHidden": False, "showAxes": True})
    root = ET.fromstring(image)
    ns = "http://www.w3.org/2000/svg"
    projection = ET.Element(f"{{{ns}}}g", {"transform": "rotate(180 700 500)"})
    for child in list(root):
        root.remove(child)
        projection.append(child)
    root.append(projection)
    root.insert(0, ET.Element(f"{{{ns}}}rect", {"width": "100%", "height": "100%", "fill": "white"}))
    text = ET.SubElement(root, "{http://www.w3.org/2000/svg}text", {"x": "25", "y": "30", "font-family": "Arial", "font-size": "19", "fill": "#172d39"})
    text.text = f"{a.id} / SERVICE + KEEPOUT ALLOCATIONS / NOT PHYSICAL PARTS / mm / {REVISION}"
    (destination / f"{a.id}_keepouts.svg").write_text(ET.tostring(root, encoding="unicode"))


def export_assembly(a, output, views=True):
    path = output / "step" / f"{a.id}.step"
    a.native().export(str(path), "STEP")
    checks = geometry_checks(a)
    checks.append(step_roundtrip(path, a.compound()))
    keepout_records = []
    if a.keepouts:
        ka = cq.Assembly(name=a.id + "_KEEP_OUTS_NOT_PARTS")
        for name, (shape, note) in a.keepouts.items():
            ka.add(shape, name=name, color=cq.Color(0.95, 0.55, 0.16, 0.18))
            keepout_records.append({"id": name, "bbox": rounded(bbox(shape)), "note": note, "bom_item": False})
        kp = output / "keepouts" / f"{a.id}_keepouts.step"
        ka.export(str(kp), "STEP")
        checks.append(step_roundtrip(kp, cq.Compound.makeCompound([shape for shape, _ in a.keepouts.values()])))
    if views:
        write_drawing(a, output / "drawings")
        write_views(a, output / "views")
        write_keepout_view(a, output / "views")
    for part in a.parts:
        if part.printable:
            target = output / "printable" / f"{part.id}.stl"
            cq.exporters.export(part.shape, str(target), tolerance=0.08, angularTolerance=0.12)
            mesh = trimesh.load_mesh(target, process=True)
            delta = abs(mesh.volume - part.shape.Volume()) / part.shape.Volume()
            checks.append({"id": part.id + "_stl_manifold", "passed": bool(mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0 and delta < 0.01),
                           "evidence": "trimesh_actual_export_watertight_winding_positive_volume", "watertight": bool(mesh.is_watertight),
                           "winding_consistent": bool(mesh.is_winding_consistent), "faces": int(len(mesh.faces)), "volume_relative_error": round(delta, 8),
                           "units": "mm by accompanying manifest; STL format has no unit field"})
    return {"id": a.id, "description": a.description, "optional_not_populated_by_default": a.optional,
            "bbox": rounded(bbox(a.compound())), "parts": [part.metadata() for part in a.parts],
            "keepouts": keepout_records, "checks": checks,
            "step": f"step/{a.id}.step", "drawing_svg": f"drawings/{a.id}.svg", "drawing_dxf": f"drawings/{a.id}.dxf"}


def prepare_output(path):
    # Never delete/reuse existing output; broken symlinks also count as existing entries.
    if path.is_symlink():
        raise ValueError("Output must not be a symlink")
    if path.exists():
        if not path.is_dir() or any(path.iterdir()):
            raise ValueError("Output must be a new or empty owned directory; refusing nonempty output")
    else:
        path.mkdir(parents=True, exist_ok=False)
    for name in ("step", "keepouts", "drawings", "views", "printable"):
        (path / name).mkdir()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New or empty owned output directory; NEVER overwritten")
    parser.add_argument("--parameters", type=Path, help="JSON object overriding known design parameters; controlled vendor/interface features may not drift")
    parser.add_argument("--array-pitch-mm", type=float, help="Optional research fixture pitch 180..600 mm; default 300")
    parser.add_argument("--research-layout", action="store_true", help="Add optional array/projector/unpowered wiper to a second research top-level assembly; passive default remains")
    args = parser.parse_args(argv)
    try:
        p = read_parameters(args.parameters, args.array_pitch_mm)
        interfaces = interface_evidence(p)
        prepare_output(args.output)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    assemblies = [build_hub(p), build_wet(p), build_array(p), build_wiper(p), build_projector(p), build_reef(p),
                  build_farm(p), build_assembly_fixture(p), build_calibration_fixture(p), build_pressure_positioning(p)]
    top, placements = build_top(assemblies, p, False)
    assemblies.append(top)
    if args.research_layout:
        research, research_placements = build_top(assemblies[:-1], p, True)
        assemblies.append(research)
    records = []
    for a in assemblies:
        print(f"Generating {a.id}: {len(a.parts)} physical/reference parts, {len(a.keepouts)} keepouts", flush=True)
        records.append(export_assembly(a, args.output))
    checks = arithmetic_checks(p)
    all_checks = checks + [check for assembly in records for check in assembly["checks"]]
    failures = [check for check in all_checks if not check["passed"]]
    manifest = {"schema": "poseidon.cad.manifest.v1", "configuration": CONFIGURATION, "revision": REVISION,
                "status": STATUS, "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "units": {"length": "mm", "volume": "mm3", "mass": "kg"},
                "coordinate_system": "right-handed, assembly-local X/Y/Z; top-level translation table; schematic water datum Z=0",
                "passive_default": True, "default_top_assembly": "TOP_PASSIVE", "research_layout_exported": args.research_layout,
                "no_pressure_boundary_designed": True, "physical_tests_performed": [], "fabrication_authorized": False,
                "toolchain": {"python": platform.python_version(), **{name: importlib.metadata.version(name) for name in ("cadquery", "cadquery-ocp", "ezdxf", "trimesh")}},
                "source_files": {path.name: sha256(path) for path in [CAD_ROOT / "generate.py", CAD_ROOT / "parameters.py", CAD_ROOT / "pyproject.toml", CAD_ROOT / "uv.lock"]},
                "parameters": p, "interface_evidence": interfaces, "primary_source_evidence": [source_evidence(), *additional_source_evidence()],
                "external_bom": {"path": "hardware/bom/reference-v1.json", "sha256": sha256(ROOT / "hardware/bom/reference-v1.json"), "reference_id_aliases": BOM_ALIASES,
                                 "quantity_note": "Purchased envelope fragments and fixture copies are representations, not additional order quantities. Mechanical BOM excludes TOP placement copies."},
                "materials": MATERIALS, "top_level_translations_mm": placements,
                "assemblies": records, "checks": checks,
                "check_summary": {"runtime": "CAD geometry engine executed; not a stdlib-only manifest review", "total": len(all_checks), "passed": len(all_checks) - len(failures), "failed": len(failures)},
                "remaining_gates": ["Select exact purchased wet pressure boundary, camera, penetrators, cable and seal configuration; independently qualify pressure/leak tests", "Survey farm and freeze depth/current/wave/wind/storm/retrieval requirements", "Complete structural joints/fasteners/retention, loads, fatigue, buoyancy, ballast, stability and corrosion review", "Measure prototype fit, tool access, cable bend/crush/pullout and positional tolerances", "Select electrical components and verify exact board/connector/solar/battery geometry, power, thermal and RF", "Independent acoustic calibration, receive-isolation and synchronized-array geometry review", "Wiper force/jam/guard/seal and physical inhibit review; no powered mechanism here", "Optional projector remains unselected and electrically absent; acoustic safety/efficacy/permissions gate remains open", "Approve fixture materials, handling and chamber clearance with certified pressure-test facility; this package supplies no containment"]}
    if args.research_layout:
        manifest["research_top_level_translations_mm"] = research_placements
    mechanical_bom = {}
    for a in assemblies:
        if a.id.startswith("TOP_"):
            continue
        for part in a.parts:
            if part.bom_id in BOM_ALIASES.values():
                continue
            key = a.id + "/" + part.bom_id
            entry = mechanical_bom.setdefault(key, {"id": part.bom_id, "assembly": a.id, "description": part.description,
                        "reference_quantity": 0, "part_instances": [], "material_id": part.material,
                        "printable": part.printable, "critical_load": part.critical_load,
                        "status": STATUS, "procurement_or_fabrication_authorized": False,
                        "vendor_quote": None, "finish": MATERIALS[part.material]["finish"]})
            entry["reference_quantity"] += 1
            entry["part_instances"].append(part.id)
    (args.output / "mechanical-bom.json").write_text(json.dumps({"revision": REVISION, "status": STATUS,
        "note": "Counts per standalone reference assembly; fixtures and research options are not passive deployed BOM. TOP placement copies excluded.",
        "parts": list(mechanical_bom.values())}, indent=2) + "\n")
    manifest["artifacts"] = [{"path": str(path.relative_to(args.output)), "bytes": path.stat().st_size, "sha256": sha256(path)}
                             for path in sorted(args.output.rglob("*")) if path.is_file()]
    (args.output / "manifest.json").write_text(json.dumps(rounded(manifest), indent=2) + "\n")
    print(json.dumps(manifest["check_summary"]), flush=True)
    if failures:
        for failure in failures:
            print("FAILED " + json.dumps(failure), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
