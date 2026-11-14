import { ApiStatus } from "@/components/ApiStatus";
import { BriefForm } from "@/components/BriefForm";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center gap-8 px-5 py-12">
      <header className="space-y-3">
        <p className="text-sm font-semibold tracking-widest text-accent uppercase">Hestia</p>
        <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
          See your business in a real vacant space before you sign the lease.
        </h1>
        <p className="max-w-2xl text-lg text-muted text-pretty">
          Tell us what you need. An AI agent searches real vacant spaces, places your business inside the real 3D tour,
          and works out rent, fit-out cost and break-even, with a source for every number.
        </p>
      </header>
      <BriefForm />
      <footer className="flex items-center justify-between text-sm text-muted">
        <span>CoStar · Matterport · Vexcel</span>
        <ApiStatus />
      </footer>
    </main>
  );
}
