# Surface-v3: flat surface-unit study

This candidate replaces the tall-frame arrangement only within its own digital study. It does not change the frozen passive-v2 design, passive-v3 head, hardware adoption, purchasing authority or physical operating limits.

this is a non-adopted digital candidate with no pressure, corrosion or suitability evidence.

## Run D artifact catalog

HW-11 and HW-12 are recorded here and in `HARDWARE.md`; changes to the catalog rebind the frozen passive-v2 locks.

| ID | Path | Content |
|---|---|---|
| HW-11 | [Surface-v3 candidate](../../hardware/candidates/surface-v3/) | Flat two-panel tray and hub study with pole and float variants, source records, editable CadQuery, STEP/DXF/GLB, mass assumptions and digital checks. |
| HW-12 | [V4 scene manifest](../../hardware/showcase/scene-manifest-v4.json), [hero GLB](../../hardware/showcase/hero.glb) and [head GLB](../../hardware/showcase/head.glb) | Showcase v4 scenes and renders built from the vendor-free CAD exports; replaces the v3 scenes, which used supplier geometry. |

Both entries describe non-adopted digital candidates, not build or public-release authorization.

## Sources

All files already existed in the repository. No download, supplier contact, purchase, physical test or active-output operation occurred. The candidate's [source register](../../hardware/candidates/surface-v3/sources/source-register.json) records each repository path, SHA-256 and locator.

| Ref | Existing record | Used here | Boundary |
|---|---|---|---|
| S1 | `hardware/candidates/passive-v2/interface.json`, `cad/parameters.json`, `cad/model.py`; existing `hardware/cad/sources/Datasheet-BlueSolar-Monocrystalline-Panels-EN.pdf`, page 1 SPM040401200 row | Two Victron SPM040401200 envelopes, each 668 × 425 × 25 mm; 3.1 kg nominal per panel | No inferred frame section, clamp zones, cell detail, junction-box position, cable termination or stock availability |
| S2 | `hardware/candidates/passive-v2/sources/thermal-sources.json` and `Hammond-1550WJ.pdf`, page 1 | Hammond 1550WJ overall 275 × 175 × 66.6 mm; laid flat instead of the v2 vertical orientation | Simplified envelope only. Taper, bosses, lips, gasket and supplied revision remain source-owned. Actual enclosure mass unknown; drawing-family/gasket caveat retained |
| S3 | Same v2 register and `Wakefield-Thermal-Extrusions-2025.pdf`, PDF page 21 / printed page 17 | Wakefield 125460 / XX4559 occupancy 273.812 × 95.758 × 76.2 mm, profile base reference 15.748 mm | The 76.2 mm cut is a candidate use of the source's 3-inch reference, not supplied cut stock. Fin count, pitch and taper are unknown. No fin solids, solid-metal mass or installed resistance inferred |
| S4 | V2 shade and cable records; `Henkel-SIL-PAD-TSP-1600.pdf` | Custom 375 × 275 × 1.5 mm shade, 75 mm hub gap; 50 mm outlet-air allocation; inherited 8 mm cable and 56 mm bend assumptions; nominal 0.127 mm separation at sink/hub | Shade/cable sizes remain design allocations even though their v2 records are hashed. The nominal TIM separation is space, not a selected thermal joint or interface resistance |
| S5 | `research/literature/R5R6-marine-mechanical-power-2026-09-09.md`, site and mooring tables; accompanying source register | Context for farm attachment, marker/retrieval requirements and open site-load questions | Published June currents and inlet dimensions are not a storm case, farm survey, operating limit or anchor design |

The 6.4 m water depth comes from the existing illustrative site scene, not bathymetry in S5. It remains an explicit local assumption. The frozen baseline deliberately excludes mutable showcase files, `HARDWARE.md`, root reports and v2 catalog bindings so later scene/catalog work does not change the source geometry lock.

## Geometry

All geometry and placements derive from the 66 traced inputs in [interface.json](../../hardware/candidates/surface-v3/interface.json). Millimetres are CAD units. The water surface is world Z=0; positive Z points up.

| Ref | Default geometry | Basis |
|---|---|---|
| D1 | Panels side by side, centres Y=-237.5 and +237.5 mm; exact 50 mm gap | S1 dimensions; inherited v2 gap assumption |
| D2 | Both panels tilt 4 degrees along X, within the requested 3–5 degree range; low underside 8 mm above tray top | Drainage assumption, not solar yield or runoff evidence. Two 640 × 22 mm wedge rails per panel touch its inclined underside |
| D3 | Tray 720 × 940 × 4 mm; open-bottom skirt 700 × 920 mm outer plan, 2 mm wall and 180 mm drop | Custom plate/sheet assumptions. Common surface height is about 263.537 mm, including panel tilt, rather than a post tower |
| D4 | Hub laid flat at X=0, Y=-220 mm, underside 151.1 mm below the tray underside | S2 overall dimensions. Shelf with two outboard hangers supports the hub and clears the socket and shade |
| D5 | Shade roof top 8 mm below tray underside; roof underside 75 mm above hub top | S4 geometry carried over, but its environment and heat path changed. Two candidate hanger tabs touch the tray |
| D6 | Sink occupancy beside the hub toward -Y, extrusion allocation vertical; 50 mm outlet-air space above it | S3 and S4. The placement clears solid parts but does not connect a qualified thermal path to the flat enclosure |
| D7 | Central 62 mm bore socket for a 60 mm pole; 84 mm tube OD, 120 mm length, 140 × 6 mm flange; two 11 mm transverse clearance bores at 30 and 85 mm below tray | Custom assumptions. Two 10 mm cross-bolt spaces remain nonphysical; no threads, heads, torque, grade or locking method selected |
| D8 | Two 8 mm vertical cable-route stubs at X=230 mm and the two panel centres, through 10 mm tray clearances | Nonphysical route allocations, not junction boxes, glands or a full harness. The inherited 56 mm bend allowance remains an open end-routing constraint |
| D9 | Pole 60 mm OD, 3 mm assumed wall, 6900 mm long; footing plate 500 × 500 × 12 mm | Length defaults to 6400 mm site depth plus 500 mm freeboard. Plate top and pole bottom meet at Z=-6400 mm. Pole is hollow and unsealed; no sealed-tube buoyancy credit |
| D10 | Closed-cell foam collar outer 1060 × 1280 mm, inner 700 × 920 mm, height 300 mm | Assumed construction. The skirt fits the opening without common volume; the tray overlaps its upper bearing face by 10 mm on each side. Face contact is not a manufacturing clearance or bearing-strength result |

The pole and float are mutually exclusive installed variants. The float variant moves the whole common surface, including hub, socket and allocations, to its own conditional waterline; it does not retain the seabed pole or footing. No battery, BMS, charger, regulator, protection assembly or new power part is modeled. Omitted power integration remains a gate, not an inferred fit inside the small hub.

The carrier, roof tabs, panel wedges, tray, skirt and socket describe candidate geometry only. The model does not release welds, bolts, tolerances, isolation details or uplift restraint. Cable stubs are unconnected. Service access and safe disassembly remain unresolved.

## Mass and displacement

[Mass-displacement evidence](../../hardware/candidates/surface-v3/cad/generated/surface-v3/mass-displacement.json) separates physical construction from space allocations. The solid hub and panel envelopes are **not** multiplied by aluminum density. Panel mass uses the source's 3.1 kg nominal value. Actual hub and sink masses remain unknown.

| Ref | Input or result | Meaning |
|---|---|---|
| M1 | Custom aluminum 2700 kg/m³; pole/footing steel 8000 kg/m³ | Assumed densities multiplied only by the custom material BRep volumes; no alloy certificate or measured mass |
| M2 | Closed-cell foam 60 kg/m³; seawater 1025 kg/m³ | Explicit dry bulk-density and water-density assumptions; no foam product, water-uptake or site measurement |
| M3 | Common known-plus-assumed subtotal 23.393334 kg | Includes source panel nominal masses and custom material estimates; excludes actual hub/sink and unmodeled items |
| M4 | Pole-variant known-plus-assumed subtotal 77.038284 kg | Common subtotal plus hollow pole and plate. **Not complete assembled mass** |
| M5 | Collar material volume / fully submerged displacement 0.213840 m³; collar dry mass 12.830400 kg | Only the foam collar receives displacement credit. Open skirt, flooded pole and vendor envelopes do not create sealed-air buoyancy |
| M6 | Float scenario mass 42.223734 kg | Common subtotal + collar + assumed hub 1.2 kg + assumed sink 1.8 kg + 3 kg unmodeled-payload contingency. These allowances are not vendor masses or proof that omitted battery/power integration fits |
| M7 | Full-submergence supported mass 219.186 kg; conditional net lift +176.962266 kg equivalent, about +1735.407 N | **Positive under this scenario only**. This is collar capacity arithmetic, not a stability, load or wave result |
| M8 | Scenario waterplane area 0.7128 m²; displacement at posed waterline 0.041193887 m³; conditional equilibrium draft 0.057791648 m | The scene waterline is constructed from M6. Net lift at that assumed equilibrium is zero by arithmetic, not measured balance |
| M9 | Float tray-underside height 0.242208352 m above water | Collar height minus scenario draft; move the common surface here for the float pose. Hub underside remains about 0.091108352 m above the assumed calm waterline |

Actual complete mass and actual buoyancy sign are **unknown**. Missing fasteners, wiring, glands, electronics, battery/power integration, mooring, water uptake and fouling can change the result. No centre-of-gravity, metacentric height, stability, reserve-freeboard or wave-response claim follows from a positive full-submergence arithmetic sign.

## Reopened thermal question

The hub now sits directly under the panels and tray instead of in the prior post-frame shade arrangement. It lies flat, and the sink occupancy sits beside it rather than representing a released rear-base thermal connection. The skirt changes airflow. Shade geometry, outlet clearance and the retained nominal TIM separation do not establish heat transfer.

The **v2 48 W absorbed-sun and 21.9 W enclosed-heat budgets are not re-evaluated here**. No favorable solar fraction, convection coefficient, heat-capture fraction, source-to-collector resistance or installed sink resistance is selected. The source's 0.5 K/W 3-inch natural-convection reference does not become an installed result. Fin details, component thermal pickup, contact pressure, radiation/coupling and service ventilation remain open.

## Digital checks and source handoff

The generator exports 17 physical/reference part STEP files, six allocation STEP files, separate physical pole and float assemblies, 25 DXF sheets with three dimensioned views each, and a named source GLB. STEP is the BRep record; DXF curves and GLB surfaces are display approximations, not manufacturing authority.

The checker independently binds source hashes and dimension traces, imports every STEP and DXF when run with `--geometry`, checks valid closed solids and contacts, and checks every co-installed pair for common volume. It does not combine mutually exclusive mounts into a physical collision test. It also includes the allocation spaces in clearance checks, without counting them as material or displacement. Binary GLB vertices, indices, transforms, bounds and enclosed mesh volume are checked rather than trusting accessor labels or a stored PASS flag. Kernel checks compare binary mesh vertices and triangle centroids with regenerated BRep surfaces.

`SURFACE_V3.glb` uses glTF metres and +Y up. The coordinate map is CAD `(x,y,z) mm` to glTF `(x,z,-y)/1000 m`. CadQuery's raw millimetre output is measured before adding one 0.001 root scale. Blender must not apply a second unit correction or resize parts.

The source groups are `surface(tray, hub, panelA, panelB, mastSocket)`, `mountPole`, `mountFloat`. Every visible `SV3_*` part binds to its STEP hash, source BRep bounds and source-to-CAD matrix in `hierarchy.json`. Common parts use the pole-world pose in per-part STEP and world bbox records; the source-local bounds and matrices remove ambiguity for downstream grouping. `surface` is rooted at the tray underside: glTF world Y=0.5 m in pole mode, or `mountFloat.extras.floatSurfaceY` in float mode. The source collar already sits at its own waterline. `mountFloat.extras.defaultHidden` is true, and the root extras retain `seabedTopY` and `trayTopY`.

The source GLB includes both mount variants for downstream visibility handling. It is not the final animated website asset. D2/D3 owns scene production and contract-v3 website validation, not this package.

## Remaining gates

- G1 — Confirm supplied panel/hub revisions, permitted panel attachments, actual purchased masses and component dimensions. Vendor source drawings do not qualify modified parts.
- G2 — Resolve battery/power integration, protection, wiring, glands and complete electronics packaging. The present model omits them.
- G3 — Re-evaluate the changed hub thermal path and solar/ventilation environment against the retained budgets.
- G4 — Size pole bending/buckling, flange and cross-bolt joints, panel uplift, hanger/plate loads and wind fatigue. Detail corrosion isolation and coatings. No structural acceptance is claimed.
- G5 — Survey the seabed and engineer pole embedment, footing/anchor holding capacity and recoverability. The CAD models no embedment or anchor. A plate at the seabed is not evidence that a 6.9 m pole can stand there.
- G6 — Establish wind, waves, storm current, mooring load, gear movement and a clear footing/retrieval zone with the farmer. R5R6 gives no site-specific wave height or storm-load case; attachment to an existing longline adds load to someone else's structure.
- G7 — Measure complete mass, displacement, centre of gravity, foam water uptake and buoyancy. Review stability, freeboard and wave response independently.
- G8 — Resolve cable pull/bend/abrasion, terminations, service access, splash ingress, corrosion and fouling. A clear CAD space is not a connector or seal qualification.
- G9 — Agree farm and authority permissions, marking, loss reporting, retrieval and vendor-derived asset redistribution rights before deployment or public release. No request, upload or authorization is implied by these files.
