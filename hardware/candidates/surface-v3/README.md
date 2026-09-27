# Surface-v3 candidate

Two sourced solar-panel envelopes on a shallow tilted tray, with a flat hub underneath and mutually exclusive pole and float mounts. This package does not adopt or replace passive-v2 or the passive-v3 head.

this is a non-adopted digital candidate with no pressure, corrosion or suitability evidence.

## Reproduce

Run from the repository root with the existing CadQuery 2.6.1 environment. No installation or download is needed. The generator requires a new or empty output directory and refuses symlinks and other repository output scopes. It fails if the kernel cannot construct a valid box.

```sh
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python \
  hardware/candidates/surface-v3/cad/generate.py --output /tmp/surface-v3-new
PYTHONDONTWRITEBYTECODE=1 python3 \
  hardware/candidates/surface-v3/cad/check.py /tmp/surface-v3-new
PYTHONDONTWRITEBYTECODE=1 hardware/cad/.venv/bin/python \
  hardware/candidates/surface-v3/cad/check.py /tmp/surface-v3-new --geometry
```

`--water-depth-m`, `--freeboard-m` and `--tilt-deg` expose the site-depth, pole-top and drainage assumptions. Defaults are 6.4 m, 0.5 m and 4 degrees. Pole length is depth plus freeboard, with no embedment modeled. `--interface` accepts a full traced candidate parameter record; used inputs are copied into each output as `interface-used.json`. Source-bound purchased dimensions cannot change through these options.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/assurance/run_unittest.py \
  -s tests/hardware -p test_candidate_surface_v3_cad.py
PYTHONDONTWRITEBYTECODE=1 make test-hardware
PYTHONDONTWRITEBYTECODE=1 make test-hardware-kernel
```

Ordinary tests use only the standard library. Live-kernel tests live under `tests/hardware/kernel`, which has no `__init__.py`. Missing kernels fail, never skip. Set `POSEIDON_CAD_PYTHON` to an existing kernel interpreter if needed; no test installs one. `TMPDIR` and optional `POSEIDON_SURFACE_V3_TEST_TMP` control test scratch space.

## Records and exports

`interface.json` traces 66 geometry, density, placement and export inputs to existing records or explicit assumptions. `sources/source-register.json` binds v2 records and supplier PDFs by original SHA-256 and private-cache path; no supplier file is required by the normal build. `baseline-lock.json` binds frozen geometry/research, not mutable showcase files.

The canonical package is `cad/generated/surface-v3/`:

- `step/` contains 17 physical/reference part STEP files and separate pole and float physical assemblies. Purchased envelopes represent parts, not solid-metal vendor internals. The two mount assemblies are never combined into one physical installation.
- `allocations/` contains six nonphysical STEP spaces: sink occupancy, its outlet-air clearance, two cable stubs and two cross-bolt allocations. No allocation contributes material mass or displaced volume.
- `drawings/` contains three dimensioned orthographic views per part/allocation and per installed assembly. Curves are sampled; STEP is the exact geometry record. These are not fabrication drawings.
- `SURFACE_V3.glb` has 23 stable part/allocation names and the contract groups. It carries both mounts for downstream visibility handling, not as co-installed hardware.
- `hierarchy.json` binds every visible mesh to source BRep bounds, transforms, parameter keys, part STEP hash and actual binary GLB bounds/volume. `manifest.json` hashes every artifact. `mass-displacement.json` separates vendor nominal masses, density assumptions, illustrative allowances and unknown actual totals.

`check.py` ignores saved PASS flags. It independently checks source and artifact hashes, complete inventories, traces, group mapping, binary GLB indices/transforms/bounds/volume and mass arithmetic. `--geometry` rebuilds the candidate, imports each STEP and DXF, checks valid closed solids, contacts and co-installed common-volume interference, and tests binary mesh vertices and triangle centroids against the regenerated BRep.

Archived source bounds are computed from analytic BRep geometry with `BRepBndLib.AddOptimal_s(..., False, False)`, not `Shape.BoundingBox()`. The latter includes cached display tessellation tolerance: meshing `SV3_MAST_SOCKET` can inflate a 140 mm X/Y envelope by over 0.5 mm on the same machine. Tessellation caching varies between Linux and macOS, so it is not a valid source of archived CAD dimensions. The archive comparison remains strict; only the measurement source changed.


## D2/D3 coordinates

CAD uses millimetres with +Z up, X along panel length, and Y across the panel pair. World water is Z=0. CadQuery exports `(x,y,z) mm` as glTF `(x,z,-y)/1000 m`; the pinned exporter needs exactly one verified root scale of 0.001. A glTF loader imports metres already. Do not normalize or resize in Blender.

The root is `SURFACE_V3`. Its children are `surface`, `mountPole`, `mountFloat`. `surface` has exactly `tray`, `hub`, `panelA`, `panelB`, `mastSocket`. Each group contains the stable `SV3_*` meshes listed in `hierarchy.json`. The surface node's local origin is the **tray underside**. In the default pole pose its world height is 0.5 m; tray top is 0.504 m. Pole bottom and footing top are -6.4 m. The plate extends another 0.012 m below that datum; it is not an anchor or embedment design.

`mountFloat.extras.defaultHidden` is true. `mountFloat.extras.floatSurfaceY` is about 0.242208352 m in the default mass scenario. For float mode, hide `mountPole`, show `mountFloat`, and set the **world height of the surface origin** to that value. The common surface translation delta from the pole pose is about -0.257791648 m. Preserve its children as a rigid group. The float collar is already at its own conditional waterline; do not apply that delta to the collar. If reparenting in Blender, preserve world transforms first and restore this tray-underside origin before using `floatSurfaceY`.

Per-part STEP and `source_geometry_bboxes_mm` use the default world pose, including the common +500 mm tray-underside placement. `source_local_bboxes_mm` and `source_to_cad_matrix_mm` describe each construction source and its rigid placement. `source_to_group_matrix_mm` gives placement before the common surface offset. Some custom shapes were constructed in their assembled local coordinates, so their source transforms are identity by design. No downloaded vendor BRep is claimed.

See [`docs/hardware/surface-v3.md`](../../../docs/hardware/surface-v3.md) for geometry, mass assumptions and the open thermal, power, structural, mooring and rights gates.
