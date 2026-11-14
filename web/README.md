# Hestia web (The Experience)

Next.js 16 + Tailwind 4 frontend. Owner: Biniyam. It does no AI: it shows the agent's live plan, ranked results, and (soon) the 3D tour and map. Spec: root [README §9](../README.md#biniyam).

## Run it

```bash
cd web
npm install
cp .env.example .env.local        # API base + Matterport SDK key (both optional for the mock)

npm run dev:mock                  # mock API on :8000 + web on :3000, together
```

Or separately: `npm run mock` (fake API) and `npm run dev` (web). Open http://localhost:3000.

To use Abraham's real server instead, stop the mock and start his server on port 8000 (or change `NEXT_PUBLIC_API_BASE`). No code changes needed: the mock implements the same routes and event stream as the root README §5.3 and §5.4.

| Script | What |
|---|---|
| `npm run dev` / `build` / `start` | Next.js |
| `npm run mock` | Fake API with a scripted agent run (`MOCK_SPEED=3` for 3x faster) |
| `npm run typecheck` / `lint` | `tsc --noEmit` / ESLint |

## Matterport 3D tour (Bundle SDK)

Placing GLB furniture needs the **Bundle SDK** (a self-hosted Showcase with the Scene API). The npm embed package `@matterport/sdk` can show a tour but has no Scene API.

1. Put the SDK key from `/costar-keys` in `.env.local` as `NEXT_PUBLIC_MATTERPORT_SDK_KEY`. The hackathon key allows `localhost`.
2. Download the bundle (about 11 MB, gitignored, covered by the Matterport SDK Agreement) and unzip it into `public/bundle/`:
   ```bash
   curl -L -o /tmp/showcase-bundle.zip https://static.matterport.com/showcase-sdk/bundle/26.10.4_webgl-1728-g1cd7e0997a/showcase-bundle.zip
   unzip -q /tmp/showcase-bundle.zip -d public/bundle
   ```
3. Open http://localhost:3000/g2 (gate G2). Pick an item, click **Place on floor**, move over the floor, press **P** to drop it (**R** rotates 90°, **Esc** stops). The panel shows positions and a placement report to paste in the team chat.

Code: `src/lib/matterport.ts` (connect, lights, `placeGlb`, rotation about +y) and `src/components/G2Tester.tsx`.

**GLB convention for Yared's assets:** meters, origin at the bottom center of the item, front facing +z. Then `LayoutItem` `(x_m, floor_y, z_m)` and `rotation_deg` map straight onto the node.

## Layout

```
src/types/schemas.ts     TS mirror of shared/schemas.py (keep in sync, same PR)
src/lib/api.ts           createRun, streamEvents (SSE), getResults, sendFeedback, getCatalog, getRooms
src/lib/run-state.ts     reducer: AgentEvent stream -> UI state (dedupes by seq)
src/hooks/useRun.ts      subscribes to a run and exposes { view, submitFeedback }
src/components/          BriefForm, RunScreen, PlanPanel, ResultList, SpaceDetail, NumbersCard, FloorPlan, ...
src/app/                 / (brief screen), /runs/[runId] (run view)
mock-server/             Hono mock API: fixtures.ts (sample data), glb.ts (placeholder GLBs), index.ts
```

## Mock server notes

- Sample data is fake (addresses, rents, Matterport id). Five Houston bakery spaces and two downtown LA office spaces, each with a layout, scripted events. A brief that mentions "office" gets the office spaces (desk pods, cost per desk); anything else gets bakeries.
- Feedback re-plans: "closer to transit" re-ranks, "fewer"/"less" lowers seats, a `reject` removes the space.
- **Yared's side is mocked in `mock-server/reimaginer/`**, with his contract functions and file layout:
  - `assets/catalog.json` + `assets/glb/<item_type>.glb` (box GLBs at real size, origin at the bottom center, front +z), 18 bakery and office items
  - `planLayout` (bakery and office templates), `validateLayout` (real checks: inside room, overlap, aisles ≥ 0.914 m, entrance clear 1.2 m)
  - `renderGuide` → `media/guides/<layout_id>.png` (top-down plan), `renderHero` → `media/heroes/<hero_id>.png` (flat-shaded view from the entrance), `scoreImage`
  - Files are written to `mock-server/.generated/` (gitignored) and served at the same URL paths as the real server.
- **Real rooms for the tour:** `npm run mock:rooms` fetches the sample model's room outlines from the Matterport Model API (needs `MATTERPORT_API_TOKEN_ID/_SECRET` in `.env.local`) into `.generated/rooms/` (gitignored: sponsor data). With them, the mock planner fits layouts into the real rooms so furniture lines up in the 3D tour; without them it uses made-up rectangles. Conversion: floor-plan (x, y) → model (x, z) = (x, −y); areas and heights come in feet.
- **Real files win:** `/assets/*` is served from `<repo>/assets` first and `/media/*` from `<repo>/data/media` first, falling back to the mock per file. `/api/catalog` returns `<repo>/assets/catalog.json` once Yared commits it (`/api/health` reports `catalog: "real" | "mock"`).
- Aerial crops (Natnael's) are still SVG placeholders.
- The server keeps runs in memory, so restarting it (including `tsx watch` reloads) drops them.

## Status

| Task | State |
|---|---|
| E2 scaffold, types, api client, mock server | done |
| E3 brief screen (Office chip, bakery + office example briefs) | done |
| Office business type: types synced with `shared/schemas.py` (amenities, natural_light, existing_build_out, cost_per_seat_month_*); numbers card shows cost per desk and hides revenue/break-even; "desks" labels | done against the mock |
| E4 agent plan panel (todos, subagents, funnel, activity) | done |
| E7 results: cards, hero, numbers with source tooltips, broker email, validation | mostly (before/after slider needs panoramas, see below) |
| E8 feedback UI (re-plan + reject) | done against the mock |
| E1 gate G2 test page (`/g2`) | passed: 2.4 × 0.8 × 1.0 m box measures exactly that in the scene, sits on the floor (±3 cm), 90° rotation swaps x/z, scan geometry occludes it |
| E5 `<SpaceTour>` (`src/components/SpaceTour.tsx`): real tour in the space detail, one GLB per `LayoutItem` at (x, room floor y, z) + `rotation_deg`, furniture on/off, dollhouse / floor plan, jump to rooms with furniture; falls back to the 2D plan without key/bundle/scan | done against the mock: 12/12 bakery items measured at their layout positions, on the floor, inside their real rooms |
| E6 map (`src/components/MapPanel.tsx`): candidate pins colored by rank (click → that space opens), competitors (bakery) or amenities (office) + transit for the selected space, aerial crop with parking score; OpenFreeMap basemap, plain background when offline (`NEXT_PUBLIC_MAP_STYLE=offline`) | done against the mock; real neighborhood data comes from Natnael via Abraham's results |
| E9/E10 polish, animation | not started |

## Running against the real server (integration)

```bash
# repo root, Python 3.11+
python -m venv .venv && .venv/Scripts/python -m pip install fastapi uvicorn httpx deepagents langchain-aws langchain-anthropic langchain-google-genai anthropic boto3 duckdb shapely numpy pillow opencv-python-headless trimesh google-genai pytest
.venv/Scripts/python -m pipeline.sample_data           # data/sample.duckdb (fake spaces)
HESTIA_DB_PATH=data/sample.duckdb HERO_MODE=preview SCORER_LLM=0 .venv/Scripts/python -m uvicorn server.app:app --port 8000
cd web && npm run dev                                   # same NEXT_PUBLIC_API_BASE, no code change
```

**Real data locally:** ask Natnael for the demo pack (`python -m pipeline.pack_demo`, shared privately), unzip it in the repo root, and run the server without `HESTIA_DB_PATH`. Then spaces have real Matterport ids and the tour loads the real scan with the furniture in it.

**Briefs and empty results:** the brief form folds the chips into the text ("…. Office in Houston, about 25 desks, under $30,000/month.") so the server parses one description and nothing typed is lost; office budgets/desks use office-scale chips. The run header shows the conditions being searched. A run with no results explains why and offers one-click new searches with one condition loosened (budget ×2, any city, drop must-haves, any size).

Without a real scan (fake sample ids, unshared models, no SDK key) the tour detects Matterport's "model not available" in seconds and shows `LayoutViewer3D` instead: the layout in three.js with Yared's GLBs, cut-away walls, shadows and orbit controls (2D plan one click away). A preview hero (`HeroImage.model` starting with `preview`) is labelled "Placement preview", not shown as the photoreal image.

Checked on the merged `main` (scripted mode, no LLM key): bakery and office runs, live plan/events, results, map pins, numbers with sources, cost per desk, validation badge, preview hero, feedback round (re-rank + fewer desks). Sample spaces have fake Matterport ids, so the tour falls back to the floor plan after 30 s.

Frontend fixes from integration: `feedback_received.payload.feedback` is a `Feedback` object (not a string); "is this an office?" now trusts cost per desk / property type, not only `layout.business_type`; the numbers card's source tooltips match the analyst's assumption names (`fitout_psf_low`, `equipment_from_layout`, `furniture_from_layout`, `nearby_office_rent_median`, …) and show `breakeven_note`.

Re-checked after the catalog pricing fix (PRs #4, #5): fit-out now includes Yared's items priced by the analyst (e.g. bakery #1 $128,800–$351,400, was $116,500–$600,600), offices $478–600 and $948–1,156 per desk, funnel total from `count_spaces()`. Team test suite: 66 passed.

## Questions for Abraham (API gaps)

The README API has no way to fetch these, and the UI needs them:

1. **Rooms of a space.** The floor plan, "jump to room" and the tour need `Room[]` (polygons, openings). The mock serves a proposed `GET /api/spaces/{space_id}/rooms`; the UI falls back to a plan drawn from the layout alone if it 404s.
2. **Panoramas.** The before/after slider needs the empty panorama. `HeroImage` only has `source_pano_id`. Proposal: `GET /api/spaces/{space_id}/panoramas` -> `list[PanoRef]`, or add `source_pano_path` to `HeroImage`.
