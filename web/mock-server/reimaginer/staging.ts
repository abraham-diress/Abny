/**
 * Mock of Yared's staging functions (README R6–R8), with the same names, inputs and outputs:
 *   render_guide(layout, pano) -> str          writes media/guides/<layout_id>.png
 *   render_hero(space_id, layout, style) -> HeroImage   writes media/heroes/<hero_id>.png
 *   score_image(original, generated, layout, guide) -> ImageScore
 * The real guide projects item boxes onto a panorama and the real hero comes from Nova Canvas.
 * Here the guide is a top-down plan (the UI fallback R6 also asks for) and the hero is a flat-shaded
 * view from the entrance, so the UI has real PNG files at the real paths.
 */
import fs from "node:fs";
import path from "node:path";
import type { HeroImage, ImageScore, Layout, PanoRef, XZ } from "../../src/types/schemas";
import { MOCK_MEDIA_DIR } from "../paths";
import { Raster, type RGB } from "../png";
import { ITEM_COLORS } from "./catalog";
import { footprint } from "./geometry";

const toRgb = (c: [number, number, number] | undefined): RGB => (c ? (c.map((v) => Math.round(v * 255)) as RGB) : [150, 150, 150]);

function write(rel: string, png: Buffer): string {
  const file = path.join(MOCK_MEDIA_DIR, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, png);
  return `media/${rel.replace(/\\/g, "/")}`;
}

function bounds(layout: Layout) {
  const pts: XZ[] = layout.items.flatMap((it) => footprint(it));
  if (layout.entrance_xz) pts.push(layout.entrance_xz);
  const xs = pts.map((p) => p[0]);
  const zs = pts.map((p) => p[1]);
  const pad = 0.4;
  return { x0: Math.min(...xs) - pad, z0: Math.min(...zs) - pad, x1: Math.max(...xs) + pad, z1: Math.max(...zs) + pad };
}

/** Top-down plan: x right, z down (entrance at the bottom), one color per item type. */
export function renderGuide(layout: Layout, pano: PanoRef | null = null): string {
  const b = bounds(layout);
  const W = 800;
  const scale = (W - 40) / (b.x1 - b.x0);
  const H = Math.round((b.z1 - b.z0) * scale + 40);
  const r = new Raster(W, H, [245, 243, 238]);
  const px = ([x, z]: XZ): [number, number] => [20 + (x - b.x0) * scale, 20 + (z - b.z0) * scale];
  r.fillRect(20, 20, W - 40, H - 40, [228, 224, 214]);
  for (const it of layout.items) {
    const fp = footprint(it).map(px);
    r.fillPolygon(fp, toRgb(ITEM_COLORS[it.item_type]));
    // Front edge (+z side before rotation) drawn darker so orientation is visible.
    const [, , c2, c3] = fp;
    r.fillPolygon([c3, c2, [c2[0] + 0.01, c2[1] + 3], [c3[0], c3[1] + 3]], [40, 40, 40], 0.6);
  }
  if (layout.entrance_xz) {
    const [ex, ez] = px(layout.entrance_xz);
    r.fillRect(ex - 18, ez - 4, 36, 8, [76, 154, 106]);
  }
  void pano; // the real guide uses the pano's camera pose
  return write(`guides/${layout.layout_id}.png`, r.toPng());
}

/** Flat-shaded view from just outside the entrance, looking into the space (-z). */
function renderView(layout: Layout, style: "bakery" | "office"): Raster {
  const W = 1280;
  const H = 720;
  const r = new Raster(W, H);
  r.gradient(style === "office" ? [226, 232, 238] : [244, 232, 214], style === "office" ? [196, 206, 214] : [222, 200, 170]);
  const b = bounds(layout);
  const [ex, ez] = layout.entrance_xz ?? [(b.x0 + b.x1) / 2, b.z1];
  const camZ = ez + 1.5;
  const camH = 1.7;
  const F = 620;
  const horizon = H * 0.38;
  const proj = (x: number, y: number, z: number): [number, number] => {
    const depth = Math.max(0.6, camZ - z);
    return [W / 2 + ((x - ex) * F) / depth, horizon + ((camH - y) * F) / depth];
  };
  // Floor and back wall.
  const floor: RGB = style === "office" ? [176, 170, 160] : [184, 140, 98];
  r.fillPolygon([proj(b.x0, 0, b.z0), proj(b.x1, 0, b.z0), proj(b.x1, 0, ez), proj(b.x0, 0, ez)], floor);
  r.fillPolygon([proj(b.x0, 3, b.z0), proj(b.x1, 3, b.z0), proj(b.x1, 0, b.z0), proj(b.x0, 0, b.z0)], style === "office" ? [236, 238, 240] : [246, 240, 228]);
  // Items far to near so nearer ones paint over.
  const items = [...layout.items].sort((a, c) => a.z_m - c.z_m);
  for (const it of items) {
    const fp = footprint(it);
    const base = toRgb(ITEM_COLORS[it.item_type]);
    const shade = (k: number): RGB => base.map((v) => Math.min(255, Math.round(v * k))) as RGB;
    // Shadow, top face, then the face toward the camera (largest z edge).
    r.fillPolygon(fp.map(([x, z]) => proj(x + 0.05, 0, z + 0.05)), [0, 0, 0], 0.18);
    const edges = fp.map((p, i) => [p, fp[(i + 1) % 4]] as [XZ, XZ]).sort((e1, e2) => e2[0][1] + e2[1][1] - (e1[0][1] + e1[1][1]));
    for (const [k, [a, c]] of edges.slice(0, 2).entries()) {
      r.fillPolygon([proj(a[0], it.height_m, a[1]), proj(c[0], it.height_m, c[1]), proj(c[0], 0, c[1]), proj(a[0], 0, a[1])], shade(k === 0 ? 0.82 : 0.68));
    }
    r.fillPolygon(fp.map(([x, z]) => proj(x, it.height_m, z)), shade(1.08));
  }
  return r;
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0) / 4294967295;
}

/** Deterministic scores in a plausible range; `passed` uses the thresholds Yared's scorer will apply. */
export function scoreImage(originalPath: string, generatedPath: string, layout: Layout, guidePath: string | null = null): ImageScore {
  const h = hash(generatedPath + layout.layout_id);
  const structure = Math.round((0.86 + h * 0.11) * 100) / 100;
  const plan = Math.round((0.78 + ((h * 7) % 1) * 0.17) * 100) / 100;
  const realism = Math.round((3.6 + ((h * 13) % 1) * 0.9) * 10) / 10;
  void originalPath;
  void guidePath;
  return {
    structure_preserved: structure,
    plan_adherence: plan,
    realism_1to5: realism,
    passed: structure >= 0.85 && plan >= 0.75 && realism >= 3.5,
    notes: ["Mock score (web/mock-server/reimaginer)."],
  };
}

export function renderHero(spaceId: string, layout: Layout, style: string | null = null): HeroImage {
  const kind = layout.business_type === "office" ? "office" : "bakery";
  const sourcePano = `${spaceId}_pano_1`;
  const guidePath = renderGuide(layout, null);
  const heroId = `${layout.layout_id}_hero`;
  const heroPath = write(`heroes/${heroId}.png`, renderView(layout, kind).toPng());
  const prompt = kind === "office" ? `A modern open-plan office, ${style ?? "bright, plants and light wood"}` : `A warm artisan bakery, ${style ?? "wood and white tile"}`;
  return {
    hero_id: heroId,
    space_id: spaceId,
    layout_id: layout.layout_id,
    path: heroPath,
    source_pano_id: sourcePano,
    guide_path: guidePath,
    model: "mock-renderer",
    prompt,
    attempt: 1,
    score: scoreImage(`media/panos/${spaceId}/${sourcePano}.jpg`, heroPath, layout, guidePath),
  };
}
