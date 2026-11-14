/**
 * Hand-made sample data shaped like `shared/schemas.py`. Everything here is FAKE:
 * placeholder addresses, rents and Matterport ids. It exists so the UI can run
 * before Abraham's server and Natnael's data are ready.
 *
 * Two business types, as in README "Business types": bakery (Houston) and office (downtown LA).
 * This file plays Natnael's (spaces, rooms, neighborhood, numbers) and Abraham's (inspection, ranking)
 * parts. Yared's parts (catalog, layout, validation, images) live in ./reimaginer.
 */
import type {
  Assumption,
  Brief,
  CandidateResult,
  Citation,
  Inspection,
  Layout,
  NeighborhoodProfile,
  Numbers,
  POI,
  Room,
  Space,
} from "../src/types/schemas";
import fs from "node:fs";
import path from "node:path";
import { GENERATED_DIR } from "./paths";
import { planLayout, renderHero, validateLayout } from "./reimaginer";

export type Kind = "bakery" | "office";

// --- Spaces --------------------------------------------------------------------

interface SpaceSeed {
  id: string;
  kind: Kind;
  address: string;
  city: "Houston" | "Los Angeles";
  lat: number;
  lon: number;
  w: number; // room width (x, m)
  d: number; // room depth (z, m)
  rent: number;
  year: number;
  kitchen: boolean;
  light: number; // natural_light 0..1
  buildOut: string;
  reasons: string[];
  score: number;
  transit: boolean;
  /** A public Matterport sample model; swap for the real model ids once Natnael's data lands. */
  model: string;
}

/** The hackathon quickstart's sample model (5836 La Mirada Ave, LA). Works with the hackathon SDK key. */
const SAMPLE_MODEL = "zvKHR9DHNjJ";

const seedSpaces: SpaceSeed[] = [
  { id: "sp_houston_001", kind: "bakery", city: "Houston", address: "2412 Rice Blvd, Houston, TX", lat: 29.7176, lon: -95.4153, w: 8, d: 12, rent: 5400, year: 1998, kitchen: true, light: 0.6, buildOut: "restaurant kitchen", score: 0.91, transit: false, model: SAMPLE_MODEL,
    reasons: ["Existing kitchen and vent hood cut fit-out cost", "Rent $5,400/mo is under the $6,000 cap", "3 office tenants and 2 apartment blocks within 400 m"] },
  { id: "sp_houston_002", kind: "bakery", city: "Houston", address: "1109 Westheimer Rd, Houston, TX", lat: 29.7433, lon: -95.3921, w: 7, d: 13, rent: 5900, year: 2004, kitchen: false, light: 0.8, buildOut: "shell", score: 0.84, transit: true, model: SAMPLE_MODEL,
    reasons: ["Storefront glass on two sides", "Strong foot traffic: 11 tenants within 400 m", "Two bakeries nearby (competition risk)"] },
  { id: "sp_houston_003", kind: "bakery", city: "Houston", address: "803 Studewood St, Houston, TX", lat: 29.7989, lon: -95.3981, w: 9, d: 11, rent: 4800, year: 1987, kitchen: false, light: 0.5, buildOut: "shell", score: 0.78, transit: false, model: SAMPLE_MODEL,
    reasons: ["Lowest rent of the shortlist", "Ample surface parking (score 0.8)", "No restroom detected: add to fit-out"] },
  { id: "sp_houston_004", kind: "bakery", city: "Houston", address: "3320 Main St, Houston, TX", lat: 29.7382, lon: -95.3794, w: 7.5, d: 12, rent: 5750, year: 2011, kitchen: true, light: 0.55, buildOut: "restaurant kitchen", score: 0.72, transit: true, model: SAMPLE_MODEL,
    reasons: ["Light-rail stop 180 m away", "Existing kitchen, but ceiling only 2.6 m", "Slightly narrow for 20 seats"] },
  { id: "sp_houston_005", kind: "bakery", city: "Houston", address: "1517 Harrisburg Blvd, Houston, TX", lat: 29.7411, lon: -95.3442, w: 8.5, d: 12.5, rent: 5100, year: 1992, kitchen: false, light: 0.4, buildOut: "shell", score: 0.66, transit: false, model: SAMPLE_MODEL,
    reasons: ["Up-and-coming district, low competition", "Few offices nearby: lunch trade is thinner", "Older building: inspect HVAC"] },
  { id: "sp_la_office_001", kind: "office", city: "Los Angeles", address: "700 S Flower St, Los Angeles, CA", lat: 34.0484, lon: -118.2593, w: 16, d: 18, rent: 14800, year: 1989, kitchen: false, light: 0.85, buildOut: "open plan", score: 0.89, transit: true, model: SAMPLE_MODEL,
    reasons: ["7th St/Metro Center station 150 m away", "Already open plan: lower fit-out", "Windows on three sides (natural light 0.85)"] },
  { id: "sp_la_office_002", kind: "office", city: "Los Angeles", address: "350 S Grand Ave, Los Angeles, CA", lat: 34.0527, lon: -118.2524, w: 15, d: 19, rent: 12900, year: 1991, kitchen: true, light: 0.6, buildOut: "private offices", score: 0.8, transit: true, model: SAMPLE_MODEL,
    reasons: ["Lowest cost per desk of the shortlist", "14 restaurants and 2 gyms within 400 m", "Private offices need demolition for open plan"] },
];

const seedOf = (id: string) => seedSpaces.find((s) => s.id === id)!;
export const seedIds = (kind: Kind) => seedSpaces.filter((s) => s.kind === kind).map((s) => s.id);
export const SEED_SCORES: Record<string, number> = Object.fromEntries(seedSpaces.map((s) => [s.id, s.score]));
export const SEED_TRANSIT: Record<string, boolean> = Object.fromEntries(seedSpaces.map((s) => [s.id, s.transit]));

const costarCite = (id: string, field: string, value: string | number): Citation => ({
  source: "costar", dataset: "commercial_listing", record_id: id, field, value, note: "sample data",
});

function buildRoom(s: SpaceSeed): Room {
  return {
    room_id: `${s.id}_main`,
    space_id: s.id,
    label: s.kind === "office" ? "Open office" : "Main room",
    room_type: s.kind === "office" ? "office" : "retail",
    floor_index: 0,
    polygon_m: [[0, 0], [s.w, 0], [s.w, s.d], [0, s.d]],
    floor_y_m: 0,
    ceiling_m: s.kind === "office" ? 2.9 : 3.2,
    area_m2: s.w * s.d,
    openings: [
      { kind: "door", a: [s.w / 2 - 0.5, s.d], b: [s.w / 2 + 0.5, s.d] },
      { kind: "window", a: [0.6, s.d], b: [s.w / 2 - 1.2, s.d] },
      { kind: "window", a: [s.w / 2 + 1.2, s.d], b: [s.w - 0.6, s.d] },
    ],
  };
}

export const MOCK_MODEL_IDS = [...new Set(seedSpaces.map((s) => s.model))];

/**
 * Real room outlines of the space's Matterport model when `npm run mock:rooms` has fetched them
 * (so furniture lines up with the real tour), else a made-up rectangle.
 */
function roomsFor(s: SpaceSeed): Room[] {
  const file = path.join(GENERATED_DIR, "rooms", `${s.model}.json`);
  if (fs.existsSync(file)) {
    try {
      const rooms = JSON.parse(fs.readFileSync(file, "utf8")) as Omit<Room, "space_id">[];
      if (rooms.length) return rooms.map((r) => ({ ...r, space_id: s.id }));
    } catch {
      /* fall through to the synthetic room */
    }
  }
  return [buildRoom(s)];
}

export const ROOMS: Record<string, Room[]> = Object.fromEntries(seedSpaces.map((s) => [s.id, roomsFor(s)]));

function buildSpace(s: SpaceSeed): Space {
  const sqft = Math.round(s.w * s.d * 10.7639);
  return {
    space_id: s.id,
    costar_property_id: `P${s.id.slice(-3)}`,
    listing_id: `L${s.id.slice(-3)}`,
    matterport_model_id: s.model,
    address: s.address,
    city: s.city,
    lat: s.lat,
    lon: s.lon,
    property_type: s.kind === "office" ? "Office" : "Retail",
    sqft,
    asking_rent_month: s.rent,
    rent_per_sqft_year: Math.round(((s.rent * 12) / sqft) * 100) / 100,
    year_built: s.year,
    has_scan: true,
    citations: [costarCite(`L${s.id.slice(-3)}`, "asking_rent", s.rent), costarCite(`L${s.id.slice(-3)}`, "sqft", sqft)],
  };
}

export const SPACES: Record<string, Space> = Object.fromEntries(seedSpaces.map((s) => [s.id, buildSpace(s)]));

// --- Neighborhood, inspection, numbers -------------------------------------------

function buildNeighborhood(s: SpaceSeed): NeighborhoodProfile {
  const cite = (src: Citation["source"], dataset: string, field: string, value: string | number): Citation => ({
    source: src, dataset, record_id: s.id, field, value, note: "sample data",
  });
  const poi = (name: string, kind: string, dx: number, dy: number, distance_m: number): POI => ({
    name, kind, lat: s.lat + dy, lon: s.lon + dx, distance_m, citation: cite("costar", "location_occupancy", "tenant_name", name),
  });
  const office = s.kind === "office";
  return {
    space_id: s.id,
    nearby_tenant_count: (office ? 30 : 6) + Math.round(s.score * 8),
    nearby_employees_est: (office ? 2400 : 140) + Math.round(s.score * 300),
    nearby_residential_units: 80 + Math.round(s.score * 160),
    // Offices: no competitors; amenities instead.
    competitors: office ? [] : [poi("Sweet Crumb Bakery", "competitor", 0.0031, 0.0012, 340), poi("Café Nube", "competitor", -0.0024, -0.0019, 310)],
    amenities: office
      ? [poi("Grand Central Market", "amenity", 0.0021, 0.0016, 290), poi("Bluebird Café", "amenity", -0.0012, 0.0009, 160), poi("Equinox Gym", "amenity", 0.0016, -0.0013, 230)]
      : [],
    transit: s.transit
      ? [{ ...poi(office ? "7th St/Metro Center" : "Light rail stop", "transit", 0.0012, -0.0011, office ? 150 : 180), citation: cite("costar", "commercial_property", "transit", "rail") }]
      : [],
    parking_score: Math.round((0.4 + s.score * 0.5) * 100) / 100,
    parking_notes: office ? "Structured parking in the building" : "Surface lot visible in aerial crop",
    footprint_wkt: null,
    parcel_wkt: null,
    aerial_ortho_path: `media/aerial/${s.id}_ortho.svg`,
    aerial_oblique_path: `media/aerial/${s.id}_oblique.svg`,
    score: s.score,
    citations: [cite("vexcel", "property/extract", "parking", "yes"), cite("costar", "location_occupancy", "tenant_count", 9)],
  };
}

function buildInspection(s: SpaceSeed): Inspection {
  return {
    space_id: s.id,
    storefront_glass: s.kind === "bakery" ? true : null,
    existing_kitchen: s.kitchen,
    existing_restroom: s.id !== "sp_houston_003",
    vent_hood: s.kind === "bakery" ? s.kitchen : null,
    ceiling_height_m: s.kind === "office" ? 2.9 : 3.2,
    natural_light: s.light,
    existing_build_out: s.buildOut,
    notes: ["Sample inspection from the mock server."],
    pano_ids: [`${s.id}_pano_1`],
    confidence: 0.7,
    unverified_fields: ["ceiling_height_m"],
    citations: [{ source: "model", dataset: "vision_inspection", record_id: s.id, field: "existing_build_out", value: s.buildOut, note: "sample data" }],
  };
}

const A = (name: string, value: number | string, unit: string | null, source: Assumption["source"], note: string | null = null): Assumption => ({ name, value, unit, source, note });
const round100 = (n: number) => Math.round(n / 100) * 100;

function bakeryNumbers(s: SpaceSeed, layout: Layout, sqft: number): Numbers {
  const perSqftLow = s.kitchen ? 28 : 45;
  const perSqftHigh = s.kitchen ? 55 : 85;
  const fitLow = round100(sqft * perSqftLow);
  const fitHigh = round100(sqft * perSqftHigh);
  const ticket = 14, turns = 4, days = 26, margin = 0.35;
  const base = layout.seat_count * turns * ticket * days;
  const revLow = round100(base * 0.8);
  const revHigh = round100(base * 1.3);
  const months = (fit: number, rev: number) => {
    const net = rev * margin - s.rent;
    return net > 0 ? Math.round((fit / net) * 10) / 10 : null;
  };
  return {
    space_id: s.id,
    rent_month: s.rent,
    fitout_cost_low: fitLow,
    fitout_cost_high: fitHigh,
    revenue_month_low: revLow,
    revenue_month_high: revHigh,
    breakeven_months_low: months(fitLow, revHigh),
    breakeven_months_high: months(fitHigh, revLow),
    cost_per_seat_month_low: null,
    cost_per_seat_month_high: null,
    assumptions: [
      A("Asking rent", s.rent, "USD/month", "costar", `Listing L${s.id.slice(-3)}`),
      A("Fit-out cost low", perSqftLow, "USD/sqft", "assumption", s.kitchen ? "Lower: existing kitchen detected" : null),
      A("Fit-out cost high", perSqftHigh, "USD/sqft", "assumption"),
      A("Table turns per day", turns, "turns", "assumption"),
      A("Average ticket", ticket, "USD", "assumption"),
      A("Open days per month", days, "days", "assumption"),
      A("Operating margin before rent", margin * 100, "%", "assumption"),
    ],
    citations: [costarCite(`L${s.id.slice(-3)}`, "asking_rent", s.rent)],
  };
}

function officeNumbers(s: SpaceSeed, layout: Layout, sqft: number): Numbers {
  const openPlan = s.buildOut === "open plan";
  const perSqftLow = openPlan ? 20 : 40;
  const perSqftHigh = openPlan ? 45 : 75;
  const fitLow = round100(sqft * perSqftLow);
  const fitHigh = round100(sqft * perSqftHigh);
  const leaseMonths = 60;
  const desks = Math.max(layout.seat_count, 1);
  const perDesk = (fit: number) => Math.round((s.rent + fit / leaseMonths) / desks);
  const nearbyRentSqftYr = 46;
  return {
    space_id: s.id,
    rent_month: s.rent,
    fitout_cost_low: fitLow,
    fitout_cost_high: fitHigh,
    revenue_month_low: 0,
    revenue_month_high: 0,
    breakeven_months_low: null,
    breakeven_months_high: null,
    cost_per_seat_month_low: perDesk(fitLow),
    cost_per_seat_month_high: perDesk(fitHigh),
    assumptions: [
      A("Asking rent", s.rent, "USD/month", "costar", `Listing L${s.id.slice(-3)}`),
      A("Fit-out cost low", perSqftLow, "USD/sqft", "assumption", openPlan ? "Lower: already open plan" : "Includes removing private offices"),
      A("Fit-out cost high", perSqftHigh, "USD/sqft", "assumption"),
      A("Lease term (fit-out spread over)", leaseMonths, "months", "assumption"),
      A("Desks", desks, "desks", "model", "From the layout"),
      A("Nearby office asking rent", nearbyRentSqftYr, "USD/sqft/yr", "costar", "Average of 6 office listings within 800 m"),
    ],
    citations: [
      costarCite(`L${s.id.slice(-3)}`, "asking_rent", s.rent),
      { source: "costar", dataset: "commercial_listing", record_id: "nearby_office_avg", field: "rent_per_sqft_year", value: nearbyRentSqftYr, note: "sample data" },
    ],
  };
}

function broker(s: SpaceSeed, seats: number): string {
  const what = s.kind === "office" ? `office space for a team of about ${seats}` : `a second bakery location (about ${seats} seats)`;
  return `Subject: Tour request for ${s.address}\n\nHello,\n\nI'm looking for ${what}, and ${s.address} looks like a strong fit at around $${s.rent.toLocaleString()}/month. Could we schedule a visit this week?\n\nThank you.`;
}

/** One fitted candidate, assembled the way Abraham's orchestrator will: data -> inspect -> layout -> validate -> hero -> numbers. */
export function buildResult(spaceId: string, rank: number, brief: Brief, runId: string | null): CandidateResult {
  const s = seedOf(spaceId);
  const rooms = ROOMS[s.id];
  const inspection = buildInspection(s);
  const layout = planLayout(s.id, rooms, inspection, brief);
  const validation = validateLayout(layout, rooms);
  const hero = renderHero(s.id, layout, brief.style);
  const sqft = SPACES[s.id].sqft ?? Math.round(s.w * s.d * 10.7639);
  return {
    run_id: runId,
    rank,
    rank_score: Math.round(s.score * 100) / 100,
    rank_reasons: s.reasons,
    status: validation.passed ? "fitted" : "failed",
    space: SPACES[s.id],
    neighborhood: buildNeighborhood(s),
    inspection,
    layout,
    validation,
    hero,
    numbers: s.kind === "office" ? officeNumbers(s, layout, sqft) : bakeryNumbers(s, layout, sqft),
    broker_email: broker(s, layout.seat_count),
  };
}

// --- Brief parsing (very rough; the real one is Abraham's parse_brief) -----------

export function mockParseBrief(text: string): Brief {
  const t = text.toLowerCase();
  const office = /\boffice\b/.test(t);
  const count =
    /(\d+)[\s-]*(?:seats?|desks?|people|person|employees|staff)/i.exec(text) ?? /team of (\d+)/i.exec(text);
  const rent = /\$\s?(\d+(?:\.\d+)?)\s*(k)?/i.exec(text);
  const food = ["bakery", "cafe", "café", "restaurant", "retail", "clinic", "gym", "salon"].find((x) => t.includes(x)) ?? "bakery";
  return {
    raw_text: text,
    business_type: office ? "office" : ((food === "café" ? "cafe" : food) as Brief["business_type"]),
    city: /los angeles|\bla\b/i.test(text) ? "Los Angeles" : "Houston",
    area_hint: /transit/i.test(text) ? "close to transit" : /downtown/i.test(text) ? "downtown" : null,
    seats_wanted: count ? Number(count[1]) : office ? 25 : 20,
    sqft_min: null,
    sqft_max: null,
    max_rent_month: rent ? Number(rent[1]) * (rent[2] ? 1000 : 1) : null,
    must_haves: /parking/i.test(text) ? ["parking"] : [],
    nice_to_haves: [],
    style: office ? "bright, modern, plants and light wood" : "warm artisan, wood and white tile",
    feedback_history: [],
  };
}
