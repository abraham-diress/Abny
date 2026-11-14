/** Floor-plan geometry in model coordinates: (x, z) meters. Mirrors what Yared does with shapely. */
import type { LayoutItem, XZ } from "../../src/types/schemas";

/**
 * The item's footprint corners. rotation_deg is about +y, 0 = front faces +z,
 * so a local (x, z) maps to (x cosθ + z sinθ, −x sinθ + z cosθ).
 */
export function footprint(it: Pick<LayoutItem, "x_m" | "z_m" | "width_m" | "depth_m" | "rotation_deg">): XZ[] {
  const t = (it.rotation_deg * Math.PI) / 180;
  const c = Math.cos(t);
  const s = Math.sin(t);
  const hw = it.width_m / 2;
  const hd = it.depth_m / 2;
  return ([[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]] as XZ[]).map(([x, z]) => [it.x_m + x * c + z * s, it.z_m - x * s + z * c]);
}

export function pointInPolygon(p: XZ, poly: XZ[], eps = 1e-6): boolean {
  if (pointToPolygonBoundary(p, poly) < eps) return true; // on the edge counts as inside
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i];
    const [xj, zj] = poly[j];
    if (zi > p[1] !== zj > p[1] && p[0] < ((xj - xi) * (p[1] - zi)) / (zj - zi) + xi) hit = !hit;
  }
  return hit;
}

function pointToSegment(p: XZ, a: XZ, b: XZ): number {
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const len2 = dx * dx + dz * dz;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dz));
}

function pointToPolygonBoundary(p: XZ, poly: XZ[]): number {
  let d = Infinity;
  for (let i = 0; i < poly.length; i++) d = Math.min(d, pointToSegment(p, poly[i], poly[(i + 1) % poly.length]));
  return d;
}

/** Distance from a point to a (filled) polygon: 0 inside. */
export function pointToPolygon(p: XZ, poly: XZ[]): number {
  return pointInPolygon(p, poly) ? 0 : pointToPolygonBoundary(p, poly);
}

/** Overlap depth of two convex polygons by the separating axis test (≤ 0 means they don't overlap). */
export function overlapDepth(a: XZ[], b: XZ[]): number {
  let min = Infinity;
  for (const poly of [a, b]) {
    for (let i = 0; i < poly.length; i++) {
      const [x1, z1] = poly[i];
      const [x2, z2] = poly[(i + 1) % poly.length];
      const len = Math.hypot(x2 - x1, z2 - z1) || 1;
      const axis: XZ = [-(z2 - z1) / len, (x2 - x1) / len];
      const proj = (q: XZ[]) => q.map((p) => p[0] * axis[0] + p[1] * axis[1]);
      const pa = proj(a);
      const pb = proj(b);
      const o = Math.min(Math.max(...pa), Math.max(...pb)) - Math.max(Math.min(...pa), Math.min(...pb));
      if (o <= 0) return o;
      min = Math.min(min, o);
    }
  }
  return min;
}

/** Shortest distance between two convex polygons (0 if they touch or overlap). */
export function polygonDistance(a: XZ[], b: XZ[]): number {
  if (overlapDepth(a, b) > 0) return 0;
  let d = Infinity;
  for (const p of a) d = Math.min(d, pointToPolygonBoundary(p, b));
  for (const p of b) d = Math.min(d, pointToPolygonBoundary(p, a));
  return d;
}
