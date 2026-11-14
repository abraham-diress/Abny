/**
 * Mock of Yared's `agent/layout/planner.py: plan_layout(space_id, rooms, inspection, brief, strategy=None) -> Layout`.
 *
 * Greedy rule templates per business type (README R3, R10), much simpler than the real planner:
 * - the biggest usable room is the main room; its template is turned to face the room's entrance
 *   (a door opening, else the middle of the bounding box's +z side);
 * - every candidate item is kept only if it `fits` (inside the room, no overlap, aisles ≥ 0.914 m
 *   or pushed together, entrance clear), so it adapts to small or odd-shaped real rooms;
 * - seating / desks that don't fit spill into the next biggest usable rooms.
 */
import type { Brief, Inspection, Layout, LayoutItem, Room, XZ } from "../../src/types/schemas";
import { catalogItem } from "./catalog";
import { fits } from "./validator";

const UTILITY = /bath|closet|hall|stair|garage|laundry|utility|toilet|storage/i;

type Front = "+z" | "-z" | "+x" | "-x";

/** A room's local frame: u across, v from the back wall (0) to the entrance side (d). */
interface Frame {
  room: Room;
  w: number;
  d: number;
  /** Local (u, v) -> model (x, z). */
  toModel(u: number, v: number): XZ;
  /** Local rotation (0 = front faces the entrance side) -> model rotation_deg. */
  rot(local: number): number;
  entrance: XZ;
  entranceU: number;
}

function bbox(poly: XZ[]) {
  const xs = poly.map((p) => p[0]);
  const zs = poly.map((p) => p[1]);
  return { x0: Math.min(...xs), x1: Math.max(...xs), z0: Math.min(...zs), z1: Math.max(...zs) };
}

function frame(room: Room, entranceHint?: XZ): Frame {
  const b = bbox(room.polygon_m);
  const door = room.openings.find((o) => o.kind === "door");
  const entrance: XZ = entranceHint ?? (door ? [(door.a[0] + door.b[0]) / 2, (door.a[1] + door.b[1]) / 2] : [(b.x0 + b.x1) / 2, b.z1]);
  // Which bounding-box side is the entrance on?
  const dist: Record<Front, number> = { "+z": Math.abs(b.z1 - entrance[1]), "-z": Math.abs(entrance[1] - b.z0), "+x": Math.abs(b.x1 - entrance[0]), "-x": Math.abs(entrance[0] - b.x0) };
  const front = (Object.keys(dist) as Front[]).sort((p, q) => dist[p] - dist[q])[0];
  const W = b.x1 - b.x0;
  const D = b.z1 - b.z0;
  const f = {
    "+z": { w: W, d: D, toModel: (u: number, v: number): XZ => [b.x0 + u, b.z0 + v], theta: 0, eu: entrance[0] - b.x0 },
    "-z": { w: W, d: D, toModel: (u: number, v: number): XZ => [b.x1 - u, b.z1 - v], theta: 180, eu: b.x1 - entrance[0] },
    "+x": { w: D, d: W, toModel: (u: number, v: number): XZ => [b.x0 + v, b.z1 - u], theta: 90, eu: b.z1 - entrance[1] },
    "-x": { w: D, d: W, toModel: (u: number, v: number): XZ => [b.x1 - v, b.z0 + u], theta: -90, eu: entrance[1] - b.z0 },
  }[front];
  return { room, w: f.w, d: f.d, toModel: f.toModel, rot: (r) => (((r + f.theta) % 360) + 360) % 360, entrance, entranceU: f.eu };
}

class Placer {
  items: LayoutItem[] = [];
  private n = 0;
  constructor(private spaceId: string, private entrance: XZ) {}

  /** Try to place `type` at local (u, v) in frame `f`; returns the item if it fits. */
  tryPlace(f: Frame, type: string, u: number, v: number, localRot = 0): LayoutItem | null {
    const c = catalogItem(type);
    const [x, z] = f.toModel(u, v);
    const it: LayoutItem = {
      item_id: `${this.spaceId}_${type}_${this.n + 1}`,
      item_type: type,
      glb_asset: c.glb_asset,
      room_id: f.room.room_id,
      x_m: Math.round(x * 100) / 100,
      z_m: Math.round(z * 100) / 100,
      rotation_deg: f.rot(localRot),
      width_m: c.width_m,
      depth_m: c.depth_m,
      height_m: c.height_m,
      zone: c.zone,
      seats: c.seats,
    };
    if (!fits(it, this.items, f.room, this.entrance)) return null;
    this.n++;
    this.items.push(it);
    return it;
  }

  get seats() {
    return this.items.reduce((s, it) => s + it.seats, 0);
  }
}

/** Items in a row along the back wall (v = 0), pushed together; skips what doesn't fit. */
function backWall(p: Placer, f: Frame, types: string[], startU = 0.3) {
  let u = startU;
  for (const type of types) {
    const c = catalogItem(type);
    if (p.tryPlace(f, type, u + c.width_m / 2, c.depth_m / 2 + 0.05)) u += c.width_m;
  }
}

/** Fill a grid of seats/desks from the front (v = d) backwards until `target` seats. */
function seatingGrid(p: Placer, f: Frame, big: string, small: string, target: number, opts: { stepU: number; stepV: number; minV: number; laneU?: number }) {
  const bigC = catalogItem(big);
  for (let v = f.d - 1.9; v - bigC.depth_m / 2 > opts.minV; v -= opts.stepV) {
    for (let u = 0.3 + bigC.width_m / 2; u + bigC.width_m / 2 <= f.w - 0.2; u += opts.stepU) {
      if (p.seats >= target) return;
      if (opts.laneU != null && v > f.d - 2.5 && Math.abs(u - opts.laneU) < 1.7) continue;
      if (target - p.seats >= bigC.seats && p.tryPlace(f, big, u, v)) continue;
      p.tryPlace(f, small, u, v);
    }
  }
}

function bakery(p: Placer, main: Frame, others: Frame[], target: number) {
  // Item types from Yared's assets/catalog.json (the mock catalog only fills gaps, e.g. office items).
  backWall(p, main, ["three_comp_sink", "prep_table", "deck_oven", "proofing_cabinet"]);
  // Service line roughly mid-room, facing the entrance.
  let serviceV = 2.0;
  outer: for (let v = main.d * 0.45; v <= main.d * 0.7; v += 0.25) {
    for (const u of [Math.max(2.4, main.w * 0.32), main.w / 2, main.w - 2.4]) {
      if (p.tryPlace(main, "service_counter", u, v)) {
        serviceV = v;
        if (!p.tryPlace(main, "display_case", u + 2.1, v)) p.tryPlace(main, "display_case", u - 2.1, v);
        break outer;
      }
    }
  }
  if (!p.tryPlace(main, "menu_board", 0.1, serviceV, 90)) p.tryPlace(main, "menu_board", main.w - 0.1, serviceV, -90);
  seatingGrid(p, main, "bench_table_4", "table_2", target, { stepU: 2.6, stepV: 1.8, minV: serviceV + 1.4, laneU: main.entranceU });
  for (const f of others) seatingGrid(p, f, "bench_table_4", "table_2", target, { stepU: 2.6, stepV: 1.8, minV: 0.3 });
}

function office(p: Placer, main: Frame, others: Frame[], target: number) {
  const eu = main.entranceU;
  if (!p.tryPlace(main, "reception_desk", eu + 2.2, main.d - 2.4)) p.tryPlace(main, "reception_desk", eu - 2.2, main.d - 2.4);
  if (!p.tryPlace(main, "sofa", eu - 2.6, main.d - 1.4, 180)) p.tryPlace(main, "sofa", eu + 2.6, main.d - 1.4, 180);
  backWall(p, main, ["storage", "storage"], 0.4);
  const k = catalogItem("kitchenette_counter");
  p.tryPlace(main, "kitchenette_counter", main.w - k.width_m / 2 - 0.3, k.depth_m / 2 + 0.05);
  p.tryPlace(main, "meeting_table", main.w - 3.0, 3.2);
  p.tryPlace(main, "phone_booth", 1.0, main.d - 6.0, 90);
  p.tryPlace(main, "phone_booth", 1.0, main.d - 7.0, 90);
  seatingGrid(p, main, "desk_pod_4", "single_desk", target, { stepU: 3.9, stepV: 3.0, minV: 1.5 });
  for (const f of others) seatingGrid(p, f, "desk_pod_4", "single_desk", target, { stepU: 3.9, stepV: 3.0, minV: 0.3 });
}

const STRATEGY = {
  bakery: "front seating, service line mid-room, production on the back wall",
  office: "reception by the door, desk pods in the open area, services on the back wall",
};

export function planLayout(spaceId: string, rooms: Room[], inspection: Inspection | null, brief: Brief, strategy: string | null = null): Layout {
  const isOffice = brief.business_type === "office";
  const usable = rooms.filter((r) => !UTILITY.test(r.label ?? r.room_type ?? "")).sort((a, b) => b.area_m2 - a.area_m2);
  const pool = usable.length ? usable : [...rooms].sort((a, b) => b.area_m2 - a.area_m2);
  if (!pool.length) throw new Error("plan_layout needs at least one room");
  const main = frame(pool[0]);
  const others = pool.slice(1, 4).map((r) => frame(r));
  const placer = new Placer(spaceId, main.entrance);
  const target = brief.seats_wanted ?? (isOffice ? 25 : 20);
  if (isOffice) office(placer, main, others, target);
  else bakery(placer, main, others, target);

  const seatCount = placer.seats;
  const unit = isOffice ? "desks" : "seats";
  const notes = ["Mock layout (web/mock-server/reimaginer), not Yared's planner."];
  if (seatCount < target) notes.push(`The rooms fit ${seatCount} of the ${target} ${unit} requested.`);
  const roomsUsed = new Set(placer.items.map((it) => it.room_id)).size;
  if (roomsUsed > 1) notes.push(`${unit[0].toUpperCase() + unit.slice(1)} spill into ${roomsUsed - 1} adjacent room(s).`);
  if (!isOffice && inspection?.existing_kitchen) notes.push("Back of house placed where the existing kitchen is.");
  return {
    layout_id: `${spaceId}_${isOffice ? "office" : "bakery"}_${target}`,
    space_id: spaceId,
    business_type: isOffice ? "office" : brief.business_type,
    entrance_xz: main.entrance,
    items: placer.items,
    seat_count: seatCount,
    strategy: strategy ?? (isOffice ? STRATEGY.office : STRATEGY.bakery),
    notes,
  };
}
