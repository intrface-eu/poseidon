/**
 * The listening head, turned slowly, with a button that takes it apart.
 *
 * The file's explode clip drives the parts; the button scrubs it. The
 * enclosure tube stays put and the camera backs off as the parts spread.
 */

import {
  AnimationMixer,
  DirectionalLight,
  Group,
  HemisphereLight,
  PerspectiveCamera,
  Scene,
  Sphere,
  Vector3,
} from 'three';
import { MODELS } from './models.ts';
import { createRenderer, environment, findClip, horizontalDrag, loadModel, shownBox, visibleLoop, watchSize } from './runtime.ts';

const FOV = 30;
const EXPLODE_MS = 1200;
/** Turntable angle that shows the tube broadside with a little of the dome end. */
const SIDE_ON = -0.35;

function ease(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
}

export async function mountHead(stage: HTMLElement, reducedMotion: boolean): Promise<void> {
  const canvas = stage.querySelector<HTMLCanvasElement>('canvas');
  const figure = stage.closest('figure');
  const button = figure?.querySelector<HTMLButtonElement>('[data-explode]');
  const hint = figure?.querySelector<HTMLElement>('.headfig__drag');
  if (!canvas) return;

  const config = MODELS.head;
  const renderer = createRenderer(canvas, 2);
  const scene = new Scene();
  scene.environment = environment(renderer);
  scene.environmentIntensity = 1.3;
  scene.add(new HemisphereLight('#f4f8f7', '#2a6a70', 2.2));
  const key = new DirectionalLight('#ffffff', 3.4);
  key.position.set(2, 3, 4);
  scene.add(key);
  const rim = new DirectionalLight('#9fe3d6', 2.2);
  rim.position.set(-3, 1.5, -3);
  scene.add(rim);

  const gltf = await loadModel(config.url);
  const clip = findClip(gltf.animations, config.explodeClip);
  const mixer = new AnimationMixer(gltf.scene);
  const action = clip ? mixer.clipAction(clip) : null;
  action?.play();
  if (action) action.paused = true;

  /* Frame both states: the assembled head and the parts at full spread. */
  const pose = (v: number) => {
    if (action && clip) {
      action.time = v * clip.duration;
      mixer.update(0);
    }
  };
  /* Turn about the enclosure tube, which no clip moves; the cables above it only widen the fit. */
  const tube = gltf.scene.getObjectByName('enclosureTube') ?? gltf.scene;
  const pivot = shownBox(tube).getCenter(new Vector3());
  const bounds = (v: number) => {
    pose(v);
    const sphere = shownBox(gltf.scene).getBoundingSphere(new Sphere());
    return { radius: sphere.radius + sphere.center.distanceTo(pivot) * 0.6 };
  };
  const closed = bounds(0);
  const open = bounds(1);
  pose(0);
  gltf.scene.position.copy(pivot).negate();

  const turntable = new Group();
  const model = new Group();
  model.add(gltf.scene);
  turntable.add(model);
  scene.add(turntable);

  const radius = Math.max(closed.radius, open.radius);
  const camera = new PerspectiveCamera(FOV, 1, radius / 50, radius * 40);
  const tan = Math.tan((FOV * Math.PI) / 360);
  let fitPerRadius = 3;

  const explode = { value: 0, from: 0, to: 0, start: 0 };
  const setExplode = (v: number) => {
    explode.value = v;
    pose(v);
  };

  const drag = horizontalDrag(canvas, () => {
    if (hint) hint.hidden = true;
  });
  let spun = 0;

  const draw = () => {
    drag.yaw += (drag.target - drag.yaw) * 0.1;
    /* Taken apart, the head swings to the nearest side-on view so the parts do not stack up. */
    const spin = 0.55 + (reducedMotion ? 0 : spun);
    const side = SIDE_ON + Math.round((spin - SIDE_ON) / Math.PI) * Math.PI;
    turntable.rotation.y = spin + (side - spin) * explode.value + drag.yaw;
    const r = closed.radius + (open.radius - closed.radius) * explode.value;
    const d = r * fitPerRadius;
    camera.position.set(0, d * 0.22, d);
    camera.lookAt(0, 0, 0);
    renderer.render(scene, camera);
  };

  const resize = (width: number, height: number) => {
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    fitPerRadius = Math.max(1 / tan, 1 / (tan * camera.aspect)) * 0.82;
    camera.updateProjectionMatrix();
    draw();
  };

  const loop = visibleLoop(stage, (dt) => {
    spun += dt * 0.12 * (1 - explode.value);
    if (explode.from !== explode.to) {
      const t = Math.min(1, (performance.now() - explode.start) / EXPLODE_MS);
      setExplode(explode.from + (explode.to - explode.from) * ease(t));
      if (t >= 1) explode.from = explode.to;
    }
    draw();
  });

  if (button) {
    const label = button.querySelector('span');
    button.hidden = false;
    button.addEventListener('click', () => {
      const open = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', String(open));
      if (label) label.textContent = (open ? button.dataset.labelAssemble : button.dataset.labelExplode) ?? '';
      explode.from = explode.value;
      explode.to = open ? 1 : 0;
      explode.start = performance.now();
      if (reducedMotion) {
        setExplode(explode.to);
        explode.from = explode.to;
      }
    });
  }
  if (hint) hint.hidden = false;

  setExplode(0);
  watchSize(stage, resize);
  const rect = stage.getBoundingClientRect();
  resize(rect.width, rect.height);
  requestAnimationFrame(() => {
    performance.mark('head-3d-first-frame');
    stage.classList.add('is-live');
  });
  loop.start();
}
