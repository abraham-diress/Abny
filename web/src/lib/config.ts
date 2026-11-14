/** Base URL of the Hestia API (FastAPI server, or `npm run mock`). */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/+$/, "");

/** Matterport Showcase SDK key. Empty means the 3D tour falls back to the 2D floor plan. */
export const MATTERPORT_SDK_KEY = process.env.NEXT_PUBLIC_MATTERPORT_SDK_KEY ?? "";

/**
 * MapLibre style URL for the map (E6). Default: OpenFreeMap (free, no key, needs internet).
 * Set to "offline" for the demo without Wi-Fi: pins on a plain background.
 */
export const MAP_STYLE = process.env.NEXT_PUBLIC_MAP_STYLE ?? "https://tiles.openfreemap.org/styles/liberty";

/**
 * Schemas store file references as paths relative to the API root (`media/...`, `assets/...`).
 * Turn one into a loadable URL.
 */
export function assetUrl(path: string): string {
  return `${API_BASE}/${path.replace(/^\/+/, "")}`;
}
