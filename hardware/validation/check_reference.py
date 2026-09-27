"""Check the issued digital reference and the absence of physical-test claims."""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REVISION = "HW-REF-1.1"
ASSEMBLIES = {"HUB", "WET", "ARRAY", "WIPER", "PROJECTOR", "REEF", "FARM", "JIG"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def positive_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def check_reference(interface: dict, plan: dict, traveler: dict) -> list[str]:
    checks: list[str] = []
    for name, record in (("interface", interface), ("physical plan", plan), ("traveler", traveler)):
        require(record["configuration"] == "reference-v1", f"{name}: wrong configuration")
        require(record["revision"] == REVISION, f"{name}: wrong revision")
    checks.append("configuration_and_revision_agree")

    require(interface["units"] == {
        "length": "mm", "voltage": "V_dc", "current": "A", "power": "W", "mass": "kg"
    }, "unsupported or ambiguous units")
    date.fromisoformat(interface["published_date"])
    checks.append("explicit_units_and_issue_date")

    require(interface["purchase_authorized"] is False, "reference cannot authorize purchases")
    require(interface["field_release_authorized"] is False, "reference cannot authorize field release")
    require(interface["status"] == "PROVISIONAL_REFERENCE_NOT_FOR_FABRICATION", "reference status changed")
    checks.append("no_purchase_fabrication_or_field_release")

    require(interface["default_variant"] == "passive_monitor", "default must remain passive")
    passive = interface["variants"]["passive_monitor"]
    require(passive["acoustic_output_hardware_populated"] is False, "passive output hardware must be absent")
    require(passive["wiper_drive_populated"] is False, "passive wiper drive must be absent")
    for name in ("array_research", "acoustic_research"):
        require(interface["variants"][name]["enabled_by_default"] is False, f"{name} enabled by default")
    checks.append("passive_default_and_optional_research")

    safety = interface["physical_safety"]
    require(safety["software_is_not_interlock"] is True, "software is not a physical interlock")
    require(safety["acoustic_limit"] is None, "no validated acoustic limit exists in this reference")
    require(safety["depth_limit_m"] is None, "no qualified depth exists in this reference")
    require(safety["environmental_operating_envelope"] is None, "no qualified environmental envelope exists")
    checks.append("unknown_physical_limits_stay_null")

    rails = {rail["id"]: rail for rail in interface["power_rails"]}
    require(len(rails) == len(interface["power_rails"]), "duplicate power rail")
    require(rails["VACT"]["nominal_v"] is None, "active branch has no selected supply")
    require(rails["VACT"]["status"] == "ABSENT_IN_PASSIVE_BUILD", "active branch is populated")
    require(rails["V3V3_REEF"]["nominal_v"] == 3.3, "REEF logical interface is 3.3 V")
    require(5.0 <= rails["V5_HUB"]["nominal_v"] <= 5.1, "hub nominal supply outside reference allocation")
    require(rails["V5_HUB"]["source_current_budget_a"] >= 3.0, "hub supply allocation below Pi vendor minimum")
    checks.append("rail_values_and_absent_output_branch")

    for envelope in interface["mechanical_envelopes"]:
        require(envelope["assembly"] in ASSEMBLIES, "unknown mechanical assembly")
        for key, value in envelope.items():
            if key.endswith("_mm"):
                dimensions = value if isinstance(value, list) else [value]
                require(all(positive_number(n) for n in dimensions), f"invalid {envelope['assembly']} {key}")
                if isinstance(value, list):
                    require(len(value) == 3, f"{key} must define three dimensions")
        if "usable_interior_mm" in envelope:
            require(all(
                inside < outside
                for inside, outside in zip(envelope["usable_interior_mm"], envelope["envelope_mm"])
            ), "usable interior must be smaller than exterior in every axis")
    checks.append("finite_positive_dimensions_and_interior_fit")

    harness_ids = [harness["id"] for harness in interface["harness_allocations"]]
    require(len(harness_ids) == len(set(harness_ids)), "duplicate harness allocation")
    for harness in interface["harness_allocations"]:
        require(harness["release_status"] not in ("APPROVED", "RELEASED"), "reference harness unexpectedly released")
    decisions = [decision["id"] for decision in interface["unresolved_decisions"]]
    require(len(decisions) == len(set(decisions)) and len(decisions) >= 8, "missing or duplicate open decisions")
    checks.append("unique_harnesses_and_open_decisions")

    require(plan["status"] == "PLAN_ONLY_NOT_AUTHORIZATION", "physical plan is not an authorization")
    require(type(plan["physical_tests_performed"]) is int and plan["physical_tests_performed"] == 0,
            "this reference contains no performed physical tests")
    test_ids = [test["id"] for test in plan["tests"]]
    require(len(test_ids) == len(set(test_ids)), "duplicate physical test")
    covered_assemblies: set[str] = set()
    for test in plan["tests"]:
        require(test["status"] == "not_performed", f"{test['id']}: unsupported performed claim")
        require(test["result"] is None and test["raw_evidence"] == [], f"{test['id']}: fabricated result")
        for field in ("owner", "method", "equipment", "freeze_before_test", "acceptance_rule", "blocks"):
            require(bool(test[field]), f"{test['id']}: missing {field}")
        covered_assemblies.update(test["assemblies"])
    require(covered_assemblies == ASSEMBLIES, "physical verification does not cover all reference assemblies")
    checks.append("unperformed_physical_plan_covers_all_assemblies")

    require(traveler["record_kind"] == "BLANK_TEMPLATE_NOT_UNIT_EVIDENCE", "traveler is not unit evidence")
    require(traveler["status"] == "not_started", "template cannot claim work started")
    for field in ("unit_serial", "activity_authorization_id", "actual_start_date", "actual_finish_date",
                  "measured_mass_kg", "measured_center_of_gravity_mm", "measured_power_states_w",
                  "pressure_qualification_record", "acoustic_calibration_record", "conformity_record", "release_signature"):
        require(traveler[field] is None, f"template contains unsupported {field}")
    require(traveler["test_results"] == [] and traveler["raw_evidence_paths"] == [], "template contains test evidence")
    checks.append("traveler_has_no_fabricated_unit_or_test_data")
    return checks


def load_records(root: Path) -> tuple[dict, dict, dict]:
    return tuple(json.loads((root / path).read_text()) for path in (
        "hardware/interfaces/reference-v1.json",
        "hardware/validation/physical-plan.json",
        "hardware/manufacturing/unit-traveler-template.json",
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    try:
        checks = check_reference(*load_records(args.root))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps({
        "status": "passed", "revision": REVISION, "checks": checks,
        "check_count": len(checks), "physical_tests_performed": 0,
        "meaning": "Digital reference consistency only; no hardware qualification or authorization."
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
