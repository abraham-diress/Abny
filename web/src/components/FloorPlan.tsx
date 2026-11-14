import { isOfficeType, seatWord } from "@/lib/business";
import type { Layout, Room, XZ, Zone } from "@/types/schemas";

const ZONE_FILL: Record<Zone, string> = {
  seating: "#d99a4e",
  service: "#c0623f",
  back_of_house: "#6b7a8c",
  front_of_house: "#8a8a8a",
  entrance: "#4c9a6a",
};

function bounds(layout: Layout, rooms?: Room[]) {
  const pts: XZ[] = rooms?.length ? rooms.flatMap((r) => r.polygon_m) : [];
  if (pts.length === 0) {
    for (const it of layout.items) {
      const r = Math.max(it.width_m, it.depth_m) / 2;
      pts.push([it.x_m - r, it.z_m - r], [it.x_m + r, it.z_m + r]);
    }
    if (layout.entrance_xz) pts.push(layout.entrance_xz);
  }
  if (pts.length === 0) return { minX: 0, minZ: 0, w: 10, h: 10 };
  const xs = pts.map((p) => p[0]);
  const zs = pts.map((p) => p[1]);
  const pad = 0.8;
  const minX = Math.min(...xs) - pad;
  const minZ = Math.min(...zs) - pad;
  return { minX, minZ, w: Math.max(...xs) + pad - minX, h: Math.max(...zs) + pad - minZ };
}

/**
 * Top-down plan in model coordinates: x to the right, z DOWN (so the entrance on the +z wall is at the bottom).
 * Doubles as the fallback when the Matterport tour can't load (gate G2).
 * `rotation_deg` is about +y with 0 = front faces +z; in this view that is SVG `rotate(-deg)`.
 */
export function FloorPlan({ layout, rooms }: { layout: Layout; rooms?: Room[] }) {
  const b = bounds(layout, rooms);
  const label = (it: Layout["items"][number]) => it.width_m >= 1.2 && it.depth_m >= 0.7;
  return (
    <svg
      viewBox={`${b.minX} ${b.minZ} ${b.w} ${b.h}`}
      role="img"
      aria-label={`Floor plan with ${layout.items.length} items and ${layout.seat_count} ${seatWord(isOfficeType(layout.business_type), layout.seat_count)}`}
      className="h-auto w-full rounded-xl bg-surface-2"
    >
      {!rooms?.length && (
        // No room outlines from the API: an approximate outline around the layout, dashed.
        <rect
          x={b.minX + 0.3}
          y={b.minZ + 0.3}
          width={b.w - 0.6}
          height={b.h - 0.6}
          rx={0.15}
          fill="var(--surface)"
          stroke="var(--muted)"
          strokeWidth={0.06}
          strokeDasharray="0.25 0.18"
        />
      )}
      {rooms?.map((r) => (
        <polygon
          key={r.room_id}
          points={r.polygon_m.map((p) => p.join(",")).join(" ")}
          fill="var(--surface)"
          stroke="var(--foreground)"
          strokeWidth={0.12}
          strokeLinejoin="round"
        />
      ))}
      {rooms?.flatMap((r) =>
        r.openings.map((o, i) => (
          <line
            key={`${r.room_id}-${i}`}
            x1={o.a[0]}
            y1={o.a[1]}
            x2={o.b[0]}
            y2={o.b[1]}
            stroke={o.kind === "door" ? "#4c9a6a" : "#5aa6d6"}
            strokeWidth={0.2}
          />
        )),
      )}
      {layout.items.map((it) => (
        <g key={it.item_id} transform={`translate(${it.x_m} ${it.z_m}) rotate(${-it.rotation_deg})`}>
          <title>{`${it.item_type}${it.seats ? ` (${it.seats} seats)` : ""}`}</title>
          <rect
            x={-it.width_m / 2}
            y={-it.depth_m / 2}
            width={it.width_m}
            height={it.depth_m}
            rx={0.05}
            fill={ZONE_FILL[it.zone ?? "front_of_house"]}
            fillOpacity={0.9}
            stroke="rgba(0,0,0,.35)"
            strokeWidth={0.03}
          />
          {/* front edge (+z side before rotation) */}
          <line x1={-it.width_m / 2} y1={it.depth_m / 2} x2={it.width_m / 2} y2={it.depth_m / 2} stroke="#fff" strokeWidth={0.07} />
          {label(it) && (
            <text
              y={0.09}
              textAnchor="middle"
              fontSize={0.26}
              fill="#fff"
              transform={`rotate(${it.rotation_deg})`}
              style={{ pointerEvents: "none" }}
            >
              {it.item_type.replace(/_/g, " ")}
            </text>
          )}
        </g>
      ))}
      {layout.entrance_xz && (
        <g transform={`translate(${layout.entrance_xz[0]} ${layout.entrance_xz[1]})`}>
          <circle r={0.22} fill="#4c9a6a" />
          <text y={0.75} textAnchor="middle" fontSize={0.3} fill="var(--foreground)">
            entrance
          </text>
        </g>
      )}
    </svg>
  );
}
