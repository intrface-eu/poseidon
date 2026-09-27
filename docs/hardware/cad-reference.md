# Reference mechanical CAD

Configuration `reference-v1`, issue **HW-REF-1.1**. This is an editable mechanical integration and fixture package, **not a fabrication release**. Source is CadQuery Python; STEP contains named BRep assembly parts. No custom pressure hull, pressure containment fixture, structural print, acoustic output program or powered wiper is supplied.

Implementation model observed in the CAD child: `unspecified implementation`. No model fallback, global installation, fabrication, pressure test or live hardware operation occurred.

## Regenerate and check

Run from the repository root. Python 3.12 and all CAD dependencies live in `hardware/cad/.venv`; `hardware/cad/pyproject.toml` and `hardware/cad/uv.lock` pin the project environment.

```sh
uv sync --project hardware/cad --frozen --python 3.12

# Choose a NEW or EMPTY owned directory. Existing files are never overwritten.
PYTHONDONTWRITEBYTECODE=1 uv run --project hardware/cad --frozen \
  python hardware/cad/generate.py \
  --output hardware/cad/.qa-review-1 --research-layout

# Rebuild solids and recheck STEP/STL in the CAD runtime.
PYTHONDONTWRITEBYTECODE=1 uv run --project hardware/cad --frozen \
  python hardware/cad/check_manifest.py hardware/cad/.qa-review-1 --geometry

# No third-party dependencies: checks archived evidence, NOT live CAD geometry.
PYTHONDONTWRITEBYTECODE=1 python3 hardware/cad/check_manifest.py \
  hardware/cad/generated/reference-v1
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v
```

The checked-in package is `hardware/cad/generated/reference-v1/manifest.json` and the artifact paths it lists. Do not point the generator at that existing directory expecting an in-place update: it refuses nonempty output. Compare a clean generation, then have the owner issue the replacement. A failed generation leaves its owned output for inspection and returns nonzero; it does not publish a passing manifest or delete earlier files.

`--array-pitch-mm 450` changes the optional square research fixture from its default 300 mm pitch. Supported pitch is 180–600 mm. `--parameters <file.json>` overrides known design assumptions; the generator rejects nonfinite/negative lengths, invalid fit budgets and changes to source-verified Pi features or controlled interface envelopes. Major envelope changes require a revised interface and supporting layout review. Parametric does not mean arbitrary dimensions fit this assembly family.

The default top-level STEP is always `TOP_PASSIVE`. `--research-layout` additionally exports `TOP_RESEARCH`, containing the optional array, unpowered parked wiper and projector envelopes. The standalone optional assemblies are exported for review even when omitted from the top-level layout. Their existence is not permission to populate or energize them.

## Package contents

| ID | Assembly | What the CAD contains |
|---|---|---|
| C1 | `HUB` | 400×300×180 mm provisional purchased enclosure allocation, conservative 360×260×140 usable volume, lift-off lid, removable drilled tray, Pi PCB/mounting pattern and standoffs, DAQ/storage/converter allocations, nonstructural cable comb, driver and plug access, tray extraction/lid space |
| C2 | `WET` | Metal base, camera clearance collars and single hydrophone support, fictional 110 mm diameter ×250 mm purchased camera/housing allocation, fictional 32 mm diameter ×100 mm hydrophone, optical-axis and axial-removal space |
| C3 | `ARRAY` | Optional four-sensor square frame and collars, configurable pitch, sensor centres and pairwise spacing checks; no synchronized DAQ or localization accuracy claim |
| C4 | `WIPER` | Optional metal annular guard, bridge, parked 70 mm arm, pivot/motor and blade references, optical clearance and conservative sweep volume; no motor/shaft/seal/drive selected |
| C5 | `PROJECTOR` | Optional metal base/collars, uncompressed generic elastomer annuli, fictional projector cylinder, axial service space; no acoustic, retention or vibration-isolation performance claim |
| C6 | `REEF` | Hollow-section metal frame, flat panel packaging pose, battery shelf/stops and 40 mm terminal allowance, electronics shelf/tray, MCU/radio/controller allocations, antenna above schematic water datum, wired wet-probe route |
| C7 | `FARM` | Fictional 60 mm rail, metal backplate and split saddles, secondary retrieval-eye concept and metal cable-clamp geometry; actual farm geometry, fasteners and safe working load remain open |
| C8 | `ASSEMBLY_FIXTURE` | Dry-bench Pi support-pattern template and true swept cable bend model with radius gauge; no PCB drilling or cable qualification claim |
| C9 | `CALIBRATION_FIXTURE` | 600 mm positioning rail, two sensor stations at 400 mm centre spacing, passive target holder; no calibrated instrument, calibration certificate or emitter |
| C10 | `PRESSURE_POSITIONING_FIXTURE` | Open drained plate with four checked mount holes, open-top handling saddles and fictional test-specimen envelope; no lid, seals, pressure connections, pressure reaction frame or containment |
| C11 | `TOP_PASSIVE`, `TOP_RESEARCH` | Placed assemblies, schematic water datum, service volumes and tether/retrieval corridors. These are spatial studies, not surveyed installation/load-path or terminated harness designs. |

Each assembly has a named STEP file, three-view dimensioned SVG and DXF, an SVG feature/fastener schedule, and assembly/exploded SVG views. Separate `keepouts/*.step` files and keepout views prevent access/allocation volumes from entering the physical BOM. The exploded view uses sequential +Z separation for review, not a verified assembly order. STEP holds exact solids; drawing polylines sample curves and show wireframe back/hidden edges. Overall dimensions come from the exact BRep. DXF uses millimetres and actual dimension entities; do not derive machining dimensions by scaling SVG screenshots.

`manifest.json` records every part's revision, material/finish, volume, mass basis, bounding box, features, BOM link and print/critical-duty flags. `mechanical-bom.json` groups custom/fixture/fastener geometry by local assembly and excludes repeated TOP copies. Purchased component IDs link to `hardware/bom/reference-v1.json`; separate shell/lid or PCB/component proxy bodies do not imply additional orders. Fixture instruments represent reused specimens, not additional deployed procurement.

## Source-verified features versus allocations

| ID | Evidence | Controlled geometry / limits |
|---|---|---|
| S1 | [Raspberry Pi mechanical drawing RP-008343](https://pip.raspberrypi.com/documents/RP-008343-DS-raspberry-pi-4-mechanical-drawing.pdf), page 1 | Verified PCB 85×56 mm, corner R3, four Ø2.7 holes. Hole centres from lower-left: (3.5,3.5), (61.5,3.5), (3.5,52.5), (61.5,52.5), giving 58×49 pitch. Thickness 1.6 mm and component/plug allocations remain assumptions. Pi 4 Model B 4GB SC0194 reference, above water, USB-C 5 V power path belongs to electrical review. |
| S2 | [Victron Smart battery manual](https://www.victronenergy.com/media/pg/Lithium_Battery_Smart/en/technical-data.html), BAT512050610 | Manual H×W×D 199×188×147 mm becomes CAD X×Y×Z 188×147×199, upright. Vendor nominal mass 7 kg, M8 terminals. Additional 40 mm terminal/driver/lug volume is provisional, not a verified cable bend envelope. |
| S3 | [Victron battery drawing](https://www.victronenergy.com/upload/documents/LiFePO4-Battery-12.8V50AH-Smart.pdf), Rev01, page 1 | Drawing/body and manual dimensions differ in detail. The manual 188 mm overall width governs the conservative box; reconcile the actual product revision before fabrication. Exact terminals, mounting and cable geometry are not modelled as verified features. |
| S4 | [Victron BlueSolar monocrystalline datasheet](https://www.victronenergy.com/upload/documents/Datasheet-BlueSolar-Monocrystalline-Panels-EN.pdf), page 1 | SPM040401200 40 W row: 425×668×25 mm, rotated to CAD 668×425×25; nominal mass 3.1 kg. The 40 W row has no discontinuation footnote; current supplier availability is unverified. Frame supports leave 42.5 mm panel overhang in ±Y; actual clamp zones/junction box/wind and solar tilt remain open. |
| S5 | Electrical source records `SRC-SD50`, `SRC-MPPT` in `hardware/bom/sources.json` | SD-50A-5 converter 159×97×38 mm; SCC075010060R controller X113×Y40×Z100 mm. Simplified boxes with provisional terminal approach volumes, not detailed vendor CAD or thermal qualification. |
| S6 | Electrical `SRC-RAK` and provisional board allocations | RAK plan evidence 25.4×32.3 mm has board/module/header ambiguity. CAD reserves 40×30×15 mm instead of an undersized box. ESP32-DevKitC-32E 55×28×14 mm remains provisional. Neither board's mounting holes or complete connector heights are verified in CAD. |

Primary supplier URLs, SHA-256 hashes, retrieval date and extracted facts remain in the manifest and `hardware/vendor-sources.json`. Supplier PDFs/HTML are fetched on demand into `hardware/.vendor-cache/` and are not distributed. The camera/housing Ø110×250 mm envelope is an original fictional integration volume; no bought pressure-boundary configuration or rating is adopted.

## Numerical evidence and its limits

The generator and explicit `--geometry` audit execute OCP validity and closed-shell checks for each part; exact pairwise physical interference checks after bounding-box filtering; minimum-distance fit/service checks; and fresh import of each physical/keepout STEP with mm-unit, solid-count, bounding-box and volume comparison. Only face contact is accepted by default. Keepout volumes are not physical parts; only named access-distance checks are validated, not every possible service motion or cable route.

Design arithmetic checks are separate from measured or source-qualified limits:

| ID | Default numerical check | Evidence boundary |
|---|---|---|
| N1 | Tray worst-case side gap 9.7 mm on X and Y, requirement 5 mm | Conservative cavity/tray dimensions and ±0.3 mm combined allowance, not a purchased enclosure tolerance specification |
| N2 | Camera collar worst-case radial gap 1.05 mm; hydrophone 0.65 mm | Assumed bore diameter ±0.2 mm and instrument diameter ±0.5 mm; clearance is not clamp retention/preload |
| N3 | Cable centreline bend R56 mm for Ø8 mm, assumed 6D minimum | Worst-case R55.5 versus 6×8.3 =49.8 mm gives 5.7 mm margin. Real swept BRep and radius-gauge clearance are checked; selected cable datasheet remains required. |
| N4 | M2.5 screw/Ø2.7 PCB hole worst-case diametral gap 0.10 mm; template Ø3.2 gap 0.55 mm | PCB nominal diameter is source-verified; screw/hole/template tolerances and assembly process remain assumptions |
| N5 | Hub driver envelope Ø16×80 mm, lid lift 180 mm, minimum tool reach 60 mm | Checks actual model clearance to shell. Exact latch/hinge/fastener/head/harness access remains open. |
| N6 | Battery top at Z299; terminal keepout to Z339; electronics shelf at Z412 | 113 mm battery headroom and 73 mm above the 40 mm terminal volume. Exact lug/boot/conductor bend and protected enclosure layout still need design. |
| N7 | Four pressure-positioning base Ø10.5 holes at (-15,-85), (265,-85), (-15,85), (265,85) mm | Each hole gets an exact cylindrical-void and surrounding-material check, preventing off-plate cuts from silently disappearing. No pressure performance is inferred. |

Mass uses geometric volume × assumed density: aluminium 2700, 316L 8000, PETG 1270, generic elastomer 1150 and FR4 1850 kg/m³. These are solid-equivalent estimates, not measured hardware mass. PETG values do not account for slicer infill; purchased envelopes have no density-derived mass. Vendor battery/panel nominal masses are separate fields. No total installed mass, centre of gravity, buoyancy, ballast or safe working load is claimed while other component masses and the installation are unknown.

The stdlib test suite validates checksums, units, dimensions, tolerance arithmetic, sources/BOM links, optional/default boundaries and archived runtime evidence. It reports that the geometry runtime did **not** execute. The separate CAD command rebuilds geometry and reimports exports; it does not silently fall back to the stdlib audit. Generation manifests carry actual per-check results and counts.

## Printing and release holds

Only these four parts export STL: `PRINT-HUB-GUIDE-01`, `PRINT-PI-TEMPLATE-01`, `PRINT-CABLE-RADIUS-GAUGE-01`, `PRINT-CAL-TARGET-HOLDER-01`. They are internal loose-cable or dry-bench fit aids, not pressure, lifting, mooring, battery retention or load-bearing fixtures. Actual STL files pass watertightness, consistent winding, positive volume and <1% volume error checks. STL itself carries no units; the manifest specifies mm. Material/process/dimensional checks remain open before even these prototypes are used.

R1. Freeze the surveyed farm, depth/duration, current/wave/wind loads, independent retrieval and operating envelope. Top-level placement is illustrative.

R2. Select the complete purchased pressure boundary and wet instruments. Independent pressure/leak testing must cover the actual assembled configuration at an approved facility. The open positioning fixture provides no containment and needs facility approval for materials, buoyancy, venting and handling.

R3. Complete joints, split-clamp retention, fastener stacks, torque, cable crush/pullout, structural proof/fatigue and corrosion review. Several supports intentionally reserve clearance for future pads/retainers; they are not proven restraints. No critical mechanical part is printable.

R4. Fit the unresolved BMS, disconnects, fuses, USB-C source, gateway, terminal protection, penetrators and complete harnesses. Current component boxes do not prove these omitted parts fit. Above-water battery weather protection, safe terminal access and heat/condensation management remain open.

R5. Measure geometry/tolerances and validate service procedures, rail spacing, optical alignment, array synchronization and receive isolation. Fixture geometry is not calibrated metrology.

R6. Keep optional wiper/projector physically absent or inhibited. Motor/guard/jam/seal, independent stop, acoustic calibration, environmental permission, biological safety and efficacy gates cannot be passed by this CAD package.
