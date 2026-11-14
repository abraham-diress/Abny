"use client";

import clsx from "clsx";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { isOffice, seatWord } from "@/lib/business";
import { usd } from "@/lib/format";
import type { CandidateResult } from "@/types/schemas";

function Card({ r, selected, onSelect }: { r: CandidateResult; selected: boolean; onSelect: () => void }) {
  const valid = r.validation?.passed;
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected}
        className={clsx(
          "w-full rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent",
          selected ? "border-accent bg-accent-soft" : "border-border bg-surface hover:border-muted",
        )}
      >
        <div className="flex items-start gap-3">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent font-semibold text-background tabular-nums">
            {r.rank}
          </span>
          <div className="min-w-0 flex-1 space-y-1">
            <p className="truncate font-medium">{r.space.address}</p>
            <p className="text-sm text-muted">
              {usd(r.space.asking_rent_month)}/mo · {r.space.sqft ? `${r.space.sqft.toLocaleString()} sqft` : "size n/a"}
              {r.layout ? ` · ${r.layout.seat_count} ${seatWord(isOffice(r), r.layout.seat_count)}` : ""}
            </p>
            {r.rank_reasons[0] && <p className="text-sm text-pretty">{r.rank_reasons[0]}</p>}
          </div>
          <div className="flex shrink-0 flex-col items-end gap-1">
            <span className="font-mono text-sm tabular-nums">{Math.round(r.rank_score * 100)}</span>
            {valid != null &&
              (valid ? (
                <ShieldCheck className="size-4 text-good" aria-label="Layout valid" />
              ) : (
                <ShieldAlert className="size-4 text-bad" aria-label="Layout has violations" />
              ))}
          </div>
        </div>
      </button>
    </li>
  );
}

export function ResultList({
  results,
  selectedId,
  onSelect,
  running,
}: {
  results: CandidateResult[];
  selectedId: string | null;
  onSelect: (spaceId: string) => void;
  running: boolean;
}) {
  if (results.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted">
        {running ? "Candidates appear here as the agent finishes fitting them out." : "No results."}
      </p>
    );
  }
  return (
    <ol className="space-y-2" aria-label="Ranked results">
      {results.map((r) => (
        <Card key={r.space.space_id} r={r} selected={r.space.space_id === selectedId} onSelect={() => onSelect(r.space.space_id)} />
      ))}
    </ol>
  );
}
