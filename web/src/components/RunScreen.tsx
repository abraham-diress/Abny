"use client";

import Link from "next/link";
import { useState } from "react";
import { Bot, Building2, ListOrdered, Loader2, Plus, TriangleAlert } from "lucide-react";
import clsx from "clsx";
import { useRun } from "@/hooks/useRun";
import { Logo } from "@/components/Brand";
import { ThemeToggle } from "@/components/ThemeToggle";
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

function Panel({
  className,
  children,
  label,
  icon: Icon,
  aside,
}: {
  className?: string;
  children: React.ReactNode;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  aside?: React.ReactNode;
}) {
  return (
    <section aria-label={label} className={clsx("shadow-soft flex min-h-0 flex-col overflow-hidden rounded-2xl border border-border bg-surface", className)}>
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-2.5">
        <Icon className="size-4 text-muted" />
        <h2 className="text-sm font-semibold">{label}</h2>
        {aside && <div className="ml-auto">{aside}</div>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
    </section>
  );
}

function StatusPill({ view, running }: { view: ReturnType<typeof useRun>["view"]; running: boolean }) {
  const label =
    view.state === "error" ? "Error" : view.state === "unknown" ? "Loading…" : running ? `Working · ${CONNECTION_LABEL[view.connection]}` : "Done";
  const tone =
    view.state === "error"
      ? "border-bad/30 bg-bad/10 text-bad"
      : running
        ? "border-primary/30 bg-primary-soft text-primary"
        : view.state === "unknown"
          ? "border-border bg-surface-2 text-muted"
          : "border-good/30 bg-good/10 text-good";
  const dot = running ? "pulse-dot bg-primary" : view.state === "error" ? "bg-bad" : view.state === "unknown" ? "bg-muted" : "bg-good";
  return (
    <span className={clsx("inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium", tone)}>
      <span className={clsx("size-1.5 rounded-full", dot)} aria-hidden />
      {label}
    </span>
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
    <div className="flex min-h-dvh flex-col xl:h-dvh xl:overflow-hidden">
      <header className="sticky top-0 z-30 shrink-0 border-b border-border bg-background/85 backdrop-blur-md">
        <div className="flex h-14 items-center gap-3 px-3 sm:px-4">
          <Logo />
          <span className="hidden h-5 w-px bg-border sm:block" aria-hidden />
          <p className="hidden min-w-0 flex-1 truncate text-sm text-muted sm:block" title={brief?.raw_text}>
            {brief?.raw_text ?? runId}
          </p>
          <div className="ml-auto flex items-center gap-2">
            {view.round > 0 && (
              <span className="hidden rounded-full border border-secondary/30 bg-secondary-soft px-2.5 py-1 text-xs font-medium text-secondary sm:inline">
                Round {view.round + 1}
              </span>
            )}
            <StatusPill view={view} running={running} />
            <ThemeToggle />
            <Link
              href="/"
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-primary px-3 text-sm font-medium text-on-primary transition-colors hover:bg-primary-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              <Plus className="size-4" /> <span className="hidden sm:inline">New search</span>
            </Link>
          </div>
        </div>
        {brief && (
          <div className="flex items-center gap-2 overflow-x-auto border-t border-border/70 px-3 py-2 sm:px-4">
            <span className="shrink-0 text-xs text-muted">Searching for</span>
            <BriefChips brief={brief} />
          </div>
        )}
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 p-3">
        {view.state === "error" && (
          <div role="alert" className="flex items-start gap-2 rounded-xl border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
            <TriangleAlert className="mt-0.5 size-4 shrink-0" />
            <span>{view.error ?? "Something went wrong."}</span>
          </div>
        )}

        <main className="grid min-h-0 flex-1 gap-3 xl:grid-cols-[19rem_minmax(0,1fr)_23rem]">
          <Panel label="Agent" icon={Bot} className="xl:order-1">
            <PlanPanel view={view} />
          </Panel>

          <Panel label="Selected space" icon={Building2} className="xl:order-2">
            <div className="space-y-6">
              <MapPanel results={view.results} selectedId={selected?.space.space_id ?? null} onSelect={setPickedId} city={brief?.city} />
              {selected ? (
                <SpaceDetail key={selected.space.space_id} result={selected} />
              ) : noResults ? (
                <EmptyResults brief={brief} funnel={view.funnel} />
              ) : (
                <div className="flex min-h-48 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border text-center text-sm text-muted">
                  {running && <Loader2 className="size-5 animate-spin text-primary" />}
                  {running ? "The agent is still working. The best match appears here first." : "No candidate to show."}
                </div>
              )}
            </div>
          </Panel>

          <Panel
            label="Results"
            icon={ListOrdered}
            className="xl:order-3"
            aside={<span className="rounded-full bg-surface-2 px-2 py-0.5 font-mono text-xs text-muted tabular-nums">{view.results.length}</span>}
          >
            <div className="space-y-5">
              <ResultList results={view.results} selectedId={selected?.space.space_id ?? null} onSelect={setPickedId} running={running} />
              {noResults ? (
                <p className="rounded-xl border border-dashed border-border p-3 text-sm text-pretty text-muted">
                  Nothing to refine yet: feedback re-plans the spaces that were found, and none were. Loosen a condition in the middle panel to search again.
                </p>
              ) : (
                <div className="border-t border-border pt-5">
                  <FeedbackBox selected={selected} disabled={running} onSubmit={submitFeedback} />
                </div>
              )}
            </div>
          </Panel>
        </main>
      </div>
    </div>
  );
}
