// MapLibre 6 loads its tile worker from a separate file, which the Next.js bundler doesn't serve.
// Copy it into public/ (gitignored) so the map can load it from /maplibre-gl-worker.mjs.
// Runs on `npm install` (postinstall) and before `dev` / `build`.
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(web, "node_modules", "maplibre-gl", "dist", "maplibre-gl-worker.mjs");
const dest = join(web, "public", "maplibre-gl-worker.mjs");
if (!existsSync(src)) {
  console.warn("maplibre-gl not installed yet; skipping worker copy");
} else {
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(src, dest);
}
