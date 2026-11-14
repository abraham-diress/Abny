"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, SearchX } from "lucide-react";
import { ApiError, createRun } from "@/lib/api";
import { isOfficeType } from "@/lib/business";
import { usd } from "@/lib/format";
import type { Brief, FunnelStats } from "@/types/schemas";

/** What the agent is actually searching for, as short labels. */
export function conditionsOf(b: Brief): string[] {
  const office = isOfficeType(b.business_type);
  const out = [b.business_type.charAt(0).toUpperCase() + b.business_type.slice(1)];
  out.push(b.city ?? "Any city");
  if (b.max_rent_month) out.push(`≤ ${usd(b.max_rent_month)}/mo`);
  if (b.seats_wanted) out.push(`~${b.seats_wanted} ${office ? "desks" : "seats"}`);
  if (b.sqft_min || b.sqft_max) out.push(`${b.sqft_min ? b.sqft_min.toLocaleString() : "?"}–${b.sqft_max ? b.sqft_max.toLocaleString() : "?"} sqft`);
  if (b.area_hint) out.push(b.area_hint);
  for (const m of b.must_haves) out.push(`needs ${m}`);
  return out;
}

export function BriefChips({ brief }: { brief: Brief }) {
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Searching for">
      {conditionsOf(brief).map((c) => (
        <li key={c} className="rounded-full border border-border bg-surface px-2.5 py-0.5 text-xs whitespace-nowrap text-foreground/80">
          {c}
        </li>
      ))}
    </ul>
  );
}

interface Retry {
  label: string;
  brief: Brief;
}

/** One-click ways to loosen a brief that matched nothing. Each starts a fresh search. */
function retries(b: Brief): Retry[] {
  const base = { ...b, feedback_history: [] };
  const out: Retry[] = [];
  if (b.max_rent_month) {
    const step = isOfficeType(b.business_type) ? 5000 : 1000;
    const next = Math.ceil((b.max_rent_month * 2) / step) * step;
    out.push({ label: `Budget up to ${usd(next)}/mo`, brief: { ...base, max_rent_month: next } });
  }
  if (b.city) out.push({ label: "Any city", brief: { ...base, city: null } });
  if (b.must_haves.length) out.push({ label: `Drop "${b.must_haves.join(", ")}"`, brief: { ...base, must_haves: [] } });
  if (b.seats_wanted || b.sqft_min || b.sqft_max) out.push({ label: "Any size", brief: { ...base, seats_wanted: null, sqft_min: null, sqft_max: null } });
  if (b.area_hint) out.push({ label: "Any neighborhood", brief: { ...base, area_hint: null } });
  return out;
}

/**
 * Shown when a finished run has no results: says which conditions were searched and offers
 * fresh searches with one condition loosened (feedback can't help here: a seats change, for
 * example, re-plans layouts but doesn't search again).
 */
export function EmptyResults({ brief, funnel }: { brief: Brief | null; funnel: FunnelStats }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function retry(r: Retry) {
    setBusy(r.label);
    setError(null);
    try {
      const { run_id } = await createRun({ text: r.brief.raw_text || "search", brief: r.brief });
      router.push(`/runs/${encodeURIComponent(run_id)}`);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start a new search.");
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-xl space-y-4 py-8 text-center">
      <SearchX className="mx-auto size-10 text-muted" aria-hidden />
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">No space matched all of these</h2>
        <p className="text-sm text-muted text-pretty">
          The agent looked at {funnel.total || "the"} spaces and none passed the filters
          {brief?.max_rent_month ? " (rent may go up to 15% over budget)" : ""}. Loosen one condition to search again.
        </p>
      </div>
      {brief && (
        <>
          <div className="flex justify-center">
            <BriefChips brief={brief} />
          </div>
          <div className="flex flex-wrap justify-center gap-2">
            {retries(brief).map((r) => (
              <button
                key={r.label}
                type="button"
                disabled={busy !== null}
                onClick={() => void retry(r)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 bg-primary-soft px-3 py-1.5 text-sm font-medium text-primary hover:border-primary focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50"
              >
                {busy === r.label && <Loader2 className="size-4 animate-spin" />}
                {r.label}
              </button>
            ))}
            <Link href="/" className="rounded-lg border border-border px-3 py-1.5 text-sm text-muted hover:text-foreground">
              Edit the brief
            </Link>
          </div>
        </>
      )}
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}
    </div>
  );
}
