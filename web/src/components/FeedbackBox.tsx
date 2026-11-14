"use client";

import { useState } from "react";
import { Loader2, RefreshCw, Ban } from "lucide-react";
import { ApiError } from "@/lib/api";
import type { CandidateResult, FeedbackRequest } from "@/types/schemas";

const SUGGESTIONS = ["Fewer seats", "Closer to transit", "Lower rent"];

export function FeedbackBox({
  selected,
  disabled,
  onSubmit,
}: {
  selected: CandidateResult | null;
  disabled: boolean;
  onSubmit: (body: FeedbackRequest) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(kind: FeedbackRequest["kind"]) {
    const body = text.trim() || (kind === "reject" ? "Not this one" : "");
    if (!body || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit({ text: body, kind, space_id: kind === "reject" ? selected?.space.space_id : null });
      setText("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not send feedback.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void send("constraint");
      }}
      className="space-y-2"
    >
      <label htmlFor="feedback" className="block text-sm font-semibold">
        Not quite right? Tell the agent.
      </label>
      <div className="flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setText((t) => (t ? `${t}, ${s.toLowerCase()}` : s))}
            className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:border-border-strong hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
          >
            {s}
          </button>
        ))}
      </div>
      <textarea
        id="feedback"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        disabled={disabled || busy}
        placeholder="e.g. fewer seats, closer to transit"
        className="w-full resize-none rounded-lg border border-border bg-surface-2/50 p-2.5 text-sm outline-none focus:border-accent focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60"
      />
      {error && (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={disabled || busy || !text.trim()}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-on-primary transition-colors hover:bg-primary-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} Re-plan
        </button>
        {selected && (
          <button
            type="button"
            onClick={() => void send("reject")}
            disabled={disabled || busy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm hover:border-bad hover:text-bad focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Ban className="size-4" /> Reject #{selected.rank}
          </button>
        )}
      </div>
    </form>
  );
}
