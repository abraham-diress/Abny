/**
 * Stand-in for Yared's `assets/catalog.json` + `assets/glb/*.glb` (README R2, R10).
 * Writes the same files in the same layout under mock-server/.generated/assets/.
 * When the real <repo>/assets/catalog.json exists, loadCatalog() returns that instead.
 */
import fs from "node:fs";
import path from "node:path";
import type { BusinessType, CatalogItem } from "../../src/types/schemas";
import { buildBoxGlb } from "../glb";
import { MOCK_ASSETS_DIR, REAL_ASSETS_DIR } from "../paths";

type Seed = Pick<CatalogItem, "item_type" | "label" | "width_m" | "depth_m" | "height_m" | "zone"> &
  Partial<Pick<CatalogItem, "clearance_front_m" | "seats">> & { color: [number, number, number]; types: BusinessType[] };

const BAKERY: BusinessType[] = ["bakery", "cafe"];
const OFFICE: BusinessType[] = ["office"];

/** Real-world sizes in meters. `seats` = customer seats (bakery) or desks (office); meeting tables count 0. */
const SEEDS: Seed[] = [
  { types: BAKERY, item_type: "display_case", label: "Display case", width_m: 1.8, depth_m: 0.7, height_m: 1.2, zone: "service", clearance_front_m: 0.9, color: [0.85, 0.9, 0.95] },
  { types: BAKERY, item_type: "service_counter", label: "Service counter", width_m: 2.4, depth_m: 0.8, height_m: 1.0, zone: "service", clearance_front_m: 1.0, color: [0.72, 0.5, 0.3] },
  { types: BAKERY, item_type: "deck_oven", label: "Deck oven", width_m: 1.4, depth_m: 1.1, height_m: 1.8, zone: "back_of_house", clearance_front_m: 1.0, color: [0.35, 0.35, 0.38] },
  { types: BAKERY, item_type: "prep_table", label: "Prep table", width_m: 1.8, depth_m: 0.8, height_m: 0.9, zone: "back_of_house", clearance_front_m: 0.9, color: [0.75, 0.75, 0.78] },
  { types: BAKERY, item_type: "sink", label: "Three-bay sink", width_m: 1.2, depth_m: 0.7, height_m: 1.0, zone: "back_of_house", clearance_front_m: 0.9, color: [0.6, 0.65, 0.7] },
  { types: BAKERY, item_type: "proofing_rack", label: "Proofing rack", width_m: 0.7, depth_m: 0.8, height_m: 1.8, zone: "back_of_house", clearance_front_m: 0.7, color: [0.5, 0.5, 0.55] },
  { types: BAKERY, item_type: "table_2", label: "Table for 2", width_m: 0.7, depth_m: 0.7, height_m: 0.75, zone: "seating", seats: 2, clearance_front_m: 0.6, color: [0.8, 0.62, 0.4] },
  { types: BAKERY, item_type: "bench_table_4", label: "Bench table for 4", width_m: 1.6, depth_m: 0.8, height_m: 0.75, zone: "seating", seats: 4, clearance_front_m: 0.6, color: [0.66, 0.48, 0.3] },
  { types: BAKERY, item_type: "chair", label: "Chair", width_m: 0.45, depth_m: 0.45, height_m: 0.9, zone: "seating", seats: 1, clearance_front_m: 0.3, color: [0.55, 0.4, 0.28] },
  { types: BAKERY, item_type: "menu_board", label: "Menu board", width_m: 1.0, depth_m: 0.1, height_m: 1.5, zone: "front_of_house", color: [0.12, 0.12, 0.14] },
  { types: OFFICE, item_type: "desk_pod_4", label: "Desk pod (4)", width_m: 2.8, depth_m: 1.6, height_m: 0.75, zone: "seating", seats: 4, clearance_front_m: 0.9, color: [0.85, 0.83, 0.78] },
  { types: OFFICE, item_type: "single_desk", label: "Single desk", width_m: 1.4, depth_m: 0.7, height_m: 0.75, zone: "seating", seats: 1, clearance_front_m: 0.9, color: [0.8, 0.78, 0.72] },
  { types: OFFICE, item_type: "meeting_table", label: "Meeting table", width_m: 3.0, depth_m: 1.2, height_m: 0.75, zone: "front_of_house", clearance_front_m: 0.9, color: [0.45, 0.33, 0.24] },
  { types: OFFICE, item_type: "reception_desk", label: "Reception desk", width_m: 2.0, depth_m: 0.8, height_m: 1.05, zone: "entrance", clearance_front_m: 1.2, color: [0.93, 0.93, 0.93] },
  { types: OFFICE, item_type: "sofa", label: "Sofa", width_m: 2.0, depth_m: 0.9, height_m: 0.8, zone: "entrance", clearance_front_m: 0.6, color: [0.3, 0.42, 0.5] },
  { types: OFFICE, item_type: "phone_booth", label: "Phone booth", width_m: 1.0, depth_m: 1.0, height_m: 2.2, zone: "front_of_house", clearance_front_m: 0.9, color: [0.2, 0.45, 0.4] },
  { types: OFFICE, item_type: "storage", label: "Storage cabinet", width_m: 1.2, depth_m: 0.5, height_m: 2.0, zone: "back_of_house", clearance_front_m: 0.8, color: [0.62, 0.62, 0.6] },
  { types: OFFICE, item_type: "kitchenette_counter", label: "Kitchenette", width_m: 3.0, depth_m: 0.65, height_m: 0.9, zone: "back_of_house", clearance_front_m: 1.0, color: [0.7, 0.66, 0.6] },
];

/** Plan/guide color per item type (0..1 RGB). */
export const ITEM_COLORS: Record<string, [number, number, number]> = Object.fromEntries(SEEDS.map((s) => [s.item_type, s.color]));

export const MOCK_CATALOG: CatalogItem[] = SEEDS.map((s) => ({
  item_type: s.item_type,
  label: s.label,
  glb_asset: `assets/glb/${s.item_type}.glb`,
  width_m: s.width_m,
  depth_m: s.depth_m,
  height_m: s.height_m,
  clearance_front_m: s.clearance_front_m ?? 0,
  seats: s.seats ?? 0,
  zone: s.zone,
  business_types: s.types,
}));

/** Write assets/catalog.json and one box GLB per item (bottom-center origin, meters, front +z). */
export function writeMockAssets(dir = MOCK_ASSETS_DIR) {
  fs.mkdirSync(path.join(dir, "glb"), { recursive: true });
  fs.writeFileSync(path.join(dir, "catalog.json"), JSON.stringify(MOCK_CATALOG, null, 2));
  for (const s of SEEDS) fs.writeFileSync(path.join(dir, "glb", `${s.item_type}.glb`), buildBoxGlb(s.width_m, s.height_m, s.depth_m, s.color));
}

export type CatalogSource = "real" | "mock";

/** Yared's real catalog if it exists, else the mock one. */
export function loadCatalog(): { items: CatalogItem[]; source: CatalogSource } {
  const real = path.join(REAL_ASSETS_DIR, "catalog.json");
  if (fs.existsSync(real)) {
    try {
      return { items: JSON.parse(fs.readFileSync(real, "utf8")) as CatalogItem[], source: "real" };
    } catch (e) {
      console.warn(`Could not read ${real}, using the mock catalog:`, e);
    }
  }
  return { items: MOCK_CATALOG, source: "mock" };
}

/** Catalog entry by type: the real catalog first, then the mock one (so mock layouts never reference a missing item). */
export function catalogItem(type: string): CatalogItem {
  const item = loadCatalog().items.find((c) => c.item_type === type) ?? MOCK_CATALOG.find((c) => c.item_type === type);
  if (!item) throw new Error(`Unknown catalog item_type: ${type}`);
  return item;
}
