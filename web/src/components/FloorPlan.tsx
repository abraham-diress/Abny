"use client";

import { useMemo, useRef, useState, type MouseEvent } from "react";
import { isOfficeType, seatWord } from "@/lib/business";
import { yawToDir } from "@/lib/matterport";
import type { Layout, LayoutItem, Room, XZ, Zone } from "@/types/schemas";

export const ZONE_FILL: Record<Zone, string> = {
  seating: "#d99a4e",
  service: "#c0623f",
  back_of_house: "#6b7a8c",
  front_of_house: "#8a8a8a",
  entrance: "#4c9a6a",
};

const ZONE_LABEL: Record<Zone, string> = {
  seating: "Seating",
  service: "Service",
  back_of_house: "Back of house",
  front_of_house: "Front of house",
  entrance: "Entrance",
};

export const itemName = (it: LayoutItem) => it.item_type.replace(/_/g, " ");

export function ZoneLegend({ layout }: { layout: Layout }) {
  const zones = [...new Set(layout.items.map((it) => it.zone ?? "front_of_house"))];
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
      {zones.map((z) => (
        <li key={z} className="inline-flex items-center gap-1.5">
          <span className="size-2.5 rounded-sm" style={{ background: ZONE_FILL[z] }} aria-hidden />
          {ZONE_LABEL[z]}
        </li>
      ))}
    </ul>
  );
}

export interface PlanPoint {
  x: number;
  z: number;
}

interface FloorPlanProps {
  layout: Layout;
  rooms?: Room[];
  /** Tour viewpoints (Matterport sweeps) on this floor. Clicking one goes there. */
  viewpoints?: (PlanPoint & { sid: string })[];
  /** Where the tour camera stands, and its yaw (degrees). */
  you?: (PlanPoint & { yaw: number }) | null;
  /** Where the photoreal image was taken from. */
  photoSpot?: PlanPoint | null;
  selectedId?: string | null;
  onPick?: (x: number, z: number, room?: Room) => void;
  onItem?: (item: LayoutItem) => void;
  onViewpoint?: (sid: string) => void;
  onPhotoSpot?: () => void;
  className?: string;
}

function insidePolygon(x: number, z: number, poly: XZ[]): boolean {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, zi] = poly[i];
    const [xj, zj] = poly[j];
    if (zi > z !== zj > z && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) hit = !hit;
  }
  return hit;
}

export const roomAt = (rooms: Room[] | undefined, x: number, z: number) => rooms?.find((r) => insidePolygon(x, z, r.polygon_m));

function bounds(layout: Layout, rooms?: Room[], extra: PlanPoint[] = []) {
  const pts: XZ[] = rooms?.length ? rooms.flatMap((r) => r.polygon_m) : [];
  if (pts.length === 0) {
    for (const it of layout.items) {
      const r = Math.max(it.width_m, it.depth_m) / 2;
      pts.push([it.x_m - r, it.z_m - r], [it.x_m + r, it.z_m + r]);
    }
    if (layout.entrance_xz) pts.push(layout.entrance_xz);
  }
  if (pts.length === 0) return { minX: 0, minZ: 0, w: 10, h: 10 };
  let minX = Math.min(...pts.map((p) => p[0]));
  let maxX = Math.max(...pts.map((p) => p[0]));
  let minZ = Math.min(...pts.map((p) => p[1]));
  let maxZ = Math.max(...pts.map((p) => p[1]));
  // Without room outlines, also take in the nearby viewpoints so you can see where you can stand.
  for (const p of extra) {
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minZ = Math.min(minZ, p.z);
    maxZ = Math.max(maxZ, p.z);
  }
  const pad = 0.8;
  return { minX: minX - pad, minZ: minZ - pad, w: maxX - minX + 2 * pad, h: maxZ - minZ + 2 * pad };
}

/**
 * Top-down plan in model coordinates: x to the right, z DOWN (so the entrance on the +z wall is at the bottom).
 * `rotation_deg` is about +y with 0 = front faces +z; in this view that is SVG `rotate(-deg)`.
 *
 * Interactive when handlers are passed: click an item or the floor to go there in the tour,
 * click a viewpoint dot to stand on it; shows where the tour camera is and which way it looks.
 */
export function FloorPlan({
  layout,
  rooms,
  viewpoints,
  you,
  photoSpot,
  selectedId,
  onPick,
  onItem,
  onViewpoint,
  onPhotoSpot,
  className,
}: FloorPlanProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<string | null>(null);

  // Viewpoints worth showing: near the furniture (a scan can cover a whole building).
  const nearViews = useMemo(() => {
    if (!viewpoints?.length) return [];
    const core = bounds(layout, rooms);
    const m = rooms?.length ? 0.2 : 3;
    return viewpoints.filter(
      (v) => v.x >= core.minX - m && v.x <= core.minX + core.w + m && v.z >= core.minZ - m && v.z <= core.minZ + core.h + m,
    );
  }, [viewpoints, layout, rooms]);

  const b = useMemo(
    () => bounds(layout, rooms, rooms?.length ? [] : [...nearViews, ...(photoSpot ? [photoSpot] : [])]),
    [layout, rooms, nearViews, photoSpot],
  );
  // Markers and text keep a readable size on big floors.
  const k = Math.max(1, Math.max(b.w, b.h) / 14);
  const label = (it: LayoutItem) => it.width_m >= 1.2 * k && it.depth_m >= 0.6 * k;
  const interactive = !!(onPick || onItem);

  function toPlan(e: MouseEvent<SVGElement>): PlanPoint | null {
    const svg = svgRef.current;
    const ctm = svg?.getScreenCTM();
    if (!svg || !ctm) return null;
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(ctm.inverse());
    return { x: p.x, z: p.y };
  }

  function onClick(e: MouseEvent<SVGSVGElement>) {
    if (!onPick) return;
    const p = toPlan(e);
    if (p) onPick(p.x, p.z, roomAt(rooms, p.x, p.z));
  }

  const hovered = layout.items.find((it) => it.item_id === hover);
  const youDir = you ? yawToDir(you.yaw) : null;

  return (
    <svg
      ref={svgRef}
      viewBox={`${b.minX} ${b.minZ} ${b.w} ${b.h}`}
      role="img"
      aria-label={`Floor plan with ${layout.items.length} items and ${layout.seat_count} ${seatWord(isOfficeType(layout.business_type), layout.seat_count)}`}
      className={className ?? "h-auto w-full rounded-xl bg-surface-2"}
      onClick={onClick}
      style={{ cursor: onPick ? "crosshair" : undefined }}
    >
      <defs>
        <radialGradient id="plan-cone">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.55} />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
        </radialGradient>
      </defs>
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
          strokeWidth={0.06 * k}
          strokeDasharray={`${0.25 * k} ${0.18 * k}`}
        />
      )}
      {rooms?.map((r) => (
        <polygon
          key={r.room_id}
          points={r.polygon_m.map((p) => p.join(",")).join(" ")}
          fill="var(--surface)"
          stroke="var(--foreground)"
          strokeWidth={0.12 * k}
          strokeLinejoin="round"
          className={onPick ? "transition-[fill] hover:fill-[var(--accent-soft)]" : undefined}
        >
          {onPick && <title>{`Go to ${r.label ?? r.room_type ?? "this room"}`}</title>}
        </polygon>
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
            strokeWidth={0.2 * k}
            pointerEvents="none"
          />
        )),
      )}

      {nearViews.map((v) => (
        <circle
          key={v.sid}
          cx={v.x}
          cy={v.z}
          r={0.13 * k}
          fill="var(--muted)"
          fillOpacity={0.55}
          className={onViewpoint ? "cursor-pointer hover:fill-[var(--accent)] hover:fill-opacity-100" : undefined}
          onClick={(e) => {
            if (!onViewpoint) return;
            e.stopPropagation();
            onViewpoint(v.sid);
          }}
        >
          {onViewpoint && <title>Stand here</title>}
        </circle>
      ))}

      {layout.items.map((it) => {
        const active = it.item_id === selectedId || it.item_id === hover;
        return (
          <g
            key={it.item_id}
            transform={`translate(${it.x_m} ${it.z_m}) rotate(${-it.rotation_deg})`}
            onMouseEnter={() => setHover(it.item_id)}
            onMouseLeave={() => setHover((h) => (h === it.item_id ? null : h))}
            onClick={(e) => {
              if (!onItem) return;
              e.stopPropagation();
              onItem(it);
            }}
            style={{ cursor: onItem ? "pointer" : undefined }}
          >
            {!interactive && <title>{`${itemName(it)}${it.seats ? ` (${it.seats} seats)` : ""}`}</title>}
            <rect
              x={-it.width_m / 2}
              y={-it.depth_m / 2}
              width={it.width_m}
              height={it.depth_m}
              rx={0.05}
              fill={ZONE_FILL[it.zone ?? "front_of_house"]}
              fillOpacity={active ? 1 : 0.85}
              stroke={active ? "var(--accent)" : "rgba(0,0,0,.35)"}
              strokeWidth={active ? 0.1 * k : 0.03}
            />
            {/* front edge (+z side before rotation) */}
            <line x1={-it.width_m / 2} y1={it.depth_m / 2} x2={it.width_m / 2} y2={it.depth_m / 2} stroke="#fff" strokeWidth={0.07} />
            {label(it) && (
              <text
                y={0.09 * k}
                textAnchor="middle"
                fontSize={0.26 * k}
                fill="#fff"
                transform={`rotate(${it.rotation_deg})`}
                pointerEvents="none"
              >
                {itemName(it)}
              </text>
            )}
          </g>
        );
      })}

      {layout.entrance_xz && (
        <g transform={`translate(${layout.entrance_xz[0]} ${layout.entrance_xz[1]})`} pointerEvents="none">
          <circle r={0.22 * k} fill="#4c9a6a" />
          <text y={0.75 * k} textAnchor="middle" fontSize={0.3 * k} fill="var(--foreground)">
            entrance
          </text>
        </g>
      )}

      {photoSpot && (
        <g
          transform={`translate(${photoSpot.x} ${photoSpot.z})`}
          onClick={(e) => {
            if (!onPhotoSpot) return;
            e.stopPropagation();
            onPhotoSpot();
          }}
          style={{ cursor: onPhotoSpot ? "pointer" : undefined }}
        >
          <title>Where the photo was taken{onPhotoSpot ? " (click to stand here)" : ""}</title>
          <rect x={-0.32 * k} y={-0.24 * k} width={0.64 * k} height={0.46 * k} rx={0.08 * k} fill="var(--foreground)" />
          <circle r={0.13 * k} fill="var(--surface)" />
          <rect x={-0.12 * k} y={-0.33 * k} width={0.24 * k} height={0.1 * k} rx={0.03 * k} fill="var(--foreground)" />
        </g>
      )}

      {you && youDir && (
        <g transform={`translate(${you.x} ${you.z})`} pointerEvents="none">
          <path
            d={`M0 0 L${1.9 * k} ${-1.1 * k} A${2.2 * k} ${2.2 * k} 0 0 1 ${1.9 * k} ${1.1 * k} Z`}
            fill="url(#plan-cone)"
            transform={`rotate(${(Math.atan2(youDir[1], youDir[0]) * 180) / Math.PI})`}
          />
          <circle r={0.26 * k} fill="var(--accent)" stroke="#fff" strokeWidth={0.08 * k} />
        </g>
      )}

      {hovered && (
        <text
          x={hovered.x_m}
          y={hovered.z_m - Math.max(hovered.width_m, hovered.depth_m) / 2 - 0.25 * k}
          textAnchor="middle"
          fontSize={0.34 * k}
          fontWeight={600}
          fill="var(--foreground)"
          stroke="var(--surface)"
          strokeWidth={0.1 * k}
          paintOrder="stroke"
          pointerEvents="none"
        >
          {itemName(hovered)}
          {hovered.seats ? ` · ${hovered.seats} seats` : ""}
          {onItem ? " · click to look" : ""}
        </text>
      )}
    </svg>
  );
}
