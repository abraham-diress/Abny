import type {
  AgentEvent,
  Brief,
  CandidateResult,
  EventPayloads,
  FunnelStats,
  RunState,
  TodoItem,
} from "@/types/schemas";

export type Connection = "connecting" | "open" | "reconnecting" | "closed";

export interface AgentInfo {
  name: string;
  status: "working" | "done";
  task?: string;
  summary?: string;
}

export interface ActivityItem {
  seq: number;
  kind: "tool_call" | "tool_result" | "file_written" | "log" | "feedback" | "error";
  agent: string | null;
  text: string;
  ok?: boolean;
  ts: string;
}

export interface RunView {
  runId: string;
  state: RunState | "unknown";
  connection: Connection;
  brief: Brief | null;
  round: number;
  todos: TodoItem[];
  agents: AgentInfo[];
  activity: ActivityItem[];
  funnel: FunnelStats;
  results: CandidateResult[];
  error: string | null;
  lastSeq: number;
}

export const EMPTY_FUNNEL: FunnelStats = { total: 0, filtered: 0, ranked: 0, inspected: 0, fitted: 0 };
const MAX_ACTIVITY = 80;

export const initialRunView = (runId: string): RunView => ({
  runId,
  state: "unknown",
  connection: "connecting",
  brief: null,
  round: 0,
  todos: [],
  agents: [],
  activity: [],
  funnel: EMPTY_FUNNEL,
  results: [],
  error: null,
  lastSeq: 0,
});

export type RunAction =
  | { type: "event"; event: AgentEvent }
  | { type: "connection"; connection: Connection }
  | { type: "status"; state: RunState; brief: Brief | null; round: number; funnel: FunnelStats }
  | { type: "results"; results: CandidateResult[] }
  | { type: "failed"; error: string };

const byRank = (a: CandidateResult, b: CandidateResult) => a.rank - b.rank;

function push(state: RunView, item: ActivityItem): ActivityItem[] {
  return [item, ...state.activity].slice(0, MAX_ACTIVITY);
}

function upsertAgent(agents: AgentInfo[], next: AgentInfo): AgentInfo[] {
  const i = agents.findIndex((a) => a.name === next.name);
  if (i === -1) return [...agents, next];
  const copy = [...agents];
  copy[i] = { ...copy[i], ...next };
  return copy;
}

export function applyEvent(state: RunView, ev: AgentEvent): RunView {
  // Streams may replay earlier events after a reconnect: ignore anything already applied.
  if (ev.seq <= state.lastSeq) return state;
  // Any event may carry the current brief (the server attaches it when a feedback round starts).
  const carried = (ev.payload as { brief?: Brief } | undefined)?.brief;
  const base: RunView = { ...state, lastSeq: ev.seq, brief: carried && typeof carried === "object" && "business_type" in carried ? carried : state.brief };
  const agent = ev.agent;
  const p = ev.payload as unknown;

  switch (ev.type) {
    case "run_started":
      return { ...base, state: "running", brief: (p as EventPayloads["run_started"]).brief ?? base.brief };
    case "plan_update":
      return { ...base, todos: (p as EventPayloads["plan_update"]).todos ?? [] };
    case "subagent_started": {
      const task = (p as EventPayloads["subagent_started"]).task;
      return { ...base, agents: upsertAgent(base.agents, { name: agent ?? "agent", status: "working", task, summary: undefined }) };
    }
    case "subagent_finished": {
      const summary = (p as EventPayloads["subagent_finished"]).summary;
      return { ...base, agents: upsertAgent(base.agents, { name: agent ?? "agent", status: "done", summary }) };
    }
    case "tool_call": {
      const { tool, args } = p as EventPayloads["tool_call"];
      const argText = args ? Object.entries(args).map(([k, v]) => `${k}=${String(v)}`).join(", ") : "";
      return { ...base, activity: push(base, { seq: ev.seq, kind: "tool_call", agent, text: `${tool}(${argText})`, ts: ev.ts }) };
    }
    case "tool_result": {
      const { tool, summary, ok } = p as EventPayloads["tool_result"];
      return { ...base, activity: push(base, { seq: ev.seq, kind: "tool_result", agent, text: `${tool}: ${summary ?? (ok ? "ok" : "failed")}`, ok, ts: ev.ts }) };
    }
    case "file_written":
      return { ...base, activity: push(base, { seq: ev.seq, kind: "file_written", agent, text: (p as EventPayloads["file_written"]).path, ts: ev.ts }) };
    case "funnel_update":
      return { ...base, funnel: (p as EventPayloads["funnel_update"]).funnel };
    case "candidate_ready": {
      const result = (p as EventPayloads["candidate_ready"]).result;
      const others = base.results.filter((r) => r.space.space_id !== result.space.space_id);
      return { ...base, results: [...others, result].sort(byRank) };
    }
    case "feedback_received": {
      const { feedback, round } = p as EventPayloads["feedback_received"];
      const text = typeof feedback === "string" ? feedback : (feedback?.text ?? ev.message ?? "feedback");
      return { ...base, state: "running", round, activity: push(base, { seq: ev.seq, kind: "feedback", agent, text, ts: ev.ts }) };
    }
    case "run_finished":
      return { ...base, state: "done", round: (p as EventPayloads["run_finished"]).round ?? base.round };
    case "error": {
      const detail = (p as EventPayloads["error"]).detail ?? ev.message ?? "Unknown error";
      return { ...base, state: "error", error: detail, activity: push(base, { seq: ev.seq, kind: "error", agent, text: detail, ts: ev.ts }) };
    }
    case "log":
      return ev.message ? { ...base, activity: push(base, { seq: ev.seq, kind: "log", agent, text: ev.message, ts: ev.ts }) } : base;
    default:
      return base;
  }
}

export function runReducer(state: RunView, action: RunAction): RunView {
  switch (action.type) {
    case "event":
      return applyEvent(state, action.event);
    case "connection":
      return { ...state, connection: action.connection };
    case "status":
      // Only fill gaps: live events are more current than a status snapshot.
      return {
        ...state,
        state: state.state === "unknown" ? action.state : state.state,
        brief: state.brief ?? action.brief,
        round: Math.max(state.round, action.round),
        funnel: state.lastSeq === 0 ? action.funnel : state.funnel,
      };
    case "results":
      return { ...state, results: state.results.length ? state.results : [...action.results].sort(byRank) };
    case "failed":
      return { ...state, state: "error", connection: "closed", error: action.error };
  }
}
