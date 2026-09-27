# Electrical reference: HW-REF-1.1

Configuration `reference-v1`, electrical issue `electrical-1`, source retrieval date **2026-09-08**. HW-REF-1.1 supersedes the early HW-REF-1.0 reference with sourced component envelopes and corrected source facts. This package is a reference for review, **not released for procurement, assembly or energization**. No measured power, vendor quotes, purchased units, electrical qualification or acoustic qualification are claimed.

The default system is passive. The amplifier, projector, output harness and wiper drive are physically absent/disconnected. Optional ports stay absent or unwired and capped. Software disabling is not the physical boundary. No output-actuation GPIO is allocated. No failed Lim pinger profile, acoustic band, sample rate, channel count or validated emitter is selected.

## Reproduce and inspect

From the repository root, using Python standard library only:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 hardware/electronics/calculate.py --output hardware/electronics/reference-evidence.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -p 'test_electrical*.py' -v
```

The hardware lead owns the final integrated run after CAD generation:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v
```

The CLI also writes deterministic JSON to stdout when `--output` is omitted. `--inputs path/to/scenario.json` accepts a copied/edited input record. It rejects nonfinite numbers, invalid fractions, invalid duty totals, duplicate JSON keys, impossible constant-power tether solutions and active population. Exit 2 means invalid input/output. Exit 0 means the calculation ran, **not** that the design passed: the reference JSON deliberately contains failed thermal/solar screens and `energization_allowed: false`.

| ID | Editable artifact | Purpose |
|---|---|---|
| E1 | `hardware/bom/sources.json` | Primary URLs, retrieval date, exact vendor facts, extraction corrections and assumptions |
| E2 | `hardware/bom/reference-v1.json` | 31 planning lines: manufacturer parts, quantities, alternatives, missing selections and missing quotes |
| E3 | `hardware/electronics/reference-inputs.json` | Unit-labeled state, peak, tether, inrush, thermal, battery and solar assumptions |
| E4 | `hardware/electronics/calculate.py` | Equations, input validation, deterministic CLI and independent-inhibit truth/sequence model |
| E5 | `hardware/electronics/reference-evidence.json` | Regenerated numerical evidence, failed screens and open gates |
| E6 | `hardware/wiring/connectors.csv` | Pin identity, mating orientation, locking/retention, ratings and unresolved connector pairs |
| E7 | `hardware/wiring/harnesses.csv` | Editable point-to-point routes, polarity, TX/RX crossing, wire/length uncertainty and absent output harness |
| E8 | `hardware/wiring/design.json` and `schematic.txt` | Power domains, fuses, grounding/isolation and independent physical stop architecture |
| E9 | `tests/hardware/test_electrical.py` | Numerical, sensitivity, invalid-input, deterministic-evidence and inhibit-sequence tests |

No custom PCB is justified. COTS boards and protected interconnect assemblies are preferred. There is no invented KiCad/ERC/DRC result.

## Component decisions and source limits

**D1 — Compute and USB power.** The above-water HUB reference is Raspberry Pi 4 Model B 4GB, hardware-lead ordering code `SC0194`. The [manufacturer brief](https://pip.raspberrypi.com/documents/RP-008344-DS-raspberry-pi-4-product-brief.pdf), published April 2026, verifies the 4GB variant and 5V/3A or 5.1V/3A minimum supply recommendation. It does not prove that ordering code. Verify the SKU and board revision before any purchase. The drawing itself says approximate reference dimensions, not production data. Pi operating ambient is 0–50°C.

The model allocates 1.8A to Pi-only peak and a separate 1.2A aggregate USB allowance, totaling 3A at 5.1V, or 15.3W. These are sizing allocations, not measurements. The retrieved brief does not verify the aggregate USB limit; that remains a gate. DAQ/storage share that allocation, not an additional 1.2A per port.

The [official Raspberry Pi 15W USB-C PSU](https://www.raspberrypi.com/products/type-c-power-supply/) is a dry-bench alternative: 5.1V/3A, captive 1.5m 18AWG cable. Its exact EU ordering variant is unresolved. It is mutually exclusive with the DC converter path. Mains remains outside this DC package; no bench operation is authorized here.

**D2 — Protected 12V bus and converter.** The source is an above-water protected nominal 12V DC bus. Actual source, transient envelope and fault current remain unselected. The battery-based static sizing example is 11.2–14.4V. [MEAN WELL SD-50A-5](https://www.meanwell.com/Upload/PDF/SD-50/SD-50-SPEC.PDF), revision 2024-11-22, accepts 9.2–18V, adjusts 4.5–5.5V, and rates 50W/10A at nominal 5V. Typical efficiency is **70%**. Dimensions are **159 × 97 × 38mm**. At 5.1V, do not turn the 50W rating into an assumed 51W rating.

An early automated source summary mixed table values. The directly inspected PDF supersedes its 9.5V minimum, 78% efficiency, smaller envelope, DC withstand and 20A inrush claims. The PDF specifies 1.5kVAC input/output withstand, 2kVAC input/FG and 0.5kVAC output/FG. It does **not** specify inrush. These component withstand ratings do not establish system isolation.

The converter is **not a USB-C power-source assembly**. An actual COTS source-role/CC implementation, current limit, Pi-suitable OVP and retained cable must be selected and tested in both plug orientations. A PD sink trigger does not implement a USB-C source. Do not wire a bare buck into USB-C and assume proper current advertisement. The converter's 5.75–6.75V OVP trip range at 10% load does not prove protection of a nominal 5V Pi. The 12V-to-Pi route remains incomplete and not energizable.

**D3 — REEF processor and radio.** [Espressif's DevKitC guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html) verifies `ESP32-DevKitC-32E` with WROOM-32E. WROVER is not an interchangeable board because it uses GPIO16/17 internally. The [RAK3272S datasheet](https://docs.rakwireless.com/product-categories/wisduo/rak3272s-breakout-board/datasheet/) verifies these local above-water interfaces:

| Net | ESP32-DevKitC-32E | RAK3272S / destination |
|---|---|---|
| UART transmit from ESP | GPIO17, J3 pin 11 | UART2_RX / PA3, J4 pin 8 |
| UART receive at ESP | GPIO16, J3 pin 12 | UART2_TX / PA2, J4 pin 7 |
| Radio supply | Dedicated regulated 3.3V source, not assumed DevKit spare current | J5 pin 9, 3V3 |
| Radio return | Same reviewed local logic-reference island | J5 pin 7, GND |
| Local I2C SDA | GPIO21, J3 pin 6 | Conditioned local 3.3V interface, exact device open |
| Local I2C SCL | GPIO22, J3 pin 3 | Conditioned local 3.3V interface, exact device open |
| ESP power option | J2 pin 19, 5V; J2 pin 14, GND | One protected source only |

RAK **J4 pin 9 is not the common power pin**: VerB uses PA8, while VerC uses 3V3. Use J5 pin 9 and verify the board revision. VCC is 2.0–3.6V, nominal 3.3V. The 87mA transmit figure at 20dBm/868MHz is a vendor operating point, not a measured maximum or permission to radiate at that power. The model's 120mA burst allocation is an assumption. DevKit 3V3 spare capacity is unknown; the independent radio supply part, decoupling and burst response remain open.

RAK's current page mixes module-family/order-suffix wording. `RAK3272S` / RAK3172-family with EU868 is the reference, but exact regional core suffix, antenna connector and firmware/order variant are not invented. UART2 serves AT commands and firmware updates; UART1 is not silently substituted.

Only one ESP supply method may be used: Micro-USB, 5V header or 3V3 header. Remove service USB VBUS when header-powered, and prevent signal backpower into unpowered boards. **Never put 12V, 5V logic, an unconditioned battery divider or a wet probe cable directly on ESP GPIO.** Local I2C pullups use the reviewed 3.3V island only. Retained/keyed production harnesses have not been selected; development headers are not locking marine connectors.

**D4 — Battery, solar and fit.** The reference battery candidate is Victron `BAT512050610`, 12.8V/50Ah Smart, 640Wh at 25°C. The [manual](https://www.victronenergy.com/media/pg/Lithium_Battery_Smart/en/technical-data.html) gives H199 × W188 × D147mm, 7kg and M8 terminals. The [Rev01 drawing](https://www.victronenergy.com/upload/documents/LiFePO4-Battery-12.8V50AH-Smart.pdf) verifies the ordering code; reconcile its width detail with the manual before fit release. The early 181 × 77 × 167mm provisional envelope was incompatible. The hardware/CAD lead adopted the sourced envelope with extra terminal-service space; this electrical document does not certify the final fit or clamp loads.

The battery permits charge at 14.0–14.4V, recommends 14.2V, and specifies a +5 to +50°C charge-temperature range. Its [integrated BTV requires an external BMS](https://www.victronenergy.com/media/pg/Lithium_Battery_Smart/en/introduction.html). BTV is not a complete load/charge disconnect. Exact BMS, low-temperature protection, compatible MPPT charge disable, load disconnect, terminal fusing and fault-current coordination remain mandatory unresolved parts.

Victron `SCC075010060R` SmartSolar MPPT75/10 is verified by its [drawing](https://www.victronenergy.com/upload/documents/BlueSolar-&-SmartSolar-MPPT-75-10-&-75-15.pdf). The [datasheet](https://www.victronenergy.com/upload/documents/Datasheet-SmartSolar-charge-controller-MPPT-75-10,-75-15,-100-15,-100-20_48V-EN.pdf) gives 10A charge, 75V maximum PV open circuit, 13A maximum PV short circuit, 145W nominal PV at 12V, and 100 × 113 × 40mm H/W/D. Electronics are IP43 and the connection area IP22; it belongs above water in a reviewed enclosure. Full rated output applies only up to 40°C. Do not invent a linear derating percentage.

The [panel table](https://www.victronenergy.com/upload/documents/Datasheet-BlueSolar-Monocrystalline-Panels-EN.pdf) verifies `SPM040401200`, 40W, 425 × 668 × 25mm, Vmp18.3V, Voc22.45V, Isc2.40A and Voc coefficient −0.35%/°C. CAD rotates it to X668 × Y425 × Z25mm; mounting/junction-box clearance is additional. Do not assume supplied MC4 leads on this small model. A mistaken discontinuation-marker reading was resolved by direct visual inspection: the 40W row has no `(2)`, while the adjacent 30W and 55W rows do. That does not establish present production, stock or a quote. Availability and any replacement remain open.

**D5 — Wet acquisition and other parts.** Analog hydrophone plus above-water DAQ and Ethernet/isolated wet camera interface remain candidates. No underwater USB tether length is selected. Exact acoustic channel/band/sample rate, receive bias/impedance, camera voltage/driver, pressure tube, window/endcaps, seals, penetrators and cable assembly are unresolved. The [Blue Robotics locking-tube family](https://bluerobotics.com/store/watertight-enclosures/locking-series/wte-locking-tube-r1-vp/) is only a purchased pressure-boundary candidate; no unselected tube-family depth rating transfers to this system. No printed pressure hull is approved.

[Hammond 1554V2GY](https://www.hammfg.com/files/parts/pdf/1554V2GY.pdf) is a sourced smaller enclosure alternative, not a fit-equivalent to the HUB or REEF reference envelopes. All actual enclosure/gland/terminal clearances remain integration gates. ARRAY, WIPER, PROJECTOR, FARM and JIG BOM lines identify omitted options or missing sizing rather than fabricated manufacturer SKUs.

## Numerical evidence and equations

Every number below is **calculated from assumptions**, not measured. HUB and REEF are separate loads, not a claim that one REEF battery powers the HUB. Gateway/backhaul, heater, lights, extra channels and other unselected loads are excluded and block final sizing.

| ID | Default scenario result | Interpretation |
|---|---|---|
| N1 | HUB 413.854Wh/day; simultaneous peak 30.667W, 2.738A at 11.2V | Includes converter loss and camera tether copper/contact loss at the minimum battery voltage. Pi5V1 output peak is 15.3W. |
| N2 | REEF 27.525Wh/day; peak 4.948W | Includes assumed whole DevKit demand, separate radio converter, probe allocation, MPPT self-consumption and assumed BMS power. No chip-only sleep claim. |
| N3 | Assumed capacitor ramp 6.768A; coincident startup 9.506A; stored energy 0.487296J | 4700µF, 14.4V and 10ms linear voltage ramp are assumptions. Not a measured inrush bound or fuse selection. |
| N4 | 25m one-way, 0.75mm² copper, 40°C, 0.05Ω contacts: loop1.30837Ω; 8W load sees10.1709V at11.2V source | Constant-power solution includes increased current as load voltage falls. 9–16V camera range is only an assumption. |
| N5 | Peak internal heat21.857W; shade internal-air screen67.786°C at35°C ambient and1.5K/W | Fails Pi50°C ambient screen. Absorbed-sun scenario adds48W and also fails. No measured thermal resistance or junction temperature. |
| N6 | Battery usable load-side reserve294.912Wh; REEF zero-solar10.714days; hypothetical HUB-on-same-battery17.102hours | Uses0.8DoD ×0.8age ×0.8cold ×0.9discharge efficiency. Does not establish field autonomy or a selected HUB battery. |
| N7 | 40W ×1peak-sun-hour yields23.4Wh stored and21.06Wh load-side; net−6.465Wh/day | Both charge and discharge loss apply before comparing with load-side demand. Break-even is1.307peak-sun-hours under these assumptions, not a site climate claim. |
| N8 | Cold Voc25.200V fits75V screen; hot Voc18.914V is below19.4V startup requirement at14.4V battery | Hot startup fails the scenario despite adequate cold-voltage and current screens. A positive static result would still not prove startup under load. |

Implemented equations:

- `P_bus = P_regulated / efficiency + direct_branch_power`. Camera branch input includes its calculated tether loss. Daily energy sums `hours × state_power`, and hours must total24.
- `R_loop = 2 × one_way_length × rho20 × (1 + alpha × (T−20)) / area + contact_loop_resistance`. Copper constants are explicit handbook-level modeling assumptions, not selected cable certification.
- Constant-power load: `V_load = (V_source + sqrt(V_source² − 4 R_loop P_load)) / 2`; `I = P_load / V_load`, `P_loss = I²R`. Nonpositive discriminant is rejected rather than returning an imaginary/unstable solution.
- Linear-ramp capacitor approximation: `I_C = C ΔV / Δt`, `E = C V² / 2`. The reported rectangular coincident `I²t` is not actual converter hot-plug waveform evidence.
- Lumped internal-air screen: `T_internal = T_ambient + R_theta × (enclosed_heat + absorbed_solar_heat)`. Solar absorption is `irradiance × area × absorptivity`. This is not a CFD or junction model.
- Usable load-side battery energy: `V_nom × Ah × usable_DoD × age_factor × cold_factor × discharge_efficiency`.
- Stored solar harvest: `STC_W × peak_sun_hours × field_derate × charge_efficiency`; load-side harvest also multiplies `discharge_efficiency`. Conservatively, all harvest is modeled through storage. Reserve exhaustion and net-energy comparisons use the same boundary.
- Temperature-adjusted open-circuit PV voltage: `Voc_STC × (1 + beta_Voc × (T_cell−25))`. The model checks cold Voc, assumed design Isc, charging-current screen and hot Voc against battery+5V startup.

The fuse helper checks only `load ≤ proposed fuse ≤ assumed derated wire/connector ampacity`. It always returns `certified: false`. Actual fuse ratings and wire/connector ampacities remain null in the wiring source because DC interrupt capacity, time-current curves, minimum remote fault current, let-through energy, installation derating and terminations are unverified. A positive inequality cannot certify fault clearing.

## Physical stop, grounding and open release gates

The editable text schematic and JSON specify a **future independent hardware** output route, not firmware. If active research is later approved, separately fused output power must pass through a lockable service isolator and independent normally-open disconnects K1/K2. A reviewed floating supply may require interruption of both conductors. The Pi/ESP/GPIO cannot directly energize either coil or bypass the route.

A selected independent safety controller must require physical key permission, NC physical stop channels, an independent edge/window watchdog, contact feedback and a monitored local manual rearm button. Rearm requires release followed by a fresh press while healthy. Restored power, released stop, watchdog recovery, software requests or a held reset do not rearm. An internal MCU watchdog or software amplifier-enable bit is not this safety controller. Opening power alone does not eliminate stored amplifier/cable energy; a sized discharge path and measured time-to-safe remain open. Passive diagnostics use a separate path where safe.

The Python inhibit class verifies Boolean and sequence requirements only. It does not implement a safety circuit, measure stop latency or establish a performance level/SIL. Exact safety-controller, DC contact, feedback, watchdog, coil suppression, discharge and connector parts are intentionally unselected while amplifier/projector requirements and acoustic authorization remain absent.

| Gate | Required evidence before the affected path can be built or energized |
|---|---|
| G1 | Qualified USB-C source/cable/CC/OVP/current-limit path, Pi revision/USB limit, transients, brownout and full peripheral-load measurement |
| G2 | Actual 12V source, fuse curves/DC interrupt ratings, fault current, wire/connector ratings, locking mating pairs, crimps/lugs/torque and polarity/continuity tests |
| G3 | Independent REEF5V/3V3 regulator selection, radio burst/decoupling measurement, service-USB and UART power-off backfeed prevention |
| G4 | Compatible external Smart-battery BMS, battery temperature/voltage protection, independent load/charge disconnects and actual PV/MPPT cold/hot startup tests |
| G5 | Measured internal air/junction rise, converter orientation/derating, passive heat path, enclosure/gland/condensation/corrosion review and site solar reserve |
| G6 | Selected receive/camera/probe chain, wet tether/transport, rated purchased pressure assembly, calibrated acquisition and actual installation envelope |
| G7 | Site-specific frame/FG/negative/shore-earth bonds, isolation continuity, shielding/EMC, lightning/surge and corrosion review |
| G8 | For any future output: separate approvals plus independently reviewed safety circuit, stored-energy bound, welded-contact/open/short/stuck-watchdog/rearm/backfeed fault tests and acoustic calibration/safety/efficacy evidence |

Never use the frame, shield or seawater as a normal DC return. Do not casually bond converter input/output negative together; USB/Ethernet/radio/analog shields can defeat isolation. FG connects to a reviewed frame/equipotential design, not an invented universal marine earth rule. Hydrophone shield termination depends on the selected sensor/DAQ and measured noise. No live hardware, procurement, permit, stakeholder contact or acoustic emission follows from this package.
