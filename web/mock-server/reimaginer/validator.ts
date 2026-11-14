/**
 * Mock of Yared's `agent/layout/validator.py: validate_layout(layout, rooms) -> ValidationReport` (README R5).
 * Real geometric checks on item footprints: inside rooms, no overlaps, aisles ≥ MIN_AISLE_M between
 * items that aren't pushed together, entrance clear for DOOR_CLEARANCE_M. Not done here (Yared's
 * validator does): grid BFS reachability of every seat, clearance in front of each item.
 */
import type { Layout, LayoutItem, Room, ValidationReport, Violation, XZ } from "../../src/types/schemas";
import { footprint, overlapDepth, pointInPolygon, pointToPolygon, polygonDistance } from "./geometry";

// Mirrors shared/conventions.py
export const MIN_AISLE_M = 0.914;
export const DOOR_CLEARANCE_M = 1.2;
/** Items closer than this are treated as pushed together on purpose (e.g. counter + display case). */
const ABUT_M = 0.05;
const TOL_M = 0.01;

/**
 * Would `it` be valid next to `placed`? Same rules as validateLayout, for one candidate
 * (the planner's greedy placement uses it).
 */
export function fits(it: LayoutItem, placed: LayoutItem[], room: Room, entrance: XZ | null): boolean {
  const fp = footprint(it);
  if (!fp.every((p) => pointInPolygon(p, room.polygon_m, TOL_M))) return false;
  if (entrance && pointToPolygon(entrance, fp) < DOOR_CLEARANCE_M) return false;
  for (const other of placed) {
    const ofp = footprint(other);
    if (overlapDepth(fp, ofp) > TOL_M) return false;
    const gap = polygonDistance(fp, ofp);
    if (gap >= ABUT_M && gap < MIN_AISLE_M) return false;
  }
  return true;
}

export function validateLayout(layout: Layout, rooms: Room[]): ValidationReport {
  const violations: Violation[] = [];
  const shapes = layout.items.map((it) => ({ it, fp: footprint(it) }));

  for (const { it, fp } of shapes) {
    const room = rooms.find((r) => r.room_id === it.room_id) ?? rooms[0];
    if (!room || !fp.every((p) => pointInPolygon(p, room.polygon_m, TOL_M))) {
      violations.push({ kind: "out_of_bounds", item_ids: [it.item_id], message: `${it.item_type} sticks out of ${room?.label ?? "the room"}` });
    }
  }

  let minAisle: number | null = null;
  for (let i = 0; i < shapes.length; i++) {
    for (let j = i + 1; j < shapes.length; j++) {
      const a = shapes[i];
      const b = shapes[j];
      if (overlapDepth(a.fp, b.fp) > TOL_M) {
        violations.push({ kind: "overlap", item_ids: [a.it.item_id, b.it.item_id], message: `${a.it.item_type} overlaps ${b.it.item_type}` });
        continue;
      }
      const gap = polygonDistance(a.fp, b.fp);
      if (gap < ABUT_M) continue;
      minAisle = minAisle == null ? gap : Math.min(minAisle, gap);
      if (gap < MIN_AISLE_M) {
        violations.push({
          kind: "aisle_too_narrow",
          item_ids: [a.it.item_id, b.it.item_id],
          message: `Only ${gap.toFixed(2)} m between ${a.it.item_type} and ${b.it.item_type} (needs ${MIN_AISLE_M} m)`,
        });
      }
    }
  }

  if (layout.entrance_xz) {
    for (const { it, fp } of shapes) {
      const d = pointToPolygon(layout.entrance_xz, fp);
      if (d < DOOR_CLEARANCE_M) {
        violations.push({ kind: "entrance_blocked", item_ids: [it.item_id], message: `${it.item_type} is ${d.toFixed(2)} m from the entrance (keep ${DOOR_CLEARANCE_M} m clear)` });
      }
    }
  }

  return {
    layout_id: layout.layout_id,
    passed: violations.length === 0,
    violations,
    min_aisle_m: minAisle == null ? null : Math.round(minAisle * 100) / 100,
    seat_count: layout.items.reduce((n, it) => n + it.seats, 0),
  };
}
