const SQFT_PER_M2 = 10.7639;

export const m2ToSqft = (m2: number) => Math.round(m2 * SQFT_PER_M2);

export const usd = (n: number | null | undefined) =>
  n == null ? "n/a" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const usdRange = (low: number | null | undefined, high: number | null | undefined) =>
  low == null || high == null ? "n/a" : `${usd(low)} – ${usd(high)}`;

export const monthsRange = (low: number | null | undefined, high: number | null | undefined) => {
  if (low == null && high == null) return "Not reached";
  if (low == null) return `> ${high} months`;
  if (high == null) return `${low}+ months`;
  return `${low} – ${high} months`;
};

export const pct = (n: number) => `${Math.round(n * 100)}%`;
