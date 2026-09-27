"""Illustrative load and buoyancy calculations, not a released operating envelope."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent


def number(value: object, label: str, *, zero_allowed: bool = False) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if value < 0 or (value == 0 and not zero_allowed):
        raise ValueError(f"{label} must be {'nonnegative' if zero_allowed else 'positive'}")
    return float(value)


def drag_n(density_kg_m3: float, coefficient: float, area_m2: float, speed_m_s: float) -> float:
    rho = number(density_kg_m3, "density")
    cd = number(coefficient, "drag coefficient")
    area = number(area_m2, "projected area")
    speed = number(speed_m_s, "speed", zero_allowed=True)
    return 0.5 * rho * cd * area * speed**2


def cylinder_volume_m3(diameter_mm: float, length_mm: float) -> float:
    diameter = number(diameter_mm, "diameter") / 1000.0
    length = number(length_mm, "length") / 1000.0
    return math.pi * (diameter / 2.0)**2 * length


def calculate(scenario: dict) -> dict:
    if scenario["scenario_label"] != "ILLUSTRATIVE_NOT_OPERATING_LIMITS":
        raise ValueError("This model is an illustrative scenario only")
    if scenario["operating_envelope_frozen"] is not False:
        raise ValueError("This model cannot release an operating envelope")
    values = scenario["inputs"]
    for name, value in values.items():
        if isinstance(value, list):
            if not value:
                raise ValueError(f"{name} cannot be empty")
            for item in value:
                number(item, name, zero_allowed=True)
        else:
            number(value, name, zero_allowed=name == "illustrative_depth_m")
    rho = values["water_density_kg_m3"]
    gravity = values["gravity_m_s2"]
    camera_area = values["camera_envelope_diameter_mm"] * values["camera_envelope_length_mm"] / 1_000_000.0
    hydrophone_area = values["hydrophone_envelope_diameter_mm"] * values["hydrophone_envelope_length_mm"] / 1_000_000.0
    tether_area = values["tether_diameter_mm"] / 1000.0 * values["tether_wet_length_m"]
    panel_area = values["panel_width_mm"] * values["panel_height_mm"] / 1_000_000.0
    submerged = []
    for speed in values["current_speeds_m_s"]:
        camera = drag_n(rho, values["camera_transverse_drag_coefficient"], camera_area, speed)
        hydrophone = drag_n(rho, values["hydrophone_transverse_drag_coefficient"], hydrophone_area, speed)
        tether = drag_n(rho, values["tether_transverse_drag_coefficient"], tether_area, speed)
        total = camera + hydrophone + tether
        submerged.append({
            "current_m_s": speed,
            "camera_drag_n": camera,
            "hydrophone_drag_n": hydrophone,
            "tether_drag_n": tether,
            "sum_of_modeled_transverse_drag_n": total,
            "illustrative_support_moment_nm": total * values["support_drag_lever_arm_m"],
        })
    winds = [{
        "wind_m_s": speed,
        "panel_normal_force_n": drag_n(values["air_density_kg_m3"], values["panel_normal_drag_coefficient"], panel_area, speed),
    } for speed in values["wind_speeds_m_s"]]
    volume = cylinder_volume_m3(values["camera_envelope_diameter_mm"], values["camera_envelope_length_mm"])
    buoyancy = rho * gravity * volume
    weight = values["illustrative_dry_wet_head_mass_kg"] * gravity
    return {
        "schema": "poseidon.hardware.mechanical-calculation.v1",
        "configuration": scenario["configuration"], "revision": scenario["revision"],
        "evidence_class": "ILLUSTRATIVE_CALCULATION_NOT_MEASURED_OR_QUALIFIED",
        "operating_envelope_frozen": False, "physical_tests_performed": 0,
        "equations": {
            "drag": "F_N = 0.5 * rho_kg_m3 * Cd * projected_area_m2 * speed_m_s^2",
            "hydrostatic_gauge_pressure": "p_Pa = water_density_kg_m3 * gravity_m_s2 * depth_m",
            "cylinder_displacement": "V_m3 = pi * (diameter_mm / 2000)^2 * length_mm / 1000",
            "buoyancy": "B_N = water_density_kg_m3 * gravity_m_s2 * V_m3",
            "weight": "W_N = assumed_mass_kg * gravity_m_s2",
            "illustrative_support_moment": "M_Nm = sum_of_modeled_drag_N * assumed_lever_arm_m",
        },
        "projected_areas_m2": {"camera": camera_area, "hydrophone": hydrophone_area, "tether": tether_area, "panel": panel_area},
        "submerged_drag_sensitivity": submerged,
        "panel_wind_sensitivity": winds,
        "illustrative_pressure": {
            "depth_m": values["illustrative_depth_m"],
            "gauge_pressure_pa": rho * gravity * values["illustrative_depth_m"],
            "meaning": "Hydrostatic calculation only, NOT allowed operating depth or pressure-test instruction.",
        },
        "illustrative_buoyancy": {
            "gross_camera_cylinder_volume_m3": volume,
            "gross_camera_cylinder_volume_l": volume * 1000.0,
            "gross_camera_cylinder_buoyancy_n": buoyancy,
            "assumed_total_wet_head_weight_n": weight,
            "weight_minus_gross_camera_buoyancy_n": weight - buoyancy,
            "meaning": "Mixed assumed total mass and gross camera envelope only; NOT as-built net buoyancy. Other displacement, flooded voids and cables omitted.",
        },
        "inputs": values, "input_evidence": scenario["input_evidence"], "omissions": scenario["omissions"],
        "release_note": "Do not size or approve restraints from these incomplete load cases. Site survey, independent load review and physical tests remain open.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "scenario.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = calculate(json.loads(args.input.read_text()))
        content = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x") as stream:
                stream.write(content)
        else:
            print(content, end="")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.exit(1, f"mechanical reference: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
