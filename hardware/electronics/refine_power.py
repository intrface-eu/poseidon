#!/usr/bin/env python3
"""Bounded, non-adopted power comparison. Never edits the HW-REF-1.1 baseline."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "refinement-evidence.json"
EXPECTED_BASELINE_SHA256 = "dfc71d2a6bfffc8a99b12e83af9e5daf9ad33ead8da6337c50cdfb7f1b17e40f"
DISPOSITION = "BLOCKED_ON_THERMAL_POWER_PATH_AND_PART_SELECTION"
BASELINE_PATHS = (
    "hardware/electronics/reference-inputs.json",
    "hardware/electronics/reference-evidence.json",
    "hardware/electronics/calculate.py",
    "hardware/bom/sources.json",
    "hardware/bom/reference-v1.json",
    "hardware/wiring/connectors.csv",
    "hardware/wiring/harnesses.csv",
    "hardware/wiring/design.json",
    "hardware/wiring/schematic.txt",
)
_SPEC = importlib.util.spec_from_file_location("poseidon_frozen_power_calculations", HERE / "calculate.py")
assert _SPEC and _SPEC.loader
base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(base)


def baseline_hashes() -> dict[str, str]:
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in BASELINE_PATHS}


def load_frozen() -> tuple[dict, dict, dict, dict]:
    hashes = baseline_hashes()
    if hashes["hardware/electronics/reference-evidence.json"] != EXPECTED_BASELINE_SHA256:
        raise ValueError("frozen baseline evidence hash changed; review rather than replace the failed case")
    inputs = base.load_inputs(HERE / "reference-inputs.json")
    evidence = base.load_inputs(HERE / "reference-evidence.json")
    sources = base.load_inputs(ROOT / "hardware/bom/sources.json")
    for record in (inputs, evidence, sources):
        if record["reference"] != "HW-REF-1.1" or record["configuration"] != "reference-v1":
            raise ValueError("refinement requires HW-REF-1.1/reference-v1")
    if evidence["energization_allowed"] is not False:
        raise ValueError("baseline must remain unqualified and not energizable")
    controller = next(s["verified_facts"] for s in sources["sources"] if s["id"] == "SRC-MPPT")
    return inputs, evidence, controller, hashes


def positive_count(value: int, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer, not a boolean or fractional count")
    return value


def array_comparison(series: int, parallel: int, inputs: dict, evidence: dict,
                     controller: dict) -> dict:
    series = positive_count(series, "series count")
    parallel = positive_count(parallel, "parallel count")
    s, r = inputs["solar"], inputs["rails"]
    panel_w = base.number(s["panel_stc_w"], "catalog panel W", positive=True)
    catalog_voc = base.number(s["panel_voc_stc_v"], "catalog Voc V", positive=True)
    catalog_isc = base.number(s["panel_isc_stc_a"], "catalog Isc A", positive=True)
    multiplier = base.number(s["isc_sizing_multiplier"], "Isc multiplier", minimum=1)
    array_w = panel_w * series * parallel
    array_voc = catalog_voc * series
    design_isc = catalog_isc * parallel * multiplier
    cold_voc = base.pv_voc_at_temperature(array_voc, s["voc_temperature_coefficient_per_c"], s["cold_cell_c"])
    hot_voc = base.pv_voc_at_temperature(array_voc, s["voc_temperature_coefficient_per_c"], s["hot_cell_c"])
    start_v = base.number(r["battery_max_v"], "battery max V", positive=True) + base.number(s["mppt_start_margin_v"], "start margin V", positive=True)
    ideal_charge_a = array_w / base.number(r["battery_min_v"], "battery min V", positive=True)
    energy = base.solar_energy(array_w, s["peak_sun_hours"], s["field_derate"],
                              s["charge_efficiency"], evidence["reef"]["daily_wh"],
                              inputs["battery"]["discharge_efficiency"])
    screens = {
        "cold_voc_below_controller_max": cold_voc < base.number(s["mppt_max_voc_v"], "max Voc", positive=True),
        "hot_voc_above_start_requirement": hot_voc > start_v,
        "design_isc_below_controller_max": design_isc < base.number(s["mppt_max_isc_a"], "max Isc", positive=True),
        "ideal_stc_charge_within_controller_limit": ideal_charge_a <= base.number(s["mppt_max_charge_a"], "max charge A", positive=True),
        "stc_power_within_nominal_12v_pv_limit": array_w <= base.number(controller["nominal_pv_w_at_12v"], "nominal PV limit W", positive=True),
        "load_side_daily_energy_covers_reef": energy["sustainable_under_assumptions"],
    }
    return {
        "scenario": f"{series}S{parallel}P", "series": series, "parallel": parallel,
        "panel_count": series * parallel, "panel_mpn": "SPM040401200",
        "array_stc_power_w": array_w, "array_stc_voc_v": array_voc,
        "array_design_isc_a": design_isc, "cold_voc_v": cold_voc,
        "hot_voc_v": hot_voc, "required_start_v": start_v,
        "ideal_stc_charge_a_at_min_battery": ideal_charge_a,
        "reef_daily_load_wh": evidence["reef"]["daily_wh"],
        "energy": energy, "screens": screens,
        "all_array_calculation_screens_pass": all(screens.values()),
        "adopted_configuration": False,
        "all_reference_hardware_qualified": False,
        "energization_allowed": False,
        "disposition": DISPOSITION,
        "screen_limits": "Voc is a necessary startup screen, not loaded startup/MPPT validation. No series mismatch, shading, cable, connector, tolerance or fault qualification is implied.",
    }


def uncertainty_temperature_screen(air_c: float, uncertainty_c: float,
                                   vendor_limit_c: float = 50.0) -> dict:
    air = base.number(air_c, "air temperature C", minimum=-100, maximum=200)
    uncertainty = base.number(uncertainty_c, "temperature uncertainty C", minimum=0)
    limit = base.number(vendor_limit_c, "vendor ambient limit C", minimum=-100, maximum=200)
    return {"upper_air_c": air + uncertainty,
            "inequality_passes": air + uncertainty <= limit,
            "qualification": False,
            "note": "Arithmetic only; no measurement, approved method or live-test authorization supplied."}


def thermal_requirements(inputs: dict, evidence: dict) -> dict:
    t = inputs["thermal"]
    heat = base.number(evidence["thermal"]["peak_enclosed_heat_w"], "frozen peak heat W", positive=True)
    ambient = base.number(t["ambient_c"], "ambient C", minimum=-100, maximum=150)
    limit = base.number(t["pi_max_ambient_c"], "Pi ambient limit C", minimum=-100, maximum=150)
    rth = base.number(t["enclosure_rth_k_per_w"], "existing Rtheta K/W", positive=True)
    sun = base.number(evidence["thermal"]["absorbed_solar_w"], "absorbed sun W", minimum=0)
    eta = base.fraction(inputs["converter"]["efficiency"], "converter efficiency")
    voltage = base.number(inputs["rails"]["pi_source_v"], "Pi supply V", positive=True)
    margin = limit - ambient
    if margin <= 0:
        raise ValueError("no positive thermal headroom at the frozen ambient")
    heat_cap = margin / rth
    output_cap = eta * heat_cap
    workload = [{"state": state["name"], "pi_and_usb_output_w": state["output_5v_w"],
                 "exceeds_shade_output_cap": state["output_5v_w"] > output_cap}
                for state in evidence["hub"]["states"]]
    peak_output = evidence["hub"]["peak"]["output_5v_w"]
    workload.append({"state": "peak", "pi_and_usb_output_w": peak_output,
                     "exceeds_shade_output_cap": peak_output > output_cap})
    return {
        "ambient_c": ambient, "pi_vendor_ambient_limit_c": limit,
        "headroom_c": margin, "peak_enclosed_heat_w": heat,
        "absorbed_solar_w": sun, "existing_assumed_rtheta_k_per_w": rth,
        "required_shade_rtheta_max_k_per_w": margin / heat,
        "required_sun_rtheta_max_k_per_w": margin / (heat + sun),
        "shade_temperature_at_existing_assumption_c": ambient + rth * heat,
        "sun_temperature_at_existing_assumption_c": ambient + rth * (heat + sun),
        "shade_enclosed_heat_cap_w_at_existing_rtheta": heat_cap,
        "shade_pi_and_usb_output_cap_w_at_existing_rtheta": output_cap,
        "shade_pi_and_usb_output_cap_a_at_5v1": output_cap / voltage,
        "sun_heat_alone_exceeds_headroom_at_existing_rtheta": rth * sun > margin,
        "workload_comparison": workload,
        "workload_reduction_justified": False,
        "replacement_rtheta_selected": None,
        "measured_rtheta_k_per_w": None,
        "thermal_path_selected": False,
        "thermal_qualified": False,
        "requirements_are_zero_uncertainty_upper_bounds": True,
        "uncertainty_acceptance": {
            "inequality": "Tair_measured + U <= 50 degC",
            "measurement": None, "uncertainty": None,
            "frozen_conditions": "35degC ambient, frozen simultaneous peak load and declared shade or48W absorbed-sun exposure; no cooler ambient or reduced load substitution",
            "method_owner": "qualified reviewer sets approved sensor locations, calibration, uncertainty, stabilization, duration and exposure method before testing",
            "extra_requirements": "Verify Pi/converter local hotspots, junction/derating and fault behavior separately; air-temperature inequality alone is not full qualification.",
            "live_tests_authorized": False,
        },
        "mechanical_measurement_blocker": "No selected purchased enclosure wall material/thickness, Pi/converter heat-spreader/contact stack, external dissipator mounting/area, or sun-shield spacing/ventilation. No measured internal-air rise or effective heat-path resistance at frozen load/exposure. A lower convenient Rtheta cannot be substituted for those missing parts and measurements.",
    }


def build_refinement() -> dict:
    inputs, evidence, controller, hashes = load_frozen()
    arrays = [array_comparison(s, p, inputs, evidence, controller) for s, p in ((1, 1), (2, 1), (1, 2))]
    result = {
        "study": "POWER-REFINEMENT-1", "baseline_reference": "HW-REF-1.1",
        "baseline_configuration": "reference-v1", "evidence_kind": "calculated_comparison_not_measured_or_adopted",
        "baseline_evidence_sha256": EXPECTED_BASELINE_SHA256,
        "baseline_file_sha256": hashes,
        "baseline_failed_case_preserved": True,
        "adopted_configuration": False, "all_reference_hardware_qualified": False,
        "energization_allowed": False, "disposition": DISPOSITION,
        "frozen_solar_inputs": inputs["solar"],
        "frozen_battery_inputs": inputs["battery"],
        "frozen_battery_rail_v": [inputs["rails"]["battery_min_v"], inputs["rails"]["battery_max_v"]],
        "unchanged_reef_daily_load_wh": evidence["reef"]["daily_wh"],
        "unchanged_usable_load_side_battery_wh": evidence["battery"]["usable_load_side_wh"],
        "controller_nominal_pv_power_limit_w_at_12v": controller["nominal_pv_w_at_12v"],
        "arrays": arrays, "thermal": thermal_requirements(inputs, evidence),
        "adoption_boundary": "Physical CAD frame, BOM, panel count and harness remain the1-panel HW-REF-1.1 reference. Any2-panel choice needs a new reference issue, frame/loads/geometry, cable/connector/protection and BMS/MPPT review before adoption.",
        "remaining_physical_blockers": [
            "Unselected/unmeasured enclosure heat path and exposure control; current thermal assumption fails.",
            "Pi USB-C source/CC/current limit/OVP/cable and12V source/protection are not a qualified power path.",
            "External Smart-battery BMS, charger/load disconnects and REEF regulators remain unselected.",
            "Two-panel framing/mount loads, series voltage insulation/connectors, parallel reverse-current/fusing and MPPT hot loaded startup need separate design and qualification.",
            "Panel availability, wet acquisition/pressure/connector parts, site solar and all electrical qualification remain open.",
        ],
        "claims_not_supported": ["viable passive product", "field autonomy", "thermal qualification", "procurement approval", "two-panel adoption", "live-test authorization"],
    }
    if baseline_hashes() != hashes:
        raise ValueError("baseline files changed during comparison; retry only after coordinator review")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Only hardware/electronics/refinement-evidence.json may be written; otherwise stdout")
    args = parser.parse_args()
    try:
        if args.output is not None and args.output.resolve() != OUTPUT.resolve():
            raise ValueError("output must be the new refinement-evidence.json, never a baseline or other file")
        # Resolve/check symlinks against the fixed new output path before writing.
        if args.output is not None and (args.output.is_symlink() or OUTPUT.is_symlink()):
            raise ValueError("refinement output may not be a symlink")
        text = base.deterministic_json(build_refinement())
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (ValueError, KeyError, TypeError, OSError, OverflowError, StopIteration) as exc:
        parser.exit(2, f"invalid refinement input/output: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
