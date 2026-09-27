# HW-REF-1.1 mechanical sensitivity calculations

These are incomplete illustrative load cases, not Lim Bay measurements, selected operating limits, structural sizing loads or a pressure-test procedure. `hardware/analysis/scenario.json` records every input and omission; the operating envelope remains unfrozen. No mooring, bracket, enclosure or safety factor is qualified by these results.

Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 hardware/analysis/mechanical.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -p test_mechanical_calculations.py -v
```

`--input PATH` selects another explicitly labeled scenario. `--output NEW_FILE` writes JSON and refuses to overwrite an existing file. `hardware/analysis/calculated-reference.json` is the stored deterministic output for the issued input; tests reproduce it exactly.

| ID | Calculation | Inputs and result | Interpretation |
|---|---|---|---|
| MC-01 | Transverse drag, `F = 0.5 rho Cd A v²` | Assumed water density 1025 kg/m³, 10 m transverse tether at 8 mm diameter, camera 110×250 mm cylinder side area and hydrophone 32×100 mm side area. At 0.5 m/s the summed modeled drag is 16.668 N, of which 12.3 N comes from the tether. At 1 m/s the sum is 66.671 N. | Quadratic speed sensitivity. Frame, fouling, array, wave, cable catenary and dynamic loads are omitted; the sum is not a complete attachment load. |
| MC-02 | Normal panel wind force | The 668×425 mm reference panel drawing gives 0.2839 m² projected area. With assumed air density 1.225 kg/m³ and drag coefficient 1.2, 25 m/s normal wind gives 130.417 N. | Neither 25 m/s nor the coefficient is a site/design wind requirement. Uplift, overturning, frame and storm dynamics are omitted. Current panel availability and procurement selection remain open. |
| MC-03 | Gross cylinder displacement | The provisional 110 mm diameter ×250 mm camera envelope displaces 2.375829 L if treated as a closed cylinder, giving 23.881 N buoyancy at the assumed density/gravity. | This is envelope geometry, not as-built sealed volume. Flooded voids, other parts/cables and compressibility are omitted. |
| MC-04 | Illustrative weight balance | An assumed 3 kg complete wet-head mass weighs 29.420 N. Subtracting only the modeled camera cylinder buoyancy gives 5.539 N downward. | Mixed assumed mass/incomplete displacement, not a measured net-buoyancy or recovery result. Actual mass, CG and displaced volume must replace these inputs. |
| MC-05 | Hydrostatic gauge pressure, `p = rho g h` | An illustrative 10 m depth gives 100518 Pa gauge with 1025 kg/m³ and 9.80665 m/s². | Not a housing rating, selected depth, allowed exposure or test pressure. Only the qualified facility can define the pressure-test procedure. |

Numerical tests cover mm/m/volume conversion, drag at a known point, quadratic speed dependence, zero flow, buoyancy/weight sign, hydrostatic arithmetic, panel axes against the physical interface, invalid inputs and exact output reproduction. All physical load, displacement and pressure gates remain PV-03/PV-04 in the [physical verification plan](verification-plan.md).
