#!/usr/bin/env python3
"""Offline reference calculations. No hardware, networking, or third-party imports.

Equations use SI units except explicitly named mm2, Ah and Wh. Results are
assumption-led sizing evidence, never electrical/acoustic qualification.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


DEFAULT_INPUT = Path(__file__).with_name("reference-inputs.json")


def number(value: Any, name: str, *, minimum: float | None = None,
           maximum: float | None = None, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be <= {maximum}")
    return value


def fraction(value: Any, name: str) -> float:
    return number(value, name, positive=True, maximum=1.0)


def battery_usable_wh(nominal_v: float, capacity_ah: float, depth: float,
                      aged: float, cold: float, efficiency: float) -> float:
    return (number(nominal_v, "battery nominal V", positive=True)
            * number(capacity_ah, "capacity Ah", positive=True)
            * fraction(depth, "depth") * fraction(aged, "aged")
            * fraction(cold, "cold") * fraction(efficiency, "discharge efficiency"))


def loop_resistance(one_way_m: float, area_mm2: float, conductor_c: float,
                    contact_loop_ohm: float, resistivity: float = 0.0175,
                    alpha: float = 0.00393) -> float:
    length = number(one_way_m, "one-way length m", minimum=0)
    area = number(area_mm2, "area mm2", positive=True)
    temp = number(conductor_c, "copper temperature C", minimum=-50, maximum=150)
    contacts = number(contact_loop_ohm, "contact loop ohm", minimum=0)
    rho = number(resistivity, "resistivity", positive=True)
    coefficient = number(alpha, "copper temperature coefficient", minimum=0)
    temperature_factor = 1 + coefficient * (temp - 20)
    if temperature_factor <= 0:
        raise ValueError("nonphysical copper resistance temperature factor")
    return 2 * length * rho * temperature_factor / area + contacts


def constant_power_tether(source_v: float, load_w: float, loop_ohm: float) -> dict:
    """Solve Vload^2 - Vsource*Vload + R*P = 0 on high-voltage branch.

    A positive discriminant is not proof that an actual converter starts stably.
    Collapse threshold and startup controls still need measurement.
    """
    v = number(source_v, "source V", positive=True)
    p = number(load_w, "load W", minimum=0)
    resistance = number(loop_ohm, "loop ohm", minimum=0)
    discriminant = v * v - 4 * resistance * p
    if discriminant <= 0:
        raise ValueError("constant-power tether has no stable high-voltage margin")
    load_v = (v + math.sqrt(discriminant)) / 2
    current = p / load_v
    return {"load_v": load_v, "current_a": current,
            "drop_v": v - load_v, "cable_loss_w": current * current * resistance,
            "source_w": p + current * current * resistance,
            "collapse_power_w": None if resistance == 0 else v * v / (4 * resistance)}


def capacitor_startup(capacitance_f: float, supply_v: float, ramp_s: float,
                      steady_a: float) -> dict:
    c = number(capacitance_f, "capacitance F", minimum=0)
    v = number(supply_v, "inrush supply V", positive=True)
    t = number(ramp_s, "voltage ramp s", positive=True)
    steady = number(steady_a, "steady current A", minimum=0)
    cap_current = c * v / t
    coincident = steady + cap_current
    return {"assumed_linear_ramp_capacitor_current_a": cap_current,
            "coincident_assumed_current_a": coincident,
            "stored_energy_j": c * v * v / 2,
            "rectangular_coincident_i2t_a2s": coincident * coincident * t,
            "qualification": "unmeasured; does not bound hot-plug parasitic/ESR peaks or select a fuse"}


def enclosure_temperature(ambient_c: float, heat_w: float, rth: float,
                          solar_heat_w: float = 0) -> float:
    ambient = number(ambient_c, "ambient C", minimum=-100, maximum=150)
    heat = number(heat_w, "enclosed heat W", minimum=0)
    theta = number(rth, "thermal resistance K/W", positive=True)
    solar = number(solar_heat_w, "solar heat W", minimum=0)
    return ambient + (heat + solar) * theta


def solar_energy(panel_w: float, sun_hours: float, derate: float, efficiency: float,
                 daily_load_wh: float, discharge_efficiency: float = 1.0) -> dict:
    """Compare harvest and demand at the same LOAD-SIDE energy boundary.

    Conservative daily storage-cycle assumption: all harvested energy incurs
    charge and discharge losses, even if some real loads could use PV directly.
    """
    panel = number(panel_w, "panel W", positive=True)
    sun = number(sun_hours, "sun hours", minimum=0, maximum=24)
    loss = fraction(derate, "solar derate")
    eff = fraction(efficiency, "charge efficiency")
    discharge = fraction(discharge_efficiency, "solar discharge path efficiency")
    load = number(daily_load_wh, "daily load Wh", positive=True)
    stored = panel * sun * loss * eff
    harvest = stored * discharge
    return {"harvest_stored_wh_per_day": stored, "harvest_wh_per_day": harvest,
            "net_wh_per_day": harvest - load,
            "break_even_peak_sun_hours": load / (panel * loss * eff * discharge),
            "energy_boundary": "load-side; all harvested energy modeled through storage cycle",
            "sustainable_under_assumptions": harvest >= load}


def pv_voc_at_temperature(voc_stc: float, beta_per_c: float, cell_c: float) -> float:
    voltage = number(voc_stc, "panel Voc V", positive=True)
    beta = number(beta_per_c, "Voc coefficient /C", minimum=-0.02, maximum=0)
    temp = number(cell_c, "cell temperature C", minimum=-50, maximum=100)
    result = voltage * (1 + beta * (temp - 25))
    if result <= 0:
        raise ValueError("nonphysical modeled PV voltage")
    return result


def fuse_coordination_screen(load_a: float, proposed_fuse_a: float,
                             assumed_derated_wire_a: float,
                             assumed_connector_a: float) -> dict:
    """Necessary ampacity inequalities ONLY; no melting/interrupt approval."""
    load = number(load_a, "load A", minimum=0)
    fuse = number(proposed_fuse_a, "proposed fuse A", positive=True)
    wire = number(assumed_derated_wire_a, "assumed derated wire A", positive=True)
    connector = number(assumed_connector_a, "assumed connector A", positive=True)
    return {"inequality_passes": load <= fuse <= min(wire, connector),
            "certified": False,
            "missing": ["DC breaking capacity vs prospective fault current",
                        "time-current curve and ambient derating",
                        "startup I2t and conductor/connector withstand",
                        "installation bundling, terminations and temperature"]}


class ManualInhibitModel:
    """Truth/sequence model of a required INDEPENDENT hardware latch.

    This is NOT firmware, a safety controller, or a real coil drive. It cannot
    validate contacts, fault coverage, stop latency, or actual watchdog circuitry.
    GPIO/software_request is intentionally incapable of setting the latch.
    """
    def __init__(self) -> None:
        self.latched = False
        self.rearm_was_released = False

    def step(self, *, installed: bool, control_power: bool, physical_key: bool,
             stop_a_nc_closed: bool, stop_b_nc_closed: bool,
             independent_watchdog_ok: bool, feedback_ok: bool,
             manual_rearm: bool, software_request: bool = False) -> bool:
        values = (installed, control_power, physical_key, stop_a_nc_closed,
                  stop_b_nc_closed, independent_watchdog_ok, feedback_ok,
                  manual_rearm, software_request)
        if any(type(value) is not bool for value in values):
            raise ValueError("inhibit inputs must be booleans")
        healthy = all((installed, control_power, physical_key, stop_a_nc_closed,
                       stop_b_nc_closed, independent_watchdog_ok, feedback_ok))
        if not healthy:
            self.latched = False
            self.rearm_was_released = False
        elif manual_rearm:
            if self.rearm_was_released:
                self.latched = True
            self.rearm_was_released = False
        else:
            self.rearm_was_released = True
        return self.latched


def _profile(states: Any, power_function: Any) -> dict:
    if not isinstance(states, list) or not states:
        raise ValueError("states must be a nonempty list")
    hours = 0.0
    total_wh = 0.0
    names = set()
    result = []
    for state in states:
        name = state["name"]
        if not isinstance(name, str) or not name or name in names:
            raise ValueError("state names must be nonempty and unique")
        names.add(name)
        duration = number(state["hours"], f"{name} hours", minimum=0, maximum=24)
        powers = power_function(state)
        energy = powers["bus_w"] * duration
        hours += duration
        total_wh += energy
        result.append({"name": name, "hours": duration, **powers, "wh": energy})
    if not math.isclose(hours, 24.0, abs_tol=1e-9, rel_tol=0):
        raise ValueError("state duration must total exactly 24 hours")
    if not math.isfinite(total_wh) or total_wh <= 0:
        raise ValueError("daily energy must be positive and finite for reserve sizing")
    return {"states": result, "daily_wh": total_wh, "average_w": total_wh / 24}


def build_evidence(config: dict) -> dict:
    if config["reference"] != "HW-REF-1.1" or config["configuration"] != "reference-v1":
        raise ValueError("unsupported reference/configuration")
    population = config["default_population"]
    for key in ("amplifier_installed", "projector_connected", "wiper_installed"):
        if population[key] is not False:
            raise ValueError("active hardware is outside the passive reference model")
    if population["output_actuation_gpio"] != []:
        raise ValueError("no output-actuation GPIO belongs in this reference")
    r, cv = config["rails"], config["converter"]
    bus = number(r["bus_nominal_v"], "nominal bus V", positive=True)
    vmin = number(r["battery_min_v"], "battery minimum V", positive=True)
    vmax = number(r["battery_max_v"], "battery maximum V", positive=True)
    if not vmin <= bus <= vmax:
        raise ValueError("bus nominal must be within battery rail range")
    vb = number(r["battery_nominal_v"], "battery nominal V", positive=True)
    if not vmin <= vb <= vmax:
        raise ValueError("battery nominal must be within rail range")
    v5 = number(r["pi_source_v"], "Pi source V", positive=True)
    if not 4.5 <= v5 <= 5.5:
        raise ValueError("source outside candidate converter adjustment range")
    min_supply = number(r["pi_min_supply_a"], "Pi minimum supply A", positive=True)
    pi_peak_allocation = number(r["pi_only_peak_a"], "Pi-only allocation A", positive=True)
    usb_budget = number(r["usb_budget_a"], "USB allocation A", positive=True)
    efficiency = fraction(cv["efficiency"], "DC/DC efficiency")
    cmin = number(cv["min_input_v"], "converter min V", positive=True)
    cmax = number(cv["max_input_v"], "converter max V", positive=True)
    if cmin >= cmax:
        raise ValueError("invalid converter input range")
    rating_w = number(cv["rated_output_w"], "converter rated W", positive=True)
    rating_a = number(cv["rated_output_a"], "converter rated A", positive=True)
    factor = fraction(cv["assumed_available_power_factor"], "available converter power factor")
    available_w = min(rating_w, rating_a * v5) * factor
    tc = config["tether"]
    resistance = loop_resistance(tc["one_way_m"], tc["area_mm2"], tc["conductor_c"],
                                 tc["contact_loop_ohm"], tc["resistivity_20c_ohm_mm2_per_m"],
                                 tc["temperature_coefficient_per_c"])

    def hub_power(state: dict) -> dict:
        pi = number(state["pi_a"], "Pi A", minimum=0)
        usb = number(state["usb_a"], "USB A", minimum=0)
        if usb > usb_budget or pi > pi_peak_allocation:
            raise ValueError("hub state exceeds frozen allocation; revise budget explicitly")
        external = number(state["camera_load_w"], "camera terminal W", minimum=0)
        camera_feed = constant_power_tether(vmin, external, resistance)
        output = v5 * (pi + usb)
        loss = output / efficiency - output
        return {"output_5v_w": output, "converter_loss_w": loss,
                "camera_load_w": external, "camera_cable_loss_w": camera_feed["cable_loss_w"],
                "camera_bus_w": camera_feed["source_w"],
                "bus_w": output + loss + camera_feed["source_w"]}

    hub = _profile(config["hub_states"], hub_power)
    hub_peak = hub_power(config["hub_peak"])
    if hub_peak["bus_w"] < max(s["bus_w"] for s in hub["states"]):
        raise ValueError("hub peak cannot be below a scheduled state")
    full_usb_supply_a = pi_peak_allocation + usb_budget
    hub.update({"peak": hub_peak, "peak_bus_a_at_min_v": hub_peak["bus_w"] / vmin,
                "full_usb_allocation_source_a": full_usb_supply_a,
                "required_source_a": max(full_usb_supply_a, min_supply),
                "required_source_w": v5 * max(full_usb_supply_a, min_supply),
                "assumed_available_converter_w": available_w,
                "converter_capacity_screen_passes": available_w >= v5 * max(full_usb_supply_a, min_supply),
                "usb_c_path_qualified": False})

    reef_cfg = config["reef"]
    e5 = fraction(reef_cfg["efficiency_5v"], "REEF5V efficiency")
    e3 = fraction(reef_cfg["efficiency_3v3"], "REEF3V3 efficiency")
    esp_v = number(r["esp_supply_v"], "ESP supply V", positive=True)
    rf_v = number(r["radio_supply_v"], "radio supply V", positive=True)
    rf_min = number(r["radio_min_v"], "radio min V", positive=True)
    rf_max = number(r["radio_max_v"], "radio max V", positive=True)
    if rf_min >= rf_max:
        raise ValueError("invalid radio operating range")
    if r["devkit_3v3_spare_a"] is not None:
        number(r["devkit_3v3_spare_a"], "DevKit3V3 spare A", minimum=0)
    # Datasheet current is measured at12V; holding its W constant over rail range
    # is a modeling approximation, not an assertion about controller current.
    overhead = (12.0 * number(reef_cfg["mppt_self_consumption_a_at_12v"], "MPPT self A", minimum=0)
                + number(reef_cfg["bms_assumed_w"], "BMS W", minimum=0))

    def reef_power(state: dict) -> dict:
        esp_a = number(state["esp_a"], "ESP A", minimum=0)
        radio_a = number(state["radio_a"], "radio A", minimum=0)
        probe = number(state["probe_bus_w"], "probe W", minimum=0)
        esp = esp_a * esp_v / e5
        radio = radio_a * rf_v / e3
        return {"esp_bus_w": esp, "radio_bus_w": radio,
                "probe_bus_w": probe, "controller_bms_bus_w": overhead,
                "bus_w": esp + radio + probe + overhead}

    reef = _profile(reef_cfg["states"], reef_power)
    reef_peak = reef_power(reef_cfg["peak"])
    if reef_peak["bus_w"] < max(s["bus_w"] for s in reef["states"]):
        raise ValueError("REEF peak cannot be below a scheduled state")
    radio_design_a = number(reef_cfg["peak"]["radio_a"], "radio design peak A", minimum=0)
    vendor_radio_a = number(reef_cfg["vendor_radio_tx_operating_point_a"], "vendor radio TX A", positive=True)
    if any(s["radio_a"] > radio_design_a for s in reef_cfg["states"]):
        raise ValueError("REEF state radio A exceeds radio peak allocation")
    reef.update({"peak": reef_peak, "peak_bus_a_at_min_v": reef_peak["bus_w"] / vmin,
                 "radio_design_peak_a": radio_design_a,
                 "radio_vendor_operating_point_a": vendor_radio_a,
                 "radio_current_headroom_over_operating_point_a": radio_design_a - vendor_radio_a,
                 "devkit_3v3_spare_a": r["devkit_3v3_spare_a"],
                 "radio_supply_capacity_qualified": False,
                 "dedicated_3v3_supply_part_selected": False})

    tether_min = constant_power_tether(vmin, tc["camera_power_w"], resistance)
    tether_max = constant_power_tether(vmax, tc["camera_power_w"], resistance)
    camera_min = number(tc["assumed_camera_min_v"], "camera min V", positive=True)
    camera_max = number(tc["assumed_camera_max_v"], "camera max V", positive=True)
    if camera_min >= camera_max:
        raise ValueError("invalid candidate camera input range")
    tether = {"loop_ohm": resistance, "at_min_battery": tether_min,
              "at_max_battery": tether_max,
              "input_range_screen_passes": tether_min["load_v"] >= camera_min and vmax <= camera_max,
              "camera_range_vendor_verified": False,
              "maximum_unloaded_camera_v": vmax,
              "usb_tether_length_selected": False,
              "unmodeled": "transients, wet insulation/leakage, signal transport, startup/control stability"}

    th = config["thermal"]
    heat = hub_peak["output_5v_w"] + hub_peak["converter_loss_w"]
    solar_heat = (number(th["sun_irradiance_w_m2"], "solar irradiance W/m2", minimum=0)
                  * number(th["exposed_area_m2"], "exposed area m2", minimum=0)
                  * number(th["absorptivity"], "absorptivity", minimum=0, maximum=1))
    shade = enclosure_temperature(th["ambient_c"], heat, th["enclosure_rth_k_per_w"])
    sun = enclosure_temperature(th["ambient_c"], heat, th["enclosure_rth_k_per_w"], solar_heat)
    limit = number(th["pi_max_ambient_c"], "Pi max ambient C", minimum=-100, maximum=150)
    thermal = {"peak_enclosed_heat_w": heat, "absorbed_solar_w": solar_heat,
               "estimated_shade_internal_air_c": shade, "estimated_sun_internal_air_c": sun,
               "pi_ambient_limit_c": limit,
               "shade_screen_passes": shade <= limit, "sun_screen_passes": sun <= limit,
               "max_rth_for_shade_limit_k_per_w": max(0, (limit - th["ambient_c"]) / heat) if heat else None,
               "qualification": "lumped steady-state screen only; no measured internal air/junction or marine thermal evidence"}

    bc = config["battery"]
    usable = battery_usable_wh(vb, bc["capacity_ah"], bc["usable_depth_fraction"],
                              bc["aged_capacity_fraction"], bc["cold_capacity_fraction"], bc["discharge_efficiency"])
    reserve_days = number(bc["reserve_days"], "reserve days", positive=True)
    battery = {"usable_load_side_wh": usable,
               "reef_zero_solar_days": usable / reef["daily_wh"],
               "reef_required_reserve_wh": reef["daily_wh"] * reserve_days,
               "reef_reserve_screen_passes": usable >= reef["daily_wh"] * reserve_days,
               "illustrative_hub_on_same_battery_hours": usable / hub["average_w"],
               "hub_battery_not_selected": True, "bms_power_path_qualified": False}

    sc = config["solar"]
    solar = solar_energy(sc["panel_stc_w"], sc["peak_sun_hours"], sc["field_derate"],
                         sc["charge_efficiency"], reef["daily_wh"], bc["discharge_efficiency"])
    cold_v = pv_voc_at_temperature(sc["panel_voc_stc_v"], sc["voc_temperature_coefficient_per_c"], sc["cold_cell_c"])
    hot_v = pv_voc_at_temperature(sc["panel_voc_stc_v"], sc["voc_temperature_coefficient_per_c"], sc["hot_cell_c"])
    if sc["cold_cell_c"] >= sc["hot_cell_c"]:
        raise ValueError("cold cell temperature must be below hot cell temperature")
    isc = number(sc["panel_isc_stc_a"], "panel Isc A", positive=True) * number(sc["isc_sizing_multiplier"], "Isc sizing multiplier", minimum=1)
    start = vmax + number(sc["mppt_start_margin_v"], "MPPT startup margin V", positive=True)
    max_voc = number(sc["mppt_max_voc_v"], "MPPT max Voc V", positive=True)
    max_isc = number(sc["mppt_max_isc_a"], "MPPT max Isc A", positive=True)
    max_charge = number(sc["mppt_max_charge_a"], "MPPT max charge A", positive=True)
    charge_screen = sc["panel_stc_w"] / vmin
    deficit = -solar["net_wh_per_day"]
    solar.update({"cold_voc_v": cold_v, "hot_voc_v": hot_v,
                  "assumed_design_isc_a": isc, "required_start_v_at_max_battery": start,
                  "cold_voc_screen_passes": cold_v < max_voc,
                  "isc_screen_passes": isc < max_isc,
                  "hot_voc_start_screen_passes": hot_v > start,
                  "ideal_stc_charge_a_at_min_battery": charge_screen,
                  "charge_current_screen_passes": charge_screen <= max_charge,
                  "days_until_usable_reserve_exhaustion_at_deficit": usable / deficit if deficit > 0 else None,
                  "qualification": "site yield not measured; hot Voc startup is necessary not sufficient; BMS/charger interaction open"})

    ic = config["inrush"]
    inrush = capacitor_startup(ic["input_capacitance_f"], vmax, ic["voltage_ramp_s"], hub["peak_bus_a_at_min_v"])
    return {
        "reference": config["reference"], "configuration": config["configuration"],
        "evidence_kind": "calculated_reference_not_measured", "energization_allowed": False,
        "default_population": population,
        "battery_rail_screen": {"minimum_v": vmin, "maximum_v": vmax,
                                "converter_input_minimum_v": cmin, "converter_input_maximum_v": cmax,
                                "converter_static_range_passes": vmin >= cmin and vmax <= cmax,
                                "radio_static_regulated_range_passes": rf_min <= rf_v <= rf_max,
                                "direct_bus_to_esp_or_radio_forbidden": True,
                                "transients_drop_and_regulators_qualified": False},
        "hub": hub, "reef": reef, "inrush": inrush, "tether": tether,
        "thermal": thermal, "battery": battery, "solar": solar,
        "open_gates": ["USB-C source/OVP/current limit/cable/Pi revision and full USB limit verification",
                       "12V source and transient, fuse/connector/wire/fault-current coordination",
                       "Independent REEF5V/3V3 regulators and radio burst/backpower measurement",
                       "External Smart battery BMS, charger/load disconnect and temperature protection",
                       "Actual load states including missing gateway/backhaul/heater/lighting if needed",
                       "Thermal path, enclosure, shading and measured ambient/junction rise",
                       "Solar season/shading and hot-panel startup/charge compatibility",
                       "Wet DAQ/camera/hydrophone/harness/pressure/grounding integration",
                       "Optional physical output absent; safety hardware and all electrical/acoustic qualification open"],
        "assumptions": config["provenance"]
    }


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_inputs(path: Path) -> dict:
    def reject_constant(value: str) -> None:
        raise ValueError(f"nonfinite JSON constant: {value}")
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates,
                       parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError("configuration must be a JSON object")
    return value


def deterministic_json(value: Any) -> str:
    def rounded(obj: Any) -> Any:
        if isinstance(obj, float):
            if not math.isfinite(obj):
                raise ValueError("nonfinite evidence result")
            return round(obj, 9)
        if isinstance(obj, dict):
            return {key: rounded(item) for key, item in obj.items()}
        if isinstance(obj, list):
            return [rounded(item) for item in obj]
        return obj
    return json.dumps(rounded(value), indent=2, sort_keys=True, allow_nan=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, help="Write deterministic JSON instead of stdout")
    args = parser.parse_args()
    try:
        output = deterministic_json(build_evidence(load_inputs(args.inputs)))
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except (ValueError, KeyError, TypeError, OSError, OverflowError, ZeroDivisionError) as exc:
        parser.exit(2, f"invalid electrical calculation input/output: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
