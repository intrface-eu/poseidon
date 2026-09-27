# Poseidon hardware reference

Configuration `reference-v1`, revision `HW-REF-1.1`, issued 2026-09-08. This package contains editable parametric CAD, STEP assemblies, dimensioned engineering views, reference BOM/wiring, executable calculations and unperformed physical validation plans. It is not a fabrication, purchase, energization, pressure, acoustic, field or production release.

The reference arrangement keeps Pi compute, DAQ/power candidates, radio and REEF solar/battery electronics above water, with wired wet receive/camera instruments. The default variant has no amplifier, projector or powered wiper populated. Optional array, wiper and projector geometry is research-only; no acquisition band, qualified depth or safe/effective acoustic treatment is selected.

## Recreate the digital package

Run from the repository root. CAD uses a separate project-local locked environment and does not change the app's dependencies. `uv sync` needs access to the locked public packages on first setup; no global CAD installation is required.

```sh
uv sync --project hardware/cad --frozen
OUT="$(mktemp -d /tmp/poseidon-hardware-reference.XXXXXX)"
PYTHONDONTWRITEBYTECODE=1 uv run --project hardware/cad --frozen python hardware/cad/generate.py --output "$OUT/cad" --research-layout
PYTHONDONTWRITEBYTECODE=1 uv run --project hardware/cad --frozen python hardware/cad/check_manifest.py "$OUT/cad" --geometry
PYTHONDONTWRITEBYTECODE=1 python3 hardware/electronics/calculate.py --output "$OUT/electrical.json"
PYTHONDONTWRITEBYTECODE=1 python3 hardware/analysis/mechanical.py --output "$OUT/mechanical.json"
PYTHONDONTWRITEBYTECODE=1 python3 hardware/electronics/refine_power.py > "$OUT/refinement.json"
PYTHONDONTWRITEBYTECODE=1 python3 hardware/validation/check_reference.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v
printf 'Generated reference artifacts: %s\n' "$OUT"
```

The CAD generator rejects a nonempty output directory. Its normal top-level assembly is passive; `--research-layout` adds optional research layout geometry, not actual connected output hardware or an operating authorization. Keep editable Python construction source, parameters and the lockfile with exported STEP files. STL files are restricted to the stated non-pressure/non-primary-load printable parts; they are not the engineering source.

The stdlib test command alone does not prove a CAD kernel recompute. Run the CAD generation command and inspect its manifest/checks, including actual solid/export tests. The root controller owns full-repository `make test`, `make check` and frontend build results; this lane does not run or imply those checks.

## Artifact map

| ID | Path | Content |
|---|---|---|
| HW-01 | [`hardware/interfaces/reference-v1.json`](hardware/interfaces/reference-v1.json) | Versioned physical contract, source-verified board pin functions, provisional harness/rail allocations and explicitly null operating limits. |
| HW-02 | [`hardware/cad/`](hardware/cad/) | Locked CadQuery/OCP project, editable construction, source evidence, generated STEP, allowed STL, dimensioned DXF/SVG views, assembly/exploded views and numerical check manifest. |
| HW-03 | [`hardware/bom/`](hardware/bom/) | Exact reference COTS identities, source URLs/dates, quantities, alternatives, missing prices/quotes and unresolved selections. Not approval to order. |
| HW-04 | [`hardware/electronics/`](hardware/electronics/) and [`hardware/wiring/`](hardware/wiring/) | Executable assumed-load budgets, rail/drop/inrush/thermal/solar calculations, pin/harness schedules and physical inhibit requirements. |
| HW-05 | [`hardware/analysis/`](hardware/analysis/) | Illustrative drag, wind, hydrostatic and gross-envelope buoyancy calculations with explicit site/mass assumptions and omitted loads. |
| HW-06 | [`hardware/manufacturing/`](hardware/manufacturing/) | Reference assembly/inspection instructions, material/fastener/finish hold points and a blank unit traveler. |
| HW-07 | [`hardware/validation/`](hardware/validation/) | Reference consistency checker and 14 unperformed physical gates covering every major assembly group. |
| HW-08 | [`tests/hardware/`](tests/hardware/) | Focused numerical, source-consistency, geometry/export and fail-closed reference checks. |
| HW-09 | [`hardware/candidates/passive-v3/`](hardware/candidates/passive-v3/) and [head records](docs/hardware/passive-v3-head.md) | Intrface's Poseidon passive-v3 digital candidate: source-traced CAD, STEP/DXF/GLB and 14 unperformed physical gates. Unsealed, non-adopted and not build authorized; 30 m and 90 days are required targets, not verified ratings. |
| HW-10 | [`hardware/showcase/`](hardware/showcase/) | Local Blender scenes, unit/site/orada GLBs, test renders and CAD-lineage manifest for the site handoff. Concept-only; vendor CAD reuse rights remain unverified, and no public release or deterrence efficacy is established. |
| HW-11 | [`hardware/candidates/surface-v3/`](hardware/candidates/surface-v3/) and [surface-v3 records](docs/hardware/surface-v3.md) | Flat two-panel tray with the hub underneath and pole or float mounting variants: source-traced CadQuery, STEP/DXF/GLB, mass and displacement scenarios with the buoyancy sign unknown, reopened thermal budget and open mounting-load gates. Non-adopted, not build authorized. |
| HW-12 | [`hardware/showcase/scene-manifest-v4.json`](hardware/showcase/scene-manifest-v4.json), [hero.glb](hardware/showcase/hero.glb), [head.glb](hardware/showcase/head.glb) | Showcase v4 built from the vendor-free CAD exports: the surface unit on its pole at the farm with the float variant hidden, water, longlines, mussel droppers, seabream and a work boat for scale; the listening head with explode and assemble clips; press renders in `hardware/showcase/renders-v4/`. Presentation assets only. |

## Engineering notes

[Reference decisions](docs/hardware/reference-decisions.md) define evidence classes and change control. [CAD notes](docs/hardware/cad-reference.md) define geometry, units, interfaces, materials and drawing/check limits. [Electrical notes](docs/hardware/electrical-reference.md) explain equations, source verification, wiring and power gates. [Mechanical calculations](docs/hardware/mechanical-calculations.md) explain incomplete illustrative loads and displacement. [Physical verification](docs/hardware/verification-plan.md) identifies test owners, freeze criteria and required evidence.

The Pi board outline/mounting pattern and named battery/panel/converter dimensions can be source-backed while surrounding enclosures, supports, service clearances, cable assumptions and wet instrument envelopes remain provisional. The battery manual/drawing width discrepancy requires reconciliation, and current panel availability remains unconfirmed. Exact pressure housing/endcaps/windows/penetrators, receive chain, camera tether, gateway, battery management and complete USB-C source implementation remain open.

The issued assumption set fails thermal and solar sizing screens: the shaded HUB internal-air estimate is 67.8°C against the Pi's 50°C ambient limit, and the 40 W / one-peak-sun-hour REEF case has a 6.465 Wh/day load-side deficit plus a hot-panel startup shortfall. These results require revised heat-path/energy design and measurements; they are not field observations.

The separate [power refinement](docs/hardware/power-refinement.md) preserves that failed case. Two series-connected reference panels pass the stated array calculation screens; two parallel panels do not fix hot startup. Neither option changes the one-panel CAD/BOM. The [thermal/power hold point](hardware/validation/thermal-power-hold-point.json) defines the unresolved heat path and authorized-test prerequisites: the nominal zero-uncertainty requirements are at most 0.6863 K/W shaded or 0.2147 K/W in the modeled sun case, not measured achievements. [Digital verification results](docs/hardware/digital-verification.md) record the commands and passing software/CAD checks without closing those physical gates.

No measured power, actual unit mass/CG, fit, leak/pressure, marine load, corrosion, thermal, solar autonomy, RF, acoustic calibration, ecological efficacy, conformity, vendor quote or manufacturing success is claimed. The package's physical tests performed count is zero. Those gates require qualified people, real equipment, source-backed part freeze and separate authorization.
