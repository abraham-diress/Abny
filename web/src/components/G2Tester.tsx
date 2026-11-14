"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Crosshair, Eye, EyeOff, Loader2, MapPin, Trash2 } from "lucide-react";
import clsx from "clsx";
import { getCatalog } from "@/lib/api";
import { MATTERPORT_SDK_KEY, assetUrl } from "@/lib/config";
import {
  BUNDLE_PATH,
  COLLIDER_MODEL,
  addLights,
  connectBundle,
  measure,
  placeGlb,
  setTransform,
  setVisible,
  showcaseUrl,
  type MpSdk,
  type PlacedModel,
  type Vec3,
} from "@/lib/matterport";
import type { CatalogItem } from "@/types/schemas";

/** Public sample model used in the hackathon quickstart (5836 La Mirada Ave, Los Angeles). */
const DEFAULT_MODEL = "zvKHR9DHNjJ";

type Phase = "checking" | "no-bundle" | "no-key" | "loading" | "ready" | "error";

interface Dropped {
  id: number;
  item: CatalogItem;
  pos: Vec3;
  rotationDeg: number;
  floorY: number | null;
  model: PlacedModel;
}

const fmt = (v: Vec3) => `${v.x.toFixed(2)}, ${v.y.toFixed(2)}, ${v.z.toFixed(2)}`;

/**
 * Gate G2: load a real Matterport tour with the Bundle SDK, drop catalog GLBs on the floor,
 * and check that they sit on the floor at real-world scale.
 */
export function G2Tester() {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const sdkRef = useRef<MpSdk | null>(null);
  const ghostRef = useRef<PlacedModel | null>(null);
  const hitRef = useRef<Vec3 | null>(null);
  const rotationRef = useRef(0);
  const nextId = useRef(1);

  const [phase, setPhase] = useState<Phase>(MATTERPORT_SDK_KEY ? "checking" : "no-key");
  const [error, setError] = useState<string | null>(null);
  const [modelInput, setModelInput] = useState(DEFAULT_MODEL);
  const [modelId, setModelId] = useState(DEFAULT_MODEL);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [itemType, setItemType] = useState<string>("");
  const [rotation, setRotation] = useState(0);
  const [placing, setPlacing] = useState(false);
  const [dropped, setDropped] = useState<Dropped[]>([]);
  const [visible, setVisibleAll] = useState(true);
  const [cursor, setCursor] = useState<Vec3 | null>(null);
  const [sweepFloorY, setSweepFloorY] = useState<number | null>(null);
  const floorYRef = useRef<number | null>(null);
  const [measured, setMeasured] = useState<Record<number, string>>({});

  // Measured size of each placed model in the scene (meters), once its GLB has loaded.
  useEffect(() => {
    if (dropped.length === 0) return;
    const t = setInterval(() => {
      const next: Record<number, string> = {};
      for (const d of dropped) {
        const m = measure(d.model);
        if (m) next[d.id] = `${m.size.x.toFixed(2)} × ${m.size.z.toFixed(2)} × ${m.size.y.toFixed(2)} m (x × z × y), bottom y ${m.min.y.toFixed(3)}`;
      }
      setMeasured(next);
    }, 1000);
    return () => clearInterval(t);
  }, [dropped]);

  const item = catalog.find((c) => c.item_type === itemType) ?? null;

  // Is the bundle installed? (It is gitignored; see web/README.md.)
  useEffect(() => {
    if (!MATTERPORT_SDK_KEY) return;
    fetch(BUNDLE_PATH, { method: "HEAD" })
      .then((r) => setPhase(r.ok ? "loading" : "no-bundle"))
      .catch(() => setPhase("no-bundle"));
  }, []);

  useEffect(() => {
    getCatalog()
      .then((items) => {
        setCatalog(items);
        setItemType((cur) => cur || items.find((i) => i.item_type === "service_counter")?.item_type || items[0]?.item_type || "");
      })
      .catch((e) => setError(`Catalog: ${e instanceof Error ? e.message : String(e)}`));
  }, []);

  // Throttled cursor readout (pointer events fire every frame).
  useEffect(() => {
    const t = setInterval(() => setCursor(hitRef.current ? { ...hitRef.current } : null), 150);
    return () => clearInterval(t);
  }, []);

  const removeGhost = useCallback(() => {
    ghostRef.current?.object.stop();
    ghostRef.current = null;
  }, []);

  const spawnGhost = useCallback(async () => {
    const sdk = sdkRef.current;
    if (!sdk || !item) return;
    removeGhost();
    // Start hidden below the floor until the cursor reaches the floor, so it doesn't fill the view.
    const at = hitRef.current ?? { x: 0, y: (floorYRef.current ?? 0) - 10, z: 0 };
    ghostRef.current = await placeGlb(sdk, { url: assetUrl(item.glb_asset), position: at, rotationDeg: rotationRef.current });
  }, [item, removeGhost]);

  const drop = useCallback(
    async (where?: Vec3) => {
      const sdk = sdkRef.current;
      if (!sdk || !item) return;
      const pos = where ?? hitRef.current;
      if (!pos) return;
      let model = ghostRef.current;
      ghostRef.current = null;
      if (model) setTransform(model.node, pos, rotationRef.current);
      else model = await placeGlb(sdk, { url: assetUrl(item.glb_asset), position: pos, rotationDeg: rotationRef.current });
      setDropped((d) => [...d, { id: nextId.current++, item, pos: { ...pos }, rotationDeg: rotationRef.current, floorY: floorYRef.current, model: model! }]);
    },
    [item],
  );

  // Ghost follows the cursor while placing; a new ghost spawns after each drop.
  useEffect(() => {
    if (placing && phase === "ready") void spawnGhost();
    else removeGhost();
  }, [placing, phase, spawnGhost, removeGhost, dropped.length]);

  useEffect(() => {
    rotationRef.current = rotation;
    const g = ghostRef.current;
    if (g && hitRef.current) setTransform(g.node, hitRef.current, rotation);
  }, [rotation]);

  // Keyboard inside the tour: the bundle iframe is same-origin, so we can listen to it.
  useEffect(() => {
    if (phase !== "ready") return;
    const doc = iframeRef.current?.contentWindow?.document;
    if (!doc) return;
    const onKey = (e: KeyboardEvent) => {
      if (!placing) return;
      const t = e.target as HTMLElement | null;
      if (t && ["INPUT", "SELECT", "TEXTAREA"].includes(t.tagName)) return;
      if (e.key === "p" || e.key === "P") void drop();
      else if (e.key === "Escape") setPlacing(false);
      else if (e.key === "r" || e.key === "R") setRotation((r) => (r + 90) % 360);
    };
    // Keys work whether focus is in the tour or on this page's controls.
    doc.addEventListener("keydown", onKey);
    window.addEventListener("keydown", onKey);
    return () => {
      doc.removeEventListener("keydown", onKey);
      window.removeEventListener("keydown", onKey);
    };
  }, [phase, placing, drop]);

  async function onIframeLoad() {
    const iframe = iframeRef.current;
    if (!iframe || phase === "no-bundle" || phase === "no-key") return;
    setPhase("loading");
    setError(null);
    try {
      const sdk = await connectBundle(iframe);
      sdkRef.current = sdk;
      await addLights(sdk);
      sdk.Sweep.current.subscribe((s) => {
        const y = s.puckPosition?.y ?? null;
        floorYRef.current = y;
        setSweepFloorY(y);
      });
      sdk.Pointer.intersection.subscribe((hit) => {
        // Only floor-like surfaces of the scanned model (normal pointing up).
        if (hit.object !== COLLIDER_MODEL || hit.normal.y < 0.9) return;
        // Skip table tops and counters: stay within 15 cm of the current sweep's floor.
        const fy = floorYRef.current;
        if (fy != null && Math.abs(hit.position.y - fy) > 0.15) return;
        hitRef.current = { ...hit.position };
        const g = ghostRef.current;
        if (g) setTransform(g.node, hit.position, rotationRef.current);
      });
      setPhase("ready");
    } catch (e) {
      setPhase("error");
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function loadModel() {
    const id = modelInput.trim();
    if (!id || id === modelId) return;
    sdkRef.current = null;
    ghostRef.current = null;
    hitRef.current = null;
    setDropped([]);
    setPlacing(false);
    setPhase("loading");
    setModelId(id);
  }

  function remove(d: Dropped) {
    d.model.object.stop();
    setDropped((list) => list.filter((x) => x.id !== d.id));
  }

  function toggleVisible() {
    const next = !visible;
    dropped.forEach((d) => setVisible(d.model, next));
    setVisibleAll(next);
  }

  const report = dropped.length
    ? dropped
        .map(
          (d) =>
            `${d.item.item_type} (${d.item.width_m}×${d.item.depth_m}×${d.item.height_m} m) at ${fmt(d.pos)}, rot ${d.rotationDeg}°` +
            (d.floorY != null ? `, item y − sweep floor y = ${(d.pos.y - d.floorY).toFixed(3)} m` : "") +
            (measured[d.id] ? `; measured ${measured[d.id]}` : ""),
        )
        .join("\n")
    : "";

  return (
    <div className="grid min-h-dvh gap-3 p-3 xl:h-dvh xl:grid-cols-[minmax(0,1fr)_22rem] xl:overflow-hidden">
      <section aria-label="Matterport tour" className="relative min-h-[60vh] overflow-hidden rounded-2xl border border-border bg-surface-2">
        {phase === "no-key" && (
          <Notice title="No SDK key">
            Set <code>NEXT_PUBLIC_MATTERPORT_SDK_KEY</code> in <code>web/.env.local</code> and restart <code>npm run dev</code>.
          </Notice>
        )}
        {phase === "no-bundle" && (
          <Notice title="Matterport bundle not installed">
            Download the Bundle SDK zip from developers.matterport.com/bundle-sdk and unzip it into <code>web/public/bundle/</code> (see web/README.md).
          </Notice>
        )}
        {phase !== "no-key" && phase !== "no-bundle" && phase !== "checking" && (
          <iframe
            key={modelId}
            ref={iframeRef}
            src={showcaseUrl(modelId, MATTERPORT_SDK_KEY)}
            title="Matterport tour"
            onLoad={onIframeLoad}
            allow="fullscreen; xr-spatial-tracking"
            className="absolute inset-0 size-full"
          />
        )}
        {phase === "loading" && (
          <div className="pointer-events-none absolute top-3 left-3 inline-flex items-center gap-2 rounded-lg bg-black/60 px-3 py-1.5 text-sm text-white">
            <Loader2 className="size-4 animate-spin" /> Loading tour…
          </div>
        )}
        {placing && (
          <div className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 rounded-lg bg-black/70 px-3 py-1.5 text-sm text-white">
            Move over the floor · <b>P</b> place · <b>R</b> rotate 90° · <b>Esc</b> stop
          </div>
        )}
      </section>

      <aside className="space-y-5 overflow-y-auto rounded-2xl border border-border bg-surface p-4">
        <header className="space-y-1">
          <h1 className="text-lg font-semibold">Gate G2: GLB in a Matterport tour</h1>
          <p className="text-sm text-muted text-pretty">
            Drop catalog items on the floor and check they sit on it at real size. Mock GLBs are plain boxes with the catalog
            dimensions, origin at the bottom center.
          </p>
        </header>

        <div className="space-y-1.5">
          <label htmlFor="model" className="text-xs font-semibold tracking-wide text-muted uppercase">
            Model id
          </label>
          <div className="flex gap-2">
            <input
              id="model"
              value={modelInput}
              onChange={(e) => setModelInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadModel()}
              className="min-w-0 flex-1 rounded-lg border border-border bg-background px-2 py-1.5 font-mono text-sm outline-none focus:border-accent"
            />
            <button type="button" onClick={loadModel} className="rounded-lg border border-border px-3 text-sm hover:border-muted">
              Load
            </button>
          </div>
        </div>

        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted">Status</dt>
          <dd className={clsx(phase === "ready" ? "text-good" : phase === "error" ? "text-bad" : "text-muted")}>{phase}</dd>
          <dt className="text-muted">Sweep floor y</dt>
          <dd className="font-mono">{sweepFloorY == null ? "–" : `${sweepFloorY.toFixed(3)} m`}</dd>
          <dt className="text-muted">Cursor (floor)</dt>
          <dd className="font-mono">{cursor ? fmt(cursor) : "–"}</dd>
        </dl>

        {error && (
          <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-2 text-sm text-bad">
            {error}
          </p>
        )}

        <div className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="item" className="text-xs font-semibold tracking-wide text-muted uppercase">
              Item
            </label>
            <select
              id="item"
              value={itemType}
              onChange={(e) => setItemType(e.target.value)}
              className="w-full rounded-lg border border-border bg-background px-2 py-1.5 text-sm"
            >
              {catalog.map((c) => (
                <option key={c.item_type} value={c.item_type}>
                  {c.label} ({c.width_m}×{c.depth_m}×{c.height_m} m)
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="rot" className="text-xs font-semibold tracking-wide text-muted uppercase">
              Rotation {rotation}°
            </label>
            <input id="rot" type="range" min={0} max={359} step={1} value={rotation} onChange={(e) => setRotation(Number(e.target.value))} className="w-full accent-[var(--accent)]" />
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={phase !== "ready" || !item}
              onClick={() => setPlacing((p) => !p)}
              aria-pressed={placing}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50",
                placing ? "bg-accent text-background" : "border border-border hover:border-muted",
              )}
            >
              <Crosshair className="size-4" /> {placing ? "Placing… (Esc)" : "Place on floor"}
            </button>
            <button
              type="button"
              disabled={phase !== "ready" || !item || sweepFloorY == null}
              onClick={() => {
                const sdk = sdkRef.current;
                if (!sdk) return;
                // Under the camera: visible when you look down or switch to dollhouse view.
                sdk.Sweep.current.waitUntil(() => true).then((s) => s.puckPosition && drop(s.puckPosition));
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm hover:border-muted disabled:opacity-50"
            >
              <MapPin className="size-4" /> Drop at my spot
            </button>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">Placed ({dropped.length})</h2>
            {dropped.length > 0 && (
              <button type="button" onClick={toggleVisible} className="inline-flex items-center gap-1 text-sm text-muted hover:text-foreground">
                {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />} {visible ? "Hide" : "Show"} furniture
              </button>
            )}
          </div>
          <ul className="space-y-1.5">
            {dropped.map((d) => (
              <li key={d.id} className="flex items-start justify-between gap-2 rounded-lg border border-border p-2 text-xs">
                <span>
                  <span className="font-medium">{d.item.label}</span>
                  <span className="block font-mono text-muted">
                    {fmt(d.pos)} · {d.rotationDeg}°
                  </span>
                  <span className="block font-mono text-muted">{measured[d.id] ? `measured ${measured[d.id]}` : "loading…"}</span>
                </span>
                <button type="button" onClick={() => remove(d)} aria-label={`Remove ${d.item.label}`} className="text-muted hover:text-bad">
                  <Trash2 className="size-4" />
                </button>
              </li>
            ))}
          </ul>
          {report && (
            <details className="text-xs">
              <summary className="cursor-pointer text-muted">Placement report (paste into the team chat)</summary>
              <pre className="mt-1 rounded-lg bg-surface-2 p-2 whitespace-pre-wrap">{`G2 model ${modelId}\n${report}`}</pre>
            </details>
          )}
        </div>
      </aside>
    </div>
  );
}

function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex size-full min-h-[60vh] items-center justify-center p-6">
      <div className="max-w-md space-y-2 rounded-xl border border-border bg-surface p-4 text-sm">
        <p className="font-semibold">{title}</p>
        <p className="text-muted">{children}</p>
      </div>
    </div>
  );
}
