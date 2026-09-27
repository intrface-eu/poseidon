# Power refinement: comparison only

**Disposition: `BLOCKED_ON_THERMAL_POWER_PATH_AND_PART_SELECTION`.** This study does not establish a viable passive product. It leaves HW-REF-1.1 / `reference-v1` inputs, failed evidence, BOM, wiring and physical CAD unchanged. The two-panel alternatives are **not adopted configurations**.

Baseline evidence: `hardware/electronics/reference-evidence.json`.
SHA256: `dfc71d2a6bfffc8a99b12e83af9e5daf9ad33ead8da6337c50cdfb7f1b17e40f`.

## Reproduce

Python standard library only; no network or live hardware:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 hardware/electronics/refine_power.py --output hardware/electronics/refinement-evidence.json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -p 'test_electrical_refinement.py' -v
```

Without `--output`, the CLI writes deterministic JSON to stdout. File output is restricted to the new `refinement-evidence.json`; attempts to overwrite the baseline fail. The script checks the frozen baseline evidence hash and records before/after hashes for the baseline calculation, input, evidence, BOM/source and wiring files. The hardware lead owns the full hardware test run.

Source values come only from the existing HW-REF-1.1 records. Panel `SPM040401200` supplies the 40W, Voc22.45V, Isc2.4A and −0.35%/°C Voc coefficient. `SRC-MPPT` supplies the controller's 145W nominal PV limit at12V. No new part or source availability is claimed.

## Array comparison

The three cases use the same1peak-sun-hour/day,0.65field derate,0.9charge efficiency,0.9discharge efficiency,27.5247475Wh/day REEF demand,294.912Wh usable load-side battery reserve,11.2–14.4V battery scenario,−10°C cold cells and70°C hot cells. No better climate, lower load or larger battery makes a case pass.

`S` means panels in series per string; `P` means parallel strings. Calculations use:

- `array_STC_W = 40 × S × P`.
- `array_Voc = 22.45 × S`; temperature correction uses the existing Voc coefficient.
- `design_Isc = 2.4 × P × 1.25`.
- Stored harvest is `array_STC_W ×1 ×0.65 ×0.9`; load-side harvest also multiplies the0.9discharge efficiency before comparison with load-side demand.
- Conservative ideal STC charge screen is `array_STC_W /11.2V`. Compare with10A, array nominal STC watts with145W, cold Voc with75V and design Isc with13A. Hot Voc must exceed `14.4V +5V =19.4V` to pass the necessary startup screen.

| ID / case | STC power | Cold / hot Voc | Design Isc | Load-side harvest / net per day | Array screening result |
|---|---:|---:|---:|---:|---|
| A1: original1S1P | 40W | 25.200 /18.914V | 3A | 21.060 /−6.465Wh | Fails energy and hot startup |
| A2: comparison2S1P | 80W | 50.400 /37.828V | 3A | 42.120 /+14.595Wh | Passes these calculation screens only |
| A3: comparison1S2P | 80W | 25.200 /18.914V | 6A | 42.120 /+14.595Wh | Energy passes; hot startup still fails |

Both80W cases give46.8Wh stored and42.12Wh load-side. Their ideal charge-current screen is7.143A, below10A, and80W is below145W. Only adding series voltage fixes the modeled hot-start shortfall. Parallel panels do not increase Voc.

A2 is not full electrical qualification. Open-circuit voltage is a necessary startup check, not proof of loaded startup, MPPT operation, battery/BMS compatibility or winter yield. Shading/mismatch, component tolerances, cable loss, voltage insulation, connector ratings, reverse current and protection remain unqualified. These panels serve the REEF comparison, not the HUB's separate load budget.

The frozen CAD frame, BOM and harness still describe **one panel**. Adopting either two-panel alternative requires a new reference issue, revised frame/geometry and attachment-load review, routing and connector selection, series-voltage or parallel-fault/protection review, and BMS/MPPT integration. This study changes none of those artifacts.

## Thermal requirement, not an assumed fix

The same HUB peak enclosed heat is21.857142857W. Ambient is35°C, Pi vendor ambient limit50°C, existing assumed enclosure thermal resistance1.5K/W, and absorbed sun48W. The heat includes Pi/USB output and converter loss; camera power and tether heat leave the HUB enclosure.

| ID | Result at unchanged load/exposure | Meaning |
|---|---|---|
| T1 | Required shade effective `Rtheta ≤15/21.857142857 =0.68627451K/W` | Zero-uncertainty upper bound, not a selected or measured heat path |
| T2 | Required sun effective `Rtheta ≤15/(21.857142857+48) =0.214723926K/W` | Includes the same48W absorbed-sun scenario |
| T3 | At current1.5K/W, shade internal-air screen67.786°C; sun139.786°C | Both fail; these are lumped-model outputs, not measured temperatures |
| T4 | At current1.5K/W, shade enclosed-heat cap10W, hence combined Pi+USB output cap `0.7×10 =7W`, or1.372549A at5.1V | Record9.18W and peak15.3W exceed the cap. Upload11.73W also exceeds it. |

No workload evidence justifies lowering record/peak currents to7W. The minimum supply/full-USB allocation and workload assumptions are not revised to make thermal screening pass. Under the existing resistance,48W absorbed sun alone exceeds the15°C temperature headroom even with zero electrical heat.

**B1 — Exact mechanical blocker.** No purchased enclosure wall material/thickness, Pi/converter heat-spreader and contact stack, external dissipator area/mount, or sun-shield spacing/ventilation has been selected and verified as a heat path. The package contains no measured internal-air rise or effective thermal resistance at the frozen load and exposure. A convenient replacement resistance such as0.6K/W would not resolve those missing parts and measurements. Retain1.5K/W as the failed reference assumption until a separately reviewed physical design and evidence support a new issue.

**B2 — Measurement blocker.** A qualified reviewer must approve sensor locations, calibration, uncertainty, stabilization, duration and exposure method. At frozen35°C ambient, simultaneous peak load and declared shade or48W absorbed-sun exposure, the uncertainty-aware acceptance inequality is:

`Tair_measured + U ≤50°C`.

`U` is the temperature-measurement uncertainty allowance defined by that approved method. The calculated resistance limits above assume zero allowance and therefore cannot replace this measurement criterion. Internal Pi/converter hotspots, junction temperature, converter derating and fault behavior also require review; meeting an air-temperature inequality alone is not full qualification. No measurements or live tests are authorized or supplied.

**B3 — Power-path and part blockers.** The Pi USB-C source/CC/current limit/OVP/cable path, protected12V source and fuse coordination, external Smart-battery BMS and charge/load disconnects, REEF regulators, wet acquisition/pressure assemblies and exact connector parts remain open. Passing A2's array equations closes none of them.

All comparison records explicitly retain `all_reference_hardware_qualified: false`, `adopted_configuration: false` and `energization_allowed: false`. The original failed case is preserved; the overall disposition remains **`BLOCKED_ON_THERMAL_POWER_PATH_AND_PART_SELECTION`**.
