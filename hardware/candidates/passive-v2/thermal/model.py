"""Source-backed thermal-path sensitivities, with installed performance unknown."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
CONFIGURATION = "passive-v2"
REVISION = "HW-CAND-2.0"
BASELINE_HASH = "dfc71d2a6bfffc8a99b12e83af9e5daf9ad33ead8da6337c50cdfb7f1b17e40f"
INCH_M = 0.0254
PSI_PA = 6894.757293168


def number(value, name, *, zero=False):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (value == 0 and not zero):
        raise ValueError(f"{name} must be finite and {'nonnegative' if zero else 'positive'}")
    return float(value)


def fraction(value, name, *, zero=False):
    result = number(value, name, zero=zero)
    if result > 1:
        raise ValueError(f"{name} must not exceed1")
    return result


def read(path):
    return json.loads(path.read_text())


def load():
    inputs = read(HERE / "inputs.json")
    interface = read(ROOT / inputs["interface_path"])
    source_record = read(ROOT / inputs["source_registry_path"])
    for record in (inputs, interface, source_record):
        if record["configuration"] != CONFIGURATION or record["revision"] != REVISION:
            raise ValueError("candidate revision/configuration mismatch")
    baseline_path = ROOT / "hardware/electronics/reference-evidence.json"
    if hashlib.sha256(baseline_path.read_bytes()).hexdigest() != BASELINE_HASH:
        raise ValueError("the failed1.1 baseline changed")
    baseline = read(baseline_path)
    binputs = read(ROOT / "hardware/electronics/reference-inputs.json")
    frozen = inputs["frozen_comparison"]
    if frozen != {"ambient_c": binputs["thermal"]["ambient_c"],
                  "enclosed_peak_heat_w": baseline["thermal"]["peak_enclosed_heat_w"],
                  "potential_absorbed_sun_w": baseline["thermal"]["absorbed_solar_w"],
                  "pi_vendor_ambient_limit_c": binputs["thermal"]["pi_max_ambient_c"]}:
        raise ValueError("thermal comparison must retain frozen1.1 heat/environment/limit")
    sources = {item["id"]: item for item in source_record["sources"]}
    return inputs, interface, sources, binputs


def geometry(interface):
    m = interface["mechanical"]
    x, z = m["thermal_interfaces"]["patch_xz_mm"]
    area = number(x, "contact X") * number(z, "contact Z") / 1e6
    inside = m["hub"]["vendor_inside_reference_mm"]
    l, w, h = [number(inside[key], key) / 1000 for key in ("length", "width", "height")]
    wall_area = 2 * (l*w + l*h + w*h)
    roof_x, roof_y = m["shade"]["roof_xy_mm"]
    roof_area = number(roof_x, "roof X") * number(roof_y, "roof Y") / 1e6
    gap = number(m["shade"]["vertical_gap_above_enclosure_mm"], "shade gap")
    overhang = number(m["shade"]["side_overhang_x_mm"], "shade X overhang")
    height = number(m["hub"]["cad_xyz_mm"][2], "vertical enclosure height")
    return {"contact_patch_area_m2": area,
            "optimistic_internal_rectangular_exchange_area_m2": wall_area,
            "roof_plan_area_m2": roof_area,
            "roof_top_edge_complete_shadow_min_elevation_deg_x_section": math.degrees(math.atan(gap / overhang)),
            "roof_bottom_edge_complete_shadow_min_elevation_deg_x_section": math.degrees(math.atan((height + gap) / overhang)),
            "shadow_note": "Centered X-section with sun in XZ plane only. Below these elevations the roof alone cannot cover the corresponding far edge. Not a full3D/diffuse/radiation or side-baffle shading model; no solar attenuation selected."}


def case(label, values, inputs, interface, sources):
    f = inputs["frozen_comparison"]
    g = geometry(interface)
    q = number(f["enclosed_peak_heat_w"], "enclosed heat")
    sun = number(f["potential_absorbed_sun_w"], "potential sun", zero=True)
    ambient = number(f["ambient_c"], "ambient", zero=True)
    limit = number(f["pi_vendor_ambient_limit_c"], "ambient limit")
    pressure = number(values["contact_pressure_psi"], "pressure")
    k = number(values["material_conductivity_w_mk"], "material conductivity")
    h = number(values["internal_convection_w_m2k"], "internal convection")
    sink_multiplier = number(values["sink_reference_multiplier"], "sink multiplier")
    if sink_multiplier < 1:
        raise ValueError("do not silently improve the vendor sink reference")
    area_fraction = fraction(values["effective_contact_area_fraction"], "effective area")
    solar_fraction = fraction(values["residual_solar_fraction"], "residual solar", zero=True)
    captured = fraction(values["heat_capture_fraction"], "heat capture", zero=True)
    tim = sources["C2-SRC-HENKEL-TSP1600"]["verified"]
    table = tim["thermal_impedance_c_in2_per_w_by_psi"]
    key = str(int(pressure)) if pressure.is_integer() else str(pressure)
    if key not in table:
        raise ValueError("contact pressure must be a tabulated vendor point; no favorable interpolation")
    effective_area = g["contact_patch_area_m2"] * area_fraction
    # ASTM D5470 impedance includes pad and fixture interfaces; do not add t/k again.
    interface_r = table[key] * INCH_M**2 / effective_area
    m = interface["mechanical"]
    wall_r = number(m["hub"]["base_thickness_reference_mm"], "base thickness") / 1000 / (k * effective_area)
    collector_r = number(m["collector"]["xyz_mm"][1], "collector thickness") / 1000 / (k * effective_area)
    sink_reference = sources["C2-SRC-WAKEFIELD-XX4559"]["verified"]["natural_convection_thermal_reference_k_per_w"]
    sink_r = sink_reference * sink_multiplier
    common_r = sink_r + interface_r + wall_r
    air_r = 1 / (h * g["optimistic_internal_rectangular_exchange_area_m2"])
    residual_sun = sun * solar_fraction
    wall_c = ambient + (q + residual_sun) * common_r
    collector_c = wall_c + captured * q * (interface_r + collector_r)
    air_c = wall_c + (1 - captured) * q * air_r
    needed_capture = 1 - (limit - wall_c) / (q * air_r)
    max_solar_fraction = ((limit - ambient - (1 - captured)*q*air_r) / common_r - q) / sun if sun else None
    return {"case": label, "assumed_sensitivity_inputs": values,
            "effective_contact_area_m2": effective_area,
            "pad_interface_r_each_k_per_w": interface_r,
            "base_through_thickness_r_k_per_w": wall_r,
            "collector_through_thickness_r_k_per_w": collector_r,
            "sink_reference_case_r_k_per_w": sink_r,
            "common_wall_to_ambient_r_k_per_w": common_r,
            "air_to_common_wall_r_case_k_per_w": air_r,
            "implied_total_clamp_force_per_interface_n": pressure * PSI_PA * effective_area,
            "clamp_force_note": "Pressure*effective area only; NOT an allowed load or torque on the enclosure/PCB. No clamping pressure is selected.",
            "enclosed_heat_w": q, "residual_solar_heat_w": residual_sun,
            "heat_leaving_common_path_w": q + residual_sun,
            "calculated_common_wall_c": wall_c,
            "calculated_collector_c": collector_c,
            "calculated_lumped_internal_air_c": air_c,
            "conditional_air_inequality_passes": air_c <= limit,
            "required_capture_fraction_for_air_inequality_unclamped": needed_capture,
            "maximum_residual_solar_fraction_for_air_inequality_unclamped": max_solar_fraction,
            "bound_note": "Fractions deliberately not clamped: >1 or <0 expose infeasible combinations. Package contacts, lateral spreading, actual sink boundary and air feedback are omitted/unknown.",
            "installed_thermal_qualified": False,
            "candidate_acceptance": "UNKNOWN_INSTALLED_CONTACT_HEAT_CAPTURE_SINK_AND_SHADE"}


def build():
    inputs, interface, sources, binputs = load()
    ref = inputs["reference_sensitivity_case"]
    cases = [case("unshaded_no_capture_reference_sensitivity", ref, inputs, interface, sources)]
    ideal = dict(ref, contact_pressure_psi=50, material_conductivity_w_mk=200,
                 residual_solar_fraction=0, heat_capture_fraction=1)
    cases.append(case("ideal_all_captured_zero_solar_LIMIT_NOT_ADOPTED", ideal, inputs, interface, sources))
    sweeps = {
        "contact_pressure_psi": inputs["contact_pressure_psi_cases"],
        "material_conductivity_w_mk": inputs["material_conductivity_w_mk_cases"],
        "internal_convection_w_m2k": inputs["internal_convection_w_m2k_cases"],
        "sink_reference_multiplier": inputs["sink_reference_multipliers"],
        "effective_contact_area_fraction": inputs["effective_contact_area_fractions"],
        "residual_solar_fraction": inputs["residual_solar_fraction_cases"],
        "heat_capture_fraction": inputs["heat_capture_fraction_cases"],
    }
    # Common clearly unmeasured comparison pose, not an optimized adopted condition.
    sensitivity = dict(ref, residual_solar_fraction=0.25, heat_capture_fraction=0.9)
    for field, values in sweeps.items():
        for value in values:
            cases.append(case(f"sensitivity_{field}_{value}", dict(sensitivity, **{field: value}), inputs, interface, sources))
    g = geometry(interface)
    captured_sources = {}
    for source in sources.values():
        captured_sources[source["id"]] = {"url": source["url"], "local_file": source["local_file"],
                                          "sha256": source["sha256"]}
    return {"configuration": CONFIGURATION, "revision": REVISION,
            "status": "NON_ADOPTED_NOT_BUILD_AUTHORIZED",
            "evidence_class": "SOURCE_BACKED_COMPONENT_REFERENCE_WITH_UNVALIDATED_NETWORK_SENSITIVITIES",
            "thermal_screen": "UNKNOWN_INSTALLED_CONTACT_HEAT_CAPTURE_SINK_AND_SHADE",
            "baseline_sha256": BASELINE_HASH, "baseline_modified": False,
            "frozen_comparison": inputs["frozen_comparison"],
            "geometry": g,
            "shade_absorbed_power_if_baseline_irradiance_and_absorptivity_apply_w": g["roof_plan_area_m2"] * binputs["thermal"]["sun_irradiance_w_m2"] * binputs["thermal"]["absorptivity"],
            "shade_energy_note": "Roof area calculation does NOT replace or reduce the48W comparison exposure. Roof finish and heat transferred back to enclosure are unknown.",
            "thermal_network": {
                "common_path": "Rcommon = Rsink_reference*case_multiplier + external_TIM_Zarea/Aeffective + base_thickness/(k*Aeffective)",
                "wall": "Twall = Tambient + (Qenclosed +48W*solar_residual_fraction)*Rcommon",
                "collector": "Tcollector = Twall + capture_fraction*Qenclosed*(internal_TIM_Zarea/Aeffective + collector_thickness/(k*Aeffective))",
                "air": "Tair = Twall +(1-capture_fraction)*Qenclosed/(h_internal*optimistic_rectangular_exchange_area)",
                "missing_terms": ["source-package-to-collector contact", "wall/collector lateral spreading and casting detail", "installed sink boundary conditions", "collector-air radiative/convective feedback", "actual solar/shade coupling", "temperature-dependent nonlinear behavior"],
            },
            "actual_installed_values": inputs["actual_installed_values"],
            "source_evidence": captured_sources, "cases": cases,
            "case_count": len(cases), "model_limits": inputs["model_limits"],
            "no_conditional_pass_is_qualification": True,
            "physical_tests_performed": 0, "thermal_qualified": False,
            "purchase_authorized": False, "adopted": False,
            "exact_gates": ["Exact enclosure alloy/flatness and cut sink profile/finish/boundary data", "Reviewed contact pressure, force, PCB support and effective pad area", "Measured fraction of electronics heat captured plus local air/package/junction temperatures", "Source-backed or measured installed sink and lateral-spreading performance", "Shade direct/diffuse/radiative/ventilation behavior at frozen48W exposure budget", "Uncertainty-aware approved thermal test; no physical activity authorized"]}


def serialize(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        text = serialize(build())
        if args.output:
            with args.output.open("x") as stream:
                stream.write(text)
        else:
            print(text, end="")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"candidate thermal: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
