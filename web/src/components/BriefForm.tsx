"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowRight, Check, CornerDownLeft, Loader2, Sparkles } from "lucide-react";
import clsx from "clsx";
import { ApiError, createRun } from "@/lib/api";
import type { BusinessType, City } from "@/types/schemas";

// The two demo briefs (README §11): bakery first, office second.
const EXAMPLES = [
  { label: "Bakery in Houston", text: "I'm opening a second bakery location in Houston. About 20 seats, under $6k/month, and it needs parking." },
  { label: "Office in downtown LA", text: "Office for a 25-person team in downtown LA, near transit, under $20k/month." },
];

const TYPES: { value: BusinessType; label: string }[] = [
  { value: "bakery", label: "Bakery" },
  { value: "office", label: "Office" },
  { value: "cafe", label: "Café" },
  { value: "retail", label: "Retail" },
];
const CITIES: City[] = ["Houston", "Los Angeles"];
const SEATS = [10, 20, 30, 40];
const DESKS = [10, 25, 50, 100];
// Budgets on the scale of the business: a $6k office in LA finds nothing.
const RENTS = [4000, 6000, 8000, 10000];
const OFFICE_RENTS = [10000, 20000, 30000, 50000];

const TYPE_WORD: Record<string, string> = { bakery: "Bakery", office: "Office", cafe: "Café", retail: "Retail space" };

/** The chips as one plain sentence, e.g. "Office in Los Angeles, about 25 desks, under $20,000/month, must have parking." */
function chipSentence(c: { type: BusinessType | null; city: City | null; seats: number | null; rent: number | null; musts: string[]; office: boolean }): string {
  const parts: string[] = [];
  const head = [c.type ? TYPE_WORD[c.type] : null, c.city ? `in ${c.city}` : null].filter(Boolean).join(" ");
  if (head) parts.push(head);
  if (c.seats) parts.push(`about ${c.seats} ${c.office ? "desks" : "seats"}`);
  if (c.rent) parts.push(`under $${c.rent.toLocaleString("en-US")}/month`);
  if (c.musts.length) parts.push(`must have ${c.musts.join(", ")}`);
  return parts.length ? `${parts.join(", ")}.` : "";
}
const MUST_HAVES = ["parking", "near transit", "existing kitchen", "natural light"];

function Chip<T>({ value, selected, onPick, children }: { value: T; selected: boolean; onPick: (v: T | null) => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={() => onPick(selected ? null : value)}
      className={clsx(
        "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-primary",
        selected
          ? "border-primary/60 bg-primary-soft font-medium text-primary"
          : "border-border bg-surface text-muted hover:border-border-strong hover:text-foreground",
      )}
    >
      {selected && <Check className="size-3.5" aria-hidden />}
      {children}
    </button>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2 sm:grid-cols-[5.5rem_1fr] sm:items-center">
      <span className="text-[11px] font-semibold tracking-[0.08em] text-muted uppercase">{label}</span>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

export function BriefForm() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [type, setType] = useState<BusinessType | null>(null);
  const [city, setCity] = useState<City | null>(null);
  const [seats, setSeats] = useState<number | null>(null);
  const [rent, setRent] = useState<number | null>(null);
  const [musts, setMusts] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const office = type === "office" || (!type && /\boffice\b/i.test(text));
  const sentence = chipSentence({ type, city, seats, rent, musts, office });
  // Chips are folded into the text, so the server parses ONE description and nothing typed is lost
  // (sending a structured brief would make the server ignore the text entirely).
  const query = [text.trim(), sentence].filter(Boolean).join(text.trim() && !/[.!?]$/.test(text.trim()) ? ". " : " ");

  async function submit(e: React.SyntheticEvent) {
    e.preventDefault();
    if (!query || busy) return;
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await createRun({ text: query });
      router.push(`/runs/${encodeURIComponent(run_id)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong starting the search.");
      setBusy(false);
    }
  }

  // Switching between office and food scales clears a budget/size that only made sense on the old scale.
  const pickType = (t: BusinessType | null) => {
    const nextOffice = t === "office";
    if (nextOffice !== (type === "office")) {
      setRent((r) => (r && (nextOffice ? OFFICE_RENTS : RENTS).includes(r) ? r : null));
      setSeats((s) => (s && (nextOffice ? DESKS : SEATS).includes(s) ? s : null));
    }
    setType(t);
  };

  const toggleMust =(m: string) => setMusts((cur) => (cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m]));

  return (
    <form onSubmit={submit} className="shadow-lift overflow-hidden rounded-2xl border border-border bg-surface text-left">
      <div className="p-4 sm:p-5">
        <label htmlFor="brief" className="flex items-center gap-2 text-sm font-medium">
          <Sparkles className="size-4 text-primary" aria-hidden /> Describe the space you need
        </label>
        <textarea
          id="brief"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit(e);
          }}
          rows={3}
          placeholder="Second bakery location in Houston, ~20 seats, under $6k/month, needs parking…"
          className="mt-2 w-full resize-none bg-transparent text-lg leading-relaxed outline-none placeholder:text-muted/70"
        />
        <div className="flex flex-wrap items-center gap-2 text-[13px]">
          <span className="text-muted">Try</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              type="button"
              onClick={() => setText(ex.text)}
              className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1 text-foreground/80 transition-colors hover:bg-surface-3 hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary"
            >
              {ex.label}
              <CornerDownLeft className="size-3 text-muted" aria-hidden />
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3 border-t border-border bg-surface-2/50 p-4 sm:p-5">
        <Row label="Business">
          {TYPES.map((t) => (
            <Chip key={t.value} value={t.value} selected={type === t.value} onPick={pickType}>
              {t.label}
            </Chip>
          ))}
        </Row>
        <Row label="City">
          {CITIES.map((c) => (
            <Chip key={c} value={c} selected={city === c} onPick={setCity}>
              {c}
            </Chip>
          ))}
        </Row>
        <Row label={office ? "Desks" : "Seats"}>
          {(office ? DESKS : SEATS).map((s) => (
            <Chip key={s} value={s} selected={seats === s} onPick={setSeats}>
              {s} {office ? "desks" : "seats"}
            </Chip>
          ))}
        </Row>
        <Row label="Max rent">
          {(office ? OFFICE_RENTS : RENTS).map((r) => (
            <Chip key={r} value={r} selected={rent === r} onPick={setRent}>
              ${r / 1000}k / mo
            </Chip>
          ))}
        </Row>
        <Row label="Must have">
          {MUST_HAVES.map((m) => (
            <Chip key={m} value={m} selected={musts.includes(m)} onPick={() => toggleMust(m)}>
              {m}
            </Chip>
          ))}
        </Row>
      </div>

      {error && (
        <p role="alert" className="mx-4 mt-4 rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad sm:mx-5">
          {error}
        </p>
      )}

      <div className="flex flex-col gap-3 border-t border-border p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <p className="min-w-0 text-sm text-pretty text-muted">
          {query ? (
            <>
              <span className="font-medium text-foreground">Searching for: </span>
              {query}
            </>
          ) : (
            "Type a brief or pick a few chips. The agent does the rest."
          )}
        </p>
        <button
          type="submit"
          disabled={!query || busy}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl bg-primary px-5 py-2.5 font-medium text-on-primary shadow-sm transition-colors hover:bg-primary-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
          {busy ? "Starting…" : "Find my space"}
        </button>
      </div>
    </form>
  );
}
