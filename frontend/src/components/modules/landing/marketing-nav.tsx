/**
 * Top marketing navigation bar.
 *
 * Mobile-first: collapses primary links into a single right-aligned CTA on
 * small screens. Desktop reveals the full primary nav and a charcoal sign-in
 * pill. Anchors target landing-page sections.
 */
import Link from "next/link";

import { ThemeToggle } from "@/components/ui/theme-toggle";

const links = [
  { href: "#how-it-works", label: "How it works" },
  { href: "#roles", label: "For Contributors" },
  { href: "#trust", label: "Trust" },
  { href: "#pricing", label: "Pricing" },
];

/**
 * Render the marketing site top navigation.
 */
export function MarketingNav() {
  return (
    <header className="sticky top-0 z-30 border-b border-border-default bg-background/95 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-[1280px] items-center justify-between px-5 md:px-10">
        <Link
          className="font-heading text-lg font-semibold tracking-tight text-foreground"
          href="/"
        >
          Auracles
        </Link>
        <nav className="hidden items-center gap-8 md:flex">
          {links.map((link) => (
            <Link
              className="text-sm font-medium text-foreground-muted transition hover:text-foreground"
              href={link.href}
              key={link.href}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Link
            className="hidden h-10 items-center rounded-control px-4 text-sm font-medium text-foreground-muted transition hover:text-foreground md:inline-flex"
            href="/login"
          >
            Sign in
          </Link>
          <Link
            className="inline-flex h-10 items-center rounded-control bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-90"
            href="/register"
          >
            Get started
          </Link>
        </div>
      </div>
    </header>
  );
}
