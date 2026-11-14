"use client";

import { useState, type KeyboardEvent, type PointerEvent } from "react";
import { Camera, ShieldAlert, ShieldCheck } from "lucide-react";
import { assetUrl } from "@/lib/config";
import { pct } from "@/lib/format";
import type { HeroImage } from "@/types/schemas";

/** `source_pano_id` is "<model>:<scan>:<face>"; the empty room is media/panos/<model>/<scan>_<face>.jpg. */
export function parsePanoId(id: string): { model: string; scan: string; face: string } | null {
  const [model, scan, face] = id.split(":");
  return model && scan && face ? { model, scan, face } : null;
}

export const panoPath = (id: string) => {
  const p = parsePanoId(id);
  return p ? `media/panos/${p.model}/${p.scan}_${p.face}.jpg` : null;
};

/**
 * The generated image over the real empty room, same framing: drag (or use arrow keys) to wipe between them.
 * Without the original photo it is just the image.
 */
export function BeforeAfter({ hero, alt, onShowInTour }: { hero: HeroImage; alt: string; onShowInTour?: () => void }) {
  const before = panoPath(hero.source_pano_id);
  const [beforeOk, setBeforeOk] = useState(!!before);
  const [pos, setPos] = useState(55);
  const [dragging, setDragging] = useState(false);

  function move(e: PointerEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    setPos(Math.min(100, Math.max(0, ((e.clientX - r.left) / r.width) * 100)));
  }
  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowLeft") setPos((p) => Math.max(0, p - 5));
    else if (e.key === "ArrowRight") setPos((p) => Math.min(100, p + 5));
    else if (e.key === "Home") setPos(0);
    else if (e.key === "End") setPos(100);
    else return;
    e.preventDefault();
  }

  const showSlider = beforeOk && before;
  const tag = "pointer-events-none absolute top-2 rounded-md bg-black/60 px-2 py-0.5 text-xs font-medium text-white backdrop-blur";

  return (
    <div className="space-y-2">
      <div
        className={`relative aspect-square max-h-[34rem] w-full touch-pan-y overflow-hidden rounded-xl border border-border bg-surface-2 select-none ${showSlider ? "cursor-ew-resize" : ""}`}
        onPointerDown={(e) => {
          if (!showSlider) return;
          e.currentTarget.setPointerCapture(e.pointerId);
          setDragging(true);
          move(e);
        }}
        onPointerMove={(e) => dragging && move(e)}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- images come from the API server, not optimized by Next */}
        <img src={assetUrl(hero.path)} alt={alt} draggable={false} className="absolute inset-0 size-full object-cover" />
        {before && (
          // eslint-disable-next-line @next/next/no-img-element -- loaded only to learn whether the original photo exists
          <img
            src={assetUrl(before)}
            alt="The empty room as it is today"
            draggable={false}
            onError={() => setBeforeOk(false)}
            className="absolute inset-0 size-full object-cover"
            style={{ clipPath: `inset(0 ${100 - pos}% 0 0)`, display: beforeOk ? undefined : "none" }}
          />
        )}
        {showSlider && (
          <>
            <span className={`${tag} left-2`}>Today</span>
            <span className={`${tag} right-2`}>With your business</span>
            <div
              role="slider"
              tabIndex={0}
              aria-label="Compare the empty room with the furnished one"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(pos)}
              onKeyDown={onKey}
              className="group absolute inset-y-0 w-0.5 bg-white shadow-[0_0_0_1px_rgba(0,0,0,.25)] focus-visible:outline-2 focus-visible:outline-accent"
              style={{ left: `${pos}%` }}
            >
              <span className="absolute top-1/2 left-1/2 grid size-9 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white text-xs text-black shadow-md group-focus-visible:ring-2 group-focus-visible:ring-accent">
                ⇆
              </span>
            </div>
          </>
        )}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        {hero.score ? (
          <p className="flex items-center gap-1.5 text-xs text-muted">
            {hero.score.passed ? <ShieldCheck className="size-4 text-good" /> : <ShieldAlert className="size-4 text-bad" />}
            Image check {hero.score.passed ? "passed" : "failed"}: building kept {pct(hero.score.structure_preserved)}, plan followed{" "}
            {pct(hero.score.plan_adherence)}, realism {hero.score.realism_1to5.toFixed(1)}/5
          </p>
        ) : (
          <span />
        )}
        {onShowInTour && (
          <button
            type="button"
            onClick={onShowInTour}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs hover:border-muted focus-visible:outline-2 focus-visible:outline-accent"
          >
            <Camera className="size-3.5" /> Stand where this was taken
          </button>
        )}
      </div>
    </div>
  );
}
