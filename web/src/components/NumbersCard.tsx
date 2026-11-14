import { isOffice } from "@/lib/business";
import { monthsRange, usd, usdRange } from "@/lib/format";
import type { CandidateResult } from "@/types/schemas";
import { Sourced, assumptionLine, citationLine, uniqueLines, unitSuffix, type SourceLine } from "@/components/SourceTip";

/**
 * Which assumptions back which number. Matches the analyst's names (agent/analyst/costs.py:
 * fitout_psf_low, equipment_from_layout, furniture_from_layout, avg_ticket, cogs_pct, ...)
 * and the mock's ("Fit-out cost low", "Average ticket", ...).
 */
const FITOUT = /fit.?out|equipment|furniture|contingency|soft.?cost|it.?per.?desk/i;
const REVENUE = /ticket|turn|transaction|open.?days|revenue/i;
const BREAKEVEN = /break.?even|profit|cogs|labor|opex|nnn|cam|margin/i;
const PER_DESK = /desk|occupancy|lease|opex|fit.?out|furniture|it.?per/i;
const NEARBY_OFFICE = /nearby.?office/i;

/** Rent, fit-out and the business-type headline. Every row shows its sources on hover/focus. */
export function NumbersCard({ result }: { result: CandidateResult }) {
  const n = result.numbers;
  if (!n) return <p className="text-sm text-muted">Numbers are not ready yet.</p>;

  const office = isOffice(result);
  const pick = (re: RegExp): SourceLine[] => n.assumptions.filter((a) => re.test(a.name)).map(assumptionLine);
  const rentSources = uniqueLines([...result.space.citations.filter((c) => /rent/i.test(c.field ?? "")), ...n.citations].map(citationLine));
  const unverified = result.inspection?.unverified_fields ?? [];
  const nearby = n.assumptions.find((a) => NEARBY_OFFICE.test(a.name));
  // e.g. "low-revenue case does not break even"
  const breakevenNote = n.assumptions.find((a) => /break.?even.?note/i.test(a.name))?.value;

  return (
    <div>
      <dl className="divide-y divide-border">
        <Sourced label="Rent" lines={rentSources}>
          {usd(n.rent_month)}/mo
        </Sourced>
        <Sourced label="Fit-out cost" lines={pick(FITOUT)}>
          {usdRange(n.fitout_cost_low, n.fitout_cost_high)}
        </Sourced>
        {office ? (
          <>
            <Sourced label="Cost per desk" lines={pick(PER_DESK)}>
              {usdRange(n.cost_per_seat_month_low, n.cost_per_seat_month_high)}/mo
            </Sourced>
            {nearby && (
              <Sourced label="Nearby office rent" lines={[assumptionLine(nearby), ...n.citations.filter((c) => /rent_per_sqft/i.test(c.field ?? "")).map(citationLine)]}>
                {typeof nearby.value === "number" ? usd(nearby.value) : nearby.value}
                {unitSuffix(nearby.unit)}
              </Sourced>
            )}
          </>
        ) : (
          <>
            <Sourced label="Revenue" lines={pick(REVENUE)}>
              {usdRange(n.revenue_month_low, n.revenue_month_high)}/mo
            </Sourced>
            <Sourced label="Break-even" lines={pick(BREAKEVEN).length ? pick(BREAKEVEN) : n.assumptions.map(assumptionLine)}>
              {monthsRange(n.breakeven_months_low, n.breakeven_months_high)}
            </Sourced>
          </>
        )}
      </dl>
      {!office && typeof breakevenNote === "string" && <p className="mt-2 text-xs text-muted">Note: {breakevenNote}.</p>}
      {unverified.length > 0 && <p className="mt-3 text-xs text-muted">Unverified inspection fields: {unverified.join(", ")}</p>}
    </div>
  );
}
