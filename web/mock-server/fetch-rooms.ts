/**
 * Fetch real room outlines from the Matterport Model API for the models the mock uses, so mock
 * layouts line up with the real 3D tour. Output: mock-server/.generated/rooms/<model_id>.json
 * (gitignored: Matterport data is licensed for the hackathon only and must not be committed).
 *
 *   npm run mock:rooms            # credentials from web/.env.local (MATTERPORT_API_TOKEN_ID / _SECRET)
 *
 * This is Natnael's get_rooms() in miniature. Conversions (checked against the model's sweeps):
 *   floor-plan vertex (x, y) -> model (x, z) = (x, -y);  areas/heights come in feet.
 */
import fs from "node:fs";
import path from "node:path";
import type { Opening, Room, XZ } from "../src/types/schemas";
import { GENERATED_DIR, MOCK_DIR } from "./paths";
import { MOCK_MODEL_IDS } from "./fixtures";

const FT = 0.3048;

function loadEnv() {
  const file = path.join(MOCK_DIR, "..", ".env.local");
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, "utf8").split(/\r?\n/)) {
    const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
  }
}

interface ApiEdge {
  type?: string;
  vertices: { position: { x: number; y: number } }[];
  openings?: { type?: string; relativeCenter?: number; width?: number }[] | null;
}
interface ApiRoom {
  id: string;
  label?: string;
  classifications?: { label?: string; defaultKeywords?: string[] }[];
  dimensions?: { areaFloor?: number; height?: number };
  floor?: { sequence?: number };
  boundary?: { edges?: ApiEdge[] };
}

const QUERY = `query ($id: ID!) { model(id: $id) { rooms {
  id label dimensions { areaFloor height } floor { sequence }
  classifications { label defaultKeywords }
  boundary { edges { type vertices { position { x y } } openings { type relativeCenter width } } }
} } }`;

const toModel = (p: { x: number; y: number }): XZ => [p.x, -p.y];
const key = (p: XZ) => `${p[0].toFixed(3)},${p[1].toFixed(3)}`;

/** Chain unordered wall segments into one closed polygon (largest loop wins). */
function polygonFromEdges(edges: ApiEdge[]): XZ[] | null {
  const segs = edges.filter((e) => e.vertices.length === 2).map((e) => [toModel(e.vertices[0].position), toModel(e.vertices[1].position)] as [XZ, XZ]);
  if (segs.length < 3) return null;
  const used = new Set<number>();
  const loops: XZ[][] = [];
  for (let start = 0; start < segs.length; start++) {
    if (used.has(start)) continue;
    used.add(start);
    const loop: XZ[] = [segs[start][0], segs[start][1]];
    for (let guard = 0; guard < segs.length; guard++) {
      const tail = key(loop[loop.length - 1]);
      const next = segs.findIndex((s, i) => !used.has(i) && (key(s[0]) === tail || key(s[1]) === tail));
      if (next === -1) break;
      used.add(next);
      loop.push(key(segs[next][0]) === tail ? segs[next][1] : segs[next][0]);
    }
    if (key(loop[0]) === key(loop[loop.length - 1])) loop.pop();
    loops.push(loop);
  }
  const area = (poly: XZ[]) => Math.abs(poly.reduce((s, p, i) => s + p[0] * poly[(i + 1) % poly.length][1] - poly[(i + 1) % poly.length][0] * p[1], 0)) / 2;
  const best = loops.sort((a, b) => area(b) - area(a))[0];
  return best && best.length >= 3 ? best : null;
}

function openings(edges: ApiEdge[]): Opening[] {
  const out: Opening[] = [];
  for (const e of edges) {
    if (e.vertices.length !== 2) continue;
    const [a, b] = [toModel(e.vertices[0].position), toModel(e.vertices[1].position)];
    const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    for (const o of e.openings ?? []) {
      const c = o.relativeCenter ?? 0.5;
      const half = Math.min((o.width ?? 0.9) / 2, len / 2) / (len || 1);
      const at = (t: number): XZ => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      out.push({ kind: o.type === "window" ? "window" : o.type === "doorway" || o.type === "door" ? "door" : "opening", a: at(Math.max(0, c - half)), b: at(Math.min(1, c + half)) });
    }
  }
  return out;
}

async function fetchRooms(modelId: string): Promise<Omit<Room, "space_id">[]> {
  const id = process.env.MATTERPORT_API_TOKEN_ID;
  const secret = process.env.MATTERPORT_API_TOKEN_SECRET;
  if (!id || !secret) throw new Error("Set MATTERPORT_API_TOKEN_ID and MATTERPORT_API_TOKEN_SECRET in web/.env.local");
  const res = await fetch("https://api.matterport.com/api/models/graph", {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Basic ${Buffer.from(`${id}:${secret}`).toString("base64")}` },
    body: JSON.stringify({ query: QUERY, variables: { id: modelId } }),
  });
  const body = (await res.json()) as { data?: { model?: { rooms?: ApiRoom[] } }; errors?: { message: string }[] };
  if (body.errors?.length) throw new Error(body.errors.map((e) => e.message).join("; "));
  const rooms: Omit<Room, "space_id">[] = [];
  for (const r of body.data?.model?.rooms ?? []) {
    const kw = r.classifications?.flatMap((c) => c.defaultKeywords ?? []) ?? [];
    if (kw.includes("nonArea") || kw.includes("hide")) continue;
    const edges = r.boundary?.edges ?? [];
    const polygon = polygonFromEdges(edges);
    if (!polygon) continue;
    const label = r.label ?? r.classifications?.find((c) => c.label)?.label ?? null;
    rooms.push({
      room_id: r.id,
      label,
      room_type: label,
      floor_index: r.floor?.sequence ?? 0,
      polygon_m: polygon.map(([x, z]) => [Math.round(x * 1000) / 1000, Math.round(z * 1000) / 1000]),
      floor_y_m: 0,
      ceiling_m: r.dimensions?.height ? Math.round(r.dimensions.height * FT * 100) / 100 : null,
      area_m2: r.dimensions?.areaFloor ? Math.round(r.dimensions.areaFloor * FT * FT * 10) / 10 : 0,
      openings: openings(edges),
    });
  }
  return rooms;
}

async function main() {
  loadEnv();
  const dir = path.join(GENERATED_DIR, "rooms");
  fs.mkdirSync(dir, { recursive: true });
  for (const modelId of MOCK_MODEL_IDS) {
    const rooms = await fetchRooms(modelId);
    fs.writeFileSync(path.join(dir, `${modelId}.json`), JSON.stringify(rooms, null, 2));
    console.log(`${modelId}: ${rooms.length} rooms -> .generated/rooms/${modelId}.json`);
    for (const r of rooms) console.log(`  ${r.room_id.slice(0, 8)} ${r.label ?? "(no label)"} ${r.area_m2} m², ${r.polygon_m.length} corners, ${r.openings.length} openings`);
  }
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
