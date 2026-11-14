"""Hestia conventions: agreed constants only. Everyone uses these names and values.

Units
-----
* Lengths in METERS, areas in m^2. sqft only for display (1 m^2 = 10.7639 sqft).
* Money in USD; rent is USD per month unless a field name says otherwise.

Coordinates
-----------
* Matterport model coordinates, y is up. Floor plans use (x, z) in meters.
* LayoutItem.rotation_deg is about +y; 0 means the item's front faces +z.

Files
-----
* Schemas store URL paths relative to the API server root:
    media/...  -> files under data/media/ (downloaded/generated, gitignored)
    assets/... -> files under assets/     (committed: catalog.json, glb/)
* The frontend loads `${API_BASE}/${path}`.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- folders -----------------------------------------------------------------
DATA_DIR = REPO_ROOT / "data"  # gitignored: sponsor data never goes in git
DB_PATH = DATA_DIR / "hestia.duckdb"
RUNS_DIR = DATA_DIR / "runs"  # recorded runs for DEMO=1
MEDIA_DIR = DATA_DIR / "media"
PANOS_DIR = MEDIA_DIR / "panos"  # panos/<matterport_model_id>/<scan_id>_<face>.jpg
AERIAL_DIR = MEDIA_DIR / "aerial"  # aerial/<space_id>_ortho.jpg, aerial/<space_id>_oblique.jpg
GUIDES_DIR = MEDIA_DIR / "guides"  # guides/<layout_id>.png
HEROES_DIR = MEDIA_DIR / "heroes"  # heroes/<hero_id>.png
ASSETS_DIR = REPO_ROOT / "assets"
CATALOG_PATH = ASSETS_DIR / "catalog.json"  # JSON list of CatalogItem
GLB_DIR = ASSETS_DIR / "glb"

# --- agent virtual filesystem (deepagents) -----------------------------------
AGENT_BRIEF = "/brief.md"
AGENT_PLAN = "/plan.md"
AGENT_SHORTLIST = "/candidates/shortlist.md"
AGENT_CANDIDATE_DIR = "/candidates/{space_id}/"  # inspection.md, layout.json, hero.json, numbers.md
AGENT_MEMO = "/results/{space_id}/memo.md"

# --- layout rules (Reimaginer's validator uses these) ------------------------
MIN_AISLE_M = 0.914  # 36 in accessible route
WHEELCHAIR_TURN_DIAMETER_M = 1.524  # 60 in
DOOR_CLEARANCE_M = 1.2  # keep clear in front of the entrance

# --- funnel sizes (Brain) ----------------------------------------------------
FUNNEL_FILTER_LIMIT = 200
FUNNEL_INSPECT_TOP = 20
FUNNEL_FIT_TOP = 5
