import clsx from "clsx";
import { Info } from "lucide-react";
import type { Assumption, Citation, Source } from "@/types/schemas";

export interface SourceLine {
  source: Source;
  text: string;
}

const SOURCE_STYLE: Record<Source, string> = {
  costar: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  matterport: "bg-secondary/15 text-secondary",
  vexcel: "bg-lime-500/15 text-lime-700 dark:text-lime-300",
  model: "bg-primary/15 text-primary",
  assumption: "bg-tertiary/20 text-amber-700 dark:text-tertiary",
  user: "bg-stone-500/15 text-stone-700 dark:text-stone-300",
};

export function citationLine(c: Citation): SourceLine {
  const parts = [c.dataset, c.record_id ? `#${c.record_id}` : null, c.field ? `${c.field}${c.value != null ? ` = ${c.value}` : ""}` : null];
  return { source: c.source, text: [...parts.filter(Boolean), c.note].filter(Boolean).join(" · ") || "no detail" };
}

/** "fitout_psf_low" -> "Fitout psf low" (the analyst names assumptions in snake_case). */
export const humanize = (name: string) => {
  const s = name.replace(/_/g, " ").replace(/\bpsf\b/i, "per sqft").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
};

/** Unit after a value: "$/sqft/yr" -> "/sqft/yr", "USD" -> "", "months" -> " months". */
export const unitSuffix = (unit: string | null) => {
  if (!unit) return "";
  const u = unit.replace(/^(USD|\$)\s*/, "");
  return !u ? "" : u.startsWith("/") ? u : ` ${u}`;
};

export function assumptionLine(a: Assumption): SourceLine {
  // Keep the "$" when the unit carried it: 35 "$/sqft" -> "$35/sqft".
  const money = typeof a.value === "number" && /^(USD|\$)/.test(a.unit ?? "");
  return { source: a.source, text: `${humanize(a.name)}: ${money ? "$" : ""}${a.value}${unitSuffix(a.unit)}${a.note ? ` (${a.note})` : ""}` };
}

/** Drop repeated lines (the same citation can come from the space and from the numbers). */
export const uniqueLines = (lines: SourceLine[]) => lines.filter((l, i) => lines.findIndex((m) => m.source === l.source && m.text === l.text) === i);

/** A value with an info button that reveals where it came from (hover, focus or tap). */
export function Sourced({ label, children, lines }: { label: string; children: React.ReactNode; lines: SourceLine[] }) {
  return (
    <div className="group relative flex items-baseline justify-between gap-4 py-2">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="flex items-center gap-1.5 text-right font-medium tabular-nums">
        {children}
        <button
          type="button"
          aria-label={`Sources for ${label}`}
          className="rounded-full p-0.5 text-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
        >
          <Info className="size-4" />
        </button>
      </dd>
      <div
        role="tooltip"
        className="invisible absolute top-full right-0 z-20 w-80 max-w-[85vw] space-y-1.5 shadow-lift rounded-xl border border-border bg-surface p-3 text-left text-xs opacity-0 transition-opacity group-focus-within:visible group-focus-within:opacity-100 group-hover:visible group-hover:opacity-100"
      >
        {lines.length === 0 ? (
          <p className="text-muted">No source recorded.</p>
        ) : (
          lines.map((l, i) => (
            <p key={i} className="flex items-start gap-2 font-normal">
              <span className={clsx("shrink-0 rounded px-1.5 py-0.5 font-medium uppercase", SOURCE_STYLE[l.source])}>{l.source}</span>
              <span className="text-pretty">{l.text}</span>
            </p>
          ))
        )}
      </div>
    </div>
  );
}
