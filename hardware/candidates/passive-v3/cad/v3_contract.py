"""Standard-library bindings only. This module never imports a CAD kernel."""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

CAD = Path(__file__).resolve().parent
CANDIDATE = CAD.parent
ROOT = CANDIDATE.parents[2]
STATUS = "NON_ADOPTED_NOT_BUILD_AUTHORIZED"
SCHEMA = "intrface.passive-v3.cad.v1"
SOURCE_NAMES = (
    "interface.json", "baseline-lock.json", "sources/source-register.json",
    "sources/dimension-traces.json", "cad/v3_contract.py", "cad/v3_model.py",
    "cad/v3_proxy.py", "cad/v3_export.py", "cad/generate.py", "cad/check.py",
)
EXCLUDED_BASELINE = {
    "HARDWARE.md", "hardware/candidates/passive-v2/baseline-lock.json",
    "hardware/candidates/passive-v2/cad/baseline-lock.json",
    "hardware/candidates/passive-v2/cad/generated/passive-v2/manifest.json",
    "hardware/candidates/passive-v2/power/evidence.json",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def safe_file(base, name):
    rel = Path(name)
    require(not rel.is_absolute() and ".." not in rel.parts and bool(rel.parts), "Unsafe relative path")
    path = Path(base) / rel
    require(path.is_file() and not any((Path(base) / Path(*rel.parts[:i])).is_symlink() for i in range(1, len(rel.parts)+1)), "Missing or symlink source/artifact: " + name)
    require(path.resolve().is_relative_to(Path(base).resolve()), "Path escapes package")
    return path


def baseline_check(candidate=CANDIDATE, root=ROOT):
    lock = read_json(candidate / "baseline-lock.json")
    require(lock["schema"] == "intrface.passive-v3.baseline-lock.v1", "Baseline schema drift")
    require(set(lock["excluded_mutable_catalog_metadata"]) == EXCLUDED_BASELINE, "Mutable catalog exclusion drift")
    require(not EXCLUDED_BASELINE.intersection(lock["files"]), "Mutable B3 metadata must not be frozen")
    require(len(lock["files"]) >= 10, "Empty/truncated immutable baseline")
    for name, expected in lock["files"].items():
        require(digest(safe_file(root, name)) == expected, "Immutable baseline drift: " + name)
    return {"files_checked": len(lock["files"]), "changed": 0, "lock_sha256": digest(candidate / "baseline-lock.json")}


def numeric_leaves(value, prefix=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from numeric_leaves(child, prefix + "." + key if prefix else key)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from numeric_leaves(child, prefix + "." + str(i))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        require(math.isfinite(value), "Nonfinite dimension")
        yield prefix, value


def validate(interface, candidate=CANDIDATE):
    p = interface
    require(p["schema"] == "intrface.passive-v3.interface.v1" and p["configuration"] == "passive-v3" and p["revision"] == "HW-CAND-3.0" and p["product"] == "Poseidon Trident" and p["company"] == "Intrface", "Candidate identity drift")
    require(p["status"] == STATUS and all(p[k] is False for k in ("adopted", "build_authorized", "procurement_authorized", "active_emission_hardware_populated")), "Candidate authorization boundary")
    require(p["physical_tests_performed"] == [], "No physical evidence exists")
    require(p["target_envelope"] == {"depth_m": 30, "continuous_immersion_days": 90, "classification": "required target, NOT verified assembly rating", "verified_assembly_depth_m": None, "verified_assembly_immersion_days": None}, "Targets are not assembly ratings")
    require(p["units"] == {"cad": "mm", "glb": "m", "mass": "kg", "volume": "mm3"}, "Units drift")
    source = candidate / "sources"
    require(digest(source / "source-register.json") == p["sources"]["register_sha256"], "Source register binding drift")
    require(digest(source / "dimension-traces.json") == p["sources"]["dimension_traces_sha256"], "Dimension register binding drift")
    register = read_json(source / "source-register.json")
    records = register["records"]
    require(p["reuse_rights"] == register["reuse_rights"], "Vendor rights binding drift")
    require(register["reuse_rights"]["vendor_cad"] == "UNVERIFIED_NOT_CC0"
            and register["reuse_rights"]["vendor_files_public_redistribution_authorized"] is False
            and register["reuse_rights"]["public_redistribution_authorized"] is True
            and register["reuse_rights"]["derived_assembly_wholly_original"] is True
            and register["reuse_rights"]["original_design_license"] == "CERN-OHL-S-2.0",
            "Vendor source rights and original proxy boundary")
    for name, record in records.items():
        require(record["file"] == name and record["retrieved"] == "2026-09-09"
                and record["url"].startswith(("https://", "local://"))
                and len(record["sha256"]) == 64
                and record["license_status"] == ("CERN-OHL-S-2.0" if record["url"].startswith("local://")
                                                  else "supplier_redistribution_unverified"),
                "Source provenance or redistribution status missing")
        if record["url"].startswith("local://"):
            require(digest(safe_file(source, name)) == record["sha256"], "Source hash drift: " + name)
        if "archive" in record:
            require(record["archive"] in records
                    and records[record["archive"]]["sha256"] == record["archive_sha256"],
                    "Archive provenance drift")
    traces = read_json(source / "dimension-traces.json")["dimensions"]
    require(set(p["dimensions"]) == set(traces) and len(traces) >= 200, "Dimension trace coverage drift")
    for name, record in traces.items():
        require(p["dimensions"][name] == record["value"] and math.isfinite(record["value"]), "Traced dimension drift: " + name)
        authority = records[record["source_file"]]
        require(record["source_sha256"] == authority["sha256"] and record["url"] == authority["url"] and record["retrieved"] == authority["retrieved"] and record["locator"], "Per-dimension provenance drift: " + name)
        for support in record.get("supporting_records", []):
            require(support["sha256"] == records[support["file"]]["sha256"] and support["url"] == records[support["file"]]["url"], "Supporting page/PDF hash drift")
    design = read_json(source / "design-inputs.json")["allocations"]
    require(p["allocations"] == design, "Local design allocation drift")
    require({"design."+k: v for k, v in numeric_leaves(design)} == {k: v["value"] for k, v in traces.items() if k.startswith("design.")}, "Untraced local design dimension")
    receive = p["receive_chain"]
    require(receive["preamp"] == "PA4/PA6 phantom preamp ABOVE WATER dry hub" and receive["underwater_preamp_populated"] is False and receive["underwater_preamp_dimensions_mm"] is None and receive["preamp_reserve"] == "EMPTY_NONPOPULATED_LOCAL_ALLOCATION" and receive["conditioner_relocated"] is False, "Preamp must stay above water; reserve EMPTY")
    require(receive["analog_transport_verified"] is False and receive["camera_usb_transport_30m_verified"] is False and receive["standard_as1_cable_m"] == 9, "30 m transport unresolved; standard AS1 cable insufficient")
    require(p["pressure_boundary"]["dome"] == "BR-107201 hardened polycarbonate, NOT acrylic", "Vendor polycarbonate material must not become acrylic")
    require(p["pressure_boundary"]["sealed_in_model"] is False and p["pressure_boundary"]["unused_open_penetrator_holes"] == 4, "Incomplete closure must not claim sealed assembly")
    require(p["connector_option"]["populated"] is False and p["connector_option"]["cad_exported"] is False and p["connector_option"]["body_length_mm"] is None, "Incomplete Cobalt option cannot masquerade as manufactured CAD")
    require(all(value is None for value in p["unresolved"].values()), "Unknown interfaces must remain null")
    require(p["future_projector"] == {"label": "EMPTY_FUTURE_PROJECTOR_MOUNT_ENVELOPE", "populated": False, "included_in_physical_interference": False, "included_in_mass": False, "included_in_displacement": False}, "Empty future projector boundary")
    require([g["id"] for g in p["open_gates"]] == [f"G{i:02d}" for i in range(1, 15)] and all(g["status"] == "not_performed" and g["result"] is None for g in p["open_gates"]), "14 physical gates remain unperformed")
    require(p["required_sentence"] == "this is a non-adopted digital candidate with no pressure, corrosion or suitability evidence.", "Physical evidence disclaimer missing")
    budget = stack_budget(p)
    require(budget["selected_tube_length_mm"] == 300 and budget["margin_mm"] >= 0 and budget["rejected_200mm_margin_mm"] < 0, "Tube stack allocation does not fit sourced length")
    return register, traces


def stack_budget(p):
    d, a = p["dimensions"], p["allocations"]
    contributions = {"camera_front_and_rear": d["camera.front_depth"] + d["camera.rear_depth"], "camera_mount": a["camera_mount_depth_mm"], "service_route": a["service_route_axial_mm"], "EMPTY_preamp_reserve": a["empty_preamp_reserve_size_mm"][2], "two_flange_insertions": 2*d["flange.piston_length"], "clearance": a["stack_clearance_mm"]}
    required = sum(contributions.values())
    return {"contributions_mm": contributions, "required_mm": required, "selected_tube_length_mm": d["tube.length"], "margin_mm": d["tube.length"]-required, "rejected_200mm_margin_mm": 200-required, "note": "Axial allocation budget only; EMPTY reserve is not preamp hardware. Vendor 300 mm is shortest listed length that fits this budget."}


def load(path=None, candidate=CANDIDATE):
    p = read_json(path or candidate / "interface.json")
    validate(p, candidate)
    return p


def source_bindings(candidate=CANDIDATE):
    return {name: digest(safe_file(candidate, name)) for name in SOURCE_NAMES}


def prepare_output(output):
    output = Path(output)
    require(not output.is_symlink() and not (output.exists() and (not output.is_dir() or any(output.iterdir()))), "Output must be NEW or EMPTY; refusing overwrite")
    output.mkdir(parents=True, exist_ok=True)
    for name in ("step", "drawings", "keepouts"):
        (output / name).mkdir()


def write_json(path, value):
    path = Path(path)
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")
