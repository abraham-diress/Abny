import { API_BASE } from "@/lib/config";
import {
  EVENT_TYPES,
  type AgentEvent,
  type CandidateResult,
  type CatalogItem,
  type CreateRunRequest,
  type CreateRunResponse,
  type FeedbackRequest,
  type Room,
  type RunStatus,
  type Space,
} from "@/types/schemas";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, `Cannot reach the Hestia API at ${API_BASE}. Is the server (or \`npm run mock\`) running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const health = () => request<{ status: string; mode: string }>("/api/health");

export const createRun = (body: CreateRunRequest) =>
  request<CreateRunResponse>("/api/runs", { method: "POST", body: JSON.stringify(body) });

export const getRun = (runId: string) => request<RunStatus>(`/api/runs/${encodeURIComponent(runId)}`);

export const getResults = (runId: string) =>
  request<CandidateResult[]>(`/api/runs/${encodeURIComponent(runId)}/results`);

export const sendFeedback = (runId: string, body: FeedbackRequest) =>
  request<RunStatus>(`/api/runs/${encodeURIComponent(runId)}/feedback`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getSpace = (spaceId: string) => request<Space>(`/api/spaces/${encodeURIComponent(spaceId)}`);

/** PROPOSED endpoint (not in README §5.3 yet): rooms of a space, for the floor plan and tour. */
export const getRooms = (spaceId: string) => request<Room[]>(`/api/spaces/${encodeURIComponent(spaceId)}/rooms`);

export const getCatalog =() => request<CatalogItem[]>("/api/catalog");

export interface StreamHandlers {
  onEvent: (event: AgentEvent) => void;
  onOpen?: () => void;
  /** Called on connection drops. EventSource retries on its own; this is for UI state only. */
  onError?: () => void;
}

/**
 * Subscribe to a run's SSE stream. Each frame is `event: <type>` + `data: <AgentEvent JSON>`.
 * Consumers must dedupe by `seq`, because a (re)connect may replay earlier events.
 * Returns a function that closes the stream.
 */
export function streamEvents(runId: string, handlers: StreamHandlers): () => void {
  const es = new EventSource(`${API_BASE}/api/runs/${encodeURIComponent(runId)}/events`);
  es.onopen = () => handlers.onOpen?.();
  es.onerror = () => handlers.onError?.();
  for (const type of EVENT_TYPES) {
    es.addEventListener(type, (e) => {
      try {
        handlers.onEvent(JSON.parse((e as MessageEvent<string>).data) as AgentEvent);
      } catch (err) {
        console.error(`Bad ${type} event`, err);
      }
    });
  }
  return () => es.close();
}
