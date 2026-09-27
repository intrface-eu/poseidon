# Passive-v2 candidate CAD

**Configuration `passive-v2`, revision `HW-CAND-2.0`, status `NON_ADOPTED_NOT_BUILD_AUTHORIZED`.** This additive candidate does not replace `HW-REF-1.1`. The source and both CAD commands verify all 144 frozen baseline files by SHA-256 before accepting the candidate. No baseline source, parameter, dependency, generated artifact, document or test was edited by this CAD work.

Observed implementation model: `unspecified implementation`. The existing pinned CadQuery 2.6.1 / OCP environment is reused read-only. No package installation, pressure part, live hardware, acoustic output, fabrication or procurement occurred.

## Reproduce

Run from the repository root, using the existing locked CAD environment directly. Do not resync or modify the frozen environment for this candidate.

```sh
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python \
  hardware/candidates/passive-v2/cad/generate.py \
  --output hardware/candidates/passive-v2/cad/.qa-independent-1

PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python \
  hardware/candidates/passive-v2/cad/check.py \
  hardware/candidates/passive-v2/cad/.qa-independent-1 --geometry

# Standard-library evidence checks. These do NOT execute CadQuery or OCP.
PYTHONDONTWRITEBYTECODE=1 python3 \
  hardware/candidates/passive-v2/cad/check.py \
  hardware/candidates/passive-v2/cad/generated/passive-v2
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s tests/hardware -p test_candidate_v2_cad.py -v
```

The output directory must be new or empty and owned by the caller. The generator refuses an existing package rather than deleting or overwriting it. The checked-in candidate is `hardware/candidates/passive-v2/cad/generated/passive-v2/manifest.json` and its hashed artifacts. Failed checks return nonzero and preserve the attempted output for inspection.

Editable source is `hardware/candidates/passive-v2/cad/model.py`; bound inputs are `parameters.json`. `candidate_parameters.py` rejects binding to `HW-REF-1.1`, source-dimension drift, one-panel/parallel substitutions, reduced frozen heat assumptions and insufficient bend/service allowances. Input hashes bind the parent `hardware/candidates/passive-v2/interface.json`, official evidence files and `power/part-envelopes.json`. Source changes require explicit candidate rebinding, not silent reuse of stale exports.

## Changed assemblies

| ID | CAD content | Boundary |
|---|---|---|
| C1 | `C2-HUB`: vertical Hammond 1550WJ enclosure and lid, custom collector, two source-thickness interface patches, rear Wakefield sink base and fin-field occupancy, Pi mounting geometry/standoffs, DAQ and unresolved USB-C source regions, open shade/support geometry | Overall vendor sizes are sourced; detailed casting, gasket, component pickup, contact pressure, fasteners and enclosure modifications are not qualified. |
| C2 | `C2-REEF`: two distinct panels, support rails/posts, panel supports/end-clamp concepts, generic M8 anchor shanks/heads/washers, actual series/free-lead cable sweeps, battery shelf/terminal volume, electronics shell and source-bound power-component allocations | Custom clamps and generic fasteners are candidates, not a sourced compatible mounting system. Exact panel zones, wire terminations, complete weather protection and structural/thermal/electrical approval remain open. |
| C3 | `C2-TOP`: changed HUB/REEF placement and combined keepouts | Spatial study only. Frozen WET, array, wiper and projector are not rebuilt, modified or adopted into this candidate. |

Each assembly exports physical STEP, separate keepout STEP, dimensioned orthographic DXF/SVG, feature/source/fastener SVG, and assembly/exploded/keepout SVG views. STEP contains exact named BRep solids; DXF dimension entities and geometry use mm. SVG drawings sample curved edges and show orthographic wireframe back edges. Do not scale a screenshot for machining. Exploded +Z offsets are review aids, not a validated assembly order.

No STL/3MF is exported: the candidate printable whitelist is empty. There are no pressure parts or primary-duty prints. Custom metal material/density/finish assumptions and source-qualified versus provisional geometry status appear per part. Vendor-envelope mass is not derived by filling an integration box with metal; the sink fin-field block is occupied space, explicitly **not solid metal**.

## Two-panel geometry and real routing

P1 and P2 are separate `V2-PV-001` instances, each Victron SPM040401200, **668×425×25 mm**, 40 W nameplate. Their Y centres are −237.5 and +237.5 mm. Their actual BRep edge gap is **50 mm** and panel-group footprint is **668×900 mm**. The complete frame/clamp assembly is larger than that panel footprint.

The two panel faces total **0.5678 m²**, exactly twice the baseline's 0.2839 m². The enclosing panel-pair rectangle is 0.6012 m², including the open service gap. These are geometric areas, not a structural rating or wind coefficient. Parent calculations must include frame, supports, shade and actual installation loads. Panel nominal masses total 6.2 kg from the inherited supplier table, not a measured installed mass.

`C2-REEF-SERIES-LINK` is an actual swept solid connecting assumed `PV1_POS` and `PV2_NEG` faces. Its service loop has four tangent quarter-circle centreline bends, each R56 mm. Two separate bent free-lead solids terminate above the electronics service boundary as `ARRAY_NEG` and `ARRAY_POS`; they are not falsely connected to an unspecified protection or MPPT terminal. The physical cable geometry and the BOM/topology record are separate from the source-qualified electrical design.

The cable is an **8 mm provisional diameter allocation**, not a selected conductor or overmould. A provisional 6D allowance gives a worst-case margin of **5.7 mm**: R56 minus 0.5 mm radius tolerance, compared with 6×(8+0.3) mm. Actual path-arc radii and cable-to-panel/cable-to-cable gaps are checked in OCP. The junction-box locations and port faces are clearly labelled unverified allocations; true swept routing is not a vendor cable compatibility or energization claim.

`bom-links.json` counts exactly the two panel body instances, not their junction allocations or repeated TOP copies. Shared enclosure/lid, sink base/fin-field and PCB/component bodies also represent one purchased parent, not additional orders. Custom geometry counts are not approved procurement quantities.

## Source-bound HUB heat-path geometry

| ID | Geometry/evidence | Unresolved detail |
|---|---|---|
| S1 | Hammond 1550WJ official drawing, PDF page 1: vendor L×W×H 275×175×66.6 mm, rotated to vertical CAD X×Y×Z **275×66.6×175 mm**. Rear/base plane XZ, lid toward +Y. Reference base 2.5 mm, lid 1.5 mm. | Tapered walls, lips, bosses, gasket and actual attachment remain the vendor drawing's authority. Simplified CAD is not a replacement seal/pressure/ingress design. |
| S2 | Custom aluminium collector **200×6×120 mm**, against the rear wall through a cut TIM patch. | Alloy, flatness, loading and source-to-collector thermal pickup are unknown. No unsupported PCB package thermal-pad map is invented. Pi supports are mechanical mounting references, not a claimed CPU cooling bridge. |
| S3 | Henkel BERGQUIST SIL PAD TSP1600 data sheet, page 1: **0.127 mm** nominal thickness. Two custom **200×70 mm** cut patches, one inside and one outside the rear wall. | Cut SKU, actual pressure, large-area contact resistance, creep and electrical insulation performance remain unqualified. Datasheet contact-pressure performance is not automatically transferable. |
| S4 | Wakefield Thermal 2025 catalogue, PDF page 21 / printed page 17: stock 125460 / XX4559, 10.780 in width, 3.770 in depth, 0.620 in base; CAD **273.812×95.758×76.2 mm** for a candidate 3 in cut. Channels are oriented vertically in Z, behind −Y. | Fin pitch/taper/count and bolt pattern are not dimensioned in the retrieved page. Only the source-sized base and a labelled fin-field occupancy block are modelled. No cutting/drilling or stock availability is approved. Catalogue 0.5 K/W at 3 in is not installed thermal performance. |
| S5 | Opaque custom aluminium shade **375×275×1.5 mm**, **75 mm above the enclosure**, 50 mm X overhang and over 50 mm front/rear overhang around enclosure plus sink. Actual lid-removal and sink-outlet volumes remain clear. | No side baffles are modelled. Roof material finish, absorption/emission, angled sunlight, air motion and residual heat coupling are unknown. Geometry is not zero solar load. |

The CAD checks four geometric contact interfaces: wall/inner TIM, inner TIM/collector, wall/outer TIM and outer TIM/sink base. Each uses a 14,000 mm² nominal rectangular patch and near-zero BRep separation. This proves only coincident reference faces. It does not establish real contact resistance, clamping pressure, enclosed-heat capture, Pi junction temperature or inside-air temperature.

The comparison retains **35 °C ambient, 21.857142857 W enclosed peak heat, 48 W potential absorbed sun, 27.5247475 Wh/day REEF demand and 1 peak-sun-hour**. Parent thermal calculations are in `hardware/candidates/passive-v2/thermal/`; this CAD manifest deliberately leaves whole-box air, Pi junction, installed sink performance, heat-capture fraction and residual solar fraction **unknown**. No convenient whole-box thermal resistance or zero absorbed sunlight was introduced.

## Power-component integration

The provisional REEF electronics shell now contains source-bound envelopes for SCC075010060R MPPT, BMS400100000 smallBMS, BPR065022000 BatteryProtect and two Pololu D36V28 regulators, plus provisional ESP32/RAK board regions. The source envelope records own vendor notes and contradictions.

- BMS **107×46×23 mm** is explicitly a conservative union of conflicting drawing/data-sheet dimensions, not a single verified vendor box. Its 30 mm connector approach is provisional.
- BatteryProtect **106.3×55×46 mm** follows the larger drawing allocation, retaining the conflicting manual dimensions. Additional 40 mm M6 lug/driver space is modelled and checked against the lid.
- Both regulators use **20.3×17.8×8.8 mm** source board envelopes, with an extra 5 mm plan allowance on every side; header/wire/thermal details are still open.
- Battery **188×147×199 mm** retains the conservative sourced upright envelope and at least 40 mm terminal space. Restraint, weather guarding, cable protection and safe servicing are not proved by an open-frame model.
- The field USB-C source, inline charge-disable cable/module, exact connectors and complete harness remain unresolved. Reserved spaces are not invented vendor dimensions or evidence that these missing parts fit.

## Checks and remaining gates

G1. **Geometry pass:** canonical generation executed 230 checks; fresh candidate CAD reexecution checks the same solids, cable paths, contacts/clearances and six STEP imports. The stdlib audit explicitly states that it did not run the CAD engine. Additive tests also reject one-panel substitutions, source/candidate identity drift, altered thermal assumptions, corrupted exports and unsafe printing claims.

G2. **Baseline preserved:** all 144 wave-one files remain byte-identical. The original failed power/thermal reference remains historical evidence, not silently replaced by this candidate.

G3. **Thermal unknown:** source-to-collector path, fraction of enclosed heat collected, actual TIM pressure/flatness, installed sink conditions and shaded solar coupling block an enclosure-air or Pi-temperature acceptance claim. Consult the parent's analytical cases; no case is a physical test.

G4. **Mechanical/electrical release open:** exact panel clamp zones, complete fastener/rail compatibility, joints, stock cuts, wind/fatigue/galvanic isolation, enclosure modifications, battery weather/retention, source-conflicting power dimensions, terminal/cable/protection selection and actual farm attachment still need review and measurement. No build or field release follows these digital checks.
