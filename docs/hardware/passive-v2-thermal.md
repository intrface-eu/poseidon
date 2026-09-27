# Passive-v2 thermal candidate: HW-CAND-2.0

This is a separate **non-adopted digital candidate**, not a replacement for HW-REF-1.1. The 144 historical files remain byte-preserved. The candidate supplies a named enclosure, external sink, thermal-interface material, collector and spaced shade arrangement, but installed thermal acceptance remains **UNKNOWN**. No favorable effective enclosure resistance, zero solar absorption or complete heat capture is selected.

## Source-backed geometry and data

| ID | Candidate element | Direct source and supported precision | Open condition |
|---|---|---|---|
| CT-01 | Hammond1550WJ enclosure | [Manufacturer drawing](https://www.hammfg.com/files/parts/pdf/1550WJ.pdf), Rev09.04.2025 as printed:275×175×66.6mm overall, inside reference266.91×166.91×61.6mm,2.5mm base and1.5mm lid references. Vertical candidate axesX275/Y66.6/Z175. | Casting taper/bosses are not a constant rectangular cavity. Alloy/conductivity, flatness and modified ingress are unknown.245×145×48mm usable space is a conservative allocation. Wpart table says silicone gasket while generic notes mentionEVA; confirm exact supplied variant. |
| CT-02 | Wakefield125460 stock, XX4559 profile, proposed76.2mm cut | [2025 manufacturer catalog](https://wakefieldthermal.com/content/catalogs/Thermal_Extrusions_WakefieldThermal-2025.pdf), PDFp21/printed17:10.78in width,3.77in depth,.620in base,12in stock. Catalog0.5K/W explicitly uses a3in natural-convection reference. | Installed test heat/orientation/surface/boundaries are not stated. Do not scale resistance inversely with stock length. Fin pitch/taper/count are not dimensioned; CAD reserves their field instead of fabricating precision. No cutting or purchase is authorized. |
| CT-03 | Two BERGQUIST SIL PAD TSP1600 interfaces | [Henkel November2018 datasheet](https://datasheets.tdx.henkel.com/BERGQUIST-SIL-PAD-TSP-1600-en_GL.pdf):0.127mm nominal thickness,k1.6W/mK; pressure-dependent ASTM D5470 impedance0.92/0.60/0.45/0.36/0.29°C·in²/W at10/25/50/100/200psi. | Typical reference properties, not product specifications. Fixture interface resistance is included. Actual large-area pressure, effective area, roughness and flatness are not known. |
| CT-04 | Collector and mounting contact | Custom200×6×120mm aluminum collector,200×70mm thermal contact patch, one TIM layer inside the base and one outside before the sink. | Collector alloy, PCB support, component contact layout, clamp force and source-to-collector resistance are not selected. No screw torque or direct unsupported PCB clamp is released. |
| CT-05 | Shade | Custom375×275×1.5mm opaque roof,75mm above the enclosure,50mm X overhang and open ventilation allocation. | Finish, direct/diffuse exposure, shade-to-box radiation/convection and wind behavior are unknown. A roof is not proof of zero solar heat. |

Original primary files are archived under `hardware/candidates/passive-v2/sources/`; `thermal-sources.json` records exact facts, caveats and unverified availability/prices. No supplier contact or quote exists. Converted inch dimensions do not tighten a manufacturer's manufacturing tolerance.

## Reproduce

```sh
PYTHONDONTWRITEBYTECODE=1 python3 hardware/candidates/passive-v2/thermal/model.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -p test_candidate_v2_thermal.py -v
```

`--output NEW_FILE` writes deterministic JSON and refuses an existing destination. The stored result is `hardware/candidates/passive-v2/thermal/results.json`. Inputs bind the candidate interface/source registry and the preserved1.1 electrical evidence hash.

## Network and sensitivity, not an invented enclosure Rtheta

Every case retains35°C ambient,21.857142857W enclosed heat,48W potential absorbed-sun budget and the vendor Pi50°C ambient limit. The model separates common wall temperature, collector temperature and local-air approximation:

```text
Acontact = 200mm ×70mm =0.014m²
R_TIM_each = vendor_Zarea ×(0.0254m/in)² / effective_contact_area
R_wall = source_base_thickness / (case_k ×effective_contact_area)
R_collector = design_collector_thickness / (case_k ×effective_contact_area)
R_common = source_sink_reference ×case_multiplier + R_TIM_external + R_wall
T_wall = T_ambient +(Q_enclosed +48W ×residual_solar_fraction) ×R_common
T_collector = T_wall +capture_fraction ×Q_enclosed ×(R_TIM_internal +R_collector)
T_air = T_wall +(1−capture_fraction) ×Q_enclosed / (case_h ×optimistic_internal_wall_area)
```

Quoted pad impedance already contains material/test-fixture interfaces; adding `thickness/k` again would double-count it. The internal exchange area0.142547m² comes from the source inside rectangular dimensions and is optimistic because taper, obstructions and actual flow are not resolved. Package contact resistance, lateral spreading, collector-to-air feedback, nonlinear behavior and installed sink conditions remain missing terms.

The26 cases vary only explicitly labeled sensitivities: source tabulated clamp pressure; illustrative material conductivity70/120/200W/mK; internal coefficient2/5/10W/m²K; sink multiplier1/1.5/2; effective contact area1/0.5; solar residual0/0.25/0.5/1; and heat capture0/0.5/0.9/1. These ranges are **not vendor-guaranteed bounds**. Actual installed values remain null. Zero sun/full capture are mathematical limits only.

| ID | Calculated case | Result | Meaning |
|---|---|---|---|
| TS-01 | Full48W residual solar, no capture,10psi reference,70W/mK material,5W/m²K internal coefficient, catalog sink reference | Common wall73.068°C; lumped air103.735°C. | Fails the conditional air inequality; extrapolated linear temperatures are not predicted physical measurements. |
| TS-02 | Ideal all heat collected and zero residual sun,50psi table point,200W/mK material | Wall/air46.401°C; collector46.901°C. | An optimistic limit, not an adopted operating case or local-air/junction qualification. |
| TS-03 |90% capture with zero residual solar under the10psi/70W/mK/5W/m²K sensitivity | Air49.978°C; required capture about89.93%. | Almost no nominal margin, before uncertainty. Neither90% capture nor zero sun has evidence. |
| TS-04 | Same90% capture, but25% of the48W exposure remains | Air56.517°C; required capture exceeds100%. | This combination cannot meet the inequality even by assuming more capture. |

At the nominal0.014m² area, even the10psi datum implies about965N clamp force per interface;50psi implies4826N. These are `pressure×area` calculations, **not allowable forces or an instruction to apply them**. Thin cast-wall and PCB loading need an independent mechanical design, actual effective area and controlled testing.

Roof geometry also prevents an unsupported complete-shadow claim. In a centered XZ section, the75mm gap/50mm overhang needs solar elevation above56.31° to cover the corresponding top edge and above78.69° to cover the enclosure's bottom edge. These are section geometry checks, not a full solar model. Applying the old800W/m² and0.5 absorptivity assumptions to the new roof area gives41.25W absorbed at the roof, but the model does not use that to replace/reduce the48W comparison budget or guess heat transfer to the box.

## Exact gates

The candidate has real editable thermal-path geometry and named source components, not a selected installed thermal rating. A qualified reviewer must resolve source-package contacts/support, enclosure alloy/flatness, clamp force/effective area, wall spreading, installed sink conditions, heat-capture fraction and shade coupling. Then verify local air, package/junction and all component limits at the frozen heat/exposure with calibration and uncertainty. `Measured local ambient + expanded uncertainty <= applicable vendor limit` is a test acceptance requirement, not evidence that a test occurred.

No thermal test, clamp loading, cutting, drilling, live power, fabrication or field operation is authorized or performed. The exact source/measurement gaps keep thermal acceptance UNKNOWN even when an idealized conditional calculation prints `true`.
