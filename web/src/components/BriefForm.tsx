"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, Send } from "lucide-react";
import clsx from "clsx";
import { ApiError, createRun } from "@/lib/api";
import type { BusinessType, City } from "@/types/schemas";

// The two demo briefs (README §11): bakery first, office second.
const EXAMPLES = [
  { label: "Bakery example", text: "I'm opening a second bakery location in Houston. About 20 seats, under $6k/month, and it needs parking." },
  { label: "Office example", text: "Office for a 25-person team in downtown LA, near transit, under $20k/month." },
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
        "rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-accent",
        selected ? "border-accent bg-accent-soft text-accent" : "border-border bg-surface text-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-20 text-xs font-medium tracking-wide text-muted uppercase">{label}</span>
      {children}
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

  async function submit(e: React.FormEvent) {
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
    <form onSubmit={submit} className="space-y-5 rounded-2xl border border-border bg-surface p-5 shadow-sm">
      <div className="space-y-2">
        <label htmlFor="brief" className="text-sm font-medium">
          What do you need?
        </label>
        <textarea
          id="brief"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          placeholder="e.g. Second bakery location in Houston, ~20 seats, under $6k/month, needs parking"
          className="w-full resize-none rounded-xl border border-border bg-background p-3 text-base outline-none focus:border-accent focus-visible:outline-2 focus-visible:outline-accent"
        />
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
          <span className="text-muted">Try:</span>
          {EXAMPLES.map((ex) => (
            <button key={ex.label} type="button" onClick={() => setText(ex.text)} className="text-accent underline-offset-2 hover:underline">
              {ex.label}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
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

      {query && (
        <p className="rounded-lg bg-surface-2 px-3 py-2 text-sm text-pretty">
          <span className="text-muted">We&apos;ll search for: </span>
          {query}
        </p>
      )}

      {error && (
        <p role="alert" className="rounded-lg border border-bad/40 bg-bad/10 p-3 text-sm text-bad">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={!query || busy}
        className="inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 font-medium text-background transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
        {busy ? "Starting…" : "Find my space"}
      </button>
    </form>
  );
}
