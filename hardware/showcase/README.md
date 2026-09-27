# Showcase scenes (v4)

3D scenes and press renders for the Poseidon Trident public page. They are design renders of a candidate that has not been built or tested.

## Files

| File | What it is |
| --- | --- |
| `hero.glb` | The surface unit on its pole at a Limski kanal mussel farm: three longlines with barrel buoys and mussel droppers, the listening head on its sensor line, seabed, nine gilthead seabream, a 5.2 m work boat for scale, and a water surface. Clips `descend` and `swim`. The float-collar mount is the `mountFloat` node, hidden by default. |
| `head.glb` | The listening head alone, with `explode` and `assemble` clips along the tube axis. |
| `scene-manifest-v4.json` | Node names, clips, bounds, triangle counts, byte sizes and sha256 for both GLBs, the frame convention, the decoder the page needs, sources and lineage. |
| `hero.blend`, `head.blend` | Uncompressed master scenes, saved with relative paths. |
| `renders-v4/` | Press renders: `hero-16x9.png` (1920x1080), `og-image.png` (1200x630, left third kept calm for a title), `farm-wide.png` (1920x1080), `unit-closeup.png` (1600x1600), `head-exploded.png` (1600x1200). |
| `textures/` | Solar-cell and seabream skin textures the hero build paints. |
| `build_head_v4.py`, `build_hero_v4.py`, `v4_lib.py` | Blender build scripts. |
| `render_v4.py` | Press render script. It builds the water volume, section face, sediment and studio set at render time; none of that is saved into the scenes or GLBs. |
| `package_v4.ts` | Compresses the GLBs and writes the manifest. |

Frame: metres, +Y up. In `hero.glb` the origin is the water surface on the pole axis. In `head.glb` it is the centre of the enclosure tube.

## Loading on the page

Both GLBs use Draco geometry compression (`KHR_draco_mesh_compression`). In three.js, give `GLTFLoader` a `DRACOLoader` pointed at a hosted copy of the Draco decoder. `hero.glb` also uses `EXT_texture_webp`; both use `KHR_materials_transmission` and `KHR_materials_ior` for the dome. `GLTFLoader` handles those without extra setup.

Hide `mountFloat` on load, or hide `mountPole` to show the float variant; each mount group carries its own tether. `waterSurface` carries `extras.role = "water"` so the page can swap in its own water.

## Rebuilding

Blender 5.2 LTS and bun are needed. From the repository root:

```sh
Blender -b --factory-startup --python hardware/showcase/build_head_v4.py
Blender -b --factory-startup --python hardware/showcase/build_hero_v4.py
bun hardware/showcase/package_v4.ts
```

The Blender steps write `head.blend`, `hero.blend`, `textures/` and the uncompressed `build/*.raw.glb`. The bun step writes `head.glb`, `hero.glb` and `scene-manifest-v4.json`.

Renders (open the matching scene; `--samples` and `--scale` are optional):

```sh
Blender -b hardware/showcase/hero.blend --python hardware/showcase/render_v4.py -- --shot hero
Blender -b hardware/showcase/hero.blend --python hardware/showcase/render_v4.py -- --shot og
Blender -b hardware/showcase/hero.blend --python hardware/showcase/render_v4.py -- --shot farm
Blender -b hardware/showcase/hero.blend --python hardware/showcase/render_v4.py -- --shot unit
Blender -b hardware/showcase/head.blend --python hardware/showcase/render_v4.py -- --shot head
```

The outdoor shots light with the Poly Haven HDRI `kloofendal_48d_partly_cloudy_puresky` (CC0). It is not stored here: download the 2k `.hdr` from polyhaven.com and pass it with `--hdri PATH` or the `POSEIDON_HDRI` variable. Without it the script falls back to a procedural sky. The script removes PNG text chunks, so the renders carry no file paths.

## Sources

Geometry comes only from the project's own CAD exports:

- `hardware/candidates/surface-v3/cad/generated/surface-v3/SURFACE_V3.glb`
- `hardware/candidates/passive-v3/cad/generated/passive-v3/INTRFACE_PASSIVE_V3.glb`

Space reservations in those exports (sink and cable allocations, cross-bolt allocations, the head's `EMPTY_*` envelopes) are left out. The farm, buoys, droppers, seabed, fish, boat and water are modelled by the build scripts. No third-party models are used.

These scenes replace run B (`unit`, `site`, `orada`) and the v3 scenes, which were built from vendor-derived geometry. Their files were removed; `scene-manifest-v4.json` lists them under `lineage`.

## Licence

Models, scenes and build scripts: CERN-OHL-S-2.0. Renders in `renders-v4/`: CC-BY-4.0.
