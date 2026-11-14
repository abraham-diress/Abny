# Data Engine (`pipeline/` + `agent/analyst/`)

Owner: Natnael. Turns CoStar + Matterport + Vexcel (+ OpenStreetMap transit) into a local DuckDB file
and a media cache. Everything the agent calls reads only local data, so the demo never waits on a live API.

## For teammates: use it now

Without sponsor data (synthetic, clearly labeled `SAMPLE DATA`):

```bash
uv pip install -r pyproject.toml --extra data
python -m pipeline.sample_data                 # 12 retail + 4 office fake spaces -> data/sample.duckdb
export HESTIA_DB_PATH=data/sample.duckdb       # PowerShell: $env:HESTIA_DB_PATH="data/sample.duckdb"
```

```python
from pipeline.queries import query_spaces, get_space, get_rooms, get_panoramas, neighborhood_profile
from pipeline.queries import score_for_brief          # extra: brief-aware 0–1 score + rank_reasons
from agent.analyst.costs import estimate_costs, draft_broker_email
```

With the real DB (`data/hestia.duckdb`), unset `HESTIA_DB_PATH` and the same calls return real data.

Notes for callers:
- **Bakery and office.** Everything follows `brief.business_type` (README "Business types"):

  | | bakery (and cafe/retail/…) | office |
  |---|---|---|
  | `query_spaces` | retail spaces (`space_use` Retail / Office Retail); `seats_wanted` = customer seats | office spaces; `seats_wanted` = desks, sized at ~175 sqft/desk |
  | `neighborhood_profile(id, bt)` | `competitors` within 800 m, `amenities` empty | `amenities` (food, cafés, gyms within 500 m), `competitors` empty |
  | `score_for_brief` | foot traffic, residents, competition, parking | transit (heaviest), amenities, parking; reasons mention desks and lunch options |
  | `estimate_costs` | fit-out, revenue, break-even | fit-out (by `inspection.existing_build_out`), `cost_per_seat_month_*` = (rent + opex + fit-out / 60-month lease) / desks, rent vs nearby office listings (`nearby_office_rent_median` + one citation per comp); revenue 0, break-even None |
  | `draft_broker_email` | food-service questions | gross vs net, existing build-out/furniture, after-hours HVAC, fiber |

  **Abraham:** pass the brief's type: `neighborhood_profile(space_id, brief.business_type)`. The contract signature
  only has `space_id`, so without it you get the bakery profile (competitors, no amenities).
- `score` on the profile is brief-agnostic; use `score_for_brief(profile, brief, space)` for ranking. It re-weights for
  "transit"/"parking" in the brief and feedback, and returns human-readable reasons.
- `get_rooms`: real room outlines from Matterport `room.boundary` (`polygon_source='api'`), with doors/windows as
  `openings`, `ceiling_m` from `room.ceiling`, `room_type` from Matterport's classifier (e.g. "Kitchen"). Everything
  is converted to **y-up** (`x`, `z` = −API `y`). Rooms without a boundary fall back to rectangles (`approx_rect`).
- `get_panoramas`: cube faces (2048 px, 90° FOV), furniture-free variants first.
- `Space.citations` has a `has_scan` citation whose note says whether the scan is **of this suite**, **attached to
  the listing**, or **of the building (may be a different suite)**. Don't present a building scan as the suite.
- `estimate_costs` also puts `breakeven_months_base` (the headline number) and `revenue_month_base` in `assumptions`.

## Data sources and how we use them

| Source | Access | What we use |
|---|---|---|
| CoStar kit (zip from `/costar-keys`) | local files, `COSTAR_DATA_DIR=data/costar_kit/kit` | listings → spaces, rent, broker; property → location, parking ratio, year built; occupancy + company → nearby tenants/competitors; apartments + homes → residents; `commercial-properties.csv` → Matterport model per property |
| Matterport Model API | GraphQL `https://api.matterport.com/api/models/graph`, HTTP Basic (`MATTERPORT_API_TOKEN_ID` = "API key", `_SECRET` = "API token") | rooms (outline, openings, ceiling, type), scan poses, skybox faces |
| Matterport Showcase SDK | `MATTERPORT_SDK_KEY` (Biniyam: `NEXT_PUBLIC_MATTERPORT_SDK_KEY`), localhost only | 3D tour in the frontend |
| Vexcel API 2.0 | `https://api.vexcelgroup.com/v2`, `X-API-KEY: $VEXCEL_API_KEY` | `property/extract` (parcel, footprint, 76 attributes), `ortho/extract`, `oriented/extract` (oblique), `elements/detect` ("car", "parking lot" → parking score) |
| OpenStreetMap Overpass | no key | transit stops (credit "© OpenStreetMap contributors") |

## Build the real database

```bash
python scripts/smoke_apis.py                         # D1: keys + data work?
python -m pipeline.ingest_kit                        # ~10 s: spaces / tenants / residential / candidates
python -m pipeline.gates g1                          # G1 coverage, retail/restaurant and office counted separately
python -m pipeline.gates g1-classify                 # G1: is each retail/office scan commercial or an apartment? (~2 min)
python -m pipeline.gates g4 --model <model_id>       # G4 room fields
python -m pipeline.fetch_transit                     # once
# pick 5 demo spaces (3 bakery + 2 office): scan_vs_listing_area ≈ 1 means the scan is the suite itself
python -m pipeline.cache_status --set-demo id1,id2,id3,id4,id5
python -m pipeline.fetch_matterport --space-ids id1,...,id5 --scans all
python -m pipeline.fetch_vexcel --space-ids id1,...,id5
python -m pipeline.cache_status                      # D7 check
python -m pipeline.fetch_matterport --no-images      # background: rooms + poses for all candidates
python -m pipeline.fetch_matterport                  # background: 2 scans x 4 faces per candidate
python -m pipeline.fetch_vexcel                      # background
```

All fetchers are resumable (re-run after a crash). Failures are logged in `mp_fetch_log` / `vx_props.error`.
`pipeline.ingest_costar` is the generic loader for other dump formats; it hands off to `ingest_kit` when it sees the kit.

## Tables (`pipeline/tables.py`)

`spaces` · `candidates` · `tenants` · `residential` · `mp_rooms` · `mp_scans` · `mp_panos` · `mp_fetch_log` · `mp_model_info` · `vx_props` · `transit`

## Tests

`pytest tests/test_data_engine.py tests/test_fetch_matterport.py`. These cover the contracts on the sample DB, an ingest of
a fake dump with unusual column names, Matterport axis conversion and room-boundary parsing.
