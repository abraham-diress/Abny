/**
 * Mock Hestia API: same routes and event stream as README §5.3–5.4, backed by fixtures.
 * Run:  npm run mock     (listens on :8000 by default, the same port as the real server)
 * Speed up / slow down the scripted run with MOCK_SPEED (e.g. MOCK_SPEED=3).
 */
import { serve } from "@hono/node-server";
import { Hono } from "hono";
import { cors } from "hono/cors";
import { streamSSE } from "hono/streaming";
import type {
  AgentEvent,
  Brief,
  CandidateResult,
  CreateRunRequest,
  EventType,
  FeedbackRequest,
  FunnelStats,
  RunStatus,
  TodoItem,
} from "../src/types/schemas";
import fs from "node:fs";
import path from "node:path";
import { ROOMS, seedIds, SEED_SCORES, SEED_TRANSIT, SPACES, buildResult, type Kind, mockParseBrief } from "./fixtures";
import { MOCK_ASSETS_DIR, MOCK_MEDIA_DIR, REAL_ASSETS_DIR, REAL_MEDIA_DIR } from "./paths";
import { loadCatalog, writeMockAssets } from "./reimaginer";

// Yared's stand-in files: assets/catalog.json + assets/glb/*.glb (regenerated on every start).
writeMockAssets();

const PORT = Number(process.env.PORT ?? process.env.API_PORT ?? 8000);
const SPEED = Number(process.env.MOCK_SPEED ?? 1);
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms / SPEED));

// --- Run state -----------------------------------------------------------------

class Run {
  events: AgentEvent[] = [];
  listeners = new Set<() => void>();
  status: RunStatus;
  results = new Map<string, CandidateResult>();
  seats: number;
  kind: Kind;

  constructor(public id: string, public brief: Brief) {
    this.kind = brief.business_type === "office" ? "office" : "bakery";
    this.seats = brief.seats_wanted ?? (this.kind === "office" ? 25 : 20);
    this.status = {
      run_id: id,
      state: "queued",
      brief,
      funnel: { total: 0, filtered: 0, ranked: 0, inspected: 0, fitted: 0 },
      result_count: 0,
      round: 0,
      error: null,
    };
  }

  emit<T extends EventType>(type: T, payload: Record<string, unknown>, agent: string | null = "orchestrator", message: string | null = null) {
    const ev = {
      run_id: this.id,
      seq: this.events.length + 1,
      type,
      ts: new Date().toISOString(),
      agent,
      message,
      payload,
    } as unknown as AgentEvent;
    this.events.push(ev);
    this.listeners.forEach((l) => l());
  }

  sorted(): CandidateResult[] {
    return [...this.results.values()].sort((a, b) => a.rank - b.rank);
  }
}

const runs = new Map<string, Run>();
let runCounter = 0;

const todos = (kind: Kind, done: number, active: number | null): TodoItem[] =>
  ["Parse brief and write /brief.md", "Scout: filter and rank spaces", "Inspector: check the top 20 panoramas", "Designer: lay out the business in the top picks", "Stager: render and score hero images", kind === "office" ? "Analyst: rent, fit-out cost, cost per desk" : "Analyst: rent, fit-out cost, break-even"].map(
    (content, i) => ({ content, status: i < done ? "completed" : i === active ? "in_progress" : "pending" }),
  );

async function agentSteps(run: Run, from: "scout" | "designer", feedback?: string) {
  const funnel = (f: Partial<FunnelStats>) => {
    run.status.funnel = { ...run.status.funnel, ...f };
    run.emit("funnel_update", { funnel: run.status.funnel });
  };
  const tool = async (agent: string, name: string, args: Record<string, unknown>, summary: string, ms = 900) => {
    run.emit("tool_call", { tool: name, args }, agent, `Calling ${name}`);
    await sleep(ms);
    run.emit("tool_result", { tool: name, summary, ok: true }, agent, summary);
  };

  const ids = seedIds(run.kind);
  const first = ids[0];
  const n = ids.length;
  const unit = run.kind === "office" ? "desk" : "seat";

  if (from === "scout") {
    run.emit("plan_update", { todos: todos(run.kind, 1, 1) });
    run.emit("subagent_started", { task: "Find vacant spaces matching the brief" }, "scout");
    await tool("scout", "query_spaces", { city: run.brief.city, max_rent: run.brief.max_rent_month }, run.kind === "office" ? "238 office spaces, 61 pass the filter" : "612 spaces, 148 pass the filter");
    funnel(run.kind === "office" ? { total: 238, filtered: 61 } : { total: 612, filtered: 148 });
    await tool("scout", "neighborhood_profile", { space_ids: "148 spaces" }, run.kind === "office" ? "Ranked 61 → 20 by transit, amenities and daylight" : "Ranked 148 → 20 by neighborhood score");
    funnel({ ranked: 20 });
    run.emit("file_written", { path: "/candidates/shortlist.md" }, "scout");
    run.emit("subagent_finished", { summary: "Shortlisted 20 spaces" }, "scout");

    run.emit("plan_update", { todos: todos(run.kind, 2, 2) });
    run.emit("subagent_started", { task: "Inspect the top 20 panoramas" }, "inspector");
    await tool("inspector", "get_panoramas", { space_id: "top 20" }, "Loaded 4 panoramas per space", 700);
    await tool("inspector", "inspect_space", { space_id: first }, run.kind === "office" ? "Open plan, windows on 3 sides" : "Kitchen + vent hood found", 1100);
    funnel({ inspected: 20 });
    run.emit("file_written", { path: `/candidates/${first}/inspection.md` }, "inspector");
    run.emit("subagent_finished", { summary: `20 inspected, ${n} selected for fit-out` }, "inspector");
  } else {
    run.emit("log", {}, "orchestrator", `Feedback "${feedback}" changes the layout: restarting at designer`);
  }

  run.emit("plan_update", { todos: todos(run.kind, 3, 3) });
  run.emit("subagent_started", { task: "Place the business inside the real rooms" }, "designer");
  await tool("designer", "plan_layout", { space_id: `top ${n}`, seats: run.seats }, `Planned ${run.seats}-${unit} layouts`, 1200);
  await tool("designer", "validate_layout", { space_id: `top ${n}` }, `${n}/${n} layouts valid`);
  run.emit("file_written", { path: `/candidates/${first}/layout.json` }, "designer");
  run.emit("subagent_finished", { summary: `${n} valid layouts` }, "designer");

  run.emit("plan_update", { todos: todos(run.kind, 4, 4) });
  run.emit("subagent_started", { task: "Render and score hero images" }, "stager");
  await tool("stager", "render_hero", { space_id: `top ${n}` }, `${n} hero images, best of 2`, 1400);
  run.emit("file_written", { path: `/candidates/${first}/hero.json` }, "stager");
  run.emit("subagent_finished", { summary: `All ${n} images passed scoring` }, "stager");

  run.emit("plan_update", { todos: todos(run.kind, 5, 5) });
  run.emit("subagent_started", { task: "Estimate rent, fit-out and break-even" }, "analyst");
  await tool("analyst", "estimate_costs", { space_id: `top ${n}` }, "Numbers ready", 1000);
  run.emit("file_written", { path: `/candidates/${first}/numbers.md` }, "analyst");
  run.emit("subagent_finished", { summary: "Costs and sources attached" }, "analyst");

  // Rank order: by score, optionally boosted by transit feedback.
  const wantsTransit = /transit/i.test(run.brief.area_hint ?? "") || /transit/i.test(feedback ?? "");
  const order = [...ids].sort(
    (a, b) => SEED_SCORES[b] + (wantsTransit && SEED_TRANSIT[b] ? 0.2 : 0) - (SEED_SCORES[a] + (wantsTransit && SEED_TRANSIT[a] ? 0.2 : 0)),
  );
  for (const [i, id] of order.entries()) {
    const result = buildResult(id, i + 1, { ...run.brief, seats_wanted: run.seats }, run.id);
    if (wantsTransit && SEED_TRANSIT[id]) result.rank_reasons = [feedback ? "Closer to transit (per your feedback)" : "Close to transit, as you asked", ...result.rank_reasons.slice(0, 2)];
    run.results.set(id, result);
    run.status.result_count = run.results.size;
    funnel({ fitted: run.results.size });
    run.emit("candidate_ready", { result }, "orchestrator", `#${i + 1} ${result.space.address}`);
    await sleep(600);
  }
  run.emit("plan_update", { todos: todos(run.kind, 6, null) });
  run.status.state = "done";
  run.emit("run_finished", { result_count: run.results.size, round: run.status.round }, "orchestrator");
}

async function startRun(run: Run) {
  run.status.state = "running";
  run.emit("run_started", { brief: run.brief }, "orchestrator");
  try {
    await agentSteps(run, "scout");
  } catch (e) {
    run.status.state = "error";
    run.status.error = String(e);
    run.emit("error", { detail: String(e) });
  }
}

// --- HTTP ----------------------------------------------------------------------

const app = new Hono();
app.use("*", cors());

app.get("/api/health", (c) => c.json({ status: "ok", mode: "mock", catalog: loadCatalog().source }));

app.post("/api/runs", async (c) => {
  const body = (await c.req.json()) as CreateRunRequest;
  if (!body?.text) return c.json({ detail: "text is required" }, 422);
  const brief = body.brief ?? mockParseBrief(body.text);
  const run = new Run(`run_${++runCounter}`, brief);
  runs.set(run.id, run);
  void startRun(run);
  return c.json({ run_id: run.id });
});

const getRun = (id: string) => runs.get(id);

app.get("/api/runs/:id", (c) => {
  const run = getRun(c.req.param("id"));
  return run ? c.json(run.status) : c.json({ detail: "run not found" }, 404);
});

app.get("/api/runs/:id/results", (c) => {
  const run = getRun(c.req.param("id"));
  return run ? c.json(run.sorted()) : c.json({ detail: "run not found" }, 404);
});

app.get("/api/runs/:id/events", (c) => {
  const run = getRun(c.req.param("id"));
  if (!run) return c.json({ detail: "run not found" }, 404);
  const last = Number(c.req.header("last-event-id") ?? 0) || 0;
  return streamSSE(c, async (stream) => {
    let cursor = last;
    let closed = false;
    let wake: (() => void) | null = null;
    const listener = () => wake?.();
    run.listeners.add(listener);
    stream.onAbort(() => {
      closed = true;
      run.listeners.delete(listener);
      wake?.();
    });
    while (!closed) {
      while (cursor < run.events.length) {
        const ev = run.events[cursor++];
        await stream.writeSSE({ id: String(ev.seq), event: ev.type, data: JSON.stringify(ev) });
      }
      await new Promise<void>((resolve) => {
        wake = resolve;
        setTimeout(resolve, 15000);
      });
      wake = null;
      if (!closed && cursor >= run.events.length) await stream.write(": keep-alive\n\n");
    }
  });
});

app.post("/api/runs/:id/feedback", async (c) => {
  const run = getRun(c.req.param("id"));
  if (!run) return c.json({ detail: "run not found" }, 404);
  const body = (await c.req.json()) as FeedbackRequest;
  if (!body?.text) return c.json({ detail: "text is required" }, 422);
  run.status.round += 1;
  run.status.state = "running";
  run.brief = {
    ...run.brief,
    feedback_history: [...run.brief.feedback_history, { text: body.text, kind: body.kind ?? "constraint", space_id: body.space_id ?? null, created_at: new Date().toISOString() }],
  };
  run.status.brief = run.brief;
  const fewer = /fewer|less|smaller/i.test(body.text);
  if (fewer) run.seats = Math.max(8, run.seats - 6);
  run.emit("feedback_received", { feedback: body.text, round: run.status.round }, "orchestrator");
  if (body.kind === "reject" && body.space_id) run.results.delete(body.space_id);
  void agentSteps(run, "designer", body.text).catch((e) => {
    run.status.state = "error";
    run.status.error = String(e);
    run.emit("error", { detail: String(e) });
  });
  return c.json(run.status);
});

app.get("/api/spaces/:id", (c) => {
  const space = SPACES[c.req.param("id")];
  return space ? c.json(space) : c.json({ detail: "space not found" }, 404);
});

// PROPOSED (not in README §5.3 yet): the floor plan and 3D tour need the rooms of a space.
app.get("/api/spaces/:id/rooms", (c) => {
  const rooms = ROOMS[c.req.param("id")];
  return rooms ? c.json(rooms) : c.json({ detail: "space not found" }, 404);
});

// Yared's catalog: <repo>/assets/catalog.json when it exists, else the mock one.
app.get("/api/catalog", (c) => c.json(loadCatalog().items));

// Static files, real first: /assets/* from <repo>/assets then the mock assets;
// /media/* from <repo>/data/media then the mock media (guides, heroes).
const CONTENT_TYPES: Record<string, string> = {
  ".glb": "model/gltf-binary",
  ".gltf": "model/gltf+json",
  ".bin": "application/octet-stream",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".svg": "image/svg+xml",
  ".json": "application/json",
};

function sendFile(roots: string[], rel: string): Response | null {
  let clean: string;
  try {
    clean = path.posix.normalize(decodeURIComponent(rel));
  } catch {
    return null;
  }
  if (clean.startsWith("..") || path.isAbsolute(clean)) return null;
  for (const root of roots) {
    const file = path.resolve(root, clean);
    if (!file.startsWith(path.resolve(root) + path.sep)) continue;
    if (fs.existsSync(file) && fs.statSync(file).isFile()) {
      const type = CONTENT_TYPES[path.extname(file).toLowerCase()] ?? "application/octet-stream";
      return new Response(new Uint8Array(fs.readFileSync(file)), { headers: { "content-type": type, "cache-control": "no-cache" } });
    }
  }
  return null;
}

app.get("/assets/*", (c) => sendFile([REAL_ASSETS_DIR, MOCK_ASSETS_DIR], c.req.path.slice("/assets/".length)) ?? c.json({ detail: "asset not found" }, 404));

const svg = (body: string) => new Response(body, { headers: { "content-type": "image/svg+xml", "cache-control": "max-age=3600" } });

app.get("/media/*", (c) => {
  const rel = c.req.path.slice("/media/".length);
  const file = sendFile([REAL_MEDIA_DIR, MOCK_MEDIA_DIR], rel);
  if (file) return file;
  // Aerial crops are Natnael's (Vexcel); until they exist, draw a placeholder.
  if (!rel.startsWith("aerial/")) return c.json({ detail: "media not found" }, 404);
  const name = path.posix.basename(rel).replace(/\.\w+$/, "");
  return svg(`<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="640" height="480" fill="#5f7f55"/><rect x="40" y="260" width="560" height="60" fill="#444"/><rect x="250" y="150" width="140" height="90" fill="#c9b79c"/><rect x="60" y="330" width="200" height="110" fill="#6b6b6b"/><text x="320" y="60" font-family="sans-serif" font-size="28" text-anchor="middle" fill="#fff">Mock aerial: ${name}</text></svg>`);
});

serve({ fetch: app.fetch, port: PORT }, (info) => {
  console.log(`Hestia mock API on http://localhost:${info.port} (speed x${SPEED})`);
});
