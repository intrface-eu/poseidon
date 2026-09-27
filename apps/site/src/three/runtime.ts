/**
 * Shared three.js plumbing for the two stages: renderer, loader, pausing
 * off-screen, resizing and pointer drag.
 */

import {
  AnimationClip,
  Box3,
  NeutralToneMapping,
  Object3D,
  PMREMGenerator,
  SRGBColorSpace,
  WebGLRenderer,
  type Mesh,
  type Scene,
  type Texture,
} from 'three';
import { DRACOLoader, DRACO_GLTF_CONFIG } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { GLTFLoader, type GLTF } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';

let loader: GLTFLoader | null = null;

function gltfLoader(): GLTFLoader {
  if (loader) return loader;
  const draco = new DRACOLoader();
  /* The glTF build of the decoder, bundled and hashed by Vite. */
  draco.setDecoderPath(DRACO_GLTF_CONFIG);
  loader = new GLTFLoader();
  loader.setDRACOLoader(draco);
  loader.setMeshoptDecoder(MeshoptDecoder);
  return loader;
}

export function loadModel(url: string): Promise<GLTF> {
  return gltfLoader().loadAsync(url);
}

export function createRenderer(canvas: HTMLCanvasElement, maxDpr: number): WebGLRenderer {
  const renderer = new WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: 'high-performance',
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, maxDpr));
  renderer.outputColorSpace = SRGBColorSpace;
  renderer.toneMapping = NeutralToneMapping;
  renderer.toneMappingExposure = 1;
  renderer.setClearColor(0x000000, 0);
  /* If the GPU drops the context, fall back to the poster instead of a blank panel. */
  canvas.addEventListener('webglcontextlost', () => canvas.closest('.stage')?.classList.remove('is-live'));
  return renderer;
}

export function environment(renderer: WebGLRenderer): Texture {
  const pmrem = new PMREMGenerator(renderer);
  const texture = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  return texture;
}

/** Hide nodes by exact name. */
export function hideNodes(root: Object3D, names: string[]): void {
  root.traverse((node) => {
    if (names.includes(node.name)) node.visible = false;
  });
}

/** Phones and low-end machines get a lighter scene and a lower pixel ratio. */
export function isLightDevice(): boolean {
  const nav = navigator as Navigator & { deviceMemory?: number };
  return (
    window.matchMedia('(max-width: 899px)').matches || (nav.hardwareConcurrency ?? 8) <= 4 || (nav.deviceMemory ?? 8) <= 4
  );
}

export function meshes(root: Object3D): Mesh[] {
  const out: Mesh[] = [];
  root.traverse((node) => {
    if ((node as Mesh).isMesh && isShown(node)) out.push(node as Mesh);
  });
  return out;
}

function isShown(node: Object3D): boolean {
  for (let n: Object3D | null = node; n; n = n.parent) if (!n.visible) return false;
  return true;
}

/** Bounding box of the shown meshes only; hidden planning volumes do not count. */
export function shownBox(root: Object3D): Box3 {
  root.updateMatrixWorld(true);
  const box = new Box3();
  for (const mesh of meshes(root)) box.expandByObject(mesh, true);
  return box;
}

export function findClip(clips: AnimationClip[], name: string): AnimationClip | undefined {
  return clips.find((clip) => clip.name === name);
}

export interface Loop {
  start(): void;
  stop(): void;
  dispose(): void;
}

/**
 * Runs `frame` on animation frames while the element is on screen and the tab
 * is visible. `frame` gets seconds since the last frame, capped.
 */
export function visibleLoop(element: Element, frame: (dt: number) => void): Loop {
  let raf = 0;
  let last = 0;
  let onScreen = false;
  let running = false;
  const tick = (now: number) => {
    raf = requestAnimationFrame(tick);
    const dt = last ? Math.min((now - last) / 1000, 0.1) : 0;
    last = now;
    frame(dt);
  };
  const sync = () => {
    const want = running && onScreen && document.visibilityState === 'visible';
    if (want && !raf) {
      last = 0;
      raf = requestAnimationFrame(tick);
    } else if (!want && raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
  };
  const io = new IntersectionObserver(
    (entries) => {
      onScreen = entries.some((e) => e.isIntersecting);
      sync();
    },
    { rootMargin: '80px' },
  );
  io.observe(element);
  document.addEventListener('visibilitychange', sync);
  return {
    start() {
      running = true;
      sync();
    },
    stop() {
      running = false;
      sync();
    },
    dispose() {
      running = false;
      sync();
      io.disconnect();
      document.removeEventListener('visibilitychange', sync);
    },
  };
}

/** Calls `resize` when the element changes size. */
export function watchSize(element: Element, resize: (width: number, height: number) => void): () => void {
  const ro = new ResizeObserver((entries) => {
    const box = entries[0]?.contentRect;
    if (box && box.width > 0 && box.height > 0) resize(box.width, box.height);
  });
  ro.observe(element);
  return () => ro.disconnect();
}

/**
 * Horizontal drag in radians, eased back to zero when `spring` is set.
 * Vertical movement is left to the page so touch scrolling still works.
 */
export function horizontalDrag(element: HTMLElement, onFirstDrag?: () => void) {
  const state = { yaw: 0, target: 0, dragging: false };
  let startX = 0;
  let startTarget = 0;
  let used = false;
  element.addEventListener('pointerdown', (e) => {
    state.dragging = true;
    startX = e.clientX;
    startTarget = state.target;
    element.setPointerCapture(e.pointerId);
  });
  element.addEventListener('pointermove', (e) => {
    if (!state.dragging) return;
    const width = element.clientWidth || 1;
    state.target = startTarget + ((e.clientX - startX) / width) * Math.PI * 1.2;
    if (!used && Math.abs(e.clientX - startX) > 4) {
      used = true;
      onFirstDrag?.();
    }
  });
  const end = (e: PointerEvent) => {
    state.dragging = false;
    if (element.hasPointerCapture(e.pointerId)) element.releasePointerCapture(e.pointerId);
  };
  element.addEventListener('pointerup', end);
  element.addEventListener('pointercancel', end);
  return state;
}

export function disposeScene(scene: Scene): void {
  scene.traverse((node) => {
    const mesh = node as Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry.dispose();
    const material = mesh.material;
    for (const m of Array.isArray(material) ? material : [material]) m.dispose();
  });
}
