import { Check, Info, Loader2, ShieldCheck } from "lucide-react";
import clsx from "clsx";

/**
 * A static picture of the run screen for the landing page. Sample values only; it is labeled
 * "Sample" so nobody mistakes it for a live result.
 */

const FUNNEL = [
  { label: "Listings", n: 612 },
  { label: "Filtered", n: 41 },
  { label: "Ranked", n: 12 },
  { label: "Inspected", n: 6 },
  { label: "Fitted out", n: 5 },
];

const PLAN = [
  { label: "Read the brief", done: true },
  { label: "Filter vacant listings", done: true },
  { label: "Inspect top spaces in 3D", done: true },
  { label: "Fit out & price", done: false },
];

const RESULTS = [
  { rank: 1, name: "Montrose storefront", meta: "$5,400/mo · 1,840 sqft · 22 seats", score: 91 },
  { rank: 2, name: "Heights corner retail", meta: "$5,950/mo · 2,100 sqft · 26 seats", score: 84 },
  { rank: 3, name: "Midtown end-cap", meta: "$4,800/mo · 1,520 sqft · 18 seats", score: 77 },
];

const NUMBERS: { label: string; value: string; src: "costar" | "model" | "assumption" }[] = [
  { label: "Rent", value: "$5,400/mo", src: "costar" },
  { label: "Fit-out", value: "$62k – $88k", src: "assumption" },
  { label: "Revenue", value: "$31k – $44k/mo", src: "model" },
  { label: "Break-even", value: "14 – 22 mo", src: "model" },
];

const SRC_STYLE = {
  costar: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  model: "bg-primary/15 text-primary",
  assumption: "bg-tertiary/20 text-amber-700 dark:text-tertiary",
};

function MiniPlan() {
  // A simple bakery fit-out in plan view: seating (tertiary), service (primary), back of house (stone).
  return (
    <svg viewBox="0 0 320 190" className="mx-auto h-auto max-h-56 w-full" role="img" aria-label="Sample floor plan of a fitted-out bakery">
      <rect x="6" y="6" width="308" height="178" rx="6" fill="var(--surface)" stroke="var(--foreground)" strokeOpacity="0.7" strokeWidth="2.5" />
      {/* back of house */}
      <rect x="214" y="12" width="94" height="72" rx="4" fill="var(--muted)" fillOpacity="0.35" />
      <text x="261" y="52" textAnchor="middle" fontSize="10" fill="var(--foreground)" opacity="0.7">kitchen</text>
      {/* counter + display */}
      <rect x="150" y="96" width="140" height="16" rx="3" fill="var(--primary)" />
      <rect x="150" y="116" width="54" height="12" rx="3" fill="var(--primary)" fillOpacity="0.7" />
      <text x="220" y="108" textAnchor="middle" fontSize="9" fill="#fff">service counter</text>
      {/* tables */}
      {[0, 1, 2].map((r) =>
        [0, 1].map((c) => (
          <g key={`${r}-${c}`} transform={`translate(${36 + c * 56} ${30 + r * 46})`}>
            <rect x="-11" y="-11" width="22" height="22" rx="4" fill="var(--tertiary)" />
            <circle cx="-17" cy="0" r="4" fill="var(--tertiary)" fillOpacity="0.55" />
            <circle cx="17" cy="0" r="4" fill="var(--tertiary)" fillOpacity="0.55" />
          </g>
        )),
      )}
      <rect x="150" y="30" width="48" height="14" rx="3" fill="var(--tertiary)" fillOpacity="0.85" />
      <rect x="150" y="56" width="48" height="14" rx="3" fill="var(--tertiary)" fillOpacity="0.85" />
      {/* entrance */}
      <line x1="56" y1="184" x2="104" y2="184" stroke="var(--secondary)" strokeWidth="5" strokeLinecap="round" />
      <text x="80" y="176" textAnchor="middle" fontSize="9" fill="var(--secondary)">entrance</text>
      {/* windows */}
      <line x1="130" y1="184" x2="200" y2="184" stroke="var(--secondary)" strokeOpacity="0.45" strokeWidth="4" />
      <line x1="6" y1="40" x2="6" y2="130" stroke="var(--secondary)" strokeOpacity="0.45" strokeWidth="4" />
    </svg>
  );
}

export function ProductPreview() {
  return (
    <div className="shadow-lift overflow-hidden rounded-2xl border border-border bg-surface">
      {/* window chrome */}
      <div className="flex items-center gap-3 border-b border-border bg-surface-2 px-4 py-2.5">
        <div className="flex gap-1.5" aria-hidden>
          <span className="size-2.5 rounded-full bg-border-strong" />
          <span className="size-2.5 rounded-full bg-border-strong" />
          <span className="size-2.5 rounded-full bg-border-strong" />
        </div>
        <div className="mx-auto flex min-w-0 items-center gap-2 rounded-md border border-border bg-surface px-3 py-1 text-xs text-muted">
          <span className="truncate">Bakery · Houston · ~20 seats · ≤ $6,000/mo · needs parking</span>
        </div>
        <span className="hidden rounded-full bg-tertiary-soft px-2 py-0.5 text-[10px] font-semibold tracking-wide text-amber-700 uppercase sm:inline dark:text-tertiary">
          Sample
        </span>
      </div>

      <div className="grid gap-px bg-border text-left lg:grid-cols-[13rem_minmax(0,1fr)_17rem]">
        {/* agent column */}
        <div className="hidden space-y-5 bg-surface p-4 lg:block">
          <div className="space-y-2">
            <p className="text-[10px] font-semibold tracking-[0.1em] text-muted uppercase">Funnel</p>
            {FUNNEL.map((f) => (
              <div key={f.label} className="grid grid-cols-[4.5rem_1fr_2rem] items-center gap-2 text-[11px]">
                <span className="text-muted">{f.label}</span>
                <span className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                  <span className="block h-full rounded-full bg-primary" style={{ width: `${Math.max(6, Math.sqrt(f.n / 612) * 100)}%` }} />
                </span>
                <span className="text-right font-mono tabular-nums">{f.n}</span>
              </div>
            ))}
          </div>
          <div className="space-y-2">
            <p className="text-[10px] font-semibold tracking-[0.1em] text-muted uppercase">Plan</p>
            {PLAN.map((p) => (
              <p key={p.label} className="flex items-center gap-2 text-[11px]">
                {p.done ? <Check className="size-3.5 text-good" /> : <Loader2 className="size-3.5 animate-spin text-primary" />}
                <span className={clsx(p.done ? "text-muted line-through decoration-muted/40" : "font-medium")}>{p.label}</span>
              </p>
            ))}
          </div>
        </div>

        {/* selected space */}
        <div className="space-y-3 bg-surface p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[11px] text-muted">Rank #1 · Retail · 1,840 sqft</p>
              <p className="font-semibold tracking-tight">Montrose storefront</p>
            </div>
            <span className="inline-flex items-center gap-1 rounded-full bg-secondary-soft px-2 py-0.5 text-[11px] font-medium text-secondary">
              <ShieldCheck className="size-3.5" /> Layout passes
            </span>
          </div>
          <div className="rounded-xl bg-surface-2 p-2">
            <MiniPlan />
          </div>
          <div className="flex flex-wrap gap-1.5 text-[11px]">
            {["22 seats", "min aisle 1.1 m", "storefront glass", "existing restroom"].map((t) => (
              <span key={t} className="rounded-full border border-border px-2 py-0.5 text-muted">
                {t}
              </span>
            ))}
          </div>
        </div>

        {/* results + numbers */}
        <div className="space-y-4 bg-surface p-4">
          <ol className="space-y-1.5">
            {RESULTS.map((r) => (
              <li
                key={r.rank}
                className={clsx("flex items-center gap-2.5 rounded-lg border p-2", r.rank === 1 ? "border-primary/50 bg-primary-soft" : "border-border")}
              >
                <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary text-[11px] font-semibold text-on-primary">{r.rank}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium">{r.name}</span>
                  <span className="block truncate text-[10px] text-muted">{r.meta}</span>
                </span>
                <span className="font-mono text-[11px] text-muted tabular-nums">{r.score}</span>
              </li>
            ))}
          </ol>
          <dl className="divide-y divide-border rounded-lg border border-border px-3">
            {NUMBERS.map((n) => (
              <div key={n.label} className="flex items-center justify-between gap-2 py-1.5 text-xs">
                <dt className="text-muted">{n.label}</dt>
                <dd className="flex items-center gap-1.5 font-medium whitespace-nowrap tabular-nums">
                  {n.value}
                  <span className={clsx("rounded px-1 py-px text-[9px] font-semibold uppercase", SRC_STYLE[n.src])}>{n.src}</span>
                  <Info className="size-3 text-muted" aria-hidden />
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </div>
  );
}
