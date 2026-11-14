"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Eye, EyeOff, Loader2, Map as MapIcon, MapPin } from "lucide-react";
import clsx from "clsx";
import { MATTERPORT_SDK_KEY, assetUrl } from "@/lib/config";
import {
  MODE_DOLLHOUSE,
  MODE_FLOORPLAN,
  TRANSITION_FLY,
  addLights,
  bundleInstalled,
  collection,
  connectBundle,
  measure,
  nearestSweep,
  placeGlb,
  setVisible,
  showcaseUrl,
  type MpSdk,
  type PlacedModel,
  type SweepInfo,
} from "@/lib/matterport";
import type { Layout, Room, Space, XZ } from "@/types/schemas";
import { FloorPlan } from "@/components/FloorPlan";
import { LayoutViewer3D } from "@/components/LayoutViewer3D";

type Phase = "checking" | "fallback" | "loading" | "ready" | "error";

const TOUR_TIMEOUT_MS = 20_000;

/** No real tour: the layout in 3D (Yared's models), with the 2D plan one click away. */
function TourFallback({ layout, rooms, reason }: { layout: Layout | null; rooms?: Room[]; reason: string | null }) {
  const [view, setView] = useState<"3d" | "plan">("3d");
  if (!layout) return <p className="text-xs text-muted">3D tour unavailable{reason ? `: ${reason}` : "."}</p>;
  const tab = (v: "3d" | "plan", label: string) => (
    <button
      type="button"
      onClick={() => setView(v)}
      aria-pressed={view === v}
      className={clsx("rounded-md px-2 py-1", view === v ? "bg-primary-soft font-medium text-primary" : "text-muted hover:text-foreground")}
    >
      {label}
    </button>
  );
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted">
          Showing the layout without the real scan{reason ? ` (${reason})` : ""}.
        </p>
        <div className="flex gap-1 text-xs" role="group" aria-label="View">
          {tab("3d", "3D")}
          {tab("plan", "Floor plan")}
        </div>
      </div>
      {view === "3d" ? <LayoutViewer3D layout={layout} rooms={rooms} /> : <FloorPlan layout={layout} rooms={rooms} />}
    </div>
  );
}

function insidePolygon(x: number, z: number, poly: XZ[]): boolean {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i];
    const [xj, zj] = poly[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) hit = !hit;
  }
  return hit;
}

const centroid = (poly: XZ[]): XZ => [poly.reduce((s, p) => s + p[0], 0) / poly.length, poly.reduce((s, p) => s + p[1], 0) / poly.length];

/**
 * E5: the space's real Matterport tour with the layout's furniture placed in it.
 * One GLB per LayoutItem at (x_m, room floor y, z_m), rotated rotation_deg about +y.
 * Works for any catalog item_type (bakery, office, ...). Falls back to the 2D floor plan
 * (gate G2 fallback) when there is no SDK key, no bundle, or no scan.
 */
export function SpaceTour({ space, layout, rooms }: { space: Space; layout: Layout | null; rooms?: Room[] }) {
  const modelId = space.matterport_model_id;
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const sdkRef = useRef<MpSdk | null>(null);
  const placedRef = useRef<PlacedModel[]>([]);
  const sweepsRef = useRef<SweepInfo[]>([]);
  const [phase, setPhase] = useState<Phase>("checking");
  const [reason, setReason] = useState<string | null>(null);
  const [visible, setVisibleState] = useState(true);
  const [loaded, setLoaded] = useState(0);
  const [placedLayoutId, setPlacedLayoutId] = useState<string | null>(null);

  // Rooms that hold furniture (most items first); the rest of the house isn't worth a button.
  const jumpRooms = useMemo(() => {
    if (!rooms?.length) return [];
    const count = new Map<string, number>();
    for (const it of layout?.items ?? []) count.set(it.room_id, (count.get(it.room_id) ?? 0) + 1);
    const used = rooms.filter((r) => count.has(r.room_id)).sort((a, b) => (count.get(b.room_id) ?? 0) - (count.get(a.room_id) ?? 0));
    return used.length ? used : rooms;
  }, [rooms, layout]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!modelId || !space.has_scan) return setFallback("This space has no 3D scan.");
      if (!MATTERPORT_SDK_KEY) return setFallback("No Matterport SDK key (NEXT_PUBLIC_MATTERPORT_SDK_KEY).");
      if (!(await bundleInstalled())) return setFallback("Matterport bundle not installed in web/public/bundle.");
      if (!cancelled) setPhase("loading");
    })();
    function setFallback(why: string) {
      if (cancelled) return;
      setReason(why);
      setPhase("fallback");
    }
    return () => {
      cancelled = true;
    };
  }, [modelId, space.has_scan]);

  const clearFurniture = useCallback(() => {
    placedRef.current.forEach((m) => m.object.stop());
    placedRef.current = [];
    setLoaded(0);
  }, []);

  const floorY = useCallback(
    (roomId: string) => rooms?.find((r) => r.room_id === roomId)?.floor_y_m ?? rooms?.[0]?.floor_y_m ?? 0,
    [rooms],
  );

  const jumpTo = useCallback(async (x: number, z: number, poly?: XZ[]) => {
    const sdk = sdkRef.current;
    if (!sdk) return;
    const s = nearestSweep(sweepsRef.current, x, z, poly ? (px, pz) => insidePolygon(px, pz, poly) : undefined);
    if (s) await sdk.Sweep.moveTo(s.sid, { transition: TRANSITION_FLY, transitionTime: 1500 }).catch(() => {});
  }, []);

  // Place (or re-place, after a feedback round) the layout once the tour is ready.
  useEffect(() => {
    const sdk = sdkRef.current;
    if (phase !== "ready" || !sdk) return;
    if (!layout || layout.layout_id === placedLayoutId) return;
    let cancelled = false;
    (async () => {
      // Also removes anything a cancelled earlier pass already placed (they're tracked in placedRef).
      clearFurniture();
      for (const it of layout.items) {
        const m = await placeGlb(sdk, {
          url: assetUrl(it.glb_asset),
          position: { x: it.x_m, y: floorY(it.room_id), z: it.z_m },
          rotationDeg: it.rotation_deg,
        });
        if (cancelled) {
          m.object.stop();
          return;
        }
        if (!visible) setVisible(m, false);
        placedRef.current.push(m);
      }
      setPlacedLayoutId(layout.layout_id);
      // Start where the furniture is, so the business is the first thing you see.
      // Aim at the furniture itself (rooms can be huge, e.g. a whole office floor, and the
      // rooms endpoint may be missing): the viewpoint nearest the first item, which is the
      // service counter / reception for Yared's templates.
      const first = layout.items[0];
      const room = rooms?.find((r) => r.room_id === first?.room_id);
      const [cx, cz]: XZ = first ? [first.x_m, first.z_m] : room ? centroid(room.polygon_m) : layout.entrance_xz ?? [0, 0];
      await jumpTo(cx, cz, room?.polygon_m);
    })();
    return () => {
      cancelled = true;
    };
    // `visible` is applied separately; re-placing on toggle would reload every GLB.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, layout, placedLayoutId, clearFurniture, floorY, jumpTo, rooms]);

  // Dev-only hook for checking placement from the console / tests: measured box of every placed model.
  useEffect(() => {
    if (process.env.NODE_ENV === "production") return;
    const w = window as unknown as { __hestiaTour?: unknown };
    w.__hestiaTour = {
      layoutId: () => placedLayoutId,
      placed: () => placedRef.current.map((m, i) => ({ item: layout?.items[i]?.item_id, box: measure(m) })),
    };
    return () => {
      delete w.__hestiaTour;
    };
  }, [layout, placedLayoutId]);

  // Progress: how many GLBs have finished loading.
  useEffect(() => {
    if (phase !== "ready" || !layout) return;
    const t = setInterval(() => setLoaded(placedRef.current.filter((m) => measure(m)).length), 700);
    return () => clearInterval(t);
  }, [phase, layout, placedLayoutId]);

  // Fail fast when Matterport says the model doesn't exist (fake sample ids, unshared scans):
  // the bundle iframe is same-origin, so we can hear its "Model not found" rejection directly
  // instead of waiting for the timeout behind Matterport's "Oops" screen.
  useEffect(() => {
    if (phase !== "loading") return;
    let win: Window | null = null;
    const onReject = (e: PromiseRejectionEvent) => {
      const msg = String((e.reason as { message?: string } | undefined)?.message ?? e.reason ?? "");
      if (/not\s*found|not available|404/i.test(msg)) {
        setReason(`Matterport has no model ${modelId} for this key`);
        setPhase("error");
      }
    };
    const t = setInterval(() => {
      const w = iframeRef.current?.contentWindow;
      if (w && w !== win) {
        win?.removeEventListener("unhandledrejection", onReject);
        win = w;
        w.addEventListener("unhandledrejection", onReject);
      }
      // The rejection can fire before we attach; Matterport's error page text is the backup signal.
      try {
        if (/model not available/i.test(w?.document?.body?.innerText ?? "")) {
          setReason(`Matterport has no model ${modelId} for this key`);
          setPhase("error");
        }
      } catch {
        /* not same-origin (shouldn't happen with the self-hosted bundle) */
      }
    }, 250);
    return () => {
      clearInterval(t);
      win?.removeEventListener("unhandledrejection", onReject);
    };
  }, [phase, modelId]);

  async function onLoad() {
    const iframe = iframeRef.current;
    if (!iframe || phase === "fallback" || phase === "checking") return;
    try {
      // A model id the key can't open (fake sample ids, unshared scans) never reaches "playing".
      const sdk = await Promise.race([
        connectBundle(iframe),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error(`the tour for model ${modelId} didn't load in time`)), TOUR_TIMEOUT_MS),
        ),
      ]);
      sdkRef.current = sdk;
      await addLights(sdk);
      sweepsRef.current = await collection(sdk.Sweep.data).catch(() => []);
      setPhase("ready");
    } catch (e) {
      setReason(e instanceof Error ? e.message : String(e));
      setPhase("error");
    }
  }

  function toggleFurniture() {
    const next = !visible;
    placedRef.current.forEach((m) => setVisible(m, next));
    setVisibleState(next);
  }

  if (phase === "fallback" || phase === "error") {
    return <TourFallback layout={layout} rooms={rooms} reason={reason} />;
  }

  const total = layout?.items.length ?? 0;
  const btn = "inline-flex items-center gap-1.5 rounded-lg bg-black/60 px-2.5 py-1.5 text-xs text-white backdrop-blur hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";

  return (
    <div className="space-y-2">
      <div className="relative aspect-video overflow-hidden rounded-xl border border-border bg-surface-2">
        {phase !== "checking" && modelId && (
          <iframe
            key={modelId}
            ref={iframeRef}
            src={showcaseUrl(modelId, MATTERPORT_SDK_KEY)}
            title={`3D tour of ${space.address}`}
            onLoad={onLoad}
            allow="fullscreen; xr-spatial-tracking"
            className="absolute inset-0 size-full"
          />
        )}
        {(phase === "checking" || phase === "loading") && (
          <div className="pointer-events-none absolute top-2 left-2 inline-flex items-center gap-2 rounded-lg bg-black/60 px-2.5 py-1.5 text-xs text-white">
            <Loader2 className="size-3.5 animate-spin" /> Loading 3D tour…
          </div>
        )}
        {phase === "ready" && (
          <div className="absolute top-2 right-2 flex flex-wrap justify-end gap-1.5">
            <button type="button" onClick={toggleFurniture} disabled={!total} className={btn} aria-pressed={visible}>
              {visible ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />} {visible ? "Hide" : "Show"} furniture
            </button>
            <button type="button" onClick={() => sdkRef.current?.Mode.moveTo(MODE_DOLLHOUSE).catch(() => {})} className={btn}>
              <Box className="size-3.5" /> Dollhouse
            </button>
            <button type="button" onClick={() => sdkRef.current?.Mode.moveTo(MODE_FLOORPLAN).catch(() => {})} className={btn}>
              <MapIcon className="size-3.5" /> Floor plan
            </button>
          </div>
        )}
        {phase === "ready" && total > 0 && loaded < total && (
          <div className="pointer-events-none absolute bottom-2 left-2 inline-flex items-center gap-2 rounded-lg bg-black/60 px-2.5 py-1.5 text-xs text-white">
            <Loader2 className="size-3.5 animate-spin" /> Placing furniture {loaded}/{total}
          </div>
        )}
      </div>

      {phase === "ready" && jumpRooms.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted">Jump to:</span>
          {jumpRooms.map((r) => (
            <button
              key={r.room_id}
              type="button"
              onClick={() => {
                const [cx, cz] = centroid(r.polygon_m);
                void jumpTo(cx, cz, r.polygon_m);
              }}
              className={clsx("inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 transition-colors hover:border-border-strong hover:text-foreground")}
            >
              <MapPin className="size-3" /> {r.label ?? r.room_type ?? r.room_id}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
