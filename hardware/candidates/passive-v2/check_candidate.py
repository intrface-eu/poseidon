"""Verify the historical byte lock and calculate candidate panel-load changes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(path):
    return json.loads(path.read_text())


def verify_baseline():
    lock = load(HERE / "baseline-lock.json")
    if lock["reference"] != "HW-REF-1.1" or lock["configuration"] != "reference-v1":
        raise ValueError("wrong historical baseline")
    failures = []
    for name, expected in lock["files"].items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            failures.append(name)
    if failures:
        raise ValueError("historical baseline changed: " + ", ".join(failures))
    return len(lock["files"])


def wind_comparison(interface, baseline):
    reef = interface["mechanical"]["reef"]
    count = reef["panel_count"]
    if type(count) is not int or count != 2 or reef["topology"] != "2S1P_NON_ADOPTED":
        raise ValueError("this candidate requires two actual series panels")
    x, y, thick = reef["single_panel_xyz_mm"]
    if [x, y, thick] != [668,425,25]:
        raise ValueError("vendor panel geometry changed")
    if reef["panel_pair_footprint_xy_mm"] != [x, count*y + reef["gap_between_panels_mm"]]:
        raise ValueError("two-panel footprint does not include the physical gap")
    original = baseline["inputs"]
    single_area = original["panel_width_mm"] * original["panel_height_mm"] / 1e6
    candidate_area = count*x*y/1e6
    if abs(candidate_area - reef["total_panel_area_m2"]) > 1e-12:
        raise ValueError("candidate panel count/area mismatch")
    roof_x, roof_y = interface["mechanical"]["shade"]["roof_xy_mm"]
    roof_area = roof_x*roof_y/1e6
    rows = []
    for speed in original["wind_speeds_m_s"]:
        scale = .5*original["air_density_kg_m3"]*original["panel_normal_drag_coefficient"]*speed**2
        rows.append({"assumed_normal_wind_m_s":speed,
                     "one_panel_reference_force_n":scale*single_area,
                     "two_panel_candidate_force_n":scale*candidate_area,
                     "hub_roof_separate_force_n_using_same_assumed_coefficient":scale*roof_area})
    return {"equation":"F=0.5*rho*Cd*projected_area*v^2",
            "single_panel_area_m2":single_area,"candidate_panel_area_m2":candidate_area,
            "candidate_panel_area_ratio":candidate_area/single_area,"hub_roof_plan_area_m2":roof_area,
            "rows":rows,"frame_strength_qualified":False,
            "note":"Same illustrative air density, normal drag coefficient and wind speeds as1.1, not site loads. Panel force doubles; roof is a separate component load, not added to another mounting without a load-path model. Frame drag, angle/shielding, gusts/waves, overturning and attachments remain unqualified."}


def build():
    checked = verify_baseline()
    interface = load(HERE / "interface.json")
    if (interface["configuration"],interface["revision"],interface["status"]) != ("passive-v2","HW-CAND-2.0","NON_ADOPTED_NOT_BUILD_AUTHORIZED"):
        raise ValueError("candidate identity/status mismatch")
    if interface["adopted"] or interface["purchase_authorized"] or interface["physical_tests_performed"]:
        raise ValueError("this digital candidate cannot adopt or qualify physical hardware")
    thermal = load(HERE / "thermal/results.json")
    if thermal["thermal_qualified"] or thermal["adopted"] or thermal["physical_tests_performed"]:
        raise ValueError("thermal reference contains unsupported qualification")
    if not all(value is None for value in thermal["actual_installed_values"].values()):
        raise ValueError("unmeasured installed thermal values must remain null")
    baseline_scenario = load(ROOT / "hardware/analysis/scenario.json")
    return {"configuration":"passive-v2","revision":"HW-CAND-2.0",
            "status":"DIGITAL_CHECKS_ONLY_NO_ADOPTION","baseline_files_verified":checked,
            "baseline_modified":False,"wind_comparison":wind_comparison(interface,baseline_scenario),
            "thermal_screen":thermal["thermal_screen"],"thermal_sensitivity_cases":thermal["case_count"],
            "physical_tests_performed":0,"adopted":False,
            "meaning":"Byte-preservation and analytical/source consistency only. Execute separate candidate CAD geometry and power checks; this command does not run those engines or approve hardware."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    try:
        text=json.dumps(build(),indent=2,sort_keys=True,allow_nan=False)+"\n"
        if args.output:
            with args.output.open("x") as stream: stream.write(text)
        else: print(text,end="")
    except (ValueError,KeyError,TypeError,OSError) as exc:
        parser.exit(2,f"candidate check: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
