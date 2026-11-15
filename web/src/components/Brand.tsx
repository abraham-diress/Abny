import Link from "next/link";
import clsx from "clsx";

/** The mark: a hearth (roof + flame) on an ember tile. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-tertiary text-white shadow-[inset_0_1px_0_rgb(255_255_255/0.25)]",
        className ?? "size-8",
      )}
      aria-hidden
    >
      <svg viewBox="0 0 24 24" className="size-[62%]" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 11.2 12 4.5l8 6.7" />
        <path d="M6.5 9.6v9.4h11V9.6" />
        <path
          d="M12 17.2c-1.5 0-2.5-1-2.5-2.4 0-1.4 1.2-2.3 1.7-3.6.9.7 1.4 1.5 1.5 2.3.4-.3.6-.7.7-1.1.7.7 1.1 1.5 1.1 2.4 0 1.4-1 2.4-2.5 2.4z"
          fill="currentColor"
          stroke="none"
        />
      </svg>
    </span>
  );
}

export function Logo({ href = "/", className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={clsx("inline-flex items-center gap-2.5 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary", className)}>
      <LogoMark />
      <span className="text-[17px] font-semibold tracking-tight">Hestia</span>
    </Link>
  );
}
