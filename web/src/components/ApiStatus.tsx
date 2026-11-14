"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/config";
import { health } from "@/lib/api";

/** Small badge showing whether the API (real or mock) is reachable. */
export function ApiStatus() {
  const [state, setState] = useState<{ ok: boolean; mode?: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    health()
      .then((h) => !cancelled && setState({ ok: h.status === "ok", mode: h.mode }))
      .catch(() => !cancelled && setState({ ok: false }));
    return () => {
      cancelled = true;
    };
  }, []);

  const label = state === null ? "Checking API…" : state.ok ? `API connected (${state.mode ?? "live"})` : "API unreachable";
  const color = state === null ? "bg-muted" : state.ok ? "bg-good" : "bg-bad";
  return (
    <span className="inline-flex items-center gap-2" title={API_BASE}>
      <span className={`size-2 rounded-full ${color}`} aria-hidden />
      {label}
    </span>
  );
}
