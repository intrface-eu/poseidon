// Compress the v4 showcase GLBs and write scene-manifest-v4.json.
//
// Run from the repo root after both Blender builds:
//   bun hardware/showcase/package_v4.ts
//
// Input:  hardware/showcase/build/{hero,head}.raw.glb (Blender exports, not tracked)
// Output: hardware/showcase/{hero,head}.glb and hardware/showcase/scene-manifest-v4.json
//
// Geometry goes through Draco (KHR_draco_mesh_compression). Draco keeps the node tree
// and node transforms exactly as exported, so node names, clips and morph targets stay
// valid. Textures were already written as WebP by the Blender exporter.

import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { Document, Node, NodeIO } from "@gltf-transform/core@4.5.0";
import { ALL_EXTENSIONS } from "@gltf-transform/extensions@4.5.0";
import { dedup, draco, getBounds, prune, resample } from "@gltf-transform/functions@4.5.0";
import draco3d from "draco3dgltf@1.5.7";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, "..", "..");
const rel = (p: string) => relative(REPO, p).split("\\").join("/");

const io = new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({
  "draco3d.decoder": await draco3d.createDecoderModule(),
  "draco3d.encoder": await draco3d.createEncoderModule(),
});

type Stats = {
  triangles: number;
  uniqueTriangles: number;
  meshes: number;
  nodes: number;
  materials: number;
  textures: number;
};

function stats(doc: Document): Stats {
  const root = doc.getRoot();
  const triOf = new Map<unknown, number>();
  for (const mesh of root.listMeshes()) {
    let t = 0;
    for (const prim of mesh.listPrimitives()) {
      const idx = prim.getIndices();
      const n = idx ? idx.getCount() : prim.getAttribute("POSITION")!.getCount();
      t += Math.floor(n / 3);
    }
    triOf.set(mesh, t);
  }
  let triangles = 0;
  const scene = root.getDefaultScene() ?? root.listScenes()[0];
  scene.traverse((node: Node) => {
    const mesh = node.getMesh();
    if (mesh) triangles += triOf.get(mesh) ?? 0;
  });
  return {
    triangles,
    uniqueTriangles: [...triOf.values()].reduce((a, b) => a + b, 0),
    meshes: root.listMeshes().length,
    nodes: root.listNodes().length,
    materials: root.listMaterials().length,
    textures: root.listTextures().length,
  };
}

const r4 = (v: number) => Math.round(v * 10000) / 10000;

function labelled(doc: Document) {
  const out: { name: string; parent: string | null; label: string; mesh: boolean }[] = [];
  for (const node of doc.getRoot().listNodes()) {
    const extras = node.getExtras() as Record<string, unknown>;
    if (typeof extras.label !== "string") continue;
    const parent = node.getParentNode();
    out.push({ name: node.getName(), parent: parent ? parent.getName() : null, label: extras.label, mesh: !!node.getMesh() });
  }
  return out;
}

function clips(doc: Document) {
  return doc.getRoot().listAnimations().map((anim) => {
    let duration = 0;
    for (const s of anim.listSamplers()) {
      const input = s.getInput();
      if (input) duration = Math.max(duration, input.getMax([0])[0]);
    }
    const channels = [...new Set(anim.listChannels().map((c) => `${c.getTargetNode()?.getName()}.${c.getTargetPath()}`))].sort();
    return { name: anim.getName(), durationSeconds: r4(duration), channels };
  });
}

async function pack(name: string) {
  const src = join(HERE, "build", `${name}.raw.glb`);
  const out = join(HERE, `${name}.glb`);
  const doc = await io.read(src);
  await doc.transform(
    dedup(),
    prune({ keepLeaves: true, keepExtras: true, keepAttributes: true }),
    resample(),
    draco({ method: "edgebreaker", encodeSpeed: 5, decodeSpeed: 5 }),
  );
  const s = stats(doc);
  const scene = doc.getRoot().getDefaultScene() ?? doc.getRoot().listScenes()[0];
  const b = getBounds(scene);
  const rootNode = scene.listChildren()[0];
  await io.write(out, doc);
  const bytes = readFileSync(out);
  // read back to prove the file decodes
  const check = await io.read(out);
  // Draco drops degenerate triangles, so report what the written file holds.
  const s2 = stats(check);
  if (s2.triangles < s.triangles * 0.98) throw new Error(`${name}: ${s.triangles - s2.triangles} triangles lost on read-back`);
  console.log(`${name}: ${s.triangles} triangles before encoding, ${s2.triangles} in the file`);
  return {
    file: rel(out),
    bytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    sourceRaw: rel(src),
    rawBytes: readFileSync(src).length,
    root: rootNode.getName(),
    rootExtras: rootNode.getExtras(),
    boundsMin: b.min.map(r4),
    boundsMax: b.max.map(r4),
    ...s2,
    extensionsUsed: check.getRoot().listExtensionsUsed().map((e) => e.extensionName).sort(),
    extensionsRequired: check.getRoot().listExtensionsRequired().map((e) => e.extensionName).sort(),
    clips: clips(check),
    namedNodes: labelled(check),
  };
}

const hero = await pack("hero");
const head = await pack("head");

const manifest = {
  schema: "poseidon.showcase.scene-manifest.v4",
  status: "Design renders of a non-adopted candidate. Nothing shown here has been built or tested.",
  frame: {
    units: "metres",
    upAxis: "+Y",
    origin: "hero.glb: the water surface at y = 0 on the pole axis (x = z = 0); depth is negative y. head.glb: the enclosure tube centre.",
    handedness: "glTF right-handed, +Y up; Blender authoring axes Z-up were converted by the exporter.",
  },
  decoder: {
    needed: "KHR_draco_mesh_compression",
    threejs: "GLTFLoader with DRACOLoader (setDecoderPath to a hosted copy of the three.js draco decoder files).",
    alsoUsed: "KHR_materials_transmission, KHR_materials_ior, EXT_texture_webp (hero only); all handled by GLTFLoader.",
  },
  exports: {
    hero: {
      ...hero,
      contents:
        "Surface unit on its 60 mm pole with the seabed footing plate, the float-collar variant, the listening head on its sensor line, three mussel longlines with barrel buoys and droppers, seabed, a school of nine gilthead seabream, a 5.2 m work boat for scale, and a water surface.",
      variants: {
        rule: "Show mountPole (default) or mountFloat, never both. mountFloat carries extras.defaultHidden = true; hide it on load. Each mount group holds its own tether (tetherPole, tetherFloat).",
        floatSurfaceY: hero.rootExtras && (hero.rootExtras as Record<string, unknown>).floatSurfaceY,
      },
      clipNotes: {
        descend: "Lowers the head from just below the surface to its working depth among the droppers; the tether follows through its headRaised morph weight (1 at the start, 0 at the end).",
        swim: "The school circles once; tails beat. Loops.",
      },
      waterNode: "waterSurface carries extras.role = 'water'. Hide it if the page draws its own water.",
    },
    head: {
      ...head,
      contents: "The passive listening head alone, at the origin, with explode and assemble clips.",
      clipNotes: {
        explode: "Parts move apart along the tube axis (glTF +X toward the dome); the hydrophone lifts on +Y and the clamp drops on -Y. The enclosure tube and the head root never move.",
        assemble: "The reverse of explode.",
      },
    },
  },
  sources: {
    surface: "hardware/candidates/surface-v3/cad/generated/surface-v3/SURFACE_V3.glb (+ hierarchy.json)",
    head: "hardware/candidates/passive-v3/cad/generated/passive-v3/INTRFACE_PASSIVE_V3.glb (+ hierarchy.json)",
    excludedAllocations: [
      "Surface: SINK_OCCUPANCY_NOT_FINS, SINK_OUTLET_AIR_ALLOCATION, CROSS_BOLT_ALLOCATION_1/2, CABLE_ROUTE_ALLOCATION_A/B (space reservations, not parts)",
      "Head: EMPTY_* reserve envelopes (space reservations, not parts)",
    ],
    modelledHere:
      "Longlines, buoys, mussel droppers, seabed, shells, seabream, work boat, water and the render stage are modelled by the build scripts in this folder. No third-party models are used.",
    lighting: "Renders use the Poly Haven HDRI kloofendal_48d_partly_cloudy_puresky (CC0). It is not stored in the repository and is not part of any GLB.",
  },
  build: {
    blender: "Blender 5.2 LTS",
    steps: [
      "Blender -b --factory-startup --python hardware/showcase/build_head_v4.py",
      "Blender -b --factory-startup --python hardware/showcase/build_hero_v4.py",
      "bun hardware/showcase/package_v4.ts",
    ],
    masters: ["hardware/showcase/hero.blend", "hardware/showcase/head.blend"],
  },
  lineage: {
    replaces: "Run B (unit.glb, site.glb, orada.glb) and the v3 scenes (unit-v3.glb, site-v3.glb). Both were built from geometry that included vendor-derived CAD and were retired together with their .blend files, build scripts, manifests and renders.",
    retiredFiles: [
      "hardware/showcase/blender/{unit,site,unit-v3,site-v3}.blend",
      "hardware/showcase/exports/{unit,site,orada,unit-v3,site-v3,hub-source,reef-source,surface-v3-source}.glb",
      "hardware/showcase/exports/scene-manifest.json, scene-manifest-v3.json",
      "hardware/showcase/renders/{unit,site,unit-v3,site-v3}.png",
      "hardware/showcase/build_{unit,site}_blender.py, build_{unit,site}_v3_blender.py, blender_common.py, blender_fish.py, blender_v3_bindings.py, export_surface_cad.py",
      "hardware/showcase/scene-spec.json, unit-build-checks.json, site-build-checks.json, surface-cad-baseline.json, validate_assets.ts",
    ],
    fixedDefects: [
      "The explode clip keeps the enclosure tube and the head root still; only the parts move.",
      "The descend clip ends at the working depth among the droppers, not below them.",
      "Root extras match the mesh: seabedTopY is the footing plate top.",
      "The tether is parented to its mount group and follows the head through a morph target.",
      "The water surface is a named, flagged node the page can hide.",
      "Renders use an HDRI sky, a water volume and a sun.",
      "The footing plate uses dark galvanised steel.",
      "The float collar sits clear of the head, which hangs on its own sensor line.",
    ],
  },
  renders: {
    dir: "hardware/showcase/renders-v4",
    licence: "CC-BY-4.0",
    files: ["hero-16x9.png", "og-image.png", "farm-wide.png", "unit-closeup.png", "head-exploded.png"],
    script: "hardware/showcase/render_v4.py",
  },
  licence: { models: "CERN-OHL-S-2.0", renders: "CC-BY-4.0" },
};

writeFileSync(join(HERE, "scene-manifest-v4.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(`hero.glb ${hero.bytes} B, ${hero.triangles} triangles; head.glb ${head.bytes} B, ${head.triangles} triangles`);
