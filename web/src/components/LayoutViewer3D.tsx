"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2, Pause, Play, RotateCcw } from "lucide-react";
import type { Group, Object3D } from "three";
import { assetUrl } from "@/lib/config";
import type { Layout, Room, XZ } from "@/types/schemas";

const WALL_H = 1.1; // cut-away walls, so you can see in from any angle
const WALL_T = 0.12;

function boundsOf(layout: Layout, rooms?: Room[]): XZ[][] {
  if (rooms?.length) return rooms.map((r) => r.polygon_m);
  // No rooms from the API: a rectangle around the furniture and the entrance.
  const pts: XZ[] = [];
  for (const it of layout.items) {
    const r = Math.hypot(it.width_m, it.depth_m) / 2;
    pts.push([it.x_m - r, it.z_m - r], [it.x_m + r, it.z_m + r]);
  }
  if (layout.entrance_xz) pts.push(layout.entrance_xz);
  if (!pts.length) return [];
  const pad = 0.8;
  const xs = pts.map((p) => p[0]);
  const zs = pts.map((p) => p[1]);
  const [x0, x1, z0, z1] = [Math.min(...xs) - pad, Math.max(...xs) + pad, Math.min(...zs) - pad, Math.max(...zs) + pad];
  return [[[x0, z0], [x1, z0], [x1, z1], [x0, z1]]];
}

/**
 * The layout in 3D without Matterport: floor + cut-away walls from the room outlines,
 * Yared's GLBs at (x_m, 0, z_m) turned by rotation_deg about +y (same convention as the tour).
 * Used when the real tour can't load (no scan / fake sample ids / no SDK key).
 */
export function LayoutViewer3D({ layout, rooms }: { layout: Layout; rooms?: Room[] }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const controlsRef = useRef<{ autoRotate: boolean; reset(): void } | null>(null);
  const [loading, setLoading] = useState(true);
  const [spinning, setSpinning] = useState(true);
  const [failed, setFailed] = useState(0);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let frame = 0;
    let cleanup = () => {};

    (async () => {
      const THREE = await import("three");
      const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
      const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js");
      if (disposed) return;

      const renderer = new THREE.WebGLRenderer({ antialias: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(host.clientWidth, host.clientHeight);
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      host.appendChild(renderer.domElement);

      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#1b1814");
      scene.fog = new THREE.Fog("#1b1814", 30, 80);

      // Lights: soft sky + one warm key light with shadows.
      scene.add(new THREE.HemisphereLight("#fff7ec", "#3b3226", 1.6));
      const sun = new THREE.DirectionalLight("#ffffff", 2.2);
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
      sun.shadow.bias = -0.0005;
      scene.add(sun);

      // Floor + walls from the room outlines (model (x, z) -> three (x, 0, z)).
      const polys = boundsOf(layout, rooms);
      const all = polys.flat();
      const xs = all.map((p) => p[0]);
      const zs = all.map((p) => p[1]);
      const box = { x0: Math.min(...xs), x1: Math.max(...xs), z0: Math.min(...zs), z1: Math.max(...zs) };
      const center = new THREE.Vector3((box.x0 + box.x1) / 2, 0, (box.z0 + box.z1) / 2);
      const span = Math.max(box.x1 - box.x0, box.z1 - box.z0, 4);

      const ground = new THREE.Mesh(new THREE.CircleGeometry(span * 1.6, 64), new THREE.MeshStandardMaterial({ color: "#2a251f", roughness: 1 }));
      ground.rotation.x = -Math.PI / 2;
      ground.position.set(center.x, -0.01, center.z);
      ground.receiveShadow = true;
      scene.add(ground);

      const floorMat = new THREE.MeshStandardMaterial({ color: "#c9a77c", roughness: 0.85 });
      const wallMat = new THREE.MeshStandardMaterial({ color: "#efe9df", roughness: 0.9 });
      for (const poly of polys) {
        // Shape in (x, -z), rotated -90° about x, lands on (x, 0, z).
        const shape = new THREE.Shape(poly.map(([x, z]) => new THREE.Vector2(x, -z)));
        const floor = new THREE.Mesh(new THREE.ShapeGeometry(shape), floorMat);
        floor.rotation.x = -Math.PI / 2;
        floor.receiveShadow = true;
        scene.add(floor);
        poly.forEach(([ax, az], i) => {
          const [bx, bz] = poly[(i + 1) % poly.length];
          const len = Math.hypot(bx - ax, bz - az);
          if (len < 0.05) return;
          const wall = new THREE.Mesh(new THREE.BoxGeometry(len + WALL_T, WALL_H, WALL_T), wallMat);
          wall.position.set((ax + bx) / 2, WALL_H / 2, (az + bz) / 2);
          wall.rotation.y = -Math.atan2(bz - az, bx - ax);
          wall.castShadow = true;
          wall.receiveShadow = true;
          scene.add(wall);
        });
      }

      // Entrance marker.
      if (layout.entrance_xz) {
        const mark = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 0.03, 32), new THREE.MeshStandardMaterial({ color: "#4c9a6a", emissive: "#1f4d33" }));
        mark.position.set(layout.entrance_xz[0], 0.02, layout.entrance_xz[1]);
        scene.add(mark);
      }

      // Furniture: one GLB per item, loaded once per asset and cloned.
      const loader = new GLTFLoader();
      const cache = new Map<string, Promise<Group>>();
      const load = (url: string) => {
        if (!cache.has(url)) cache.set(url, loader.loadAsync(url).then((g) => g.scene));
        return cache.get(url)!;
      };
      let misses = 0;
      await Promise.all(
        layout.items.map(async (it) => {
          let obj: Object3D;
          try {
            obj = (await load(assetUrl(it.glb_asset))).clone(true);
          } catch {
            // Missing model: a plain box of the right size so the layout still reads.
            misses++;
            obj = new THREE.Mesh(new THREE.BoxGeometry(it.width_m, it.height_m, it.depth_m), new THREE.MeshStandardMaterial({ color: "#9a8b78" }));
            obj.position.y = it.height_m / 2;
            const g = new THREE.Group();
            g.add(obj);
            obj = g;
          }
          obj.position.set(it.x_m, 0, it.z_m);
          obj.rotation.y = (it.rotation_deg * Math.PI) / 180;
          obj.traverse((o) => {
            o.castShadow = true;
            o.receiveShadow = true;
          });
          if (!disposed) scene.add(obj);
        }),
      );
      if (disposed) return;
      setFailed(misses);
      setLoading(false);

      // Camera: three-quarter view from the entrance side, framing everything.
      const camera = new THREE.PerspectiveCamera(40, host.clientWidth / host.clientHeight, 0.1, 200);
      const ex = layout.entrance_xz ?? [center.x, box.z1];
      const dir = new THREE.Vector3(ex[0] - center.x, 0, ex[1] - center.z);
      if (dir.lengthSq() < 0.01) dir.set(0, 0, 1);
      dir.normalize();
      const dist = span * 0.95;
      const home = center.clone().add(dir.multiplyScalar(dist)).add(new THREE.Vector3(span * 0.2, span * 0.7, 0));
      camera.position.copy(home);
      camera.lookAt(center);
      sun.position.set(center.x + span * 0.6, span * 1.5, center.z + span * 0.4);
      sun.target.position.copy(center);
      scene.add(sun.target);
      const s = span * 0.9;
      Object.assign(sun.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 0.5, far: span * 4 });
      sun.shadow.camera.updateProjectionMatrix();

      const controls = new OrbitControls(camera, renderer.domElement);
      controls.target.copy(center);
      controls.enableDamping = true;
      controls.maxPolarAngle = Math.PI / 2 - 0.08;
      controls.minDistance = 2;
      controls.maxDistance = span * 4;
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.6;
      controls.addEventListener("start", () => {
        controls.autoRotate = false;
        setSpinning(false);
      });
      controlsRef.current = {
        get autoRotate() {
          return controls.autoRotate;
        },
        set autoRotate(v: boolean) {
          controls.autoRotate = v;
        },
        reset() {
          camera.position.copy(home);
          controls.target.copy(center);
          controls.update();
        },
      };

      const resize = new ResizeObserver(() => {
        const w = host.clientWidth;
        const h = host.clientHeight;
        if (!w || !h) return;
        renderer.setSize(w, h);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      });
      resize.observe(host);

      const tick = () => {
        frame = requestAnimationFrame(tick);
        controls.update();
        renderer.render(scene, camera);
      };
      tick();

      cleanup = () => {
        cancelAnimationFrame(frame);
        resize.disconnect();
        controls.dispose();
        scene.traverse((o) => {
          const m = o as { geometry?: { dispose(): void }; material?: { dispose(): void } | { dispose(): void }[] };
          m.geometry?.dispose();
          (Array.isArray(m.material) ? m.material : m.material ? [m.material] : []).forEach((mat) => mat.dispose());
        });
        renderer.dispose();
        renderer.domElement.remove();
      };
    })().catch((e) => {
      console.error("3D layout viewer failed", e);
      setLoading(false);
    });

    return () => {
      disposed = true;
      controlsRef.current = null;
      cleanup();
    };
  }, [layout, rooms]);

  const btn = "inline-flex items-center gap-1.5 rounded-lg bg-black/60 px-2.5 py-1.5 text-xs text-white backdrop-blur hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-accent";

  return (
    <div className="relative aspect-video overflow-hidden rounded-xl border border-border bg-[#1b1814]">
      <div ref={hostRef} className="absolute inset-0" role="img" aria-label={`3D view of the layout: ${layout.items.length} items`} />
      {loading && (
        <div className="pointer-events-none absolute top-2 left-2 inline-flex items-center gap-2 rounded-lg bg-black/60 px-2.5 py-1.5 text-xs text-white">
          <Loader2 className="size-3.5 animate-spin" /> Placing {layout.items.length} items…
        </div>
      )}
      {!loading && (
        <div className="absolute top-2 right-2 flex gap-1.5">
          <button
            type="button"
            className={btn}
            aria-pressed={spinning}
            onClick={() => {
              const c = controlsRef.current;
              if (!c) return;
              c.autoRotate = !spinning;
              setSpinning(!spinning);
            }}
          >
            {spinning ? <Pause className="size-3.5" /> : <Play className="size-3.5" />} {spinning ? "Stop" : "Rotate"}
          </button>
          <button type="button" className={btn} onClick={() => controlsRef.current?.reset()}>
            <RotateCcw className="size-3.5" /> Reset view
          </button>
        </div>
      )}
      <p className="pointer-events-none absolute bottom-2 left-2 rounded-lg bg-black/55 px-2 py-1 text-[11px] text-white/85">
        Drag to orbit · scroll to zoom{failed ? ` · ${failed} model(s) missing, shown as boxes` : ""}
      </p>
    </div>
  );
}
