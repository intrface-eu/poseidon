#!/usr/bin/env python3
"""Offline power-path candidate. No hardware/network operations; no baseline writes."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUTPUT = HERE / "evidence.json"
_SPEC = importlib.util.spec_from_file_location("frozen_poseidon_electrical_equations", ROOT / "hardware/electronics/calculate.py")
assert _SPEC and _SPEC.loader
base = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(base)
STATUS = "NON_ADOPTED_NOT_BUILD_AUTHORIZED"
DISPOSITION = "BLOCKED_ON_FIELD_DC_POWER_PROTECTION_AND_ANCILLARY_UNCERTAINTY"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_check() -> dict:
    path = HERE.parent / "baseline-lock.json"
    lock = base.load_inputs(path)
    if lock["reference"] != "HW-REF-1.1":
        raise ValueError("wrong frozen baseline revision")
    failures = []
    for relative, expected in lock["files"].items():
        actual_path = (ROOT / relative).resolve()
        if not actual_path.is_relative_to(ROOT):
            raise ValueError("baseline path leaves repository")
        if not actual_path.is_file() or digest(actual_path) != expected:
            failures.append(relative)
    if failures:
        raise ValueError("frozen baseline changed: " + ", ".join(failures))
    return {"file_count": len(lock["files"]), "all_unchanged": True,
            "manifest_sha256": digest(path),
            "evidence_sha256": digest(ROOT / "hardware/electronics/reference-evidence.json")}


def load_context() -> dict:
    check = baseline_check()
    inputs = base.load_inputs(HERE / "inputs.json")
    if check["evidence_sha256"] != inputs["baseline_evidence_sha256"]:
        raise ValueError("failed baseline evidence hash changed")
    context = {
        "candidate": inputs,
        "sources": base.load_inputs(HERE / "source-register.json"),
        "bom": base.load_inputs(HERE / "bom.json"),
        "envelopes": base.load_inputs(HERE / "part-envelopes.json"),
        "baseline_inputs": base.load_inputs(ROOT / inputs["baseline_inputs"]),
        "baseline_evidence": base.load_inputs(ROOT / inputs["baseline_evidence"]),
        "inherited_sources": base.load_inputs(ROOT / "hardware/bom/sources.json"),
        "baseline_check": check,
    }
    for key in ("candidate", "sources", "bom", "envelopes"):
        record = context[key]
        if (record["revision"], record["configuration"], record["status"]) != ("HW-CAND-2.0", "passive-v2", STATUS):
            raise ValueError(f"candidate identity/status mismatch in {key}")
    return context


def array_screen(series: int, parallel: int, solar: dict, rails: dict,
                 nominal_controller_pv_w: float) -> dict:
    for value in (series, parallel):
        if type(value) is not int or value <= 0:
            raise ValueError("panel series/parallel counts must be positive integers")
    watts = base.number(solar["panel_stc_w"], "panel W", positive=True) * series * parallel
    voc = base.number(solar["panel_voc_stc_v"], "panel Voc", positive=True) * series
    isc = (base.number(solar["panel_isc_stc_a"], "panel Isc", positive=True) * parallel
           * base.number(solar["isc_sizing_multiplier"], "Isc factor", minimum=1))
    cold = base.pv_voc_at_temperature(voc, solar["voc_temperature_coefficient_per_c"], solar["cold_cell_c"])
    hot = base.pv_voc_at_temperature(voc, solar["voc_temperature_coefficient_per_c"], solar["hot_cell_c"])
    start = base.number(rails["battery_max_v"], "battery max V", positive=True) + base.number(solar["mppt_start_margin_v"], "MPPT start V", positive=True)
    charge_a = watts / base.number(rails["battery_min_v"], "battery min V", positive=True)
    checks = {
        "cold_voc_below75v": cold < base.number(solar["mppt_max_voc_v"], "MPPT Voc limit", positive=True),
        "hot_voc_above_battery_plus5v": hot > start,
        "design_isc_below13a": isc < base.number(solar["mppt_max_isc_a"], "MPPT Isc limit", positive=True),
        "charge_current_within10a": charge_a <= base.number(solar["mppt_max_charge_a"], "MPPT charge limit", positive=True),
        "stc_power_within_nominal145w": watts <= base.number(nominal_controller_pv_w, "nominal PV limit", positive=True),
    }
    return {"series": series, "parallel": parallel, "panel_count": series * parallel,
            "array_stc_w": watts, "stc_voc_v": voc, "cold_voc_v": cold, "hot_voc_v": hot,
            "design_isc_a": isc, "required_start_v": start, "ideal_charge_a_at_min_battery": charge_a,
            "screens": checks, "all_catalog_array_screens_pass": all(checks.values()),
            "tolerance_cable_and_loaded_start_qualified": False, "pv_protection_selected": False}


def ancillary_sensitivity(load_wh: float, harvest_load_wh: float, nominal_overlay_w: float,
                          unknown_extra_w: list[float], usable_battery_wh: float) -> dict:
    load = base.number(load_wh, "unchanged load Wh/day", positive=True)
    harvest = base.number(harvest_load_wh, "harvest load-side Wh/day", minimum=0)
    overlay = base.number(nominal_overlay_w, "nominal ancillary overlay W", minimum=0)
    reserve = base.number(usable_battery_wh, "usable load-side battery Wh", positive=True)
    if not isinstance(unknown_extra_w, list) or not unknown_extra_w:
        raise ValueError("unknown-loss sensitivity must be a nonempty list")
    cases = []
    for extra in unknown_extra_w:
        extra = base.number(extra, "unknown extra power sensitivity W", minimum=0)
        demand = load + 24 * (overlay + extra)
        cases.append({"assumed_unknown_extra_w": extra, "candidate_load_wh_per_day_under_assumption": demand,
                      "net_load_side_wh_per_day_under_assumption": harvest - demand,
                      "energy_screen_passes_under_assumption": harvest >= demand,
                      "zero_solar_days_under_assumption": reserve / demand,
                      "measured_or_guaranteed": False, "autonomy_qualified": False})
    return {"retained_baseline_load_wh_per_day": load, "nominal_added_w": overlay,
            "nominal_added_wh_per_day": 24 * overlay,
            "remaining_unknown_power_allowance_before_energy_deficit_w": (harvest - load) / 24 - overlay,
            "actual_total_candidate_load_wh_per_day": None,
            "actual_total_ancillary_w": None, "actual_autonomy_days": None,
            "overall_energy_disposition": "UNKNOWN_SELECTED_ANCILLARY_CONSUMPTION_AND_SITE_YIELD",
            "cases": cases}


def control_logic(*, bms_powered: bool, remote_enabled: bool, cells_allow_load: bool,
                  cells_allow_charge: bool, load_wire_connected: bool,
                  charge_wire_connected: bool, bp_mode_c_verified: bool,
                  mppt_rx_remote_setting_verified: bool) -> dict:
    values = (bms_powered, remote_enabled, cells_allow_load, cells_allow_charge,
              load_wire_connected, charge_wire_connected, bp_mode_c_verified, mppt_rx_remote_setting_verified)
    if any(type(value) is not bool for value in values):
        raise ValueError("control-logic fixture inputs must be booleans")
    return {"load_permission_model": all((bms_powered, remote_enabled, cells_allow_load, load_wire_connected, bp_mode_c_verified)),
            "charge_permission_model": all((bms_powered, remote_enabled, cells_allow_charge, charge_wire_connected, mppt_rx_remote_setting_verified)),
            "physical_operation": False, "qualification": False,
            "limits": "Boolean fixture only; shorts, semiconductor faults, delays and auto-reconnect need physical review/tests. Not an acoustic safety latch."}


def capture_hashes(source_register: dict) -> list[dict]:
    records = []
    for source in source_register["sources"]:
        for capture in source["captures"]:
            if not capture["file"].startswith("sources/") or ".." in Path(capture["file"]).parts:
                raise ValueError("Invalid supplier source reference")
            if len(capture["sha256"]) != 64:
                raise ValueError("Missing pinned supplier source hash")
            records.append({"source_id": source["id"], "file": capture["file"], "url": capture["url"],
                            "retrieved_date": source_register["retrieved_date"], "sha256": capture["sha256"]})
    return records


def calculate(context: dict) -> dict:
    c, original, old = context["candidate"], context["baseline_inputs"], context["baseline_evidence"]
    sources = {s["id"]: s["verified"] for s in context["sources"]["sources"]}
    inherited = {s["id"]: s["verified_facts"] for s in context["inherited_sources"]["sources"]}
    bom = context["bom"]
    parts = {part["id"]: part for part in bom["parts"]}
    if len(parts) != len(bom["parts"]):
        raise ValueError("duplicate candidate BOM part ID")
    for key, expected in (("ambient_c", original["thermal"]["ambient_c"]),
                          ("hub_peak_enclosed_heat_w", old["thermal"]["peak_enclosed_heat_w"]),
                          ("peak_sun_hours", original["solar"]["peak_sun_hours"]),
                          ("reef_baseline_daily_wh", old["reef"]["daily_wh"])):
        actual = base.number(c["fixed_comparison"][key], key)
        if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9):
            raise ValueError(f"cannot change frozen comparison input {key}")
    if c["fixed_comparison"]["load_reduction_allowed"] is not False:
        raise ValueError("load reduction cannot close this comparison")
    if c["fixed_comparison"]["zero_sun_shade_substitution_allowed"] is not False:
        raise ValueError("shade cannot silently zero absorbed sun")
    boundary = c["output_boundary"]
    if boundary["amplifier_installed"] is not False or boundary["projector_connected"] is not False or boundary["output_actuation_gpio"] != []:
        raise ValueError("candidate must remain physically passive")
    if any(bom["unpopulated_optional_output"][key] != 0 for key in ("amplifier", "projector", "wiper_drive", "output_harness")):
        raise ValueError("BOM must omit active output hardware")
    array = c["array"]
    if (array["series"], array["parallel"]) != (2, 1) or type(array["series"]) is not int or type(array["parallel"]) is not int:
        raise ValueError("this physical candidate is exactly2S1P; other counts require another candidate")
    panel = parts[array["bom_part_id"]]
    if panel["quantity"] != 2 or panel["mpn"] != "SPM040401200" or panel["cad_bom_id"] != array["cad_bom_id"]:
        raise ValueError("two-panel candidate BOM/CAD identity mismatch")
    dimensions = next(p for p in context["envelopes"]["parts"] if p["id"] == panel["id"])
    if dimensions["quantity"] != 2 or dimensions["cad_envelope_xyz_mm"] != [668, 425, 25]:
        raise ValueError("panel source envelope/count mismatch")
    if array["panel_xyz_mm"] != [668, 425, 25] or array["panel_centres_y_mm"] != [-237.5, 237.5] or array["panel_gap_mm"] != 50:
        raise ValueError("two-panel geometry contract changed")
    footprint = [668, 2 * 425 + array["panel_gap_mm"]]
    if array["combined_panel_footprint_mm"] != footprint:
        raise ValueError("panel footprint must match two physical panels and gap")
    result_array = array_screen(2, 1, original["solar"], original["rails"], inherited["SRC-MPPT"]["nominal_pv_w_at_12v"])
    energy = base.solar_energy(result_array["array_stc_w"], original["solar"]["peak_sun_hours"],
                              original["solar"]["field_derate"], original["solar"]["charge_efficiency"],
                              old["reef"]["daily_wh"], original["battery"]["discharge_efficiency"])
    a = c["ancillary_accounting"]
    voltage = base.number(a["quiescent_battery_reference_v"], "quiescent battery V", positive=True)
    if voltage != original["rails"]["battery_nominal_v"]:
        raise ValueError("ancillary overlay uses unchanged nominal battery voltage")
    quiescent = [
        ("V2-BMS-001", "S-BMS", sources["S-BMS"]["remote_on_current_a_excluding_output_loads"]),
        ("V2-LOADSW-001", "S-BP", sources["S-BP"]["bluetooth_on_operating_a"]),
        ("V2-REG5-001", "S-REG5", sources["S-REG5"]["no_load_current_a_typical_range"][1]),
        ("V2-REG3-001", "S-REG3", sources["S-REG3"]["no_load_current_a_typical_range"][1]),
    ]
    if set(a["selected_quiescent_parts"]) != {item[0] for item in quiescent}:
        raise ValueError("selected ancillary power cannot be omitted")
    qrecords = []
    for part, source, current in quiescent:
        if parts[part]["quantity"] != 1:
            raise ValueError("ancillary quantity requires recalculation")
        current = base.number(current, f"{part} source current", minimum=0)
        qrecords.append({"part_id": part, "source_id": source, "catalog_current_a": current,
                         "reference_v": voltage, "added_nominal_w": voltage * current,
                         "guaranteed_maximum": False})
    total_q = sum(r["added_nominal_w"] for r in qrecords)
    if a["measured_or_guaranteed_total_ancillary_w"] is not None or not a["unknown_selected_overheads"]:
        raise ValueError("no measured/guaranteed ancillary total exists in this candidate")
    ancillary = ancillary_sensitivity(old["reef"]["daily_wh"], energy["harvest_wh_per_day"], total_q,
                                      a["unknown_extra_w_sensitivity"], old["battery"]["usable_load_side_wh"])
    reg3 = sources["S-REG3"]
    tol = base.number(reg3["output_accuracy_fraction"], "regulator tolerance", minimum=0, maximum=1)
    rf_v = base.number(reg3["output_v"], "regulator output V", positive=True)
    low, high = rf_v * (1 - tol), rf_v * (1 + tol)
    pg_high = rf_v * reg3["pg_low_above_nominal_factor"]
    charge_min = original["rails"]["battery_min_v"] - sources["S-BMS"]["charge_output_high_drop_v"]
    charge_max = original["rails"]["battery_max_v"] - sources["S-BMS"]["charge_output_high_drop_v"]
    return {
        "revision": "HW-CAND-2.0", "configuration": "passive-v2", "status": STATUS,
        "evidence_kind": "source_backed_candidate_calculations_not_measurements",
        "disposition": DISPOSITION, "all_hardware_qualified": False, "energization_allowed": False,
        "baseline_check": context["baseline_check"],
        "preserved_comparison": {"ambient_c": 35, "hub_peak_enclosed_heat_w": old["thermal"]["peak_enclosed_heat_w"],
                                  "absorbed_sun_w": old["thermal"]["absorbed_solar_w"],
                                  "reef_daily_wh": old["reef"]["daily_wh"], "peak_sun_hours": original["solar"]["peak_sun_hours"]},
        "geometry_contract": {"cad_bom_id": array["cad_bom_id"], "power_part_id": panel["id"], "panel_quantity": 2,
                              "panel_xyz_mm": [668, 425, 25], "centres_y_mm": array["panel_centres_y_mm"],
                              "gap_mm": 50, "combined_panel_footprint_mm": footprint,
                              "actual_step_and_mount_checks_owned_by_cad": True, "fit_qualified_here": False},
        "array": result_array, "baseline_only_energy_comparison": energy,
        "selected_nominal_ancillary_overlay": qrecords, "ancillary_accounting": ancillary,
        "accounting_caveat": a["method"], "unknown_selected_overheads": a["unknown_selected_overheads"],
        "reef_voltage_screens": {"radio_output_tolerance_range_v": [low, high],
                                 "radio_nominal_tolerance_within2_to3v6": low >= original["rails"]["radio_min_v"] and high <= original["rails"]["radio_max_v"],
                                 "radio_pg_high_status_v": pg_high, "pg_is_not_ovp": True,
                                 "fault_voltage_guaranteed_below3v6": False,
                                 "regulator_input_static_range_passes": all(original["rails"]["battery_min_v"] >= sources[s]["input_v"][0] and original["rails"]["battery_max_v"] <= sources[s]["input_v"][1] for s in ("S-REG3", "S-REG5")),
                                 "current_limit_ovp_and_burst_qualified": False},
        "charge_control": {"bms_battery_family": "Lithium Battery Smart; BAT512050610; NOT NG-only BMS",
                           "bms_high_signal_range_v": [charge_min, charge_max],
                           "cable_static_enable_screen_passes": charge_min > sources["S-CHGCABLE"]["switch_on_input_v_approx"] and charge_max < sources["S-CHGCABLE"]["input_max_v"],
                           "manufacturer_topology_supported": True, "actual_rx_remote_setting_verified": False,
                           "cable_output_load_current_a": None, "ve_direct_telemetry_available_simultaneously": False,
                           "charge_disconnect_is_remote_control_not_service_isolation": True, "physical_fault_tests_complete": False},
        "load_control": {"batteryprotect_mpn": "BPR065022000", "direction": "battery IN to load OUT only",
                         "mppt_bat_branch_bypasses_load_switch": True,
                         "pv_must_not_pass_through35v_batteryprotect": True,
                         "external_bms_mode_c_required": True, "actual_mode_c_verified": False,
                         "on_state_loss_w": None, "not_an_acoustic_manual_rearm_device": True},
        "hub_power": {"qualified_12v_usbc_source_selected": False,
                       "field_dc_status": "UNKNOWN_SOURCE_CC_OVP_CURRENT_LIMIT_AND_11V2_OPERATION",
                       "bench_alternative": "SC0444 / KSA-15E-051300HE, official external AC supply only",
                       "bench_alternative_resolves_field_dc": False, "bench_operations_authorized": False},
        "protection": {"selected_verified_main_fuse": None, "selected_verified_load_fuse": None,
                       "selected_verified_pv_isolator": None, "battery_prospective_fault_a": None,
                       "fuse_interrupt_and_wire_coordination_qualified": False,
                       "minimum_catalog_pv_voltage_envelope_v_before_unknown_tolerance": result_array["cold_voc_v"],
                       "fuse_source_block": "Littelfuse403 and Eaton transport timeout; indexed ratings not promoted to verified primary values"},
        "thermal": {"owned_by": "parent thermal candidate package", "load_changed_here": False,
                    "heat_path_qualified_here": False, "overall_thermal_status": "UNKNOWN_UNMEASURED_SOURCE_PATH_AND_CONTACTS"},
        "source_captures": capture_hashes(context["sources"]),
        "bounded_source_blocks": context["sources"]["bounded_source_blocks"],
        "remaining_gates": ["HUB field DC-to-USB-C power path", "Main/branch/PV protection and fault current",
                            "BMS/MPPT/BatteryProtect actual settings and fault tests", "Selected ancillary consumption and actual site reserve",
                            "Regulator fault threshold/burst/thermal and signal backfeed", "CAD frame/enclosure/protection/connector integration",
                            "Parent heat-path physical review/measurement", "All electrical qualification, purchases and field authorization"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Only this candidate's power/evidence.json may be written; otherwise stdout")
    args = parser.parse_args()
    try:
        if args.output is not None and (args.output.resolve() != OUTPUT.resolve() or args.output.is_symlink() or OUTPUT.is_symlink()):
            raise ValueError("output must be candidate power/evidence.json, never baseline or sibling files")
        context = load_context()
        result = calculate(context)
        if baseline_check() != context["baseline_check"]:
            raise ValueError("baseline changed during calculation")
        text = base.deterministic_json(result)
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
    except (ValueError, KeyError, TypeError, OSError, OverflowError, StopIteration) as exc:
        parser.exit(2, f"invalid candidate power input/output: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
