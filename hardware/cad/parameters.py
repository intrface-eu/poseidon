"""Millimetre design inputs and stdlib checks; no CAD imports or field claims."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAD_ROOT = Path(__file__).resolve().parent
REVISION = "HW-REF-1.1"
CONFIGURATION = "reference-v1"
STATUS = "PROVISIONAL_REFERENCE_NOT_FOR_FABRICATION"
PI_SOURCE = "https://pip.raspberrypi.com/documents/RP-008343-DS-raspberry-pi-4-mechanical-drawing.pdf"
PI_PDF = CAD_ROOT / "sources/RP-008343-DS-raspberry-pi-4-mechanical-drawing.pdf"

DEFAULTS = {
    "hub_exterior_mm": [400.0, 300.0, 180.0],
    "hub_usable_mm": [360.0, 260.0, 140.0],
    "tray_mm": [340.0, 240.0, 4.0],
    "pi_outline_mm": [85.0, 56.0],
    "pi_corner_radius_mm": 3.0,
    "pi_hole_diameter_mm": 2.7,
    "pi_hole_centres_from_lower_left_mm": [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]],
    "pi_pcb_thickness_mm": 1.6,
    "esp32_envelope_mm": [55.0, 28.0, 14.0],
    "rak3272s_envelope_mm": [40.0, 30.0, 15.0],
    "camera_diameter_mm": 110.0,
    "camera_length_mm": 250.0,
    "hydrophone_diameter_mm": 32.0,
    "hydrophone_length_mm": 100.0,
    "camera_clamp_bore_mm": 112.8,
    "hydrophone_clamp_bore_mm": 34.0,
    "solar_mm": [668.0, 425.0, 25.0],
    "battery_mm": [188.0, 147.0, 199.0],
    "battery_terminal_service_mm": 40.0,
    "converter_mm": [159.0, 97.0, 38.0],
    "mppt_mm": [113.0, 40.0, 100.0],
    "reef_box_mm": [300.0, 220.0, 140.0],
    "array_pitch_mm": 300.0,
    "cable_diameter_mm": 8.0,
    "cable_bend_radius_mm": 56.0,
    "cable_min_radius_diameters": 6.0,
    "hub_lid_lift_mm": 180.0,
    "hand_tool_diameter_mm": 16.0,
    "tool_access_height_mm": 80.0,
    "assumed_linear_tolerance_mm": 0.3,
    "assumed_envelope_diameter_tolerance_mm": 0.5,
    "assumed_clamp_bore_tolerance_mm": 0.2,
    "assumed_cable_diameter_tolerance_mm": 0.3,
    "assumed_bend_radius_tolerance_mm": 0.5,
    "pi_fastener_nominal_diameter_mm": 2.5,
    "pi_fastener_max_diameter_mm": 2.5,
    "pi_hole_assumed_minus_tolerance_mm": 0.1,
    "fixture_hole_mm": 3.2,
    "fixture_hole_minus_tolerance_mm": 0.15,
    "required_camera_radial_gap_mm": 0.75,
    "required_hydrophone_radial_gap_mm": 0.5,
    "required_tray_side_gap_mm": 5.0,
    "required_tool_access_mm": 60.0,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_parameters(path: Path | None = None, array_pitch: float | None = None) -> dict:
    values = json.loads(json.dumps(DEFAULTS))
    if path:
        overrides = json.loads(path.read_text())
        if not isinstance(overrides, dict) or set(overrides) - set(values):
            raise ValueError("Parameters must be an object with known parameter names")
        values.update(overrides)
    if array_pitch is not None:
        values["array_pitch_mm"] = array_pitch
    validate_parameters(values)
    return values


def validate_parameters(p: dict) -> None:
    if set(p) != set(DEFAULTS):
        raise ValueError("Parameter set does not match reference schema")
    def numeric_tree(value):
        if isinstance(value, list):
            return bool(value) and all(numeric_tree(v) for v in value)
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    if not all(numeric_tree(value) for value in p.values()):
        raise ValueError("Every dimension must be a finite positive number; booleans are not lengths")
    for key, default in DEFAULTS.items():
        if isinstance(default, list):
            if not isinstance(p[key], list) or len(p[key]) != len(default):
                raise ValueError(f"Wrong vector size: {key}")
    # These five features come from the primary drawing, not configurable mounting guesses.
    for key in ("pi_outline_mm", "pi_corner_radius_mm", "pi_hole_diameter_mm", "pi_hole_centres_from_lower_left_mm"):
        if p[key] != DEFAULTS[key]:
            raise ValueError(f"Verified Pi feature cannot change without a new source/revision: {key}")
    if not 180 <= p["array_pitch_mm"] <= 600:
        raise ValueError("Research array pitch must be 180..600 mm in this fixture family")
    if not 80 <= p["camera_diameter_mm"] <= 114 or not 180 <= p["camera_length_mm"] <= 260:
        raise ValueError("Camera exceeds this support family; redesign support rather than clipping it")
    if not 20 <= p["hydrophone_diameter_mm"] <= 34 or p["hydrophone_length_mm"] > 150:
        raise ValueError("Hydrophone exceeds this support family")
    for check in arithmetic_checks(p):
        if not check["passed"]:
            raise ValueError(f"Failed design check {check['id']}: {check['actual']} < {check['minimum']}")


def arithmetic_checks(p: dict) -> list[dict]:
    checks = []
    def minimum(name, actual, required, note):
        checks.append({"id": name, "actual": round(actual, 6), "minimum": required,
                       "units": "mm", "passed": actual + 1e-9 >= required,
                       "evidence": "arithmetic_design_assumptions_not_measurement", "note": note})
    tol = p["assumed_linear_tolerance_mm"]
    for axis in (0, 1):
        minimum(f"tray_worst_case_side_gap_{'xy'[axis]}",
                (p["hub_usable_mm"][axis] - p["tray_mm"][axis]) / 2 - tol,
                p["required_tray_side_gap_mm"], "Half of minimum enclosure clearance minus tray/enclosure allowance")
    for prefix in ("camera", "hydrophone"):
        minimum(f"{prefix}_worst_case_radial_gap",
                (p[f"{prefix}_clamp_bore_mm"] - p["assumed_clamp_bore_tolerance_mm"]
                 - p[f"{prefix}_diameter_mm"] - p["assumed_envelope_diameter_tolerance_mm"]) / 2,
                p[f"required_{prefix}_radial_gap_mm"], "Diameter tolerance converted to radial gap; retention preload unresolved")
    minimum("cable_worst_case_bend_radius_margin",
            p["cable_bend_radius_mm"] - p["assumed_bend_radius_tolerance_mm"]
            - p["cable_min_radius_diameters"] * (p["cable_diameter_mm"] + p["assumed_cable_diameter_tolerance_mm"]),
            0.0, "6D is a design allowance, not a cable-vendor limit; radius means cable centreline")
    minimum("pi_hole_to_m2p5_worst_case_diametral_gap",
            p["pi_hole_diameter_mm"] - p["pi_hole_assumed_minus_tolerance_mm"] - p["pi_fastener_max_diameter_mm"],
            0.05, "Vendor diameter is verified; hole and screw tolerances here are assumed")
    minimum("pi_template_worst_case_diametral_gap",
            p["fixture_hole_mm"] - p["fixture_hole_minus_tolerance_mm"] - p["pi_fastener_max_diameter_mm"],
            0.3, "Template guide is for alignment only, not a drill bushing or a PCB drilling instruction")
    minimum("lid_lift_tool_access", p["hub_lid_lift_mm"] - tol,
            p["required_tool_access_mm"], "Lift-off top access only; no hinge, latch or gasket design")
    minimum("tool_vertical_access", p["tool_access_height_mm"],
            p["required_tool_access_mm"], "16 mm diameter cylindrical driver allowance at tray mounts")
    minimum("array_sensor_surface_separation", p["array_pitch_mm"] - p["hydrophone_diameter_mm"],
            100.0, "Mechanical sensor spacing only; shared acquisition clock and acoustic geometry remain open")
    return checks


def interface_evidence(p: dict, path: Path | None = None) -> dict:
    path = path or ROOT / "hardware/interfaces/reference-v1.json"
    if not path.is_file():
        raise ValueError("Controlled hardware/interfaces/reference-v1.json is required for generation")
    data = json.loads(path.read_text())
    if data.get("configuration") != CONFIGURATION or data.get("revision") != REVISION:
        raise ValueError("Interface configuration/revision mismatch")
    if data.get("units", {}).get("length") != "mm":
        raise ValueError("Interface length units must be mm")
    envelopes = {item["assembly"]: item for item in data["mechanical_envelopes"]}
    bindings = [("hub_exterior_mm", "HUB", "envelope_mm"), ("hub_usable_mm", "HUB", "usable_interior_mm"),
                ("camera_diameter_mm", "WET", "camera_reference_diameter_mm"),
                ("camera_length_mm", "WET", "camera_reference_length_mm"),
                ("hydrophone_diameter_mm", "WET", "hydrophone_reference_diameter_mm"),
                ("hydrophone_length_mm", "WET", "hydrophone_reference_length_mm"),
                ("solar_mm", "REEF", "solar_envelope_mm"), ("battery_mm", "REEF", "battery_envelope_mm"),
                ("reef_box_mm", "REEF", "electronics_envelope_mm")]
    for param, assembly, field in bindings:
        if p[param] != envelopes[assembly][field]:
            raise ValueError(f"Parameter {param} disagrees with the controlled interface")
    return {"path": "hardware/interfaces/reference-v1.json", "sha256": sha256(path),
            "revision": data["revision"], "bindings_checked": len(bindings)}


def purchased_source_hash(file: str) -> str:
    catalog = json.loads((ROOT / "hardware/vendor-sources.json").read_text())
    entry = next((row for row in catalog["files"] if row["path"] == "cad/" + file), None)
    if entry is None:
        raise ValueError("Unregistered purchased reference source: " + file)
    return entry["sha256"]


def additional_source_evidence() -> list[dict]:
    records = [
        ("SRC-VICTRON-SOLAR", "Datasheet-BlueSolar-Monocrystalline-Panels-EN.pdf", "https://www.victronenergy.com/upload/documents/Datasheet-BlueSolar-Monocrystalline-Panels-EN.pdf", {"part": "SPM040401200", "table_dimensions_mm": [425, 668, 25], "cad_xyz_mm": [668, 425, 25], "vendor_mass_kg": 3.1}, "PDF p1 visually read; 40W row has no discontinuation footnote. Supplier availability unverified."),
        ("SRC-VICTRON-BATTERY", "Victron-Lithium-Battery-Smart-technical-data.html", "https://www.victronenergy.com/media/pg/Lithium_Battery_Smart/en/technical-data.html", {"part": "BAT512050610", "manual_hwd_mm": [199, 188, 147], "cad_xyz_mm": [188, 147, 199], "vendor_mass_kg": 7.0, "terminals": "M8"}, "Vendor manual table retrieved; upright pose, additional 40 mm terminal/tool allowance is provisional."),
        ("SRC-VICTRON-BATTERY-DRAWING", "LiFePO4-Battery-12.8V50AH-Smart.pdf", "https://www.victronenergy.com/upload/documents/LiFePO4-Battery-12.8V50AH-Smart.pdf", {"part": "BAT512050610", "drawing_revision": "01", "body_width_mm": 173, "depth_mm": 147, "overall_height_mm": 199, "terminal_pitch_mm": 109, "thread": "M8"}, "PDF p1 visually read. Manual 188 mm overall width used conservatively; reconcile selected drawing revision before fabrication. Terminal positions NOT modelled as verified features."),
    ]
    return [{"id": id, "url": url, "retrieved_date": "2026-09-08", "local_path": "hardware/.vendor-cache/cad/" + file,
             "sha256": purchased_source_hash(file), "verified_features": features, "verification": note}
            for id, file, url, features, note in records]


def source_evidence() -> dict:
    return {"id": "SRC-PI4-MECH", "url": PI_SOURCE, "retrieved_date": "2026-09-08",
            "local_path": "hardware/.vendor-cache/cad/" + PI_PDF.name, "sha256": purchased_source_hash(PI_PDF.name),
            "verification": "Primary PDF page 1 visually read, 2026-09-08",
            "verified_features": {k: DEFAULTS[k] for k in ("pi_outline_mm", "pi_corner_radius_mm", "pi_hole_diameter_mm", "pi_hole_centres_from_lower_left_mm")},
            "datum": "PCB lower-left in drawing plan view, +X right, +Y up; 58 x 49 mm hole pitch",
            "not_verified": ["PCB thickness", "complete component/connector models", "supplier tolerances", "mating cable plugs", "SC0194 configuration-specific mass"]}
