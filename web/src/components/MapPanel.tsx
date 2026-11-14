"use client";

import { useEffect, useRef, useState } from "react";
import "maplibre-gl/dist/maplibre-gl.css";
import type { LngLatBounds as LngLatBoundsT, Map as MapT, Marker as MarkerT, StyleSpecification } from "maplibre-gl";
import { isOffice } from "@/lib/business";
import { MAP_STYLE, assetUrl } from "@/lib/config";
import { pct } from "@/lib/format";
import type { CandidateResult, POI } from "@/types/schemas";

/** Used when the basemap can't load (offline demo, DEMO=1): a plain background, pins still work. */
const OFFLINE_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "bg", type: "background", paint: { "background-color": "#ebe8e1" } }],
};

const POI_COLORS: Record<string, string> = { competitor: "#c0262d", amenity: "#0f766e", transit: "#2563eb" };

async function styleReachable(url: string): Promise<boolean> {
  if (!url || url === "offline") return false;
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 3000);
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(t);
    return res.ok;
  } catch {
    return false;
  }
}

/** The default OpenFreeMap style has a dark sibling; a custom MAP_STYLE is used as-is in both themes. */
function themedStyle(url: string): string {
  const dark = typeof document !== "undefined" && document.documentElement.getAttribute("data-theme") === "dark";
  return dark && /\/styles\/liberty$/.test(url) ? url.replace(/liberty$/, "dark") : url;
}

function rankColor(rank: number): string {
  // Rank 1 strongest, fading down the list.
  return ["#e0531c", "#ea6a2e", "#ef8540", "#f29f4f", "#f5b963"][Math.min(rank - 1, 4)] ?? "#f5b963";
}

function candidateEl(r: CandidateResult, selected: boolean, onClick: () => void): HTMLElement {
  const el = document.createElement("button");
  el.type = "button";
  el.textContent = String(r.rank);
  el.setAttribute("aria-label", `#${r.rank} ${r.space.address}`);
  el.title = `#${r.rank} ${r.space.address}`;
  const size = selected ? 34 : 26;
  Object.assign(el.style, {
    width: `${size}px`,
    height: `${size}px`,
    borderRadius: "9999px",
    background: rankColor(r.rank),
    color: r.rank <= 3 ? "#ffffff" : "#1a0c05",
    fontWeight: "700",
    fontSize: selected ? "15px" : "12px",
    border: selected ? "3px solid #17150f" : "2px solid #fff",
    boxShadow: "0 1px 4px rgba(0,0,0,.4)",
    cursor: "pointer",
    zIndex: selected ? "2" : "1",
  });
  el.addEventListener("click", (e) => {
    e.stopPropagation();
    onClick();
  });
  return el;
}

function poiEl(p: POI): HTMLElement {
  const el = document.createElement("div");
  el.title = `${p.name} · ${p.kind} · ${Math.round(p.distance_m)} m`;
  el.setAttribute("aria-label", el.title);
  el.setAttribute("role", "img");
  Object.assign(el.style, {
    width: "12px",
    height: "12px",
    borderRadius: p.kind === "transit" ? "3px" : "9999px",
    background: POI_COLORS[p.kind] ?? "#6b7280",
    border: "2px solid #fff",
    boxShadow: "0 1px 3px rgba(0,0,0,.4)",
  });
  return el;
}

/**
 * E6: candidate pins colored by rank (click → that space opens), plus the selected space's
 * neighborhood: competitors (bakery) or amenities (office), and transit. Aerial crop in the corner.
 */
/** Where to look before there are results (the brief's city). */
const CITY_CENTER: Record<string, [number, number]> = { Houston: [-95.39, 29.75], "Los Angeles": [-118.27, 34.05] };

export function MapPanel({
  results,
  selectedId,
  onSelect,
  city,
}: {
  results: CandidateResult[];
  selectedId: string | null;
  onSelect: (spaceId: string) => void;
  city?: string | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapT | null>(null);
  const libRef = useRef<typeof import("maplibre-gl") | null>(null);
  const markersRef = useRef<MarkerT[]>([]);
  const fittedKeyRef = useRef("");
  const [ready, setReady] = useState(false);
  const [offline, setOffline] = useState(false);

  // Create the map once (maplibre touches `window`, so it's loaded on the client only).
  useEffect(() => {
    let cancelled = false;
    let themeObserver: MutationObserver | null = null;
    (async () => {
      const [lib, online] = await Promise.all([import("maplibre-gl"), styleReachable(MAP_STYLE)]);
      if (cancelled || !containerRef.current) return;
      libRef.current = lib;
      // The worker file is copied to public/ by scripts/copy-maplibre-worker.mjs.
      lib.setWorkerUrl("/maplibre-gl-worker.mjs");
      const map = new lib.Map({
        container: containerRef.current,
        style: online ? themedStyle(MAP_STYLE) : OFFLINE_STYLE,
        center: [-95.39, 29.75],
        zoom: 11,
        attributionControl: { compact: true },
      });
      map.addControl(new lib.NavigationControl({ showCompass: false }), "top-right");
      map.on("load", () => !cancelled && setReady(true));
      map.on("error", (e) => console.warn("map error", e.error?.message ?? e));
      if (process.env.NODE_ENV !== "production") (window as unknown as { __hestiaMap?: MapT }).__hestiaMap = map;
      mapRef.current = map;
      setOffline(!online);
      // Swap the basemap when the theme toggles (markers are DOM elements, so they survive setStyle).
      if (online) {
        let current = themedStyle(MAP_STYLE);
        themeObserver = new MutationObserver(() => {
          const next = themedStyle(MAP_STYLE);
          if (next !== current) {
            current = next;
            map.setStyle(next);
          }
        });
        themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
      }
    })();
    return () => {
      cancelled = true;
      themeObserver?.disconnect();
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  const selected = results.find((r) => r.space.space_id === selectedId) ?? null;

  // Pins: redraw when results or the selection change.
  useEffect(() => {
    const map = mapRef.current;
    const lib = libRef.current;
    if (!ready || !map || !lib) return;
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    const poiList: POI[] = selected?.neighborhood
      ? [...(isOffice(selected) ? selected.neighborhood.amenities : selected.neighborhood.competitors), ...selected.neighborhood.transit]
      : [];
    for (const p of poiList) markersRef.current.push(new lib.Marker({ element: poiEl(p) }).setLngLat([p.lon, p.lat]).addTo(map));
    // Candidates last so they sit on top; the selected one above the rest.
    for (const r of [...results].sort((a, b) => Number(a.space.space_id === selectedId) - Number(b.space.space_id === selectedId))) {
      const el = candidateEl(r, r.space.space_id === selectedId, () => onSelect(r.space.space_id));
      markersRef.current.push(new lib.Marker({ element: el }).setLngLat([r.space.lon, r.space.lat]).addTo(map));
    }
  }, [ready, results, selectedId, selected, onSelect]);

  // Fit all candidates when the set of results changes (not on every selection).
  useEffect(() => {
    const map = mapRef.current;
    const lib = libRef.current;
    if (!ready || !map || !lib || results.length === 0) return;
    const key = results.map((r) => r.space.space_id).sort().join("|");
    if (key === fittedKeyRef.current) return;
    fittedKeyRef.current = key;
    const b: LngLatBoundsT = new lib.LngLatBounds();
    results.forEach((r) => b.extend([r.space.lon, r.space.lat]));
    map.fitBounds(b, { padding: 50, maxZoom: 15, duration: 600 });
  }, [ready, results]);

  // No results yet: show the brief's city.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || results.length || !city || !CITY_CENTER[city]) return;
    map.easeTo({ center: CITY_CENTER[city], zoom: 11, duration: 600 });
  }, [ready, city, results.length]);

  // Zoom in on the selected space and its neighborhood.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !selected) return;
    map.easeTo({ center: [selected.space.lon, selected.space.lat], zoom: Math.max(map.getZoom(), 14), duration: 600 });
  }, [ready, selected]);

  const office = selected ? isOffice(selected) : false;
  const n = selected?.neighborhood;
  const aerial = n?.aerial_ortho_path;

  return (
    <div className="relative h-72 overflow-hidden rounded-xl border border-border bg-surface-2 sm:h-80">
      {/* Explicit size: maplibre's CSS makes the container position:relative, so inset-0 wouldn't size it. */}
      <div ref={containerRef} className="h-full w-full" aria-label="Map of candidate spaces" role="region" />

      <div className="pointer-events-none absolute top-2 left-2 space-y-1 rounded-lg border border-border bg-surface/90 px-2.5 py-2 text-[11px] text-foreground shadow-sm backdrop-blur">
        <p className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-full border-2 border-white" style={{ background: rankColor(1) }} /> Candidates (by rank)
        </p>
        {n && (
          <>
            <p className="flex items-center gap-1.5">
              <span className="inline-block size-2.5 rounded-full" style={{ background: office ? POI_COLORS.amenity : POI_COLORS.competitor }} />
              {office ? `Amenities (${n.amenities.length})` : `Competitors (${n.competitors.length})`}
            </p>
            <p className="flex items-center gap-1.5">
              <span className="inline-block size-2.5 rounded-sm" style={{ background: POI_COLORS.transit }} /> Transit ({n.transit.length})
            </p>
          </>
        )}
        {offline && <p className="text-muted">Offline: no street map</p>}
      </div>

      {aerial && (
        <figure className="absolute bottom-2 left-2 w-36 overflow-hidden rounded-lg border border-border bg-surface shadow-sm">
          {/* eslint-disable-next-line @next/next/no-img-element -- served by the API, not optimized by Next */}
          <img src={assetUrl(aerial)} alt={`Aerial view of ${selected?.space.address}`} className="aspect-[4/3] w-full object-cover" />
          <figcaption className="px-1.5 py-1 text-[10px] text-muted">
            Aerial{n?.parking_score != null ? ` · parking ${pct(n.parking_score)}` : ""}
          </figcaption>
        </figure>
      )}

      {results.length === 0 && (
        <p className="pointer-events-none absolute inset-x-0 bottom-3 text-center text-xs text-muted">Candidates appear here as they&apos;re found.</p>
      )}
    </div>
  );
}
