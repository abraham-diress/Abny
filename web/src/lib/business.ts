import type { BusinessType, CandidateResult } from "@/types/schemas";

/** README "Business types": bakery is the main demo, office the second. Café/retail follow the bakery path. */
export const isOfficeType = (t: BusinessType | null | undefined) => t === "office";

/**
 * Is this result an office? Decided from what the data says about the space, not only the layout:
 * the planner may fall back to another template (e.g. "No template for 'office' yet; used the bakery
 * template"), but the analyst only fills cost per desk for offices, and the listing says "Office".
 */
export function isOffice(r: CandidateResult): boolean {
  if (r.numbers?.cost_per_seat_month_low != null || r.numbers?.cost_per_seat_month_high != null) return true;
  if (r.layout && isOfficeType(r.layout.business_type)) return true;
  return /\boffice\b/i.test(r.space.property_type ?? "");
}

/** "seat"/"seats" for food businesses, "desk"/"desks" for offices. */
export const seatWord = (office: boolean, n?: number) => (office ? "desk" : "seat") + (n === 1 ? "" : "s");
