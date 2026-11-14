import Link from "next/link";
import {
  ArrowRight,
  Box,
  Calculator,
  FileCheck2,
  Map as MapIcon,
  MessageSquareText,
  ScanSearch,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { ApiStatus } from "@/components/ApiStatus";
import { Logo, LogoMark } from "@/components/Brand";
import { BriefForm } from "@/components/BriefForm";
import { ProductPreview } from "@/components/ProductPreview";
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV = [
  { href: "#product", label: "Product" },
  { href: "#how", label: "How it works" },
  { href: "#data", label: "Data" },
];

const SOURCES = [
  { name: "CoStar", what: "Vacant listings, asking rents and nearby comps" },
  { name: "Matterport", what: "Real 3D scans of each space, room by room" },
  { name: "Vexcel", what: "Aerial imagery for parking and street context" },
];

const STEPS = [
  {
    icon: MessageSquareText,
    title: "Describe it like you'd tell a broker",
    body: "Plain English or a few taps: business type, city, seats or desks, budget and must-haves like parking or an existing kitchen.",
  },
  {
    icon: ScanSearch,
    title: "The agent does the legwork",
    body: "It filters real vacancies, ranks them, sends an inspector through each 3D scan, and fits out a layout that passes aisle and egress checks.",
  },
  {
    icon: Box,
    title: "Walk through it, then decide",
    body: "Tour your business inside the actual space, compare rent, fit-out and break-even side by side, and send the broker a ready-made email.",
  },
];

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <p className="text-xs font-semibold tracking-[0.14em] text-primary uppercase">{children}</p>;
}

function SectionHead({ eyebrow, title, body }: { eyebrow: string; title: React.ReactNode; body?: string }) {
  return (
    <div className="mx-auto max-w-2xl space-y-3 text-center">
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">{title}</h2>
      {body && <p className="text-lg text-pretty text-muted">{body}</p>}
    </div>
  );
}

function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-6xl items-center gap-6 px-4 sm:px-6">
        <Logo />
        <nav className="hidden items-center gap-1 text-sm md:flex" aria-label="Main">
          {NAV.map((n) => (
            <a key={n.href} href={n.href} className="rounded-md px-3 py-1.5 text-muted transition-colors hover:bg-surface-2 hover:text-foreground">
              {n.label}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <ThemeToggle />
          <a
            href="#search"
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-foreground px-3.5 text-sm font-medium text-background transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            Start a search <ArrowRight className="size-4" />
          </a>
        </div>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden">
      <div className="bg-grid pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]" aria-hidden />
      <div
        className="pointer-events-none absolute -top-40 left-1/2 h-[32rem] w-[56rem] -translate-x-1/2 rounded-full opacity-60 blur-3xl"
        style={{ background: "radial-gradient(closest-side, color-mix(in oklab, var(--primary) 22%, transparent), transparent)" }}
        aria-hidden
      />
      <div className="relative mx-auto max-w-3xl px-4 pt-16 pb-20 text-center sm:px-6 sm:pt-24">
        <a
          href="#how"
          className="fade-up inline-flex items-center gap-2 rounded-full border border-border bg-surface/80 px-3 py-1 text-[13px] text-muted shadow-sm backdrop-blur transition-colors hover:text-foreground"
        >
          <span className="relative flex size-2">
            <span className="pulse-dot absolute inline-flex size-full rounded-full bg-secondary" />
          </span>
          Now searching Houston &amp; Los Angeles
          <ArrowRight className="size-3.5" />
        </a>
        <h1 className="fade-up mt-6 text-4xl font-semibold tracking-tight text-balance [animation-delay:60ms] sm:text-6xl">
          See your business in the space <span className="text-gradient">before you sign the lease.</span>
        </h1>
        <p className="fade-up mx-auto mt-5 max-w-2xl text-lg text-pretty text-muted [animation-delay:120ms] sm:text-xl">
          Tell Hestia what you need. Its agent searches real vacant spaces, places your business inside the actual 3D scan, and
          works out rent, fit-out and break-even, with a source behind every number.
        </p>
        <div id="search" className="fade-up mt-10 scroll-mt-24 [animation-delay:180ms]">
          <BriefForm />
        </div>
        <ul className="mt-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-muted">
          {["No signup", "Real vacant listings", "Every number cited"].map((t) => (
            <li key={t} className="inline-flex items-center gap-1.5">
              <ShieldCheck className="size-4 text-secondary" aria-hidden /> {t}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function DataStrip() {
  return (
    <section id="data" className="scroll-mt-20 border-y border-border bg-surface/60">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 sm:px-6 md:grid-cols-[14rem_1fr] md:items-center">
        <p className="text-sm text-pretty text-muted">Built on the data commercial real estate already runs on.</p>
        <ul className="grid gap-6 sm:grid-cols-3">
          {SOURCES.map((s) => (
            <li key={s.name} className="space-y-1">
              <p className="text-lg font-semibold tracking-tight">{s.name}</p>
              <p className="text-sm text-pretty text-muted">{s.what}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Product() {
  return (
    <section id="product" className="scroll-mt-20 px-4 py-24 sm:px-6">
      <SectionHead
        eyebrow="The workspace"
        title="From one sentence to a fitted-out, priced shortlist"
        body="Watch the agent narrow hundreds of listings to a handful, then open any result to see the layout, the numbers and where each one came from."
      />
      <div className="mx-auto mt-14 max-w-6xl">
        <ProductPreview />
      </div>
    </section>
  );
}

function HowItWorks() {
  return (
    <section id="how" className="scroll-mt-20 border-t border-border bg-surface-2/50 px-4 py-24 sm:px-6">
      <SectionHead eyebrow="How it works" title="Three steps. No site visits until you're sure." />
      <ol className="mx-auto mt-14 grid max-w-6xl gap-4 md:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="shadow-soft relative rounded-2xl border border-border bg-surface p-6">
            <div className="flex items-center justify-between">
              <span className="flex size-10 items-center justify-center rounded-xl bg-primary-soft text-primary">
                <s.icon className="size-5" />
              </span>
              <span className="font-mono text-sm text-muted">0{i + 1}</span>
            </div>
            <h3 className="mt-5 text-lg font-semibold tracking-tight">{s.title}</h3>
            <p className="mt-2 text-pretty text-muted">{s.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Features() {
  return (
    <section className="px-4 py-24 sm:px-6">
      <SectionHead eyebrow="Why Hestia" title={<>Listing photos lie. <span className="text-muted">Scans and sources don&apos;t.</span></>} />
      <div className="mx-auto mt-14 grid max-w-6xl gap-4 md:grid-cols-6">
        {/* receipts */}
        <article className="shadow-soft rounded-2xl border border-border bg-surface p-6 md:col-span-4">
          <span className="flex size-10 items-center justify-center rounded-xl bg-secondary-soft text-secondary">
            <Calculator className="size-5" />
          </span>
          <h3 className="mt-5 text-lg font-semibold tracking-tight">Every number has a receipt</h3>
          <p className="mt-2 max-w-lg text-pretty text-muted">
            Rent comes from the listing. Fit-out and revenue come from stated assumptions you can read. Hover any figure to see exactly where it came from.
          </p>
          <div className="mt-6 grid gap-2 sm:grid-cols-3">
            {[
              { k: "Rent", v: "$5,400/mo", s: "CoStar listing" },
              { k: "Fit-out", v: "$62k – $88k", s: "$34–48/sqft assumption" },
              { k: "Break-even", v: "14 – 22 mo", s: "Model, from your seats" },
            ].map((x) => (
              <div key={x.k} className="rounded-xl border border-border bg-surface-2/60 p-3">
                <p className="text-xs text-muted">{x.k}</p>
                <p className="mt-0.5 font-semibold tabular-nums">{x.v}</p>
                <p className="mt-2 inline-flex items-center gap-1 rounded-md bg-secondary-soft px-1.5 py-0.5 text-[11px] font-medium text-secondary">
                  <FileCheck2 className="size-3" /> {x.s}
                </p>
              </div>
            ))}
          </div>
        </article>

        {/* 3D */}
        <article className="shadow-soft relative overflow-hidden rounded-2xl border border-border bg-[#16130f] p-6 text-white ring-1 ring-white/5 md:col-span-2">
          <div
            className="pointer-events-none absolute -right-16 -bottom-16 size-56 rounded-full opacity-50 blur-2xl"
            style={{ background: "radial-gradient(closest-side, var(--primary), transparent)" }}
            aria-hidden
          />
          <span className="relative flex size-10 items-center justify-center rounded-xl bg-white/10 text-[#ff8a5c]">
            <Box className="size-5" />
          </span>
          <h3 className="relative mt-5 text-lg font-semibold tracking-tight">Your layout, inside the real scan</h3>
          <p className="relative mt-2 text-pretty opacity-70">
            Counters, tables and desks are placed in the actual Matterport tour, so you walk your space, not a stock render.
          </p>
        </article>

        {/* steer */}
        <article className="shadow-soft rounded-2xl border border-border bg-surface p-6 md:col-span-2">
          <span className="flex size-10 items-center justify-center rounded-xl bg-primary-soft text-primary">
            <Sparkles className="size-5" />
          </span>
          <h3 className="mt-5 text-lg font-semibold tracking-tight">Steer it like a teammate</h3>
          <p className="mt-2 text-pretty text-muted">Not quite right? Say so. The agent re-plans in another round.</p>
          <div className="mt-5 flex flex-wrap gap-1.5">
            {["Fewer seats", "Closer to transit", "Lower rent"].map((t) => (
              <span key={t} className="rounded-full border border-border px-2.5 py-1 text-xs text-muted">
                {t}
              </span>
            ))}
          </div>
        </article>

        {/* neighborhood */}
        <article className="shadow-soft rounded-2xl border border-border bg-surface p-6 md:col-span-2">
          <span className="flex size-10 items-center justify-center rounded-xl bg-tertiary-soft text-amber-700 dark:text-tertiary">
            <MapIcon className="size-5" />
          </span>
          <h3 className="mt-5 text-lg font-semibold tracking-tight">The block, at a glance</h3>
          <p className="mt-2 text-pretty text-muted">Nearby competitors or amenities, transit stops, and parking read from aerial imagery.</p>
        </article>

        {/* layout checks */}
        <article className="shadow-soft rounded-2xl border border-border bg-surface p-6 md:col-span-2">
          <span className="flex size-10 items-center justify-center rounded-xl bg-secondary-soft text-secondary">
            <ShieldCheck className="size-5" />
          </span>
          <h3 className="mt-5 text-lg font-semibold tracking-tight">Layouts that actually fit</h3>
          <p className="mt-2 text-pretty text-muted">Every fit-out is checked for aisle widths, clearances and seat count before you ever see it.</p>
        </article>
      </div>
    </section>
  );
}

function FinalCta() {
  return (
    <section className="px-4 pb-24 sm:px-6">
      <div className="relative mx-auto max-w-6xl overflow-hidden rounded-3xl bg-[#16130f] px-6 py-16 text-center text-white ring-1 ring-white/5 sm:px-12">
        <div className="bg-grid pointer-events-none absolute inset-0 [--grid-line:rgb(255_255_255/0.05)] [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]" aria-hidden />
        <div
          className="pointer-events-none absolute -top-24 left-1/2 h-72 w-[40rem] -translate-x-1/2 rounded-full opacity-50 blur-3xl"
          style={{ background: "radial-gradient(closest-side, var(--primary), transparent)" }}
          aria-hidden
        />
        <div className="relative mx-auto max-w-2xl space-y-5">
          <h2 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">Stop guessing from listing photos.</h2>
          <p className="text-lg text-pretty opacity-70">Describe your business once. Walk through your shortlist today.</p>
          <a
            href="#search"
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-6 py-3 font-medium text-on-primary transition-colors hover:bg-primary-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            Find my space <ArrowRight className="size-4" />
          </a>
        </div>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 text-sm text-muted sm:px-6 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3">
          <LogoMark className="size-7" />
          <span>
            <span className="font-medium text-foreground">Hestia</span> · Built at HackPrinceton Fall 2026
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <span>Data: CoStar · Matterport · Vexcel</span>
          <ApiStatus />
          <Link href="#search" className="hover:text-foreground">
            Start a search
          </Link>
        </div>
      </div>
    </footer>
  );
}

export default function Home() {
  return (
    <>
      <Nav />
      <main className="flex-1">
        <Hero />
        <DataStrip />
        <Product />
        <HowItWorks />
        <Features />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}
