"""Additive passive-v2 CAD contracts. Standard library only; baseline is read-only."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

CAD = Path(__file__).resolve().parent
ROOT = CAD.parents[3]
CONFIGURATION = "passive-v2"
REVISION = "HW-CAND-2.0"
STATUS = "NON_ADOPTED_NOT_BUILD_AUTHORIZED"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def baseline_check():
    frozen = json.loads((CAD / "baseline-lock.json").read_text())
    require(frozen["reference"] == "HW-REF-1.1", "Wrong historical baseline lock")
    failures = [name for name, expected in frozen["paths"].items() if not (ROOT / name).is_file() or digest(ROOT / name) != expected]
    require(not failures, "Frozen 1.1 baseline changed: " + ", ".join(failures))
    return {"revision": "HW-REF-1.1", "files_checked": len(frozen["paths"]), "changed": 0, "lock_sha256": digest(CAD / "baseline-lock.json")}


def load(path=None):
    path = Path(path or CAD / "parameters.json")
    p = json.loads(path.read_text())
    validate(p)
    return p


def validate(p):
    require(p.get("configuration") == CONFIGURATION and p.get("revision") == REVISION, "Candidate must not bind to HW-REF-1.1/reference-v1")
    require(p.get("status") == STATUS and p.get("adopted") is False and p.get("build_authorized") is False, "Candidate authority boundary violated")
    require(p.get("units") == "mm", "Candidate geometry units must be mm")
    panel = p["panel"]
    require(panel["count"] == 2 and type(panel["count"]) is int, "Exactly two physical panels required")
    require(panel["series_count"] == 2 and panel["parallel_count"] == 1, "Candidate is 2S1P, not a one-panel model")
    require(panel["size_mm"] == [668, 425, 25] and panel["mpn"] == "SPM040401200", "Panel source dimensions/part drift")
    require(p["battery"]["size_mm"] == [188, 147, 199], "Battery conservative vendor envelope drift")
    require(p["panel_gap_mm"] >= 50, "Panel service gap under 50 mm")
    require(p["battery_terminal_gap_mm"] >= 40, "Battery terminal/tool allowance under 40 mm")
    require(p["cable_radius_mm"] - 0.5 >= 6 * (p["cable_diameter_mm"] + 0.3), "Worst-case assumed cable bend budget fails")
    require(p["hub"]["source_bound"] is True, "HUB source dimensions not bound; no canonical export allowed")
    require(p["hub"]["dimension_status"] == "SOURCE_VERIFIED_OVERALL_ENVELOPE_DETAIL_PROVISIONAL", "Do not present a fictional enclosure allocation as source-verified CAD")
    for key in ("panel_gap_mm", "battery_terminal_gap_mm", "cable_radius_mm", "cable_diameter_mm"):
        require(type(p[key]) in (int, float) and math.isfinite(p[key]) and p[key] > 0, "Finite positive dimensions required")
    for component in (p["panel"], p["battery"], p["hub"]):
        require(len(component["size_mm"]) == 3 and all(type(v) in (int, float) and math.isfinite(v) and v > 0 for v in component["size_mm"]), "Invalid component envelope")
    require(p["shade"]["gap_mm"] >= 40 and p["shade"]["overhang_mm"] >= 40, "Shade ventilation/overhang allowance fails")
    source = p["parent_interface"]
    require(source["path"].startswith("hardware/candidates/passive-v2/"), "Parent input must be candidate-scoped, not baseline reference interface")
    target = ROOT / source["path"]
    require(target.is_file() and digest(target) == source["sha256"], "Parent candidate interface changed or missing")
    parent = json.loads(target.read_text())
    require(parent.get("configuration") == CONFIGURATION and parent.get("revision") == REVISION, "Parent candidate identity mismatch")
    mechanical=parent["mechanical"]
    bindings=[(p["hub"]["size_mm"],mechanical["hub"]["cad_xyz_mm"]),(p["hub"]["base_thickness_mm"],mechanical["hub"]["base_thickness_reference_mm"]),
              (p["hub"]["lid_thickness_mm"],mechanical["hub"]["lid_thickness_reference_mm"]),(p["collector"]["size_mm"],mechanical["collector"]["xyz_mm"]),
              (p["tim"]["thickness_mm"],mechanical["thermal_interfaces"]["thickness_mm"]),(p["tim"]["patch_xz_mm"],mechanical["thermal_interfaces"]["patch_xz_mm"]),
              (p["sink"]["size_mm"],mechanical["heat_sink"]["candidate_xyz_mm"]),(p["sink"]["base_thickness_mm"],mechanical["heat_sink"]["profile_base_thickness_mm"]),
              (p["shade"]["size_xy_mm"],mechanical["shade"]["roof_xy_mm"]),(p["shade"]["gap_mm"],mechanical["shade"]["vertical_gap_above_enclosure_mm"]),
              (p["frozen_comparison"],parent["frozen_comparison"])]
    require(all(actual==source for actual,source in bindings),"Candidate source-bound dimensions/comparison drift")
    power=json.loads((ROOT/parent["power_envelopes"]).read_text())
    require(p["power_components"]==power["parts"],"Power source envelopes changed; rebind candidate explicitly")
    catalog = {row["path"]: row for row in json.loads((ROOT / "hardware/vendor-sources.json").read_text())["files"]}
    for record in p["source_files"]:
        path = record["path"]
        if not path.startswith("hardware/") or ".." in Path(path).parts:
            raise ValueError("Invalid bound source path")
        local = ROOT / path
        if local.is_file():
            require(digest(local) == record["sha256"], "Bound source changed: " + path)
            continue
        if path.startswith("hardware/candidates/passive-v2/sources/"):
            key = "passive-v2/" + Path(path).name
        elif path.startswith("hardware/cad/sources/"):
            key = "cad/" + Path(path).name
        else:
            raise ValueError("Missing original input: " + path)
        require(key in catalog and catalog[key]["sha256"] == record["sha256"],
                "Bound source changed: " + path)


def arithmetic(p):
    panel = p["panel"]["size_mm"]
    return {"physical_panel_count": 2, "series_count": 2, "parallel_count": 1,
            "nameplate_array_power_w": 80, "per_panel_face_area_m2": panel[0] * panel[1] / 1e6,
            "total_panel_face_area_m2": 2 * panel[0] * panel[1] / 1e6,
            "panel_gap_mm": p["panel_gap_mm"], "panel_group_size_mm": [panel[0], 2 * panel[1] + p["panel_gap_mm"], panel[2]],
            "panel_area_ratio_to_baseline": 2.0, "group_projected_rectangle_m2": panel[0] * (2 * panel[1] + p["panel_gap_mm"]) / 1e6,
            "cable_worst_case_bend_margin_mm": p["cable_radius_mm"] - 0.5 - 6 * (p["cable_diameter_mm"] + 0.3),
            "wind_note": "Face area doubles; total frame/shade area, drag coefficients and site loads require separate analysis. Not a load rating.",
            "solar_note": "80W nameplate and geometric shade are not zero absorbed heat, measured yield or thermal acceptance."}
