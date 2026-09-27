/**
 * The hero: the unit at the farm, seen from the waterline.
 *
 * The camera sits at the water surface with no pitch. The scene is drawn in
 * two passes split by a clipping plane at y = 0: clear air above, sea fog
 * below. The canvas is transparent, so the paper and the sea band behind it
 * come from the stylesheet; the fog colour matches the sea band, and the
 * horizon is shifted to sit exactly on the band's top edge.
 *
 * Each mesh is tagged for the pass it can appear in, so the air pass skips
 * everything that stays under water and the other way round.
 */

import {
  AmbientLight,
  AnimationMixer,
  Box3,
  BufferAttribute,
  BufferGeometry,
  Color,
  DirectionalLight,
  Fog,
  HemisphereLight,
  LoopOnce,
  type Material,
  type Mesh,
  type MeshPhysicalMaterial,
  type Object3D,
  PerspectiveCamera,
  Plane,
  Points,
  PointsMaterial,
  Scene,
  Vector3,
} from 'three';
import { MODELS, SEA } from './models.ts';
import { createRenderer, environment, findClip, hideNodes, horizontalDrag, isLightDevice, loadModel, visibleLoop, watchSize } from './runtime.ts';

const FOV = 28;
const AIR = 1;
const WATER = 2;

function particles(): Points {
  const count = 320;
  const positions = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    positions[i * 3] = (Math.random() - 0.5) * 16;
    positions[i * 3 + 1] = -Math.random() * 4.5 - 0.1;
    positions[i * 3 + 2] = (Math.random() - 0.5) * 10 + 2;
  }
  const geometry = new BufferGeometry();
  geometry.setAttribute('position', new BufferAttribute(positions, 3));
  const material = new PointsMaterial({ color: '#cfe7e1', size: 0.03, transparent: true, opacity: 0.5, depthWrite: false });
  const points = new Points(geometry, material);
  points.name = 'suspended';
  return points;
}

/** Tag every mesh for the air pass, the water pass, or both. */
function splitByWaterline(root: Object3D, moving: string[]): void {
  root.updateMatrixWorld(true);
  const box = new Box3();
  const visit = (node: Object3D, both: boolean) => {
    const always = both || moving.includes(node.name);
    if ((node as Mesh).isMesh || (node as Points).isPoints) {
      node.layers.disableAll();
      if (always) {
        node.layers.enable(AIR);
        node.layers.enable(WATER);
      } else {
        box.setFromObject(node, true);
        if (box.max.y > -0.02) node.layers.enable(AIR);
        if (box.min.y < 0.02) node.layers.enable(WATER);
      }
    } else {
      node.layers.enableAll();
    }
    for (const child of node.children) visit(child, always);
  };
  visit(root, false);
}

/**
 * The dome's glass would make three.js draw the whole farm a second time for
 * refraction. At this size plain see-through plastic reads the same.
 */
function flattenGlass(root: Object3D): void {
  root.traverse((node) => {
    const mesh = node as Mesh;
    if (!mesh.isMesh) return;
    const list = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of list as Material[]) {
      const glass = material as MeshPhysicalMaterial;
      if (glass.transmission > 0) {
        glass.transmission = 0;
        glass.transparent = true;
        glass.opacity = 0.35;
        glass.depthWrite = false;
      }
    }
  });
}

export async function mountHero(stage: HTMLElement): Promise<void> {
  const canvas = stage.querySelector<HTMLCanvasElement>('canvas');
  const hero = stage.closest<HTMLElement>('.hero');
  const water = hero?.querySelector<HTMLElement>('.hero__water');
  if (!canvas || !hero || !water) return;

  const config = MODELS.hero;
  const light = isLightDevice();
  const renderer = createRenderer(canvas, light ? 1.5 : 1.75);
  const scene = new Scene();
  scene.environment = environment(renderer);
  scene.environmentIntensity = 0.6;

  const sea = new Color(SEA);
  const fog = new Fog(sea, 1000, 1001);
  scene.fog = fog;

  scene.add(new HemisphereLight('#eef4f5', '#3d5a5c', 1.1));
  scene.add(new AmbientLight('#ffffff', 0.15));
  const sun = new DirectionalLight('#fff4e2', 2.4);
  sun.position.set(-4, 8, 6);
  scene.add(sun);

  const gltf = await loadModel(config.url);
  hideNodes(gltf.scene, light ? [...config.hide, ...config.hideLight] : config.hide);
  flattenGlass(gltf.scene);
  scene.add(gltf.scene);
  const specks = particles();
  scene.add(specks);
  splitByWaterline(scene, config.moving);

  const mixer = new AnimationMixer(gltf.scene);
  for (const name of config.loopClips) {
    const clip = findClip(gltf.animations, name);
    if (clip) mixer.clipAction(clip).play();
  }
  for (const name of config.onceClips) {
    const clip = findClip(gltf.animations, name);
    if (!clip) continue;
    const action = mixer.clipAction(clip);
    action.setLoop(LoopOnce, 1);
    action.clampWhenFinished = true;
    action.play();
  }

  const camera = new PerspectiveCamera(FOV, 1, 0.1, 90);
  const above = [new Plane(new Vector3(0, 1, 0), 0)];
  const below = [new Plane(new Vector3(0, -1, 0), 0)];
  renderer.autoClear = false;

  const view = { distance: 12, horizon: 0.6, focusX: 0.72 };
  const target = new Vector3(...config.target);
  const tan = Math.tan((FOV * Math.PI) / 360);

  const resize = (width: number, height: number) => {
    renderer.setSize(width, height, false);
    const waterTop = water.getBoundingClientRect().top - stage.getBoundingClientRect().top;
    view.horizon = Math.min(0.85, Math.max(0.2, waterTop / height));
    const style = getComputedStyle(stage);
    const focus = parseFloat(style.getPropertyValue('--stage-focus-x'));
    view.focusX = Number.isFinite(focus) ? focus : 0.5;
    const air = parseFloat(style.getPropertyValue('--stage-air-m'));
    const depth = parseFloat(style.getPropertyValue('--stage-depth-m'));
    /* Far enough back that both the unit above and the head below fit. */
    view.distance = Math.max(
      (Number.isFinite(air) ? air : config.airHeight) / (view.horizon * 2 * tan),
      (Number.isFinite(depth) ? depth : config.waterDepth) / ((1 - view.horizon) * 2 * tan),
    );
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    const m = camera.projectionMatrix.elements;
    m[8] = 1 - 2 * view.focusX;
    m[9] = 2 * view.horizon - 1;
    camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
    draw();
  };

  const drag = horizontalDrag(canvas);
  let clock = 0;
  const specksBase = (specks.geometry.getAttribute('position') as BufferAttribute).array.slice();

  const draw = () => {
    const idle = 0.12 * Math.sin((clock / 60) * Math.PI * 2);
    drag.yaw += (drag.target - drag.yaw) * 0.08;
    if (!drag.dragging) drag.target *= 0.985;
    const yaw = -0.38 + idle + drag.yaw;
    camera.position.set(target.x + Math.sin(yaw) * view.distance, 0, target.z + Math.cos(yaw) * view.distance);
    camera.lookAt(target.x, 0, target.z);
    camera.updateMatrixWorld();

    renderer.clear();
    fog.near = 1000;
    fog.far = 1001;
    camera.layers.set(AIR);
    renderer.clippingPlanes = above;
    renderer.render(scene, camera);
    fog.near = view.distance * 0.6;
    fog.far = view.distance * 1.6;
    camera.layers.set(WATER);
    renderer.clippingPlanes = below;
    renderer.render(scene, camera);
  };

  const positions = specks.geometry.getAttribute('position') as BufferAttribute;
  const loop = visibleLoop(stage, (dt) => {
    clock += dt;
    mixer.update(dt);
    for (let i = 0; i < positions.count; i++) {
      const base = specksBase[i * 3 + 1] ?? 0;
      positions.setY(i, base + 0.05 * Math.sin(clock * 0.4 + i));
    }
    positions.needsUpdate = true;
    draw();
  });

  const stopWatching = watchSize(stage, resize);
  const box = stage.getBoundingClientRect();
  resize(box.width, box.height);
  requestAnimationFrame(() => {
    performance.mark('hero-3d-first-frame');
    stage.classList.add('is-live');
  });
  loop.start();

  window.addEventListener(
    'pagehide',
    () => {
      loop.dispose();
      stopWatching();
      renderer.dispose();
    },
    { once: true },
  );
}
