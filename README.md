# Hestia

**See your business in a real vacant space before you sign the lease.**

A small-business owner says what they need ("second bakery location in Houston, ~20 seats, under $6k/month, needs parking"). Hestia's AI agent searches real vacant commercial spaces (CoStar listings and Matterport 3D scans, plus Vexcel aerial imagery), inspects the best ones, **places their business inside the real 3D tour**, renders a photorealistic "this is your bakery" image, and works out rent, fit-out cost and break-even. Every number links to its source.

The same engine also fits out **offices** ("office for a 25-person team in downtown LA, near transit, under $20k/month"): desks, meeting tables and a reception desk in the real 3D tour, with cost per desk instead of break-even. See [Business types](#business-types-bakery-first-office-second).

> **Find your name below** ([Abraham](#abraham) · [Natnael](#natnael) · [Biniyam](#biniyam) · [Yared](#yared)). Everything you need to build is listed under your name. Read [Contracts](#5-contracts-how-our-code-fits-together) before writing code.

---

## Contents
1. [Deadlines and hard rules](#1-deadlines-and-hard-rules)
2. [The pitch and what judges score](#2-the-pitch-and-what-judges-score)
3. [Architecture](#3-architecture)
4. [Quick start](#4-quick-start)
5. [Contracts: how our code fits together](#5-contracts-how-our-code-fits-together)
6. [Shared code (`shared/`)](#6-shared-code-shared)
7. [Kickoff checks (do these first)](#7-kickoff-checks-do-these-first)
8. [Milestones and timeline](#8-milestones-and-timeline)
9. [Team and tasks](#9-team-and-tasks)
10. [Git workflow](#10-git-workflow)
11. [Demo script (2 minutes)](#11-demo-script-2-minutes)
12. [Submission checklist](#12-submission-checklist)

---

## 1. Deadlines and hard rules

| When | What |
|---|---|
| **Sun 6:30 AM** | Our internal submit target on Devpost (buffer) |
| **Sun 8:00 AM** | **Hard deadline**, no exceptions |
| Sun 9:30 AM – 2:30 PM | In-person judging. **2-minute live demo**; an optional 2-min video goes on Devpost |

- **Never commit sponsor data or keys.** CoStar, Matterport and Vexcel data is licensed for this hackathon only. `data/` and `.env` are gitignored; keep it that way. The repo must be public.
- **Don't wait on each other.** Until a teammate's function exists, build against a small hand-made object of its return type (see [Contracts](#5-contracts-how-our-code-fits-together)).
- **Don't change a shared schema silently.** Post in the team chat first, and tell Biniyam so the frontend types match.
- **Bakery first, office second.** Bakery is the main demo; office is the second business type everyone supports (see [Business types](#business-types-bakery-first-office-second)). Other types are stretch goals.

## 2. The pitch and what judges score

**Problem:** finding a commercial space takes weeks of tours, and owners can't picture an empty room as their business. Hiring an architect to check fit costs money before you even know if the space works. Meanwhile empty storefronts hurt neighborhoods, and downtown office vacancy is near record highs.

**Tracks we're entering** (one project, several prizes):

| Track | Prize | What they score |
|---|---|---|
| HackPrinceton main: **Business & Enterprise** | AirPods Pro 3 each | creativity, utility, charity (societal need), avidity (passion + polish) |
| Best Overall (automatic) | PS5 + Mac Studio + Studio Display each | same rubric, across all projects |
| **CoStar "Inside and Out: AI for the Built World"** | $1,500 / $500 / $250 + AI-team interviews | 30% combines ≥2 data layers meaningfully, 30% agentic depth (plans and acts, not a chat wrapper), 25% "would someone switch it on Monday", 15% demo. Wants spatial/visual output |
| **LangChain Deep Agents** | Switch 2 | complex use case, real use of subagents + filesystem, demo |
| **Amazon Practical AI** | gift cards | creativity, usefulness, tech, UX (25% each); multi-step, adapts to feedback; Bedrock welcome |
| ChatOverflow leaderboard | cash | connect your coding agent; no submission needed |

**What makes us win:**
1. Every data layer does real work: CoStar (rent, tenants, competitors), Matterport (rooms, panoramas, 3D tour), Vexcel (parking, surroundings).
2. A real Deep Agent that plans, uses subagents and files, and **re-plans on feedback**.
3. The UI is not a chat window: a live agent plan, a map, and a 3D tour the agent furnishes. CoStar's VP asked for exactly this in the workshop.
4. Numbers with sources and measured quality (layout validity %, image scores).
5. One engine, more than one business: the demo fits out a bakery, then an office, with the same agent and the same code.

### Business types: bakery first, office second

`Brief.business_type` decides what each part of the system does. **Everyone supports `bakery` and `office`.** `cafe` and `retail` reuse the bakery path (stretch).

| Part (owner) | Bakery (main demo) | Office (second demo) |
|---|---|---|
| Example brief | "Second bakery in Houston, ~20 seats, under $6k/month, needs parking" | "Office for a 25-person team in downtown LA, near transit, under $20k/month" |
| `parse_brief` (Abraham) | `seats_wanted` = customer seats | `business_type="office"`, `seats_wanted` = desks (headcount) |
| `query_spaces` (Natnael) | retail/restaurant spaces | office spaces |
| `neighborhood_profile` (Natnael) | competitors (other bakeries/cafés), foot traffic, parking | `amenities` (food, cafés, gyms nearby), transit weighted higher, no competitors |
| `inspect_space` (Abraham) | storefront glass, existing kitchen, vent hood, restroom | `natural_light`, `existing_build_out` (open plan / private offices / shell), restrooms, ceiling |
| `plan_layout` (Yared) | display case + counter by the door, ovens/prep at the back, café tables | reception by the door, desk pods in the open area, meeting table, kitchenette/storage on the back wall. Open plan only (no new walls) |
| `render_hero` (Yared) | "artisan bakery…" prompt | "modern open-plan office…" prompt |
| `estimate_costs` (Natnael) | fit-out, revenue, break-even months | fit-out, **cost per desk per month** (`cost_per_seat_month_*`), rent vs nearby office listings; revenue 0, break-even None |
| Results card (Biniyam) | revenue + break-even | cost per desk; hide revenue/break-even |

## 3. Architecture

```
OFFLINE (once, Natnael)                           PER REQUEST (funnel, Abraham orchestrates)
CoStar JSON + join CSVs ─┐                        brief ─► SQL filter (ms) ─► neighborhood rank
Matterport rooms/panos ──┼─► DuckDB + media cache        ─► inspect top ~20 (vision) ─► fit out top 5
Vexcel props/aerials ────┘   (data/, gitignored)          ─► hero image + score ─► numbers ─► results
                                                                │
              Frontend (Biniyam) ◄── REST + SSE ── FastAPI server + Deep Agent (Abraham)
              map · live plan · 3D tour · cards          │ imports the owners' functions        
                                                         ├─ Data Engine (Natnael): queries, costs
                                                         └─ Reimaginer (Yared): layout, guide, hero, score
```

**The funnel** (why it's fast and cheap):

| Stage | Runs | Spaces left | Time |
|---|---|---|---|
| Filter | SQL on cached facts (city, size, rent, has scan) | ~600 → ~150 | ms |
| Rank | neighborhood score (tenants, competitors, parking) | 150 → 20 | < 1 s |
| Inspect | vision model on cached panoramas | 20 → 5 | ~30–60 s |
| Fit out | layout → validate → 3D placement → hero image → score → numbers | 5 | ~30–60 s |

**Agent design (Deep Agents):** the orchestrator writes `/brief.md` and a todo list, dispatches subagents, and composes `/results/<space_id>/memo.md`.

| Subagent | Tools it calls | Writes |
|---|---|---|
| `scout` | `query_spaces`, `neighborhood_profile` | `/candidates/shortlist.md` |
| `inspector` | `get_panoramas`, `inspect_space` | `/candidates/<id>/inspection.md` |
| `designer` | `get_rooms`, `plan_layout`, `validate_layout` | `/candidates/<id>/layout.json` |
| `stager` | `render_hero` (uses `render_guide` + `score_image` inside) | `/candidates/<id>/hero.json` |
| `analyst` | `estimate_costs`, `draft_broker_email` | `/candidates/<id>/numbers.md` |

**Feedback loop:** "fewer seats, closer to transit" → the brief is updated → only the affected stages re-run (location/rent changes restart at `scout`; seats/layout changes restart at `designer`).

## 4. Quick start

```bash
git clone https://github.com/abraham-diress/hestia.git && cd hestia
cp .env.example .env                     # fill in keys from /costar-keys, AWS, etc.

# Python (3.11+). Install base + the extras for your role:
uv venv && source .venv/bin/activate
uv pip install -r pyproject.toml --extra dev                    # everyone
uv pip install -r pyproject.toml --extra agent                  # Abraham
uv pip install -r pyproject.toml --extra data                   # Natnael
uv pip install -r pyproject.toml --extra reimagine              # Yared
# (--extra vision adds torch/CLIP for the scorer and the optional CLIP index; large download)

python -c "import shared.schemas, shared.contracts"   # contracts import cleanly
```

## 5. Contracts: how our code fits together

### 5.1 Conventions (everyone)
- **Units:** meters and m² internally; USD per month for rent. sqft only for display (1 m² = 10.7639 sqft).
- **Coordinates:** Matterport model coordinates, **y is up**. Floor plans use `(x, z)` in meters. `rotation_deg` is about +y; 0 means the item's front faces +z.
- **Files:** schemas store **URL paths** relative to the API server root: `media/...` (generated/downloaded, under `data/media/`) or `assets/...` (committed, under `assets/`). Folder names are in `shared/conventions.py`. The frontend loads `${API_BASE}/${path}`.
- **Sources:** every fact from data carries a `Citation` (see `shared/schemas.py`). The UI shows them.
- **IDs:** `space_id` is ours (stable string per listing/property). It joins everything.

### 5.2 Contract functions (who implements what)
Every function is stubbed in [`shared/contracts.py`](shared/contracts.py) with its docstring and a `TODO(owner)`. **To implement one: create the module below and define a function with exactly that name and signature.** Callers then import it from the owner's module (e.g. `from pipeline.queries import query_spaces`). Until it exists, callers use their own small hand-made object of the return type.

| Function | Signature (returns) | Real module | Owner |
|---|---|---|---|
| `parse_brief` | `(text: str) -> Brief` | `agent/brief.py` | Abraham |
| `inspect_space` | `(space_id: str) -> Inspection` | `agent/tools/inspector.py` | Abraham |
| `query_spaces` | `(brief: Brief, limit: int = 200) -> list[Space]` | `pipeline/queries.py` | Natnael |
| `get_space` | `(space_id: str) -> Space` | `pipeline/queries.py` | Natnael |
| `get_rooms` | `(space_id: str) -> list[Room]` | `pipeline/queries.py` | Natnael |
| `get_panoramas` | `(space_id: str) -> list[PanoRef]` | `pipeline/queries.py` | Natnael |
| `neighborhood_profile` | `(space_id: str) -> NeighborhoodProfile` | `pipeline/queries.py` | Natnael |
| `visual_search` *(stretch)* | `(text: str, k: int = 20) -> list[tuple[str, float]]` | `pipeline/visual_search.py` | Natnael |
| `estimate_costs` | `(space: Space, layout: Layout \| None, inspection: Inspection \| None, brief: Brief) -> Numbers` | `agent/analyst/costs.py` | Natnael |
| `draft_broker_email` | `(space: Space, brief: Brief) -> str` | `agent/analyst/costs.py` | Natnael |
| `plan_layout` | `(space_id: str, rooms: list[Room], inspection: Inspection \| None, brief: Brief, strategy: str \| None = None) -> Layout` | `agent/layout/planner.py` | Yared |
| `validate_layout` | `(layout: Layout, rooms: list[Room]) -> ValidationReport` | `agent/layout/validator.py` | Yared |
| `render_guide` | `(layout: Layout, pano: PanoRef) -> str` (URL path) | `agent/staging/guide.py` | Yared |
| `render_hero` | `(space_id: str, layout: Layout, style: str \| None = None) -> HeroImage` | `agent/staging/generate.py` | Yared |
| `score_image` | `(original_path: str, generated_path: str, layout: Layout, guide_path: str \| None = None) -> ImageScore` | `agent/staging/score.py` | Yared |


### 5.3 HTTP API (Abraham implements; Biniyam calls; this table is the spec)

| Method + path | Body → Response |
|---|---|
| `GET /api/health` | → `{status, mode}` |
| `POST /api/runs` | `CreateRunRequest` → `CreateRunResponse` |
| `GET /api/runs/{run_id}` | → `RunStatus` |
| `GET /api/runs/{run_id}/events` | → `text/event-stream` of `AgentEvent` (SSE event name = `type`) |
| `GET /api/runs/{run_id}/results` | → `list[CandidateResult]`, sorted by rank |
| `POST /api/runs/{run_id}/feedback` | `FeedbackRequest` → `RunStatus` (`round` + 1; events stream again) |
| `GET /api/spaces/{space_id}` | → `Space` |
| `GET /api/catalog` | → `list[CatalogItem]` |
| `GET /media/...`, `GET /assets/...` | static files |

### 5.4 Event stream (SSE)
Each frame is `id: <seq>`, `event: <type>`, `data: <AgentEvent JSON>`. Payload keys per type:

| `type` | `payload` |
|---|---|
| `run_started` | `{brief}` |
| `plan_update` | `{todos: TodoItem[]}` (draw this as the live checklist) |
| `subagent_started` / `subagent_finished` | `{task}` / `{summary}` (`agent` = subagent name) |
| `tool_call` / `tool_result` | `{tool, args}` / `{tool, summary, ok}` |
| `file_written` | `{path}` (agent virtual FS path) |
| `funnel_update` | `{funnel: FunnelStats}` (the "600 → 150 → 20 → 5" counter) |
| `candidate_ready` | `{result: CandidateResult}` |
| `feedback_received` | `{feedback, round}` |
| `run_finished` | `{result_count, round}` |
| `error` / `log` | `{detail}` / `{}` (text in `message`) |

### 5.5 Data objects
All defined in [`shared/schemas.py`](shared/schemas.py). Biniyam mirrors the ones the frontend uses as TypeScript types in `web/`. The main ones:

`Brief` (what the owner asked for) · `Space` (listing + property + Matterport model) · `Room` (polygon, openings, ceiling) · `PanoRef` (cached panorama + camera pose) · `NeighborhoodProfile` · `Inspection` · `CatalogItem` · `Layout` / `LayoutItem` · `ValidationReport` · `HeroImage` / `ImageScore` · `Numbers` · `CandidateResult` (everything for one space, what the UI renders) · `AgentEvent` · `RunStatus`.

### 5.6 Who calls whom
- **Frontend → Server:** REST + SSE only, typed by the TS mirror of `schemas.py`.
- **Agent → Data Engine:** `query_spaces`, `get_space`, `get_rooms`, `get_panoramas`, `neighborhood_profile`, `estimate_costs`, `draft_broker_email`.
- **Agent → Reimaginer:** `plan_layout`, `validate_layout`, `render_hero` (which uses `render_guide` and `score_image`).
- **Frontend ← Reimaginer:** `assets/catalog.json` + GLB models (via `/api/catalog` and `/assets/...`), and each `Layout` inside `CandidateResult`.

## 6. Shared code (`shared/`)
Owned by nobody, used by everyone. It only **describes** what to build; all implementation lives in each owner's own folder. Change it with a small PR and tell the team.

| File | What it gives you |
|---|---|
| `schemas.py` | Every data object passed between members (the return types). The source of truth |
| `contracts.py` | Signature, inputs/outputs, module and owner of every cross-member function. Stubs with `TODO(owner)` only, no code |
| `conventions.py` | Agreed constants: folder names, agent file names, layout rules (aisle width, door clearance), funnel sizes. Units/coordinates in its docstring |

Folder layout once everyone has started (only `shared/` exists at first; each owner creates their own folders):

```
agent/        Abraham (brief.py, agent.py, cli.py, tools/inspector.py) · Natnael (analyst/costs.py) · Yared (layout/, staging/)
pipeline/     Natnael (ingest_costar.py, fetch_matterport.py, fetch_vexcel.py, queries.py)
server/       Abraham (app.py)
web/          Biniyam (Next.js)
assets/       Yared (catalog.json, glb/)
eval/         Yared (layout_eval.py, image_eval.py)
shared/ scripts/ tests/   everyone
```

## 7. Kickoff checks (do these first)

These decide the details of the build. **Post results in the team chat by 1:00 PM.**

| Gate | Owner | Test | If it fails |
|---|---|---|---|
| **G1 Coverage** | Natnael | Join CoStar listings for lease with the Matterport join CSVs. How many **retail/restaurant** and how many **office** listings have scans? (count them separately) | Fewer than ~30: switch to **broker mode**, searching vacant scanned commercial spaces (occupancy + scans) instead of listings. Same code, different filter |
| **G2 3D objects** | Biniyam | Load one GLB into one Matterport tour via the Showcase SDK; check scale and floor height | Fall back to a 2D floor-plan overlay plus the hero image |
| **G3 Image quality** | Yared | 5 real room photos × Gemini image models (`gemini-3.1-flash-image`, optionally `gemini-3-pro-image`) with a plan overlay: `python eval/g3_image_test.py --images ...` | Fewer than 3/5 convincing: drop the photoreal hero, keep 3D + style board |
| **G4 Room data** | Natnael | Which room fields exist: polygons, sizes, ceiling height, doors/windows, commercial room types (incl. office rooms like "conference room")? | Missing fields get defaults and go in `unverified_fields` |

Also: run `/costar-keys` (Natnael shares keys privately, never in git) and ask `/ask-costar` whether caching the data and training on it is allowed. We have no AWS keys, so all AI (agent, inspector, hero images, image judge) runs on **Gemini** with `GOOGLE_API_KEY` in `.env`.

## 8. Milestones and timeline

| Milestone | Target | What must work |
|---|---|---|
| **M0 Skeletons run** | **Sat 2:00 PM** | Each person's code runs on hand-made sample objects: agent CLI runs, UI renders sample results, layout/data modules return valid schema objects |
| **M1 One real space** | **Sat 7:00 PM** | One real space flows through everything: real data → layout → 3D placement → hero → numbers, in the UI |
| **M2 Full funnel** | **Sat 11:00 PM** | Search over all candidates, top 5 fitted, feedback loop works |
| **M3 Freeze** | **Sun 2:00 AM** | 5 demo spaces cached (3 bakery-ready + 2 office), `DEMO=1` works offline for both briefs. Bug fixes only after this |

- **Sun 2:00–6:00 AM:** polish, record the video, Devpost, rehearse the pitch 10+ times. Sleep in shifts.
- **Sun 6:30 AM:** submit. 8:00 AM hard deadline.

## 9. Team and tasks

Each task has a **Due** milestone and a **Priority**: **Core** (needed for the demo) or **Stretch** (only after your core tasks are done). Check boxes in your PRs as you go.

---

<a id="abraham"></a>

### 🧠 Abraham: The Brain (Agent + Integration)

**Mission:** the AI agent itself, the server that streams its progress, and merging everyone's code into one working app.
**You own:** `agent/agent.py`, `agent/cli.py`, `agent/brief.py`, `agent/tools/`, `server/`. You also review and merge PRs.
**You expose:** `parse_brief`, `inspect_space` (contract functions) and the HTTP API (§5.3) + event stream (§5.4).
**You consume:** every other contract function, imported from its owner's module (see §5.2).

| # | Task | Details | Done when | Due | Priority |
|---|---|---|---|---|---|
| B1 | Agent skeleton | `agent/agent.py: build_agent()` with `create_deep_agent`: orchestrator system prompt + 5 subagents (scout, inspector, designer, stager, analyst), each with its tools (wrap the contract functions). Use the `AGENT_*` file names from `shared/conventions.py` | `python -m agent.cli "bakery in Houston, 20 seats, under $6k"` writes `/brief.md` + `/candidates/*` and prints a ranked list (on sample objects) | M0 | Core |
| B2 | Brief parser | `agent/brief.py: parse_brief(text) -> Brief` via structured output. Offices: `business_type="office"`, headcount → `seats_wanted` | 5 sample prompts parse correctly, including 2 office ones ("team of 25…") | M0 | Core |
| B3 | Server | `server/app.py`: the routes in §5.3. Run the agent as a background task; turn its stream (todo updates, file writes, tool calls, subagent start/finish) into numbered `AgentEvent`s sent as SSE (§5.4); store results per run. Ship a stub version early that returns sample results so Biniyam can connect | Biniyam's UI talks to your server | M0 | Core |
| B4 | Tool wiring | Clear tool docstrings (the LLM reads them). Tool errors return a message instead of crashing; add timeouts | The agent recovers from one failing tool | M1 | Core |
| B5 | Inspector | `agent/tools/inspector.py: inspect_space(space_id) -> Inspection`: 3–5 panoramas (`get_panoramas`) → Claude vision with a checklist (storefront glass, existing kitchen/vent hood, restroom, ceiling estimate, `natural_light`, `existing_build_out`). Use the office checklist when `business_type="office"` (daylight, build-out, restrooms matter; kitchen doesn't). Anything it can't see goes in `unverified_fields` | Hand-checked on 5 real spaces (incl. 2 offices) | M1 | Core |
| B6 | Funnel + ranking | Orchestrator policy: filter → rank → inspect top `FUNNEL_INSPECT_TOP` → fit out top `FUNNEL_FIT_TOP` (in parallel). Emit `funnel_update`. Rank with `rank_score` + human-readable `rank_reasons` (offices: transit, amenities, daylight, cost per desk; bakery: foot traffic, competitors, parking, existing kitchen) | Full run in ~2 min on cached data, for both a bakery and an office brief | M2 | Core |
| B7 | Feedback loop | `POST feedback` → append to `Brief.feedback_history` → re-run only the affected stages → stream new events (`round` + 1) | "Fewer seats, closer to transit" re-ranks in under 60 s | M2 | Core |
| B8 | Demo mode | `DEMO=1`: record a full run's events + results to `data/runs/` and replay them. Record **two** runs: the bakery brief and the office brief | Demo works with Wi-Fi off | M3 | Core |
| B9 | Provider fallback | `LLM_PROVIDER=anthropic` path in case Bedrock misbehaves | Switching is one env var | M3 | Stretch |

**Definition of done:** the agent decides *when* to call tools (real planning, visible in the plan panel), every result has reasons, nothing crashes on one bad space.

---

<a id="natnael"></a>

### 🗄️ Natnael: The Data Engine (Data + Numbers + Story)

**Mission:** turn CoStar, Matterport and Vexcel into a fast local database and media cache, answer the agent's data questions, do the money math, then own the story (Devpost, video, pitch).
**You own:** `pipeline/`, `agent/analyst/`, `data/` (local only), and the Devpost page.
**You expose:** `query_spaces`, `get_space`, `get_rooms`, `get_panoramas`, `neighborhood_profile`, `estimate_costs`, `draft_broker_email` (+ `visual_search` stretch).
**You consume:** `shared/` only.

**Indexing order** (start background downloads as soon as G1 picks the set; everyone else builds on sample objects meanwhile):

| Step | What | Priority |
|---|---|---|
| 1 | CoStar JSON + 2 join CSVs → DuckDB (`DB_PATH` in `shared/conventions.py`), `spaces` view | Core, ~1 h |
| 2 | Pick the candidate set (500–1,500 spaces) after G1: retail/restaurant **and** office spaces with scans | Core |
| 3 | Matterport rooms + scan poses per candidate | Core, background |
| 4 | Vexcel property data + 1 ortho + 1 oblique crop per candidate | Core, background |
| 5 | ~5 panorama faces per candidate (furniture-free where available) | Core for the top spaces |
| 6 | CLIP embeddings → `visual_search` | Stretch |

Vexcel's own `/v2/embedding/extract` already searches aerial imagery, so we never index aerial images ourselves. **Cache the 5 demo spaces completely first.**

| # | Task | Details | Done when | Due | Priority |
|---|---|---|---|---|---|
| D1 | Keys + gates | `/costar-keys` → `.env` (share privately); one test call per API; run **G1** (retail/restaurant and office counts separately) and **G4** | Results posted in chat | 1:00 PM | Core |
| D2 | CoStar ingest | `pipeline/ingest_costar.py`: the 8 datasets (commercial property, commercial listing, location occupancy, company detail, sale comps, apartment listings, residential listings, listing features) + the 2 Matterport join CSVs → DuckDB tables; a `spaces` view with one row per candidate | `SELECT count(*) FROM spaces WHERE has_scan` works | M0 | Core |
| D3 | Matterport fetch | `pipeline/fetch_matterport.py`: rooms (polygon, type, area, floor height, openings if available), scan poses + intrinsics, panorama faces → DuckDB + `data/media/panos/<model>/<scan>_<face>.jpg`. Resumable (skip cached), rate-limited, logs failures | Demo spaces fully cached | M1 | Core |
| D4 | Vexcel fetch | `pipeline/fetch_vexcel.py`: `/v2/property/extract` (footprint, parcel, attributes), ortho + oblique crops → DuckDB + `data/media/aerial/` | Same | M1 | Core |
| D5 | Query functions | `pipeline/queries.py`: the 5 data contract functions. `query_spaces` filters property type by `brief.business_type` (office → office spaces). `neighborhood_profile`: tenants within ~400 m (occupancy/company detail), nearby apartment units, competitors by tenant-name match ("bakery", "café"…), parking via Vexcel data/embedding search, a 0–1 `score`. Offices: leave `competitors` empty, fill `amenities` (restaurants, cafés, gyms nearby) and weight transit higher. **Every value carries a `Citation`** | Abraham's agent runs on real data | M1 | Core |
| D6 | Numbers | `agent/analyst/costs.py`: `estimate_costs` (rent from listing; fit-out $/sqft range, lower if `existing_kitchen`; revenue = seats × turns × ticket × days; break-even months; every assumption in `assumptions`) and `draft_broker_email`. **Offices:** fit-out $/sqft for office build-out (lower if `existing_build_out` is already open plan), `cost_per_seat_month_*` = (rent + fit-out spread over the lease) / desks, rent compared with nearby office listings (cite them); revenue 0, break-even None | Numbers card filled with real data and sources, for a bakery and an office | M2 | Core |
| D7 | Demo cache | 5 demo spaces fully cached and hand-checked: 3 for the bakery brief + 2 for the office brief (picked with Yared + Biniyam for good visuals) | `DEMO=1` has everything it needs | M3 | Core |
| D8 | Story | Devpost write-up, 2-min pitch script with one sourced stat on small-business site selection or vacancy (plus one on office vacancy for the office moment), edit the video from Biniyam's recording, polish this README's pitch | Submitted by 6:30 AM | Sun AM | Core |
| D9 | CLIP index | `pipeline/visual_search.py` over panorama embeddings (LanceDB) | Free-text "bright open front room" works | M2 | Stretch |

**Definition of done:** the agent never waits on a live API during the demo, and every number can be traced to a record.

---

<a id="biniyam"></a>

### 🖥️ Biniyam: The Experience (Frontend)

**Mission:** everything the judges see: the live agent, the map, the real 3D tour with the business inside, and results they trust.
**You own:** `web/` (Next.js). Put the Matterport SDK key in `web/.env.local` as `NEXT_PUBLIC_MATTERPORT_SDK_KEY` (gitignored).
**You expose:** the UI. Record the demo screen for the video.
**You consume:** the HTTP API + SSE (§5.3–5.4), typed with your TS mirror of `shared/schemas.py`; the catalog + GLBs from `/api/catalog` and `/assets/...`.

| # | Task | Details | Done when | Due | Priority |
|---|---|---|---|---|---|
| E1 | Gate G2 | Blank page embedding the Matterport Showcase SDK; load one GLB at a coordinate; check floor alignment and scale | Report posted: works / need fallback | 1:00 PM | Core |
| E2 | App scaffold | Next.js in `web/`; TS types for the schemas you use in `web/src/types/`; `web/src/lib/api.ts` with `createRun`, `streamEvents` (EventSource), `getResults`, `sendFeedback`, `getCatalog`; base URL from `NEXT_PUBLIC_API_BASE` (default `http://localhost:8000`) | Renders hand-made sample results; switches to Abraham's server when it's up | M0 | Core |
| E3 | Brief screen | Big text box + quick chips (business type incl. **Office**, city, seats/desks, max rent) → `POST /api/runs`. Two example briefs one click away: bakery and office | Starts a run and opens the run view | M0 | Core |
| E4 | Agent plan panel | Live from SSE: todo checklist (`plan_update`), which subagent is working, recent tool calls, the funnel counter (`funnel_update`), "file written" notes | Updates live during a run | M1 | Core |
| E5 | 3D tour | `<SpaceTour spaceId layout />`: load the space's Matterport model; place one GLB per `LayoutItem` at `(x_m, floor_y, z_m)` rotated by `rotation_deg`; toggle furniture on/off; jump to a room. Works for any `item_type` in the catalog (office items too); never hard-code bakery items | A real space with furniture placed correctly (bakery and office) | M1 | Core |
| E6 | Map | MapLibre: candidate pins colored by rank; aerial crop for the selected space; competitor, amenity and transit pins from `NeighborhoodProfile` | Click a pin → that space opens | M1 | Core |
| E7 | Results | Ranked cards + detail view: `rank_reasons`, before/after slider (empty panorama vs hero), numbers with **source tooltips** from citations, "Email broker" showing the draft, validation badge. Numbers card by business type: bakery shows revenue + break-even; office shows **cost per desk / month** and hides revenue/break-even. Label seats as "desks" for offices | Every number shows its source | M2 | Core |
| E8 | Feedback UI | Reject a result + free text ("fewer seats, closer to transit") → `POST feedback`; reconnect to events; show the re-ranking | Demo step 4 works | M2 | Core |
| E9 | Polish + recording | Loading/empty/error states; check at projector resolution; screen-record the demo for the video | Recording handed to Natnael | M3 | Core |
| E10 | Animations | Smooth re-rank animation, camera fly-through between rooms | Looks great | M3 | Stretch |

**Definition of done:** a judge understands what's happening without you talking: the plan panel shows the agent thinking, and the tour shows the result.

---

<a id="yared"></a>

### 🎨 Yared: The Reimaginer (Layout + Visuals)

**Mission:** the "wow." Decide where the counter, ovens and tables (or desks and meeting tables) go in the real rooms, and make the photorealistic "this is your bakery / office" image, with measured quality.
**You own:** `agent/layout/`, `agent/staging/`, `assets/` (catalog + GLBs), `eval/`.
**You expose:** `plan_layout`, `validate_layout`, `render_guide`, `render_hero`, `score_image`, and `assets/catalog.json`.
**You consume:** `Room`, `PanoRef`, `Inspection`, `Brief` (hand-made samples first, then Natnael's/Abraham's real functions).

**Stack:**

| Step | Tool/model | Output |
|---|---|---|
| Layout | Python + shapely + rule templates per business type (an LLM only picks a strategy when rules conflict) | `Layout` |
| Furniture catalog | CC0 GLB models (Poly Haven, Kenney, Sketchfab CC0) scaled to meters | `assets/catalog.json` + `assets/glb/` |
| Guide | numpy/OpenCV: project each item's 3D box onto a flat panorama face using the scan pose | guide PNG |
| Hero | **Gemini image model** (`gemini-3.1-flash-image`, ~10 s/image): edits the real photo using a placement map of the boxes, then the real photo is pasted back outside the furniture areas so walls can't move. Nova Canvas on Bedrock still works with `IMAGE_PROVIDER=bedrock_nova` | `HeroImage` |
| Scorer | Edge/correlation checks outside the boxes (building unchanged), change inside the boxes (plan followed), Gemini vision judge `gemini-3.5-flash` (realism) | `ImageScore` |

The frontend does no AI: it places your GLBs exactly where your `Layout` says. **Your `Layout` is the contract between you and Biniyam.**

| # | Task | Details | Done when | Due | Priority |
|---|---|---|---|---|---|
| R1 | Gate G3 | 5 spaces × 2 image models with a hand-drawn guide; rate building unchanged / follows plan / realism | Keep/drop decision posted | 1:00 PM | Core |
| R2 | Asset catalog | `assets/catalog.json` (list of `CatalogItem`) with ~10 bakery items: display case, service counter, deck oven, prep table, sink, proofing rack, table for 2, bench table for 4, chair, menu board. GLBs in `assets/glb/`, real-world scale in meters | Validates as `list[CatalogItem]`; Biniyam loads every GLB | M0 | Core |
| R3 | Templates | `agent/layout/templates.py`: bakery template (zones: entrance clear area, service line near the entrance/storefront, seating front zone, back of house on the plumbing/back wall), required items, counts by area/seats | Bakery template complete | M1 | Core |
| R4 | Planner | `agent/layout/planner.py: plan_layout(...)`: find the entrance (door openings, else storefront wall, else ask the LLM), assign zones, place wall items greedily, then a seating grid; maximize seats up to `brief.seats_wanted` | Valid layouts on 5 real spaces | M1 | Core |
| R5 | Validator | `agent/layout/validator.py: validate_layout(...)`: inside rooms, no overlaps, every seat reachable from the entrance with aisles ≥ `MIN_AISLE_M` (grid BFS), entrance clear (`DOOR_CLEARANCE_M`) from `shared/conventions.py`, seat count | Catches deliberately broken layouts | M1 | Core |
| R6 | Guide | `agent/staging/guide.py: render_guide(layout, pano) -> str`: project boxes onto the panorama face (camera pose + FOV), color-coded per item class. Also a top-down plan PNG (UI fallback) | Guide lines up with the room | M2 | Core |
| R7 | Hero | `agent/staging/generate.py: render_hero(...)`: pick the face that shows the most items, call the image model with photo + placement map + prompt (business type + `brief.style`), 2 variants, keep the best by `score_image`, retry once if both fail; fall back to the plan image if generation fails | 1 good hero per demo space | M2 | Core |
| R8 | Scorer | `agent/staging/score.py: score_image(...)` with thresholds → `passed` | Bad images rejected automatically | M2 | Core |
| R9 | Evals | `eval/layout_eval.py` (% valid layouts, avg seats vs requested), `eval/image_eval.py` (score stats; hand-rate 10 to sanity-check the scorer) | Numbers for the pitch | M3 | Core |
| R10 | Office | Office catalog items (desk pod, single desk, meeting table, reception desk, sofa, phone booth, storage, kitchenette counter) + GLBs; office template (reception by the door, desk pods in the open area, meeting table, kitchenette/storage on the back wall; `seat_count` = desks; open plan only); office hero prompt; office briefs in `eval/layout_eval.py` | Office brief for 25 desks gives a valid layout | M2 | Core |
| R11 | More business types | Café and retail templates | Brief with "café" works | M3 | Stretch |

**Definition of done:** every layout the demo shows passes the validator, and every hero image shown passed the scorer.

**Using the Reimaginer** (for Abraham and Biniyam):
- `from agent.layout.planner import plan_layout` / `from agent.layout.validator import validate_layout`: deterministic, ~0.2 s, no API keys. The planner tries a back counter and a side counter and keeps the better one; `Layout.notes` says what it couldn't fit.
- `from agent.staging.generate import render_hero`: needs `get_panoramas` from `pipeline.queries` and `GOOGLE_API_KEY`. Never raises on image-API trouble: it returns the plan image instead and says why in `HeroImage.model`. `HERO_MODE=preview` skips AI entirely (UI work); tests always run in preview mode (`tests/conftest.py`) so they never use the Gemini quota.
- `from agent.staging.guide import render_floorplan`: top-down plan PNG of any layout (`media/guides/<layout_id>_plan.png`), a good fallback view.
- `from agent.layout.catalog import catalog_list`: what `GET /api/catalog` returns. Models are in `assets/glb/`: meters, origin at the floor center, front faces +z. Rebuild with `python assets/build_assets.py`.
- **Offices** (`business_type="office"`, strategy `open-plan`): reception desk by the door, meeting table in the room labeled conference/meeting (else the back room, else the open area if the desks still fit), kitchenette + storage on back walls, desk pods on the open floor and single desks on side walls. `seat_count` counts desks (pods add 4, so it can land 1-3 over). Office item names match Natnael's cost table (`desk_pod`, `single_desk`, `meeting_table`, `reception_desk`, `sofa`, `phone_booth`, `storage_cabinet`, `kitchenette_counter`).
- Evals: `python eval/layout_eval.py` (200 synthetic floor plans: 100% valid, 91.5% fit every requested seat, median 0.19 s); `python eval/layout_eval.py --business office` (100% valid; the synthetic plans are shop-sized, so use real office spaces for desk-fit numbers), `python eval/image_eval.py`, gate G3: `python eval/g3_image_test.py --images ...`.
- Tests: `pytest tests/reimagine -q`.

---

## 10. Git workflow
- `main` must always run.
- Branch per person, e.g. `abraham/agent`, `natnael/pipeline`, `biniyam/web`, `yared/reimagine`. Small PRs, often. Abraham merges; ping in chat.
- Pull `main` into your branch at least every couple of hours.
- Never commit `.env`, `data/`, or anything from the sponsor data dump. Check `git status` before every commit.
- Changing `shared/`: tell the team first; small PR.

## 11. Demo script (2 minutes)
1. **(15 s)** The problem: "Finding a space takes weeks of tours, and you still can't picture it." One sourced stat.
2. **(20 s)** Type Maria's brief → the plan panel fills in, subagents fan out, the funnel counter drops: "600 → 150 → 20 → 5."
3. **(35 s)** Open #1: map with parking and competitors → walk the **real 3D tour with her bakery inside** → photoreal hero → rent, fit-out and break-even with sources.
4. **(20 s)** "Fewer seats, closer to transit" → the agent re-plans and re-ranks live.
5. **(12 s)** "Same engine, different business": click the office brief (replayed) → a vacant office with 25 desks in the 3D tour, cost per desk.
6. **(18 s)** Quality numbers (layouts 100% valid, X% of images kept the building intact), roadmap (broker mode, scan your own space), close.

## 12. Submission checklist
- [ ] Repo public; created during the event; no data, no keys (`git log -p | grep -i key` check)
- [ ] Devpost: tracks = Business & Enterprise + CoStar + LangChain + Amazon (+ ChatOverflow), every member's Discord username, video link
- [ ] README: setup steps work from a fresh clone
- [ ] Demo works offline (`DEMO=1`) and a screen recording exists as backup
- [ ] Pitch rehearsed; under 2 minutes
