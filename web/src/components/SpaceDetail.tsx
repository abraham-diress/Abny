"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Mail, ShieldAlert, ShieldCheck } from "lucide-react";
import { getRooms } from "@/lib/api";
import { assetUrl } from "@/lib/config";
import { isOffice, seatWord } from "@/lib/business";
import { pct } from "@/lib/format";
import type { CandidateResult, Inspection, Room } from "@/types/schemas";
import { BeforeAfter, parsePanoId } from "@/components/BeforeAfter";
import { NumbersCard } from "@/components/NumbersCard";
import { SpaceTour, type TourApi } from "@/components/SpaceTour";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">{title}</h3>
      {children}
    </section>
  );
}

/**
 * Yared's render_hero returns its placement guide instead of a generated image when image
 * generation is off or fails, and says so in HeroImage.model: "preview-guide (image generation unavailable: …)".
 */
const isPreviewHero = (model: string) => /^preview/i.test(model);
const previewReason = (model: string) => /\((?:image generation unavailable: )?(.*)\)\s*$/.exec(model)?.[1] ?? null;

const yesNo =(v: boolean | null) => (v == null ? "unknown" : v ? "yes" : "no");

/** The inspector's checklist. Offices care about daylight, build-out and restrooms; bakeries about kitchen and storefront. */
function InspectionFacts({ inspection: i, office }: { inspection: Inspection; office: boolean }) {
  const rows: [string, string, string][] = office
    ? [
        ["Natural light", i.natural_light == null ? "unknown" : pct(i.natural_light), "natural_light"],
        ["Existing build-out", i.existing_build_out ?? "unknown", "existing_build_out"],
        ["Restroom", yesNo(i.existing_restroom), "existing_restroom"],
        ["Ceiling", i.ceiling_height_m == null ? "unknown" : `${i.ceiling_height_m.toFixed(1)} m`, "ceiling_height_m"],
      ]
    : [
        ["Storefront glass", yesNo(i.storefront_glass), "storefront_glass"],
        ["Existing kitchen", yesNo(i.existing_kitchen), "existing_kitchen"],
        ["Vent hood", yesNo(i.vent_hood), "vent_hood"],
        ["Restroom", yesNo(i.existing_restroom), "existing_restroom"],
        ["Ceiling", i.ceiling_height_m == null ? "unknown" : `${i.ceiling_height_m.toFixed(1)} m`, "ceiling_height_m"],
      ];
  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
      {rows.map(([label, value, field]) => (
        <div key={field}>
          <dt className="text-xs text-muted">{label}</dt>
          <dd className="font-medium">
            {value}
            {i.unverified_fields.includes(field) && <span className="ml-1 text-xs font-normal text-warn">(unverified)</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function BrokerEmail({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text is still selectable */
    }
  }
  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm hover:border-muted focus-visible:outline-2 focus-visible:outline-accent"
      >
        <Mail className="size-4" /> {open ? "Hide broker email" : "Email broker"}
      </button>
      {open && (
        <div className="space-y-2 rounded-xl border border-border bg-surface p-3">
          <pre className="font-sans text-sm whitespace-pre-wrap text-pretty">{text}</pre>
          <button type="button" onClick={copy} className="inline-flex items-center gap-1.5 text-sm text-accent hover:underline">
            {copied ? <Check className="size-4" /> : <Copy className="size-4" />} {copied ? "Copied" : "Copy draft"}
          </button>
        </div>
      )}
    </div>
  );
}

export function SpaceDetail({ result }: { result: CandidateResult }) {
  const { space, layout, validation, hero } = result;
  const [rooms, setRooms] = useState<Room[] | undefined>();
  const [tour, setTour] = useState<TourApi | null>(null);
  // The photo's viewpoint: scan ids are the tour's sweep ids.
  const photoSweep = hero && !isPreviewHero(hero.model) ? (parsePanoId(hero.source_pano_id)?.scan ?? null) : null;
  const showInTour = tour && photoSweep && layout
    ? () => {
        tour.reveal();
        const cx = layout.items.reduce((s, it) => s + it.x_m, 0) / Math.max(1, layout.items.length);
        const cz = layout.items.reduce((s, it) => s + it.z_m, 0) / Math.max(1, layout.items.length);
        void tour.standAt(photoSweep, [cx, cz]);
      }
    : undefined;

  useEffect(() => {
    let cancelled = false;
    // (This component is keyed by space_id, so `rooms` starts empty for every space.)
    // Falls back to a plan drawn from the layout alone if the server doesn't expose rooms yet.
    getRooms(space.space_id)
      .then((r) => !cancelled && setRooms(r))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [space.space_id]);

  return (
    <article className="space-y-6">
      <header className="space-y-1">
        <p className="text-sm text-muted">Rank #{result.rank}</p>
        <h2 className="text-2xl font-semibold tracking-tight text-balance">{space.address}</h2>
        <p className="text-sm text-muted">
          {space.property_type ?? "Space"}
          {space.sqft ? ` · ${space.sqft.toLocaleString()} sqft` : ""}
          {space.year_built ? ` · built ${space.year_built}` : ""}
        </p>
      </header>

      <Section title="Walk through it">
        <SpaceTour space={space} layout={layout} rooms={rooms} photoSweep={photoSweep} onReady={setTour} />
      </Section>

      {hero && isPreviewHero(hero.model) ? (
        <Section title="Placement preview">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,14rem)_1fr]">
            {/* eslint-disable-next-line @next/next/no-img-element -- images come from the API server, not optimized by Next */}
            <img src={assetUrl(hero.path)} alt={`Where each item goes in ${space.address}`} className="aspect-video w-full rounded-lg border border-border object-cover" />
            <p className="text-xs text-muted text-pretty">
              Where each item goes, drawn on the room photo. The photoreal &ldquo;this is your business&rdquo; image wasn&apos;t generated
              {previewReason(hero.model) ? `: ${previewReason(hero.model)}` : " (image generation is off)"}.
            </p>
          </div>
        </Section>
      ) : hero && (
        <Section title="Your business in this space">
          <BeforeAfter
            hero={hero}
            alt={`Rendering of the ${result.layout?.business_type ?? "business"} inside ${space.address}`}
            onShowInTour={showInTour}
          />
        </Section>
      )}

      <Section title="Why it ranked here">
        <ul className="list-disc space-y-1 pl-5 text-sm marker:text-accent">
          {result.rank_reasons.map((r, i) => (
            <li key={i} className="text-pretty">{r}</li>
          ))}
        </ul>
      </Section>

      {result.inspection && (
        <Section title="What the inspector saw">
          <InspectionFacts inspection={result.inspection} office={isOffice(result)} />
        </Section>
      )}

      <Section title="Numbers">
        <NumbersCard result={result} />
      </Section>

      {layout && (
        <Section title="Layout check">
          {validation && (
            <p className="flex items-center gap-1.5 text-sm">
              {validation.passed ? <ShieldCheck className="size-4 text-good" /> : <ShieldAlert className="size-4 text-bad" />}
              {validation.passed ? "Layout valid" : "Layout has problems"} · {validation.seat_count} {seatWord(isOffice(result), validation.seat_count)}
              {validation.min_aisle_m != null && ` · min aisle ${validation.min_aisle_m.toFixed(2)} m`}
            </p>
          )}
          {validation && validation.violations.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-bad">
              {validation.violations.map((v, i) => (
                <li key={i}>{v.message}</li>
              ))}
            </ul>
          )}
        </Section>
      )}

      {result.broker_email && (
        <Section title="Next step">
          <BrokerEmail text={result.broker_email} />
        </Section>
      )}
    </article>
  );
}
