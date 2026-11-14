/**
 * TypeScript mirror of `shared/schemas.py` (SCHEMA_VERSION 1.0.0).
 *
 * The Python file is the source of truth. If you change a model there, change it here
 * in the same PR. Field names are snake_case on purpose: they match the JSON on the wire.
 * Datetimes arrive as ISO-8601 strings.
 */

export const SCHEMA_VERSION = "1.0.0";

// --- Enums / aliases ---------------------------------------------------------

export type BusinessType =
  | "bakery"
  | "cafe"
  | "restaurant"
  | "retail"
  | "clinic"
  | "gym"
  | "salon"
  | "office"
  | "other";
export type City = "Houston" | "Los Angeles";
export type Source = "costar" | "matterport" | "vexcel" | "model" | "assumption" | "user";
export type Zone = "entrance" | "front_of_house" | "seating" | "service" | "back_of_house";
export type CubeFace = "front" | "back" | "left" | "right" | "up" | "down" | "equirect";
export type CandidateStatus = "screened" | "inspected" | "fitted" | "rejected" | "failed";
export type TodoStatus = "pending" | "in_progress" | "completed";
export type RunState = "queued" | "running" | "done" | "error";
export type FeedbackKind = "reject" | "prefer" | "constraint" | "other";
export type ViolationKind =
  | "out_of_bounds"
  | "overlap"
  | "aisle_too_narrow"
  | "entrance_blocked"
  | "unreachable"
  | "seat_shortfall"
  | "other";
export type EventType =
  | "run_started"
  | "plan_update"
  | "subagent_started"
  | "subagent_finished"
  | "tool_call"
  | "tool_result"
  | "file_written"
  | "funnel_update"
  | "candidate_ready"
  | "feedback_received"
  | "run_finished"
  | "error"
  | "log";

/** (x, z) in meters, Matterport model coordinates. */
export type XZ = [number, number];
/** (x, y, z) in meters, y is up. */
export type XYZ = [number, number, number];

// --- Provenance --------------------------------------------------------------

export interface Citation {
  source: Source;
  dataset: string | null;
  record_id: string | null;
  field: string | null;
  value: string | number | boolean | null;
  note: string | null;
}

// --- The user's request ------------------------------------------------------

export interface Feedback {
  text: string;
  kind: FeedbackKind;
  space_id: string | null;
  created_at: string;
}

export interface Brief {
  raw_text: string;
  business_type: BusinessType;
  city: City | null;
  area_hint: string | null;
  /** Customer seats for food businesses; desks (= headcount) for offices. */
  seats_wanted: number | null;
  sqft_min: number | null;
  sqft_max: number | null;
  max_rent_month: number | null;
  must_haves: string[];
  nice_to_haves: string[];
  style: string | null;
  feedback_history: Feedback[];
}

// --- Data layer --------------------------------------------------------------

export interface Space {
  space_id: string;
  costar_property_id: string | null;
  listing_id: string | null;
  matterport_model_id: string | null;
  address: string;
  city: City | null;
  lat: number;
  lon: number;
  property_type: string | null;
  sqft: number | null;
  asking_rent_month: number | null;
  rent_per_sqft_year: number | null;
  year_built: number | null;
  has_scan: boolean;
  citations: Citation[];
}

export interface Opening {
  kind: "door" | "window" | "opening" | "unknown";
  a: XZ;
  b: XZ;
}

export interface Room {
  room_id: string;
  space_id: string;
  label: string | null;
  room_type: string | null;
  floor_index: number;
  polygon_m: XZ[];
  floor_y_m: number;
  ceiling_m: number | null;
  area_m2: number;
  openings: Opening[];
}

export interface PanoRef {
  pano_id: string;
  space_id: string;
  scan_id: string;
  room_id: string | null;
  face: CubeFace;
  /** URL path relative to the API root, e.g. `media/panos/<model>/<scan>_front.jpg` */
  path: string;
  defurnished: boolean;
  position_m: XYZ;
  rotation_quat: [number, number, number, number] | null;
  fov_deg: number;
  width_px: number;
  height_px: number;
}

export interface POI {
  name: string;
  /** competitor | transit | parking | anchor | residential | amenity (food/gym near an office) | other */
  kind: string;
  lat: number;
  lon: number;
  distance_m: number;
  citation: Citation | null;
}

export interface NeighborhoodProfile {
  space_id: string;
  nearby_tenant_count: number;
  nearby_employees_est: number | null;
  nearby_residential_units: number;
  /** Same-business tenants nearby; empty for offices. */
  competitors: POI[];
  /** Food, cafés, gyms within walking distance (offices). */
  amenities: POI[];
  transit: POI[];
  parking_score: number | null;
  parking_notes: string | null;
  footprint_wkt: string | null;
  parcel_wkt: string | null;
  aerial_ortho_path: string | null;
  aerial_oblique_path: string | null;
  score: number;
  citations: Citation[];
}

// --- Inspection --------------------------------------------------------------

export interface Inspection {
  space_id: string;
  storefront_glass: boolean | null;
  existing_kitchen: boolean | null;
  existing_restroom: boolean | null;
  vent_hood: boolean | null;
  ceiling_height_m: number | null;
  /** 0 = no daylight, 1 = windows on most walls (key for offices). */
  natural_light: number | null;
  /** What is already built: 'open plan', 'private offices', 'restaurant kitchen', 'shell'... */
  existing_build_out: string | null;
  notes: string[];
  pano_ids: string[];
  confidence: number;
  unverified_fields: string[];
  citations: Citation[];
}

// --- Layout + visuals --------------------------------------------------------

export interface CatalogItem {
  item_type: string;
  label: string;
  /** URL path, e.g. `assets/glb/display_case.glb` */
  glb_asset: string;
  width_m: number;
  depth_m: number;
  height_m: number;
  clearance_front_m: number;
  seats: number;
  zone: Zone;
  business_types: BusinessType[];
}

export interface LayoutItem {
  item_id: string;
  item_type: string;
  glb_asset: string;
  room_id: string;
  x_m: number;
  z_m: number;
  /** About +y; 0 means the item's front faces +z. */
  rotation_deg: number;
  width_m: number;
  depth_m: number;
  height_m: number;
  zone: Zone | null;
  seats: number;
}

export interface Layout {
  layout_id: string;
  space_id: string;
  business_type: BusinessType;
  entrance_xz: XZ | null;
  items: LayoutItem[];
  seat_count: number;
  strategy: string | null;
  notes: string[];
}

export interface Violation {
  kind: ViolationKind;
  item_ids: string[];
  message: string;
}

export interface ValidationReport {
  layout_id: string;
  passed: boolean;
  violations: Violation[];
  min_aisle_m: number | null;
  seat_count: number;
}

export interface ImageScore {
  structure_preserved: number;
  plan_adherence: number;
  realism_1to5: number;
  passed: boolean;
  notes: string[];
}

export interface HeroImage {
  hero_id: string;
  space_id: string;
  layout_id: string;
  path: string;
  source_pano_id: string;
  guide_path: string | null;
  model: string;
  prompt: string;
  attempt: number;
  score: ImageScore | null;
}

// --- Numbers -----------------------------------------------------------------

export interface Assumption {
  name: string;
  value: number | string;
  unit: string | null;
  source: Source;
  note: string | null;
}

export interface Numbers {
  space_id: string;
  rent_month: number | null;
  fitout_cost_low: number;
  fitout_cost_high: number;
  /** 0 for offices (they don't sell to walk-in customers). */
  revenue_month_low: number;
  revenue_month_high: number;
  /** None for offices. */
  breakeven_months_low: number | null;
  breakeven_months_high: number | null;
  /** (rent + fit-out spread over the lease) / seats or desks. The headline number for offices. */
  cost_per_seat_month_low: number | null;
  cost_per_seat_month_high: number | null;
  assumptions: Assumption[];
  citations: Citation[];
}

// --- Results + run state -----------------------------------------------------

export interface CandidateResult {
  run_id: string | null;
  rank: number;
  rank_score: number;
  rank_reasons: string[];
  status: CandidateStatus;
  space: Space;
  neighborhood: NeighborhoodProfile | null;
  inspection: Inspection | null;
  layout: Layout | null;
  validation: ValidationReport | null;
  hero: HeroImage | null;
  numbers: Numbers | null;
  broker_email: string | null;
}

export interface FunnelStats {
  total: number;
  filtered: number;
  ranked: number;
  inspected: number;
  fitted: number;
}

export interface TodoItem {
  content: string;
  status: TodoStatus;
}

/** Payload shapes per event type (README §5.4). */
export interface EventPayloads {
  run_started: { brief: Brief };
  plan_update: { todos: TodoItem[] };
  subagent_started: { task?: string };
  subagent_finished: { summary?: string };
  tool_call: { tool: string; args?: Record<string, unknown> };
  tool_result: { tool: string; summary?: string; ok: boolean };
  file_written: { path: string };
  funnel_update: { funnel: FunnelStats };
  candidate_ready: { result: CandidateResult };
  /** The server sends the Feedback object; older/mock servers send just its text. */
  feedback_received: { feedback: Feedback | string; round: number };
  run_finished: { result_count: number; round: number };
  error: { detail: string };
  log: Record<string, never>;
}

export interface AgentEvent<T extends EventType = EventType> {
  run_id: string;
  seq: number;
  type: T;
  ts: string;
  /** 'orchestrator' or a subagent name */
  agent: string | null;
  message: string | null;
  payload: T extends keyof EventPayloads ? EventPayloads[T] : Record<string, unknown>;
}

export const EVENT_TYPES: EventType[] = [
  "run_started",
  "plan_update",
  "subagent_started",
  "subagent_finished",
  "tool_call",
  "tool_result",
  "file_written",
  "funnel_update",
  "candidate_ready",
  "feedback_received",
  "run_finished",
  "error",
  "log",
];

// --- HTTP API bodies ---------------------------------------------------------

export interface CreateRunRequest {
  text: string;
  brief?: Brief | null;
}

export interface CreateRunResponse {
  run_id: string;
}

export interface FeedbackRequest {
  text: string;
  kind?: FeedbackKind;
  space_id?: string | null;
}

export interface RunStatus {
  run_id: string;
  state: RunState;
  brief: Brief | null;
  funnel: FunnelStats;
  result_count: number;
  round: number;
  error: string | null;
}
