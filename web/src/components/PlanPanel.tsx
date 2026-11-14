"use client";

import { Check, Circle, FileText, Loader2, MessageSquare, Wrench, TriangleAlert } from "lucide-react";
import clsx from "clsx";
import type { ActivityItem, AgentInfo, RunView } from "@/lib/run-state";
import type { FunnelStats } from "@/types/schemas";

const STAGES: { key: keyof FunnelStats; label: string }[] = [
  { key: "total", label: "Spaces" },
  { key: "filtered", label: "Filtered" },
  { key: "ranked", label: "Ranked" },
  { key: "inspected", label: "Inspected" },
  { key: "fitted", label: "Fitted out" },
];

function Funnel({ funnel }: { funnel: FunnelStats }) {
  const max = Math.max(funnel.total, 1);
  return (
    <section aria-label="Search funnel" className="space-y-2">
      <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted uppercase">Funnel</h3>
      <ul className="space-y-1.5">
        {STAGES.map(({ key, label }) => {
          const n = funnel[key];
          // sqrt scale keeps the small end (5 fitted out of 600) visible.
          const width = n > 0 ? Math.max(4, Math.sqrt(n / max) * 100) : 0;
          return (
            <li key={key} className="grid grid-cols-[5.5rem_1fr_2.5rem] items-center gap-2 text-sm">
              <span className="text-muted">{label}</span>
              <span className="h-2 overflow-hidden rounded-full bg-surface-2">
                <span className="block h-full rounded-full bg-gradient-to-r from-primary to-tertiary transition-[width] duration-500" style={{ width: `${width}%` }} />
              </span>
              <span className="text-right font-mono tabular-nums">{n || "–"}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Todos({ todos }: { todos: RunView["todos"] }) {
  return (
    <section aria-label="Agent plan" className="space-y-2">
      <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted uppercase">Plan</h3>
      {todos.length === 0 ? (
        <p className="text-sm text-muted">Waiting for the agent to plan…</p>
      ) : (
        <ul className="space-y-1.5">
          {todos.map((t, i) => (
            <li key={i} className="flex items-start gap-2 text-sm">
              {t.status === "completed" ? (
                <Check className="mt-0.5 size-4 shrink-0 text-good" aria-label="done" />
              ) : t.status === "in_progress" ? (
                <Loader2 className="mt-0.5 size-4 shrink-0 animate-spin text-accent" aria-label="in progress" />
              ) : (
                <Circle className="mt-0.5 size-4 shrink-0 text-muted" aria-label="pending" />
              )}
              <span className={clsx(t.status === "completed" && "text-muted line-through decoration-muted/50", t.status === "in_progress" && "font-medium")}>
                {t.content}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Agents({ agents }: { agents: AgentInfo[] }) {
  if (agents.length === 0) return null;
  return (
    <section aria-label="Subagents" className="space-y-2">
      <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted uppercase">Subagents</h3>
      <ul className="space-y-1.5">
        {agents.map((a) => (
          <li key={a.name} className="flex items-start gap-2 text-sm">
            <span
              className={clsx("mt-1.5 size-2 shrink-0 rounded-full", a.status === "working" ? "pulse-dot bg-accent" : "bg-good")}
              aria-hidden
            />
            <span>
              <span className="font-mono font-medium">{a.name}</span>
              <span className="text-muted"> · {a.status === "working" ? (a.task ?? "working") : (a.summary ?? "done")}</span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const ICONS: Record<ActivityItem["kind"], React.ReactNode> = {
  tool_call: <Wrench className="size-3.5" />,
  tool_result: <Check className="size-3.5" />,
  file_written: <FileText className="size-3.5" />,
  log: <Circle className="size-3.5" />,
  feedback: <MessageSquare className="size-3.5" />,
  error: <TriangleAlert className="size-3.5" />,
};

function Activity({ items }: { items: ActivityItem[] }) {
  return (
    <section aria-label="Recent activity" className="min-h-0 space-y-2">
      <h3 className="text-[11px] font-semibold tracking-[0.1em] text-muted uppercase">Activity</h3>
      {items.length === 0 ? (
        <p className="text-sm text-muted">Nothing yet.</p>
      ) : (
        <ul className="max-h-64 space-y-1 overflow-y-auto rounded-lg bg-surface-2/60 p-2 font-mono text-[11px] leading-relaxed">
          {items.slice(0, 30).map((a) => (
            <li
              key={a.seq}
              className={clsx("flex items-start gap-1.5 break-all", a.kind === "error" || a.ok === false ? "text-bad" : a.kind === "tool_result" ? "text-good" : "text-muted")}
            >
              <span className="mt-0.5 shrink-0">{ICONS[a.kind]}</span>
              <span>
                {a.agent && a.kind === "tool_call" && <span className="text-foreground">{a.agent} › </span>}
                {a.kind === "file_written" ? `wrote ${a.text}` : a.text}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function PlanPanel({ view }: { view: RunView }) {
  return (
    <div className="space-y-6">
      <Funnel funnel={view.funnel} />
      <Todos todos={view.todos} />
      <Agents agents={view.agents} />
      <Activity items={view.activity} />
    </div>
  );
}
