"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Box, Camera, Eye, EyeOff, Loader2, Map as MapIcon, MapPin, MousePointerClick, PersonStanding } from "lucide-react";
import clsx from "clsx";
import { MATTERPORT_SDK_KEY, assetUrl } from "@/lib/config";
import {
  MODE_DOLLHOUSE,
  MODE_FLOORPLAN,
  MODE_INSIDE,
  TRANSITION_FLY,
  addLights,
  bundleInstalled,
  collection,
  connectBundle,
  measure,
  placeGlb,
  setVisible,
  showcaseUrl,
  viewpointFor,
  yawToward,
  type CameraPose,
  type MpSdk,
  type PlacedModel,
  type SweepInfo,
} from "@/lib/matterport";
import type { Layout, LayoutItem, Room, Space, XZ } from "@/types/schemas";
import { FloorPlan, ZoneLegend, itemName, roomAt } from "@/components/FloorPlan";
import { LayoutViewer3D } from "@/components/LayoutViewer3D";

type Phase = "checking" | "fallback" | "loading" | "ready" | "error";

const TOUR_TIMEOUT_MS = 20_000;
const FLY_MS = 1400;
/** Look a little down at furniture, not at the ceiling line. */
const LOOK_PITCH = -12;

/** What the rest of the page can ask the tour to do. */
export interface TourApi {
  /** Stand somewhere you can see this floor point, facing it. */
  lookAt(x: number, z: number): Promise<void>;
  /** Stand on a viewpoint (scan id = sweep id), optionally facing a floor point. */
  standAt(sid: string, face?: XZ): Promise<void>;
  /** Scroll the tour into view. */
  reveal(): void;
}

/** No real tour: the layout in 3D (Yared's models), with the 2D plan one click away. */
function TourFallback({ layout, rooms, reason }: { layout: Layout | null; rooms?: Room[]; reason: string | null }) {
  const [view, setView] = useState<"3d" | "plan">("3d");
  if (!layout) return <p className="text-xs text-muted">3D tour unavailable{reason ? `: ${reason}` : "."}</p>;
  const tab = (v: "3d" | "plan", label: string) => (
    <button
      type="button"
      onClick={() => setView(v)}
      aria-pressed={view === v}
      className={clsx("rounded-md px-2 py-1", view === v ? "bg-accent-soft text-accent" : "text-muted hover:text-foreground")}
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
      <ZoneLegend layout={layout} />
    </div>
  );
}

const centroid = (poly: XZ[]): XZ => [poly.reduce((s, p) => s + p[0], 0) / poly.length, poly.reduce((s, p) => s + p[1], 0) / poly.length];

function itemsCenter(items: LayoutItem[]): XZ | null {
  if (!items.length) return null;
  return [items.reduce((s, it) => s + it.x_m, 0) / items.length, items.reduce((s, it) => s + it.z_m, 0) / items.length];
}

/**
 * E5: the space's real Matterport tour with the layout's furniture placed in it, next to a live floor plan.
 * One GLB per LayoutItem at (x_m, room floor y, z_m), rotated rotation_deg about +y.
 * The plan drives the tour: click a piece of furniture to look at it, the floor or a room to go there,
 * a dot to stand on that viewpoint; the plan shows where you are and which way you're looking.
 * Falls back to the layout in three.js (gate G2 fallback) when there is no SDK key, no bundle, or no scan.
 */
export function SpaceTour({
  space,
  layout,
  rooms,
  photoSweep,
  onReady,
}: {
  space: Space;
  layout: Layout | null;
  rooms?: Room[];
  /** Viewpoint the photoreal image was made from (HeroImage.source_pano_id's scan id). */
  photoSweep?: string | null;
  onReady?: (api: TourApi | null) => void;
}) {
  const modelId = space.matterport_model_id;
  const rootRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const sdkRef = useRef<MpSdk | null>(null);
  const placedRef = useRef<PlacedModel[]>([]);
  const [sweeps, setSweeps] = useState<SweepInfo[]>([]);
  const [phase, setPhase] = useState<Phase>("checking");
  const [reason, setReason] = useState<string | null>(null);
  const [visible, setVisibleState] = useState(true);
  const [loaded, setLoaded] = useState(0);
  const [placedLayoutId, setPlacedLayoutId] = useState<string | null>(null);
  const [pose, setPose] = useState<CameraPose | null>(null);
  const [selected, setSelected] = useState<LayoutItem | null>(null);
  const [moving, setMoving] = useState(false);

  // Rooms that hold furniture (most items first); the rest of the house isn't worth a button.
  const jumpRooms = useMemo(() => {
    if (!rooms?.length) return [];
    const count = new Map<string, number>();
    for (const it of layout?.items ?? []) count.set(it.room_id, (count.get(it.room_id) ?? 0) + 1);
    const used = rooms.filter((r) => count.has(r.room_id)).sort((a, b) => (count.get(b.room_id) ?? 0) - (count.get(a.room_id) ?? 0));
    return used.length ? used : rooms;
  }, [rooms, layout]);

  // The floor the furniture is on (multi-storey scans): the floor of the viewpoint nearest the furniture.
  const floor = useMemo(() => {
    const c = itemsCenter(layout?.items ?? []);
    if (!c || !sweeps.length) return undefined;
    return viewpointFor(sweeps, c[0], c[1])?.floorInfo?.sequence;
  }, [sweeps, layout]);

  const floorSweeps = useMemo(
    () =>
      sweeps
        .filter((s) => s.alignmentType !== "unaligned" && (floor == null || (s.floorInfo?.sequence ?? floor) === floor))
        .map((s) => ({ sid: s.sid, x: s.position.x, z: s.position.z })),
    [sweeps, floor],
  );

  const photoSpot = useMemo(() => {
    const s = photoSweep ? sweeps.find((w) => w.sid === photoSweep) : undefined;
    return s ? { x: s.position.x, z: s.position.z } : null;
  }, [sweeps, photoSweep]);

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

  const standAt = useCallback(async (sid: string, face?: XZ) => {
    const sdk = sdkRef.current;
    if (!sdk) return;
    const s = sweeps.find((w) => w.sid === sid);
    const rotation = face && s ? { x: LOOK_PITCH, y: yawToward(s.position.x, s.position.z, face[0], face[1]) } : undefined;
    setMoving(true);
    try {
      // Matterport ignores a move to the sweep you're on, so switch back inside first if needed.
      await sdk.Sweep.moveTo(sid, { transition: TRANSITION_FLY, transitionTime: FLY_MS, rotation });
    } catch {
      /* moving while a move is running rejects; the newest click wins next time */
    } finally {
      setMoving(false);
    }
  }, [sweeps]);

  const lookAt = useCallback(
    async (x: number, z: number) => {
      const room = roomAt(rooms, x, z);
      const inside = room ? (px: number, pz: number) => roomAt([room], px, pz) != null : undefined;
      const s = viewpointFor(sweeps, x, z, { inside, floor });
      if (s) await standAt(s.sid, [x, z]);
    },
    [rooms, sweeps, floor, standAt],
  );

  // Hand the page a stable handle once the tour is ready.
  const api = useMemo<TourApi>(
    () => ({
      lookAt,
      standAt,
      reveal: () => rootRef.current?.scrollIntoView({ behavior: "smooth", block: "center" }),
    }),
    [lookAt, standAt],
  );
  useEffect(() => {
    if (phase !== "ready" || !sweeps.length) return;
    onReady?.(api);
    return () => onReady?.(null);
  }, [phase, sweeps, api, onReady]);

  // Live camera pose for the plan's "you are here", throttled to ~8 updates a second.
  useEffect(() => {
    const sdk = sdkRef.current;
    if (phase !== "ready" || !sdk) return;
    let last = 0;
    let pending: CameraPose | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const flush = () => {
      timer = null;
      last = performance.now();
      if (pending) setPose(pending);
    };
    const sub = sdk.Camera.pose.subscribe((p) => {
      pending = { position: { ...p.position }, rotation: { ...p.rotation }, sweep: p.sweep, mode: p.mode };
      if (timer) return;
      timer = setTimeout(flush, Math.max(0, 120 - (performance.now() - last)));
    });
    return () => {
      sub.cancel();
      if (timer) clearTimeout(timer);
    };
  }, [phase]);

  // Place (or re-place, after a feedback round) the layout once the tour is ready.
  useEffect(() => {
    const sdk = sdkRef.current;
    if (phase !== "ready" || !sdk || !sweeps.length) return;
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
      // Start where the photo was taken (so the image and the tour match), else looking at the furniture.
      const c = itemsCenter(layout.items) ?? layout.entrance_xz ?? [0, 0];
      if (photoSweep && sweeps.some((s) => s.sid === photoSweep)) await standAt(photoSweep, c);
      else await lookAt(c[0], c[1]);
    })();
    return () => {
      cancelled = true;
    };
    // `visible` is applied separately; re-placing on toggle would reload every GLB.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, sweeps, layout, placedLayoutId, clearFurniture, floorY]);

  // Dev-only hook for checking placement from the console / tests.
  useEffect(() => {
    if (process.env.NODE_ENV === "production") return;
    const w = window as unknown as { __hestiaTour?: unknown };
    w.__hestiaTour = {
      layoutId: () => placedLayoutId,
      placed: () => placedRef.current.map((m, i) => ({ item: layout?.items[i]?.item_id, box: measure(m) })),
      pose: () => pose,
      api,
    };
    return () => {
      delete w.__hestiaTour;
    };
  }, [layout, placedLayoutId, pose, api]);

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
      // Sweep.data only fills on the first connection to an iframe; Model.getData always works.
      const list = await collection(sdk.Sweep.data, 5000)
        .catch(() => [] as SweepInfo[])
        .then(async (l) => (l.length ? l : (await sdk.Model.getData()).sweeps ?? []));
      setSweeps(list);
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

  const ready = phase === "ready";
  const total = layout?.items.length ?? 0;
  const inside = !pose || pose.mode === MODE_INSIDE;
  const btn =
    "inline-flex items-center gap-1.5 rounded-lg bg-black/60 px-2.5 py-1.5 text-xs text-white backdrop-blur hover:bg-black/75 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50";

  return (
    <div ref={rootRef} className="@container space-y-2">
      <div className="grid gap-3 @3xl:grid-cols-[minmax(0,1fr)_16rem]">
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
          {ready && (
            <div className="absolute top-2 right-2 flex flex-wrap justify-end gap-1.5">
              <button type="button" onClick={toggleFurniture} disabled={!total} className={btn} aria-pressed={visible}>
                {visible ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />} {visible ? "Empty room" : "Show furniture"}
              </button>
              {inside ? (
                <>
                  <button type="button" onClick={() => sdkRef.current?.Mode.moveTo(MODE_DOLLHOUSE).catch(() => {})} className={btn}>
                    <Box className="size-3.5" /> Dollhouse
                  </button>
                  <button type="button" onClick={() => sdkRef.current?.Mode.moveTo(MODE_FLOORPLAN).catch(() => {})} className={btn}>
                    <MapIcon className="size-3.5" /> Top view
                  </button>
                </>
              ) : (
                <button type="button" onClick={() => sdkRef.current?.Mode.moveTo(MODE_INSIDE).catch(() => {})} className={btn}>
                  <PersonStanding className="size-3.5" /> Walk inside
                </button>
              )}
            </div>
          )}
          {ready && total > 0 && loaded < total && (
            <div className="pointer-events-none absolute top-12 left-2 inline-flex items-center gap-2 rounded-lg bg-black/60 px-2.5 py-1.5 text-xs text-white">
              <Loader2 className="size-3.5 animate-spin" /> Placing furniture {loaded}/{total}
            </div>
          )}
          {ready && selected && (
            <div className="pointer-events-none absolute top-12 left-2 rounded-lg bg-black/60 px-2.5 py-1.5 text-xs text-white backdrop-blur" aria-live="polite">
              {moving ? "Going to" : "Looking at"} the <span className="font-medium">{itemName(selected)}</span>
              {` · ${selected.width_m.toFixed(1)} × ${selected.depth_m.toFixed(1)} m`}
              {selected.seats ? ` · ${selected.seats} seats` : ""}
            </div>
          )}
        </div>

        {layout && (
          <div className="space-y-2">
            <p className="flex items-center gap-1.5 text-xs text-muted">
              <MousePointerClick className="size-3.5 shrink-0" />
              {ready ? "Click furniture or the floor to go there" : "Floor plan (the tour is loading)"}
            </p>
            <FloorPlan
              layout={layout}
              rooms={rooms}
              viewpoints={ready ? floorSweeps : undefined}
              you={ready && inside && pose ? { x: pose.position.x, z: pose.position.z, yaw: pose.rotation.y } : null}
              photoSpot={ready ? photoSpot : null}
              selectedId={selected?.item_id}
              onItem={
                ready
                  ? (it) => {
                      setSelected(it);
                      void lookAt(it.x_m, it.z_m);
                    }
                  : undefined
              }
              onPick={
                ready
                  ? (x, z) => {
                      setSelected(null);
                      void lookAt(x, z);
                    }
                  : undefined
              }
              onViewpoint={ready ? (sid) => (setSelected(null), void standAt(sid)) : undefined}
              onPhotoSpot={
                ready && photoSweep
                  ? () => {
                      setSelected(null);
                      void standAt(photoSweep, itemsCenter(layout.items) ?? undefined);
                    }
                  : undefined
              }
              className="max-h-80 w-full rounded-xl border border-border bg-surface-2 @3xl:max-h-[26rem]"
            />
            <ZoneLegend layout={layout} />
            {ready && (
              <ul className="space-y-0.5 text-xs text-muted">
                <li className="inline-flex items-center gap-1.5">
                  <span className="size-2.5 rounded-full bg-accent" aria-hidden /> You, and where you&apos;re looking
                </li>
                {photoSpot && (
                  <li className="flex items-center gap-1.5">
                    <Camera className="size-3.5" /> Where the photo was taken
                  </li>
                )}
                {floorSweeps.length > 0 && (
                  <li className="flex items-center gap-1.5">
                    <span className="size-2 rounded-full bg-muted/60" aria-hidden /> Places you can stand
                  </li>
                )}
              </ul>
            )}
          </div>
        )}
      </div>

      {ready && jumpRooms.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <span className="text-muted">Jump to:</span>
          {jumpRooms.map((r) => (
            <button
              key={r.room_id}
              type="button"
              onClick={() => {
                const [cx, cz] = centroid(r.polygon_m);
                setSelected(null);
                void lookAt(cx, cz);
              }}
              className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 hover:border-muted"
            >
              <MapPin className="size-3" /> {r.label ?? r.room_type ?? r.room_id}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
