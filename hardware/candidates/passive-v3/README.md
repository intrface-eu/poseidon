# Poseidon passive-v3 by Intrface

Intrface is the company; Poseidon is the project/product. Stable `INTRFACE_PASSIVE_V3` CAD IDs are identifiers, not a product-name claim.

Supplier CAD and datasheet redistribution rights remain unverified. All exported solids are original dimension-based fit proxies, not copies of supplier BReps or manufacturing models. Vendor sources are referenced by part number, URL, retrieval date and digest; fetch them into the ignored private cache only for optional comparison.

`HW-CAND-3.0` is a **non-adopted digital candidate, not build authorized**. Required targets are 30 m depth and 90 days immersion, not verified assembly ratings. No active emission hardware is populated.

this is a non-adopted digital candidate with no pressure, corrosion or suitability evidence.

| ID | Path | Content |
|---|---|---|
| V3-01 | `interface.json` | Receive-only physical contract, targets, null unknowns, source-bound dimensions and 14 unperformed gates |
| V3-02 | `sources/` | Source URL/hash/date register, measured dimension traces and explicit local allocations; no redistributed supplier captures |
| V3-03 | `cad/v3_proxy.py`, `cad/v3_model.py` | Original parameterized purchased-part fit proxies and custom mounts, sleeves, pins, tray and cable sweeps |
| V3-04 | `cad/generate.py`, `cad/check.py` | Fresh-output generator, stdlib evidence audit and explicit CadQuery/OCP runtime audit |
| V3-05 | `cad/generated/passive-v3/` | Canonical per-part and assembly STEP, separate EMPTY STEP, dimensioned DXF sheets, metre-scale GLB, hierarchy, mass/displacement and check manifest |
| V3-06 | `baseline-lock.json` | Named immutable baseline/research inputs; excludes B3's mutable catalog and v2 relock metadata |
| V3-07 | `../../../docs/hardware/passive-v3-head.md` | Source conflicts, geometry, mass limits, B2 handoff and physical gates |

The head uses a Blue Robotics 300 mm 4-inch aluminium tube, source flange/cap geometry and a **polycarbonate** BR-107201 dome. The camera is the Blue Robotics low-light USB board. The AS-1 class receive hydrophone stands outside on a nonmetal bracket. **PA4/PA6 preamp and analog conditioner stay above water**; the underwater preamp allocation is EMPTY, not a board. The AS-1 standard 9 m cable and an ordinary USB connection do not establish 30 m transport.

Four aft holes, missing closure/seal items and unresolved WetLink compression make the modeled pressure boundary incomplete. Vendor flange identity and WetLink CAD/PDF revisions conflict. Cobalt COB-1160 is a sourced **unpopulated option**, not an invented CAD connector. The longline clamp, 316 pull pins with PEEK sleeves, strain relief and lanyard route are local allocations with no strength, isolation, cable-pull or diver-release evidence.

## Reproduce without changing the CAD environment

From the repository root, reuse `hardware/cad/.venv/bin/python` read-only. Do not install, sync or reconfigure it. Every output must be new or empty; failed attempts remain intact.

```sh
OUT="$(mktemp -d /tmp/intrface-passive-v3.XXXXXX)"
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python \
  hardware/candidates/passive-v3/cad/generate.py --output "$OUT/cad"
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python \
  hardware/candidates/passive-v3/cad/check.py "$OUT/cad" --geometry

# Evidence audit only: this command does NOT execute a CAD kernel.
PYTHONDONTWRITEBYTECODE=1 python3 \
  hardware/candidates/passive-v3/cad/check.py "$OUT/cad"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests/hardware -v
```

The runtime checks every BRep and positioned part pair, traced dimensions, reserve clearances, routes and each STEP roundtrip. Proxy envelopes are compared against hash-verified supplier STEP only by the optional `make check-vendor-fit` target; the archived check never requires supplier files. Source identity conflicts, unknown internals and unknown camera/WetLink masses remain explicit.

## GLB handoff

Canonical file: `cad/generated/passive-v3/INTRFACE_PASSIVE_V3.glb`.

Stable root: `INTRFACE_PASSIVE_V3`. Sibling `hierarchy.json` lists 25 physical part nodes and three EMPTY nodes. The exporter calls `cq.Assembly.save(exportType="GLTF")`, uses 0.3 mm chordal /0.35 rad angular tessellation, then adds provenance extras and an explicit 0.001 root scale. CAD `(x,y,z)` mm becomes glTF `(x,z,-y)/1000` metres. Binary-position/world-bounds checks verify this; **do not scale a second time**. Analytic CAD bboxes explicitly ignore display triangulation, so meshing cannot change the recorded dimensions.

Preserve polycarbonate, supplier part-number references, dry-side preamp and EMPTY/nonphysical classifications. Proxy STEP geometry is separate from web tessellation.

The mass report separates nominal density/source contributions, unknown vendor mass, hollow-shell material volume, a **conditional sealed exterior** and flooded mount solids. Its positive modeled buoyancy sign is not an actual-unit prediction: the boundary is open and complete mass is unknown. All 14 physical gates remain unperformed.
