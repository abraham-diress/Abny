/**
 * Thin wrapper over the Matterport **Bundle SDK** (self-hosted Showcase in /public/bundle).
 * The npm embed SDK has no Scene API, so it cannot place GLB models; the bundle can.
 *
 * Only the few calls we use are typed here, so the app type-checks on a fresh clone
 * that hasn't downloaded the bundle yet. Full types: public/bundle/sdk.d.ts.
 *
 * Conventions (shared/conventions.py): Matterport model coordinates, meters, y is up.
 * A LayoutItem's rotation_deg is about +y and 0 means its front faces +z.
 * Our GLBs have their origin at the bottom-center of the item (sits on y = 0).
 */

export const BUNDLE_PATH = "/bundle/showcase.html";

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

interface Subscription {
  cancel(): void;
}

interface Observable<T> {
  subscribe(cb: (value: T) => void): Subscription;
  waitUntil(cb: (value: T) => boolean): Promise<T>;
}

export interface MpComponent {
  inputs: Record<string, unknown>;
  outputs?: { objectRoot?: ThreeObject | null };
}

/** The few three.js members we touch on the loader's output (the bundle ships three.js). */
interface ThreeVector3 extends Vec3 {
  clone(): ThreeVector3;
  set(x: number, y: number, z: number): ThreeVector3;
  applyMatrix4(m: unknown): ThreeVector3;
}
interface ThreeObject {
  matrixWorld: unknown;
  updateWorldMatrix(parents: boolean, children: boolean): void;
  traverse(cb: (o: ThreeObject & { isMesh?: boolean; geometry?: ThreeGeometry }) => void): void;
}
interface ThreeGeometry {
  boundingBox: { min: ThreeVector3; max: ThreeVector3 } | null;
  computeBoundingBox(): void;
}

export interface MpNode {
  addComponent(name: string, inputs?: Record<string, unknown>, id?: string): MpComponent;
  position: { set(x: number, y: number, z: number): void };
  quaternion: { set(x: number, y: number, z: number, w: number): void };
}

export interface MpSceneObject {
  addNode(id?: string): MpNode;
  start(): void;
  stop(): void;
}

export interface Intersection {
  position: Vec3;
  normal: Vec3;
  floorIndex: number | undefined;
  object: string;
}

export interface SweepInfo {
  sid: string;
  position: Vec3;
  puckPosition?: Vec3;
  alignmentType?: string;
  floorInfo?: { sequence?: number; id?: string };
}

export interface SdkRoom {
  id: string;
  label: string;
  bounds: { min: Vec3; max: Vec3 };
  center: Vec3;
  floorInfo: { id: string; sequence: number };
}

interface ObservableMap<T> {
  subscribe(observer: { onCollectionUpdated(collection: Record<string, T>): void }): Subscription;
}

/** Camera pose; rotation is degrees, y = yaw. Matterport follows three.js: forward = (−sin yaw, −cos yaw). */
export interface CameraPose {
  position: Vec3;
  rotation: { x: number; y: number };
  sweep: string;
  mode: string;
}

/** Where the camera looks on the floor plan, from its yaw (checked against a live tour). */
export const yawToDir = (yawDeg: number): [number, number] => {
  const r = (yawDeg * Math.PI) / 180;
  return [-Math.sin(r), -Math.cos(r)];
};

/** Yaw that looks from (fx, fz) toward (tx, tz). Inverse of yawToDir. */
export const yawToward = (fx: number, fz: number, tx: number, tz: number) => (Math.atan2(-(tx - fx), -(tz - fz)) * 180) / Math.PI;

export interface MpSdk {
  App: { state: Observable<{ phase: string }> };
  Camera: { pose: Observable<CameraPose> };
  Model: { getData(): Promise<{ sid: string; sweeps: SweepInfo[] }> };
  Scene: { createObjects(count: number): Promise<MpSceneObject[]> };
  Pointer: { intersection: Observable<Intersection> };
  Sweep: {
    current: Observable<SweepInfo>;
    data: ObservableMap<SweepInfo>;
    moveTo(sweep: string, options: { transition?: string; transitionTime?: number; rotation?: { x: number; y: number } }): Promise<string>;
  };
  Room: { data: ObservableMap<SdkRoom> };
  Mode: { moveTo(mode: string, options?: Record<string, unknown>): Promise<string> };
}

export const MODE_INSIDE = "mode.inside";
export const MODE_DOLLHOUSE = "mode.dollhouse";
export const MODE_FLOORPLAN = "mode.floorplan";
export const TRANSITION_FLY = "transition.fly";

/** First full snapshot of an SDK collection (sweeps, rooms, ...). */
export function collection<T>(map: ObservableMap<T>, timeoutMs = 15000): Promise<T[]> {
  return new Promise((resolve, reject) => {
    let sub: Subscription | null = null;
    const timer = setTimeout(() => {
      sub?.cancel();
      reject(new Error("Timed out waiting for Matterport data"));
    }, timeoutMs);
    sub = map.subscribe({
      onCollectionUpdated(c) {
        clearTimeout(timer);
        resolve(Object.values(c));
        setTimeout(() => sub?.cancel(), 0);
      },
    });
  });
}

/** Is the self-hosted bundle installed? (public/bundle is gitignored; see web/README.md) */
export async function bundleInstalled(): Promise<boolean> {
  try {
    return (await fetch(BUNDLE_PATH, { method: "HEAD" })).ok;
  } catch {
    return false;
  }
}

/** The aligned sweep closest to a floor point (x, z), optionally limited to points inside a polygon. */
export function nearestSweep(sweeps: SweepInfo[], x: number, z: number, inside?: (x: number, z: number) => boolean): SweepInfo | null {
  const aligned = sweeps.filter((s) => s.alignmentType !== "unaligned");
  const pool = inside ? aligned.filter((s) => inside(s.position.x, s.position.z)) : aligned;
  const list = pool.length ? pool : aligned;
  let best: SweepInfo | null = null;
  let bestD = Infinity;
  for (const s of list) {
    const d = Math.hypot(s.position.x - x, s.position.z - z);
    if (d < bestD) {
      bestD = d;
      best = s;
    }
  }
  return best;
}

/**
 * A good place to stand to look at a floor point: on the same floor, ideally in the same room,
 * about 2.5 m away (close enough to see it, not standing on top of it).
 */
export function viewpointFor(
  sweeps: SweepInfo[],
  x: number,
  z: number,
  opts: { inside?: (x: number, z: number) => boolean; floor?: number } = {},
): SweepInfo | null {
  let pool = sweeps.filter((s) => s.alignmentType !== "unaligned");
  if (opts.floor != null) {
    const same = pool.filter((s) => (s.floorInfo?.sequence ?? opts.floor) === opts.floor);
    if (same.length) pool = same;
  }
  if (opts.inside) {
    const inRoom = pool.filter((s) => opts.inside!(s.position.x, s.position.z));
    if (inRoom.length) pool = inRoom;
  }
  let best: SweepInfo | null = null;
  let bestScore = Infinity;
  for (const s of pool) {
    const d = Math.hypot(s.position.x - x, s.position.z - z);
    // Prefer ~2.5 m; much closer means looking straight down at it.
    const score = d < 0.9 ? 3 + (0.9 - d) : Math.abs(d - 2.5);
    if (score < bestScore) {
      bestScore = score;
      best = s;
    }
  }
  return best;
}

interface BundleWindow extends Window {
  MP_SDK?: { connect(target: Window, options?: Record<string, unknown>): Promise<MpSdk> };
}

export const COLLIDER_MODEL = "intersectedobject.model";

export function showcaseUrl(modelId: string, sdkKey: string, extra: Record<string, string> = {}): string {
  const q = new URLSearchParams({ m: modelId, applicationKey: sdkKey, play: "1", qs: "1", title: "0", ...extra });
  return `${BUNDLE_PATH}?${q}`;
}

/** Connect to a bundle iframe once it has loaded, and wait until the tour is playable. */
export async function connectBundle(iframe: HTMLIFrameElement): Promise<MpSdk> {
  const win = iframe.contentWindow as BundleWindow | null;
  if (!win?.MP_SDK) throw new Error("The Matterport bundle did not load (window.MP_SDK missing).");
  const sdk = await win.MP_SDK.connect(win);
  await sdk.App.state.waitUntil((s) => s.phase === "appphase.playing");
  return sdk;
}

/** One ambient + directional light rig so loaded models aren't black. */
export async function addLights(sdk: MpSdk): Promise<MpSceneObject> {
  const [obj] = await sdk.Scene.createObjects(1);
  obj.addNode().addComponent("mp.lights");
  obj.start();
  return obj;
}

export interface Placement {
  url: string;
  position: Vec3;
  /** About +y, degrees. 0 = front faces +z. */
  rotationDeg: number;
  scale?: number;
}

export interface PlacedModel {
  object: MpSceneObject;
  node: MpNode;
  loader: MpComponent;
}

/** Load one GLB into the scene at a model-space position. */
export async function placeGlb(sdk: MpSdk, p: Placement): Promise<PlacedModel> {
  const [object] = await sdk.Scene.createObjects(1);
  const node = object.addNode();
  const s = p.scale ?? 1;
  // No collider: the pointer should pass through furniture to the floor (needed while placing).
  const loader = node.addComponent("mp.gltfLoader", { url: p.url, localScale: { x: s, y: s, z: s }, colliderEnabled: false });
  setTransform(node, p.position, p.rotationDeg);
  object.start();
  return { object, node, loader };
}

export function setTransform(node: MpNode, pos: Vec3, rotationDeg: number) {
  node.position.set(pos.x, pos.y, pos.z);
  const half = (rotationDeg * Math.PI) / 360; // quaternion about +y: (0, sin θ/2, 0, cos θ/2)
  node.quaternion.set(0, Math.sin(half), 0, Math.cos(half));
}

/**
 * World-space (model-space) bounding box of a loaded model, in meters.
 * Null until the GLB has finished loading.
 */
export function measure(m: PlacedModel): { min: Vec3; max: Vec3; size: Vec3 } | null {
  const root = m.loader.outputs?.objectRoot;
  if (!root) return null;
  root.updateWorldMatrix(true, true);
  const min = { x: Infinity, y: Infinity, z: Infinity };
  const max = { x: -Infinity, y: -Infinity, z: -Infinity };
  root.traverse((o) => {
    if (!o.isMesh || !o.geometry) return;
    if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
    const bb = o.geometry.boundingBox;
    if (!bb) return;
    for (const x of [bb.min.x, bb.max.x])
      for (const y of [bb.min.y, bb.max.y])
        for (const z of [bb.min.z, bb.max.z]) {
          const p = bb.min.clone().set(x, y, z).applyMatrix4(o.matrixWorld);
          min.x = Math.min(min.x, p.x); min.y = Math.min(min.y, p.y); min.z = Math.min(min.z, p.z);
          max.x = Math.max(max.x, p.x); max.y = Math.max(max.y, p.y); max.z = Math.max(max.z, p.z);
        }
  });
  if (!Number.isFinite(min.x)) return null;
  return { min, max, size: { x: max.x - min.x, y: max.y - min.y, z: max.z - min.z } };
}

export function setVisible(m: PlacedModel, visible: boolean) {
  m.loader.inputs.visible = visible;
}
