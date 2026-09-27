/**
 * Which 3D files the page loads, and what to do with them.
 *
 * Both files come from hardware/showcase/ (scene-manifest-v4.json lists
 * their nodes and clips). They are Draco compressed; the hero also carries
 * WebP textures. Frame: metres, +Y up, the hero's water surface at y = 0.
 */

export interface HeroModels {
  url: string;
  /** Node names to hide on load. `waterSurface` gives way to the page's own sea band. */
  hide: string[];
  /** Extra nodes to hide on phones and low-end devices, to cut triangles. */
  hideLight: string[];
  /** Nodes that move with a clip; drawn in both the air and the water pass. */
  moving: string[];
  /** Looping clips for idle life. */
  loopClips: string[];
  /** Clips played once on arrival, then held on their last frame. */
  onceClips: string[];
  /** Where the camera looks, metres. */
  target: [number, number, number];
  /** Height above the water the air part of the view must hold, metres. */
  airHeight: number;
  /** Depth below the water the sea part of the view must hold, metres. */
  waterDepth: number;
}

export interface HeadModel {
  url: string;
  explodeClip: string;
}

export const MODELS: { hero: HeroModels; head: HeadModel } = {
  hero: {
    url: '/models/hero.glb',
    /* longlineFront runs between this camera and the unit; it would fill the foreground. */
    hide: ['mountFloat', 'waterSurface', 'longlineFront'],
    hideLight: ['longlineBack'],
    moving: ['head', 'school', 'mountPole'],
    loopClips: ['swim'],
    onceClips: ['descend'],
    target: [0.3, 0, -0.6],
    airHeight: 1.3,
    waterDepth: 3.1,
  },
  head: {
    url: '/models/head.glb',
    explodeClip: 'explode',
  },
};

/** Colours the 3D shares with the stylesheet. */
export const SEA = '#0d3a41';
export const SEA_PANEL = '#0a3238';
