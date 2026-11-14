"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";
import { ApiError, getResults, getRun, sendFeedback, streamEvents } from "@/lib/api";
import { initialRunView, runReducer } from "@/lib/run-state";
import type { FeedbackRequest } from "@/types/schemas";

/** Live view of one run: subscribes to SSE and folds events into UI state. */
export function useRun(runId: string) {
  const [view, dispatch] = useReducer(runReducer, runId, initialRunView);
  const closeRef = useRef<(() => void) | null>(null);
  const lastSeqRef = useRef(0);
  /** Round the server is on (from the status snapshot / feedback reply): stream until it finishes. */
  const roundRef = useRef(0);

  const connect = useCallback(() => {
    closeRef.current?.();
    dispatch({ type: "connection", connection: "connecting" });
    closeRef.current = streamEvents(runId, {
      onOpen: () => dispatch({ type: "connection", connection: "open" }),
      onError: () => dispatch({ type: "connection", connection: "reconnecting" }),
      onEvent: (event) => {
        // A reconnect replays old events (including an old run_finished): only react to new ones.
        const fresh = event.seq > lastSeqRef.current;
        lastSeqRef.current = Math.max(lastSeqRef.current, event.seq);
        dispatch({ type: "event", event });
        const finishedRound = (event.payload as { round?: number }).round ?? 0;
        // Only the current round's run_finished ends the stream: on a reload of a run with feedback
        // rounds, earlier rounds' run_finished events replay first and must not cut the replay short.
        if (fresh && event.type === "run_finished" && finishedRound >= roundRef.current) {
          // Nothing more to stream until feedback starts a new round.
          closeRef.current?.();
          closeRef.current = null;
          dispatch({ type: "connection", connection: "closed" });
        }
      },
    });
  }, [runId]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Snapshot first: gives the brief/results if the page was reloaded mid-run.
        const status = await getRun(runId);
        if (cancelled) return;
        roundRef.current = status.round;
        dispatch({ type: "status", state: status.state, brief: status.brief, round: status.round, funnel: status.funnel });
        if (status.result_count > 0) dispatch({ type: "results", results: await getResults(runId) });
        if (!cancelled) connect();
      } catch (e) {
        if (!cancelled) dispatch({ type: "failed", error: e instanceof ApiError ? e.message : String(e) });
      }
    })();
    return () => {
      cancelled = true;
      closeRef.current?.();
      closeRef.current = null;
    };
  }, [runId, connect]);

  const submitFeedback = useCallback(
    async (body: FeedbackRequest) => {
      const status = await sendFeedback(runId, body);
      roundRef.current = status.round;
      dispatch({ type: "status", state: status.state, brief: status.brief, round: status.round, funnel: status.funnel });
      connect(); // the server streams the new round's events again
    },
    [runId, connect],
  );

  return { view, submitFeedback };
}
