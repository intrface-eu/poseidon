# HW-REF-1.1 digital verification

Executed 2026-09-08 on macOS arm64. Lead and both bounded children observed `unspecified implementation`; no model fallback or further delegation. This records digital checks, not physical qualification. The issued thermal/solar operating case remains blocked.

## Final checks

| ID | Command run from repository root | Exit and result |
|---|---|---|
| DV-01 | `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v` | 0; **117 tests passed**, no failures or skips. Includes 24 CAD, 42 baseline electrical, 14 refinement, 10 mechanical equations, 6 package integration, 5 thermal/power hold-point and 16 reference tests. |
| DV-02 | `PYTHONDONTWRITEBYTECODE=1 uv run --project hardware/cad --frozen python hardware/cad/generate.py --output /tmp/hardware-verification/reports/hardware-clean-cad --research-layout` | 0; **407/407** actual generation/arithmetic/geometry/export checks passed in a new owned directory. |
| DV-03 | `PYTHONDONTWRITEBYTECODE=1 uv run --project hardware/cad --frozen python hardware/cad/check_manifest.py /tmp/hardware-verification/reports/hardware-clean-cad --geometry` | 0; **397/397** freshly executed geometry checks passed. Solids rebuilt; STEP files reimported; BRep, intersections, clearances and actual STL meshes checked. |
| DV-04 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/cad/check_manifest.py hardware/cad/generated/reference-v1` | 0; 97 artifact hashes, 12 assemblies, source/BOM links and 407 archived/arithmetic checks verified. This stdlib command explicitly does **not** execute the geometry kernel. |
| DV-05 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/validation/check_reference.py` | 0; 10 consistency checks passed; physical tests performed remains zero. |
| DV-06 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/electronics/calculate.py --output /tmp/hardware-verification/reports/hardware-electrical-final-recheck.json` followed by `cmp hardware/electronics/reference-evidence.json /tmp/hardware-verification/reports/hardware-electrical-final-recheck.json` | Both 0; electrical JSON reproduces byte-identically. |
| DV-07 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/analysis/mechanical.py --output /tmp/hardware-verification/reports/hardware-mechanical-final-recheck.json` followed by `cmp hardware/analysis/calculated-reference.json /tmp/hardware-verification/reports/hardware-mechanical-final-recheck.json` | Both 0; mechanical JSON reproduces byte-identically. |
| DV-08 | `PYTHONDONTWRITEBYTECODE=1 python3 hardware/electronics/refine_power.py > /tmp/hardware-verification/reports/hardware-refinement-final-recheck.json` followed by `cmp hardware/electronics/refinement-evidence.json /tmp/hardware-verification/reports/hardware-refinement-final-recheck.json` | Both 0; separate refinement reproduces byte-identically without changing the baseline. |

The literal output paths above already contain evidence. Use a new owned directory to rerun generation; see `HARDWARE.md`. The refinement CLI deliberately restricts its `--output` destination to the named refinement artifact; use its documented stdout mode for another destination.

The lead compared canonical and clean regenerated revision/configuration/units/parameters/source hashes/interface evidence/check summaries and every assembly's part geometry, bounds, keepouts and checks. All 12 assemblies agree exactly. Timestamps and STEP headers may differ; this is numerical geometry reproduction, not a claim of byte-identical STEP headers.

## Delivered and inspected artifacts

Canonical package: `hardware/cad/generated/reference-v1/`. It contains 12 assemblies, 22 STEP files (12 physical/reference assemblies and 10 separate keepout files), 12 dimensioned DXFs, 58 SVG drawings/views, four printable-part STLs and a mechanical BOM. There are 97 hashed artifacts plus the manifest. Editable source and the locked CadQuery/OCP environment remain under `hardware/cad/`.

Canonical manifest SHA256:
`69bb7869727efae6561bfb7c5da69f65936f597573bd03321544b11fb7a1d527`

Preserved electrical baseline SHA256:
`dfc71d2a6bfffc8a99b12e83af9e5daf9ad33ead8da6337c50cdfb7f1b17e40f`

The lead rendered and visually inspected five final engineering views using local `rsvg-convert`: HUB, REEF and pressure-positioning orthographic drawings; passive top-level assembly; wet-head exploded view. Revision/provisional labels, dimensions and views are legible. The pressure fixture shows four mounting holes. Review evidence is in `/tmp/hardware-verification/reports/hardware-visual-qa/`; no browser or persistent service was started. Wireframes and exploded spacing remain review aids, not physical fit or assembly-order evidence.

## Corrections and negative results retained

| ID | Finding | Resolution or open gate |
|---|---|---|
| VF-01 | Early PDF text summaries mixed MEAN WELL column values; a panel discontinuation footnote was initially attributed to the wrong row. | Direct source inspection corrected the converter inputs and panel interpretation. The 40 W row has no discontinued marker, while 30 W/55 W do; actual availability remains unverified. Source register retains the corrections. |
| VF-02 | Pressure-fixture mounting holes were outside the translated plate; an early RAK envelope was narrower than its documented plan dimension. | Datum/holes corrected and checked numerically; generic drilled plates reject off-plate holes. RAK reserve enlarged to 40×30×15 mm with unresolved header/height detail. |
| VF-03 | Parent's interim electrical run found one stale-evidence failure out of 41 tests while final energy-boundary code was changing. | Regeneration resolved it. Final baseline suite passes 42 tests; complete suite passes 117. Solar comparison now includes the same discharge-path loss as load-side reserve. |
| VF-04 | Parent initially requested refinement `--output` at an unsupported temporary filename; CLI returned 2. | Used documented stdout export, then verified byte-identical output. The output-path guard was not removed. |
| VF-05 | Frozen one-panel case fails energy and hot-start screens; HUB thermal assumption fails even in shade. | Failure evidence preserved. Two series panels pass only the bounded array calculation screens; neither two-panel topology is adopted. No replacement heat resistance or workload reduction is invented. |

## Unresolved engineering conclusion

The nominal heat-path requirements are at most **0.6863 K/W shaded** or **0.2147 K/W** in the frozen absorbed-sun scenario, before measurement uncertainty. The actual enclosure, heat-spreader/contact/dissipator/shade system is not selected or measured. At the existing 1.5 K/W assumption the 7 W combined Pi/USB shaded output cap is below both recording and peak loads. A qualified reviewer must approve the method and demonstrate `measured local ambient + uncertainty <= applicable vendor limit`; no physical test is authorized here.

The USB-C source/protection path, battery external BMS and charge/load disconnects, REEF regulators, conductor/fuse/connector coordination, exact wet instruments/pressure assembly and site installation remain open. Current one-panel CAD/BOM is unchanged. Full product completion, field autonomy, manufacture, energization, pressure qualification, acoustic safety/efficacy and conformity are not claimed.

The root-owned `make check`, `make test` and `make build-ui` were not run by this lane. Raspberry Pi/ESP hardware, live drivers, RF, camera/hydrophone capture, thermal/load/pressure/leak/corrosion tests and field paths remain untested.
