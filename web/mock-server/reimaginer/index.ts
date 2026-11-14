/**
 * Mock of Yared's side of the contract (README §5.2, "Yared: The Reimaginer").
 *
 * | Contract (Python, shared/contracts.py)        | Mock (here)        | Writes                          |
 * |-----------------------------------------------|--------------------|---------------------------------|
 * | assets/catalog.json + assets/glb/*.glb        | writeMockAssets    | .generated/assets/...           |
 * | plan_layout(space_id, rooms, inspection, brief, strategy) | planLayout |                           |
 * | validate_layout(layout, rooms)                | validateLayout     |                                 |
 * | render_guide(layout, pano)                    | renderGuide        | .generated/media/guides/*.png   |
 * | render_hero(space_id, layout, style)          | renderHero         | .generated/media/heroes/*.png   |
 * | score_image(original, generated, layout, guide) | scoreImage       |                                 |
 *
 * Same inputs and outputs (shared/schemas.py), same URL paths (assets/..., media/...).
 * When Yared's real files exist (<repo>/assets, <repo>/data/media), the mock server serves those first.
 */
export { MOCK_CATALOG, loadCatalog, writeMockAssets, type CatalogSource } from "./catalog";
export { planLayout } from "./planner";
export { validateLayout, MIN_AISLE_M, DOOR_CLEARANCE_M } from "./validator";
export { renderGuide, renderHero, scoreImage } from "./staging";
