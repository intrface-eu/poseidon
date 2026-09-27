"""Surface-v3 source, trace and arithmetic contract. Standard library only."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

CAD = Path(__file__).resolve().parent
CANDIDATE = CAD.parent
ROOT = CANDIDATE.parents[2]
STATUS = "NON_ADOPTED_NOT_BUILD_AUTHORIZED"
GLB_NAME = "SURFACE_V3.glb"
SENTENCE = "this is a non-adopted digital candidate with no pressure, corrosion or suitability evidence."
PARAMETER_NAMES = set("""panel_xyz_mm panel_mass_kg panel_gap_mm panel_tilt_deg tray_xy_mm tray_thickness_mm
skirt_xy_mm skirt_wall_mm skirt_depth_mm panel_low_clearance_mm wedge_length_mm wedge_width_mm
wedge_edge_inset_mm hub_xyz_mm hub_center_xy_mm shade_xy_mm shade_thickness_mm shade_hub_gap_mm
shade_to_tray_mm shade_support_x_mm shade_support_xy_mm sink_xyz_mm sink_base_mm sink_hub_gap_mm
sink_vent_height_mm hub_carrier_width_mm hub_carrier_thickness_mm hub_hanger_xy_mm socket_od_mm
socket_id_mm socket_length_mm socket_flange_od_mm socket_flange_thickness_mm bolt_centres_below_tray_mm
bolt_hole_diameter_mm bolt_allocation_diameter_mm bolt_allocation_length_mm pole_od_mm pole_wall_mm
site_depth_mm freeboard_mm footing_xy_mm footing_thickness_mm float_outer_xy_mm float_height_mm
cable_diameter_mm cable_bend_radius_mm cable_x_mm cable_stub_z_mm cable_hole_diameter_mm
aluminum_density_kg_m3 steel_density_kg_m3 foam_density_kg_m3 seawater_density_kg_m3
hub_scenario_mass_kg sink_scenario_mass_kg unmodeled_payload_allowance_kg gravity_m_s2
brep_tolerance_mm interference_tolerance_mm3 glb_deflection_mm glb_angular_deflection_rad
dxf_curve_spacing_mm dxf_view_gap_mm dxf_text_height_mm surface_height_limit_mm""".split())
SOURCE_BINDINGS = {
    "panel_xyz_mm": "mechanical.reef.single_panel_xyz_mm",
    "panel_gap_mm": "mechanical.reef.gap_between_panels_mm",
    "hub_xyz_mm": "mechanical.hub.vendor_lwh_mm",
    "shade_xy_mm": "mechanical.shade.roof_xy_mm",
    "shade_thickness_mm": "mechanical.shade.sheet_thickness_mm",
    "shade_hub_gap_mm": "mechanical.shade.vertical_gap_above_enclosure_mm",
    "sink_xyz_mm": "mechanical.heat_sink.candidate_xyz_mm",
    "sink_base_mm": "mechanical.heat_sink.profile_base_thickness_mm",
    "sink_hub_gap_mm": "mechanical.thermal_interfaces.thickness_mm",
    "sink_vent_height_mm": "mechanical.shade.minimum_open_air_gap_mm",
    "cable_diameter_mm": "mechanical.reef.cable_reference_diameter_mm",
    "cable_bend_radius_mm": "mechanical.reef.cable_reference_centreline_bend_radius_mm",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text())


def write_json(path, value):
    # All generator outputs are new. Never silently replace evidence.
    with Path(path).open("x") as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write("\n")


def values(p):
    return {key: record["value"] for key, record in p["parameters"].items()}


def repo_file(path):
    rel = Path(path)
    require(not rel.is_absolute() and ".." not in rel.parts, "Unsafe repository source path")
    target = ROOT / rel
    require(not target.is_symlink() and target.resolve().is_relative_to(ROOT), "Source symlink escape")
    require(target.is_file(), "Missing source: " + path)
    return target


def baseline_check():
    lock = read_json(CANDIDATE / "baseline-lock.json")
    require(lock["schema"] == "poseidon.surface-v3.baseline-lock.v1", "Wrong baseline lock")
    for path, sha in lock["files"].items():
        require(digest(repo_file(path)) == sha, "Frozen source changed: " + path)
    return {"files_checked": len(lock["files"]), "changed": 0,
            "lock_sha256": digest(CANDIDATE / "baseline-lock.json")}


def validate(p):
    require(p["configuration"] == "surface-v3" and p["status"] == STATUS, "Candidate identity/status")
    for flag in ("adopted", "build_authorized", "procurement_authorized", "active_emission_hardware_populated"):
        require(p[flag] is False, "Authority boundary: " + flag)
    require(p["physical_tests_performed"] == 0 and p["assembled_mass_kg"] is None, "Unknown physical result")
    require(p["required_sentence"] == SENTENCE, "Non-adopted sentence missing")
    require(p["units"] == {"cad": "mm", "glb": "m", "mass": "kg"}, "Unit contract")
    require(p["power_parts_populated"] == ["two panel envelopes only"], "Power integration stays omitted")
    require(p["thermal"]["reevaluated"] is False and p["thermal"]["installed_thermal_performance"] is None,
            "Thermal question remains open")
    require(p["thermal"]["v2_absorbed_sun_w"] == 48 and p["thermal"]["v2_enclosed_heat_w"] == 21.9,
            "Frozen thermal comparison changed")
    require(p["contract_groups"] == {"surface": ["tray", "hub", "panelA", "panelB", "mastSocket"],
                                     "mountPole": [], "mountFloat": []}, "Contract groups changed")
    require(p["variants"]["pole"]["exclusive_with"] == "float" and p["variants"]["float"]["exclusive_with"] == "pole",
            "Variants must be mutually exclusive")
    require(p["variants"]["float"]["actual_complete_mass_kg"] is None and
            p["variants"]["float"]["actual_buoyancy_sign"] == "UNKNOWN", "Actual float result is unknown")
    require(len(p["open_gates"]) >= 9, "Open gates missing")
    register_path = CANDIDATE / "sources/source-register.json"
    require(digest(register_path) == p["source_register_sha256"], "Source register hash mismatch")
    register = read_json(register_path)
    sources = {r["id"]: r for r in register["sources"]}
    require(len(sources) == len(register["sources"]) and register["new_downloads"] == 0, "Source identity/download boundary")
    supplier = {r["path"]: r for r in read_json(ROOT / "hardware/vendor-sources.json")["files"]}
    for record in sources.values():
        path = record["path"]
        if path.startswith("hardware/.vendor-cache/"):
            source = supplier.get(path.removeprefix("hardware/.vendor-cache/"))
            require(source is not None and source["sha256"] == record["sha256"]
                    and source["url"] == record["url"]
                    and source["license_status"] == record["license_status"] == "supplier_redistribution_unverified"
                    and record["locator"],
                    "Supplier source hash/locator: " + record["id"])
        else:
            require(record["locator"] and digest(repo_file(path)) == record["sha256"],
                    "Source hash/locator: " + record["id"])
    require(set(p["parameters"]) == PARAMETER_NAMES, "Dimension trace coverage differs from parameter contract")
    v = values(p)
    for name, record in p["parameters"].items():
        numbers = record["value"] if isinstance(record["value"], list) else [record["value"]]
        require(numbers and all(type(n) in (int, float) and math.isfinite(n) for n in numbers), "Finite parameter: " + name)
        require(record["unit"] and record["basis"], "Missing dimension basis: " + name)
        require(record["kind"] in ("source_record", "design_assumption"), "Missing dimension trace: " + name)
        if record["kind"] == "source_record":
            require(record.get("source_id") in sources and record.get("locator"), "Unbound dimension: " + name)
        if name not in ("hub_center_xy_mm", "cable_stub_z_mm"):
            require(all(n > 0 for n in numbers), "Positive dimensions required: " + name)
    parent = read_json(repo_file(sources["v2-interface"]["path"]))
    for key, pointer in SOURCE_BINDINGS.items():
        expected = parent
        for bit in pointer.split("."):
            expected = expected[bit]
        record = p["parameters"][key]
        require(record.get("source_id") == "v2-interface" and record.get("locator") == pointer and
                record["kind"] == "source_record" and v[key] == expected, "Sourced dimension drift: " + key)
    require(v["panel_mass_kg"] == 3.1 and p["parameters"]["panel_mass_kg"].get("source_id") == "v2-model",
            "Panel vendor mass/source drift")
    require(v["panel_xyz_mm"] == [668, 425, 25] and v["hub_xyz_mm"] == [275, 175, 66.6], "Purchased envelope drift")
    require(3 <= v["panel_tilt_deg"] <= 5, "Drainage tilt outside 3-5 degrees")
    require(v["pole_od_mm"] == 60 and v["socket_id_mm"] > v["pole_od_mm"], "60 mm pole/socket clearance")
    require(v["socket_od_mm"] > v["socket_id_mm"] and 2*v["pole_wall_mm"] < v["pole_od_mm"], "Tube wall geometry")
    require(v["bolt_hole_diameter_mm"] > v["bolt_allocation_diameter_mm"], "Cross-bolt allocation clearance")
    require(len(v["bolt_centres_below_tray_mm"]) == 2 and len(set(v["bolt_centres_below_tray_mm"])) == 2,
            "Exactly two cross-bolt allocations required")
    require(all(v["socket_flange_thickness_mm"]+v["bolt_hole_diameter_mm"]/2 < b <
                v["socket_length_mm"]-v["bolt_hole_diameter_mm"]/2 for b in v["bolt_centres_below_tray_mm"]), "Bolt positions")
    require(v["socket_flange_od_mm"] > v["socket_od_mm"] and v["socket_length_mm"] > v["socket_flange_thickness_mm"], "Socket flange")
    require(v["float_outer_xy_mm"][0] > v["tray_xy_mm"][0] > v["skirt_xy_mm"][0] and
            v["float_outer_xy_mm"][1] > v["tray_xy_mm"][1] > v["skirt_xy_mm"][1], "Float/tray bearing relationship")
    require(v["site_depth_mm"] > v["socket_length_mm"] and v["freeboard_mm"] > v["skirt_depth_mm"], "Pole length/freeboard")
    require(v["foam_density_kg_m3"] < v["seawater_density_kg_m3"], "Foam density scenario")
    require(v["cable_stub_z_mm"][0] < 0 < v["cable_stub_z_mm"][1], "Cable pass-through allocation")
    return sources


def load(path=None):
    p = read_json(path or CANDIDATE / "interface.json")
    validate(p)
    return p


def layout(p):
    """All placements are derived from traced inputs; CAD +Z up, origin at water."""
    v = values(p)
    a = math.radians(v["panel_tilt_deg"])
    sx, sy, _ = v["panel_xyz_mm"]
    shade_top = -v["shade_to_tray_mm"]
    shade_bottom = shade_top-v["shade_thickness_mm"]
    hub_top = shade_bottom-v["shade_hub_gap_mm"]
    hub_bottom = hub_top-v["hub_xyz_mm"][2]
    hy = v["hub_center_xy_mm"][1]
    sink_front = hy-v["hub_xyz_mm"][1]/2-v["sink_hub_gap_mm"]
    sink_back = sink_front-v["sink_xyz_mm"][1]
    return {"panel_centres_y_mm": [-(sy+v["panel_gap_mm"])/2, (sy+v["panel_gap_mm"])/2],
            "panel_origin_z_mm": v["tray_thickness_mm"]+v["panel_low_clearance_mm"]+sx/2*math.sin(a),
            "panel_angle_rad": a, "shade_bottom_mm": shade_bottom, "shade_top_mm": shade_top,
            "hub_bottom_mm": hub_bottom, "hub_top_mm": hub_top,
            "hub_mid_z_mm": (hub_top+hub_bottom)/2,
            "shade_y_mm": (sink_back+hy+v["hub_xyz_mm"][1]/2)/2,
            "sink_y_mm": (sink_back+sink_front)/2,
            "pole_length_mm": v["site_depth_mm"]+v["freeboard_mm"],
            "surface_origin_pole_mm": v["freeboard_mm"]}


def prepare_output(path):
    target = Path(path).absolute()
    # macOS /tmp is a system alias for /private/tmp, not a user output redirect.
    require(not any(p.is_symlink() and not (p == Path("/tmp") and p.resolve() == Path("/private/tmp"))
                    for p in [target, *target.parents]), "Refuse symlink output")
    # Refuse any repository output except the new candidate's generated subtree.
    if target.is_relative_to(ROOT):
        require(target.is_relative_to(CAD / "generated"), "Refuse output outside candidate generated subtree")
    require(not target.exists() or (target.is_dir() and not any(target.iterdir())), "Output must be new or empty")
    target.mkdir(parents=True, exist_ok=True)
    for folder in ("step", "allocations", "drawings"):
        (target / folder).mkdir()
    return target


def mechanics(p, parts):
    """Scenario arithmetic only. Purchased envelope volume is never metal mass."""
    v = values(p)
    rows = []
    for part in parts:
        row = {"name": part["name"], "kind": part["kind"], "variant": part["variant"],
               "volume_mm3": part["volume_mm3"], "density_assumed_kg_m3": None,
               "vendor_nominal_mass_kg": None, "modeled_dry_mass_kg": None}
        if part["kind"] == "physical_custom":
            density_key = {"aluminum": "aluminum_density_kg_m3", "steel": "steel_density_kg_m3", "foam": "foam_density_kg_m3"}[part["material"]]
            row["density_assumed_kg_m3"] = v[density_key]
            row["modeled_dry_mass_kg"] = part["volume_mm3"]*v[density_key]/1e9
            row["mass_basis"] = "Custom CAD material volume times explicitly assumed density, not measured"
        elif part["name"] in ("SV3_PANEL_A", "SV3_PANEL_B"):
            row["vendor_nominal_mass_kg"] = v["panel_mass_kg"]
            row["modeled_dry_mass_kg"] = v["panel_mass_kg"]
            row["mass_basis"] = "Panel datasheet nominal mass, NOT solid-envelope density"
        else:
            row["mass_basis"] = "Unknown purchased mass" if part["kind"] == "purchased_envelope" else "Nonphysical allocation excluded from mass and displacement"
        rows.append(row)
    common = sum(r["modeled_dry_mass_kg"] or 0 for r in rows if r["variant"] == "common")
    pole = sum(r["modeled_dry_mass_kg"] or 0 for r in rows if r["variant"] == "pole")
    collar = next(r for r in rows if r["name"] == "SV3_FLOAT_COLLAR")
    full_volume = collar["volume_mm3"]/1e9
    capacity = full_volume*v["seawater_density_kg_m3"]
    allowances = {k: v[k] for k in ("hub_scenario_mass_kg", "sink_scenario_mass_kg", "unmodeled_payload_allowance_kg")}
    scenario = common+collar["modeled_dry_mass_kg"]+sum(allowances.values())
    area = (v["float_outer_xy_mm"][0]*v["float_outer_xy_mm"][1]-v["skirt_xy_mm"][0]*v["skirt_xy_mm"][1])/1e6
    draft = scenario/v["seawater_density_kg_m3"]/area
    margin = capacity-scenario
    return {"schema": "poseidon.surface-v3.mass-displacement.v1", "parts": rows,
            "actual_complete_mass_kg": None, "actual_buoyancy_sign": "UNKNOWN",
            "known_plus_assumed_common_subtotal_kg": common,
            "pole_variant_known_plus_assumed_subtotal_kg": common+pole,
            "excluded": ["hub actual mass", "sink actual mass", "attachment fasteners", "wiring and glands", "electronics", "battery and power integration", "mooring", "absorbed water and fouling"],
            "float_scenario": {"explicit_mass_allowances_kg": allowances,
                "collar_dry_mass_kg": collar["modeled_dry_mass_kg"], "dry_mass_kg": scenario,
                "foam_density_assumed_kg_m3": v["foam_density_kg_m3"], "seawater_density_assumed_kg_m3": v["seawater_density_kg_m3"],
                "waterplane_area_m2": area, "fully_submerged_displacement_m3": full_volume,
                "fully_submerged_supported_mass_kg": capacity, "fully_submerged_net_lift_kg_equivalent": margin,
                "fully_submerged_net_lift_n": margin*v["gravity_m_s2"],
                "fully_submerged_buoyancy_sign": "POSITIVE" if margin > 0 else "NEGATIVE" if margin < 0 else "NEUTRAL",
                "posed_displacement_m3": scenario/v["seawater_density_kg_m3"], "conditional_equilibrium_draft_m": draft,
                "conditional_equilibrium_net_lift_n": 0, "posed_buoyancy_sign": "NEUTRAL_BY_SCENARIO_CONSTRUCTION",
                "float_surface_y_m": v["float_height_mm"]/1000-draft,
                "basis": "Illustrative dry-mass scenario, not actual assembled mass. Only foam displacement credited. Open skirt, flooded pole and vendor envelopes receive no sealed-volume credit. No stability, load or wave claim."}}
