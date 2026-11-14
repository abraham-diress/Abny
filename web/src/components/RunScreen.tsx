"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, TriangleAlert } from "lucide-react";
import clsx from "clsx";
import { useRun } from "@/hooks/useRun";
import type { Connection } from "@/lib/run-state";
import { BriefChips, EmptyResults } from "@/components/BriefConditions";
import { FeedbackBox } from "@/components/FeedbackBox";
import { MapPanel } from "@/components/MapPanel";
import { PlanPanel } from "@/components/PlanPanel";
import { ResultList } from "@/components/ResultList";
import { SpaceDetail } from "@/components/SpaceDetail";

const CONNECTION_LABEL: Record<Connection, string> = {
  connecting: "Connecting…",
  open: "Live",
  reconnecting: "Reconnecting…",
  closed: "Idle",
};

function Panel({ className, children, label }: { className?: string; children: React.ReactNode; label: string }) {
  return (
    <section aria-label={label} className={clsx("min-h-0 overflow-y-auto rounded-2xl border border-border bg-surface p-4", className)}>
      {children}
    </section>
  );
}

export function RunScreen({ runId }: { runId: string }) {
  const { view, submitFeedback } = useRun(runId);
  const [pickedId, setPickedId] = useState<string | null>(null);

  // Follow rank #1 until the user picks something, and fall back if the pick disappears (rejected).
  const selected = view.results.find((r) => r.space.space_id === pickedId) ?? view.results[0] ?? null;
  const running = view.state === "running" || view.state === "queued";
  const brief = view.brief;
  const noResults = view.state === "done" && view.results.length === 0;

  return (
    <div className="flex min-h-dvh flex-col gap-3 p-3 xl:h-dvh xl:overflow-hidden">
      <header className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1">
        <Link href="/" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-foreground">
          <ArrowLeft className="size-4" /> New search
        </Link>
        <p className="min-w-0 flex-1 truncate text-sm text-muted" title={brief?.raw_text}>
          {brief?.raw_text ?? runId}
        </p>
        {view.round > 0 && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-xs text-accent">Round {view.round + 1}</span>}
        <span className="inline-flex items-center gap-1.5 text-xs text-muted">
          <span
            className={clsx("size-2 rounded-full", running ? "pulse-dot bg-accent" : view.state === "error" ? "bg-bad" : view.state === "unknown" ? "bg-muted" : "bg-good")}
            aria-hidden
          />
          {view.state === "error"
            ? "Error"
            : view.state === "unknown"
              ? "Loading…"
              : running
                ? `Working · ${CONNECTION_LABEL[view.connection]}`
                : "Done"}
        </span>
      </header>
      {brief && (
        <div className="flex items-center gap-2 px-1">
          <span className="text-xs text-muted">Searching for</span>
          <BriefChips brief={brief} />
        </div>
      )}

      {view.state === "error" && (
        <div role="alert" className="flex items-start gap-2 rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" />
          <span>{view.error ?? "Something went wrong."}</span>
        </div>
      )}

      <main className="grid min-h-0 flex-1 gap-3 xl:grid-cols-[20rem_minmax(0,1fr)_24rem]">
        <Panel label="Agent" className="xl:order-1">
          <PlanPanel view={view} />
        </Panel>

        <Panel label="Selected space" className="space-y-5 xl:order-2">
          <MapPanel results={view.results} selectedId={selected?.space.space_id ?? null} onSelect={setPickedId} city={brief?.city} />
          {selected ? (
            <SpaceDetail key={selected.space.space_id} result={selected} />
          ) : noResults ? (
            <EmptyResults brief={brief} funnel={view.funnel} />
          ) : (
            <div className="flex h-full min-h-48 items-center justify-center text-center text-muted">
              {running ? "The agent is still working. The best match appears here first." : "No candidate to show."}
            </div>
          )}
        </Panel>

        <Panel label="Results" className="space-y-5 xl:order-3">
          <div className="space-y-2">
            <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">Results ({view.results.length})</h2>
            <ResultList results={view.results} selectedId={selected?.space.space_id ?? null} onSelect={setPickedId} running={running} />
          </div>
          {noResults ? (
            <p className="rounded-xl border border-dashed border-border p-3 text-sm text-muted text-pretty">
              Nothing to refine yet: feedback re-plans the spaces that were found, and none were. Loosen a condition in the middle panel to search again.
            </p>
          ) : (
            <FeedbackBox selected={selected} disabled={running} onSubmit={submitFeedback} />
          )}
        </Panel>
      </main>
    </div>
  );
}
