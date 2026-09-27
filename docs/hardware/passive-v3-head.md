# Poseidon passive-v3 underwater-head candidate

Configuration `passive-v3`, revision `HW-CAND-3.0`, status `NON_ADOPTED_NOT_BUILD_AUTHORIZED`. **Intrface is the company; Poseidon is the project/product.** Stable `INTRFACE_PASSIVE_V3` node names are CAD identifiers, not marketing copy. The required envelope is **30 m depth and 90 days continuous immersion**. Neither number is a verified assembly rating. There has been no purchase, fabrication, vendor contact, physical test, acoustic operation or adoption.

this is a non-adopted digital candidate with no pressure, corrosion or suitability evidence.

## D1. Receive-only arrangement and the preamp conflict

The Aquarian AS-1 class hydrophone sits outside the enclosure on a nonmetal stand-off. Its distributor publishes a 200 m component rating, 12 mm diameter, 40 mm length and 8 g mass without cable. These are not ratings or measurements of this assembly. The ASF-2 MKII is not selected; its 10 m limit does not meet the target.

**PA4/PA6 phantom preamp, analog conditioner and DAQ remain above water in the dry hub.** The packet's reference to an underwater preamp board conflicts with that architecture. This candidate resolves the conflict by leaving a clearly named **EMPTY 40 × 40 × 40 mm local allocation**, not a board. Actual preamp dimensions remain `null`; no analog conditioner was relocated. The reserve is excluded from physical mass, displacement and physical-pair interference.

The budget camera is the Blue Robotics Low-Light HD USB board behind the **BR-107201 polycarbonate dome and aluminium retaining ring**. The original proxy models the board mounting pattern and optics clearance, not the supplier's internal design. Camera mass and internal composition remain unknown.

The AS-1's standard **9 m cable cannot reach a 30 m head**. The distributor's statement that the PA4 can drive 30 m of cable applies after the preamp and does not establish the unamplified wet-side run. No extender, conversion board, underwater conditioner or 30 m USB link was invented. Both analog transport and camera power/data transport remain unresolved. The two external cable sweeps show short head-side routes toward the surface, not a validated communications link.

## D2. Geometry and source authority

CAD uses millimetres, with optical forward along +Z, the concept surface route toward +Y and the AS-1 on +X. The tube aft rim is Z=0. `cad/v3_proxy.py` creates original parametric fit models for purchased parts from the traced dimensions; custom mounts and routes remain separately constructed. No supplier STEP is imported during ordinary generation.

| ID | Part and dimensions used | Source and limit |
|---|---|---|
| S1 | Blue Robotics BR-106279-300 RevB, 300 mm aluminium 6061-T6 tube; nominal OD 112 mm and ID 103 mm | WTE Rev C.5 PDF p1 and a private, hash-registered supplier STEP. The original proxy is hollow with locally relieved flange seating bores; no supplier pressure rating is inherited. |
| S2 | Two 4-inch flanges; OD 114.3 mm, piston Ø103.91 mm, insertion 19.1 mm, total 27 mm | WTE PDF p1. The BR-100665 download contains **BR-101040 RevC**: identity mismatch remains open. The current PDF says 103.91 mm, not the 103.95 mm web-summary value. |
| S3 | Aft aluminium cap, five 10.2 mm through-holes, nominal 10 mm thickness and 108 mm closure-screw circle | WTE PDF p2; the traced supplier CAD bore centers guide five open proxy holes. Four remain unplugged. The original proxy omits lifting ears and has a maximum X envelope 6 mm smaller than the supplier STEP. |
| S4 | BR-107201 dome: internal radius 44 mm and nominal wall 5.8 ±0.1 mm | WTE PDF p2. The original hollow spherical fit proxy has a measured-size retaining lip. Hardened **polycarbonate** and aluminium ring remain bought parts, not fabrication instructions or an assembled depth rating. |
| S5 | Camera PCB 32 × 32 mm, 28 mm mounting pitch, Ø2.44 mm holes, 1.6 mm board, 23.35 mm front and 6 mm rear depth | Source drawing and registered private STEP, used only as dimensional evidence. Proxy optics and PCB do not claim lens or electronics internals. |
| S6 | AS-1 outer envelope Ø12 × 40 mm; 4.5 mm polyurethane cable | Distributor-published dimensions and source URL in the register; no page capture is redistributed. |
| S7 | WetLink M10, 7.5 mm seal-family source revision; current Fathom candidate BR-100875-175 HC | Current PDF states 18 mm overall OD, but registered historical STEP measures 16 mm transverse. The original proxy uses the latter fit envelope; revision, nut, seal compression and termination stay unresolved. |
| S8 | Cobalt **COB-1160**, 6-pin dry-mate bulkhead option; M10 × 1.5 thread and 16 mm hex | Source URL and extracted facts are retained. This is an **unpopulated option**; body length, diameter and mass remain `null`. |
| S9 | PEEK stand-off, clamp/jaw, sleeves, tray and strain relief; nominal 316 pull pins; lanyard/route geometry | `sources/design-inputs.json`, dated 2026-09-09. These are local design allocations, not vendor dimensions, surveyed farm interfaces, manufacturing tolerances or material-suitability claims. |

Each numerical input in `sources/dimension-traces.json` retains its value, units, supplier URL, original SHA-256, retrieval date, locator and evidence class. `source-register.json` holds the historical provenance and part-number references; `hardware/vendor-sources.json` lists retrievable binary originals. Supplier captures, page text and PDF extracts are not distributed. `make fetch-vendor-sources` places verified copies in the ignored private cache.

The camera plus mounting depth (29.35 +17 mm), 100 mm service route allocation, 40 mm EMPTY reserve, two 19.1 mm flange insertions and 10 mm clearance total **234.55 mm**. A 200 mm tube fails that allocation budget by 34.55 mm. The selected 300 mm vendor tube leaves **65.45 mm**, making it the shortest listed length that fits this allocation. This arithmetic does not establish actual service access or complete harness fit.

## D3. Mount, isolation and incomplete closure

The AS-1 stand-off provides 33 mm nominal clearance from tube skin to sensor skin. A PEEK collar and arm support the source-sized sensor envelope; no metal bracket contacts the hydrophone. Mount self-noise, cable rubbing and acoustic effects are untested.

The farm fixture has a fixed jaw/saddle, separate moving jaw, two pull-ring pin concepts and PEEK isolation sleeves. The 25 mm line opening is a **local allocation**, not a measured longline. The intended release is to withdraw the two pins and lift the jaw; detents, captive-pin retention, one-handed gloved use and accidental release remain unproved. The lanyard lug and short unterminated lanyard route reserve lost-equipment prevention; there is no claimed knot, splice, rated connector or retention strength.

Both 316 pin geometries remain separated from the aluminium by PEEK and spatial clearance. This is a geometric noncontact check, not evidence that wet electrical isolation survives wear, salt, coating damage or creep. The R5/R6 corrosion table supplies the concern: conductive seawater aggravates aluminium/stainless coupling, and PEEK can absorb seawater. No POM/GRP seawater claim, copper anti-fouling ring or new coating is introduced.

The tether strain relief follows the source-sized 7.6 mm Fathom jacket with a swept clearance and a provisional 50 mm bend. The analog cable also has a 50 mm route bend. These are geometric allowances, not validated minimum bend radii or pull ratings. The WLP PDF now names Fathom BR-100987 with BR-100875-175 as a tested combination; that does not validate this exact public CAD revision, termination, long cable, power or protocol. Its axial-strain test figures are not a published allowable design pull load for this head.

The unresolved-interface record keeps `vendor_camera_internal_fit` and `vendor_wetlink_internal_fit` at `null`. The original envelopes cannot establish supplier internal-fit geometry.

**The pressure boundary is incomplete and not sealed.** Four cap holes remain open. Tube/flange O-rings, locking cords, closure screws with reviewed isolation/engagement, plugs, PRV and the final WetLink nut/compression/stripped-core termination are absent. The penetrator placement leaves an uncompressed seal gap rather than treating an elastomer collision as an accepted fit. This CAD does not release pressure parts or a closure procedure. No STL or 3MF fabrication exports are produced.

## D4. Mass, displacement and buoyancy boundary

`cad/generated/passive-v3/mass-displacement.json` gives every physical part's actual BRep volume, assumed density or source-mass contribution, and separate exterior displacement contribution. The assumptions are aluminium 2700 kg/m³, 7075 reference 2810, 316 stainless 8000, PEEK 1300, polycarbonate 1200, polyurethane 1200 and polyester 1380. Assumed seawater is 1025 kg/m³. The Fathom stub uses 1025 kg/m³ **effective bulk density** to represent the vendor's neutral-buoyancy description, not solid polyurethane. The AS-1 uses its distributor's 8 g body and 28 g/m cable figures.

Camera and WetLink exact mass remain unknown. Missing seals, closures, complete transports, hub, farm rope, fouling and ingress are omitted, not assigned zero as a real-unit estimate. The source tube's 1.066 kg nominal mass differs from the 1.188 kg geometric shell/density estimate; neither is a measured installed mass. Dome and ring source mass is **160 g combined**, not 160 g each.

The conditional sealed exterior is **not** the hollow aluminium/polycarbonate material volume. The calculation fills source-sized tube, flange and nominal-cap exteriors and closes the exact dome with a source-inner-sphere fill. It omits cap lifting ears and approximates small chamfers/slots. The exterior must pass BRep validity, one-solid and volume-retention checks. Flooded mount regions and external cable stubs contribute only their physical solid volumes outside that exterior, never their bounding boxes. Internal camera/tray and EMPTY reserves add no sealed displacement.

The nominal closed-envelope case produces a **positive modeled buoyancy sign** against the known/assumed mass subtotal. That is conditional on a future sealed boundary and missing mass; **actual unit buoyancy remains `null`**. The present open boundary cannot be treated as buoyant, watertight equipment. The generated record carries the exact subtotal and displacement numbers for its source revision.

## D5. Digital checks and reproducibility

Use the existing geometry interpreter read-only. Choose a fresh system-temp output for each run; the generator refuses nonempty or symlink outputs and preserves failed attempts.

```sh
OUT="$(mktemp -d /tmp/intrface-passive-v3.XXXXXX)"
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python \
  hardware/candidates/passive-v3/cad/generate.py --output "$OUT/cad"
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python \
  hardware/candidates/passive-v3/cad/check.py "$OUT/cad" --geometry
PYTHONDONTWRITEBYTECODE=1 python3 \
  hardware/candidates/passive-v3/cad/check.py "$OUT/cad"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v
```

The generator and `--geometry` mode execute OCP `BRepCheck_Analyzer`, Boolean intersections for **every positioned pair among 25 physical parts**, proxy-envelope comparisons against recorded supplier dimensions, analytic surface checks, route radii, EMPTY-reserve clearance, isolation and STEP roundtrips. `make check-vendor-fit` separately imports private cached supplier STEP files, verifies their hashes and reports XYZ envelope deltas. These checks are digital clearances, not supplier-internal fit or pressure evidence.

STEP roundtrip acceptance keeps BRep validity, solid counts and a 0.0001 mm bbox limit. The volume limit is the larger of 0.001 mm³ or 1 ppm of original volume. Seven DXF sheets show three orthographic views and dimensions. The original proxy STEP files are not supplier BReps or manufacturing models.

The stdlib command audits hashes, trace bindings, artifact completeness, archived check coverage, mass arithmetic and actual GLB binary positions. **It does not execute CadQuery/OCP or import STEP.** Kernel tests use the existing interpreter in an explicit bounded subprocess. Tests write only to system temp and restore write permissions on copied fixtures, so the source tree may be read-only.

`baseline-lock.json` freezes named reference/v2 geometry and research inputs; supplier captures are absent. The v3 manifest separately binds construction code, interface and source-trace metadata. Rebinding changed research inputs requires an explicit lock update.

## D6. Canonical GLB contract for B2

Canonical location: `hardware/candidates/passive-v3/cad/generated/passive-v3/INTRFACE_PASSIVE_V3.glb`. Its sibling `hierarchy.json` lists stable part names, group nodes, physical/EMPTY membership and the final GLB hash.

The root is `INTRFACE_PASSIVE_V3`, with groups `PRESSURE_BOUNDARY`, `CAMERA_AND_INTERNAL_MOUNT`, `PASSIVE_RECEIVE`, `FARM_CLAMP`, `SURFACE_ROUTE_CONCEPT` and `EMPTY_RESERVES_NOT_HARDWARE`. Geometry comes from **`cq.Assembly.save(exportType="GLTF")`**, with bounded 0.3 mm chordal and 0.35 rad angular tessellation. STEP remains exact.

The pinned exporter rotates CAD Z-up to glTF Y-up but emits millimetre vertex coordinates. The export therefore adds an explicit root scale **[0.001, 0.001, 0.001]**, plus provenance/material/physical-membership extras. World coordinates are **CAD (x,y,z) mm → glTF (x,z,−y)/1000 m**. The checker reads binary POSITION accessors, traverses root/child transforms and compares every named part's transformed world bounds to CAD. Do not apply a second mm-to-m scale in Blender. CAD optical +Z becomes glTF +Y; the concept surface route +Y becomes glTF −Z.

The three EMPTY nodes stay nonphysical, the preamp stays dry, and no active projector or pressure rating is claimed. The assembly and exports are original fit models licensed under CERN-OHL-S-2.0; supplier CAD rights remain unverified, so supplier files are fetched into a private cache and never redistributed. The downstream showcase and web assets have separate publication review.

## G1. Fourteen physical gates, all unperformed

No row below authorizes physical work. Each requires separate authorization, a specimen/configuration freeze, qualified owner, acceptance criteria set before testing, calibrated equipment where needed, raw records, uncertainty and independent review.

| Gate | Required work and evidence | Owner to assign | Status |
|---|---|---|---|
| G01 | Inspect exact delivered vendor identities, revisions, tube/cap/flange/dome/WetLink dimensions; resolve CAD/PDF and mass conflicts | Mechanical reviewer | not_performed |
| G02 | Review and inspect seal stack, plugs, PRV, locking cords, closure screws, engagement, isolation and assembly/service method | Pressure-boundary specialist | not_performed |
| G03 | Authorized leak/vacuum and target-depth pressure/cycle protocol on the frozen complete specimen | Qualified pressure-test facility | not_performed |
| G04 | Establish continuous 90-day immersion and temperature/pressure-cycle performance, without borrowing a component rating | Marine validation owner | not_performed |
| G05 | Verify galvanic isolation, anodising damage tolerance, crevice/pitting and electrical separation after salt/wear exposure | Corrosion/materials reviewer | not_performed |
| G06 | Measure PEEK water uptake, creep, fatigue and mount load capacity for actual material/process | Mechanical/materials reviewer | not_performed |
| G07 | Establish cable-pull limits, strain-relief transfer, bend/abrasion life and exact cable/seal/connector terminations | Cable/mechanical reviewer | not_performed |
| G08 | Verify actual 30 m analog and USB/data/power path, voltage drop, noise and long-run capture; preamp stays dry unless separately redesigned | Electrical/acquisition reviewer | not_performed |
| G09 | Calibrate the receive chain and measure mount/cable self-noise and passive acoustic performance | Underwater-acoustics specialist | not_performed |
| G10 | Measure camera alignment, dome refraction/aberration, field of view and low-light imaging | Optical/camera reviewer | not_performed |
| G11 | Measure local window/hydrophone/housing fouling and cleaning/coating effects; derive a service interval | Authorized local validation owner | not_performed |
| G12 | Measure complete unit dry mass, CG, actual displaced volume, buoyancy and flooding response | Mechanical/marine reviewer | not_performed |
| G13 | Survey farm line/raft, storm/current loads and added drag; test gloved diver release, accidental release and lanyard retention | Farm operator with marine/diver safety reviewer | not_performed |
| G14 | Agree and validate dry service, retrieval, owner marking, loss reporting and permissions; obtain independent suitability review | Product owner and competent reviewers/authorities | not_performed |
