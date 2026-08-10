/**
 * Top marketing navigation bar.
 *
 * Mobile-first: primary links live in a disclosure menu below `lg`, so every
 * section stays reachable on a phone rather than scroll-only. The menu uses
 * native `<details>` so this stays a Server Component with no client JS.
 * Anchors target landing-page sections.
 */
import { Cross1Icon, HamburgerMenuIcon } from "@radix-ui/react-icons";
import Link from "next/link";
import { BrandLogo } from "@/components/ui/brand-logo";

import { ThemeToggle } from "@/components/ui/theme-toggle";
import { getRoleLandingPath } from "@/lib/auth/route-guards";
import { getVerifiedSessionHintFromCookies } from "@/lib/auth/server-session";

// Waitlist mode defaults to true in production/unspecified environments to gate entry.
// Set NEXT_PUBLIC_WAITLIST_MODE=false locally to bypass the waitlist controls.
const isWaitlistMode = process.env.NEXT_PUBLIC_WAITLIST_MODE !== "false";

const navLinks = [
  { href: "#how-it-works", label: "How It Works" },
  { href: "#roles", label: "For Contributors" },
  { href: "#become", label: "Become an Auracle" },
  { href: "#pricing", label: "Licensing" },
  { href: "#faq", label: "FAQ" },
];

/**
 * Render the marketing site top navigation.
 *
 * Reads the signed session hint so a signed-in visitor sees a dashboard link
 * instead of the logged-out "Sign in / Get started" pair.
 */
export async function MarketingNav() {
  const activeLinks = navLinks;
  const hint = await getVerifiedSessionHintFromCookies();
  const dashboardHref = hint ? getRoleLandingPath(hint.roles) : null;


  return (
    <header className="sticky top-0 z-30 border-b border-border-default bg-background/95 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-[1280px] items-center justify-between gap-3 px-5 md:px-10">
        <BrandLogo className="h-7 w-28 md:h-8 md:w-32 shrink-0" />
        <nav className="hidden items-center gap-6 lg:flex">
          {activeLinks.map((link) => (
            <Link
              className="rounded-control text-sm font-medium text-foreground-muted transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-4 focus-visible:ring-offset-background"
              href={link.href}
              key={link.href}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <div className="flex shrink-0 items-center gap-2">
          <ThemeToggle />
          {isWaitlistMode ? (
            <Link
              className="inline-flex h-10 items-center rounded-control whitespace-nowrap bg-accent px-4 text-sm font-medium text-white transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              href="#waitlist-form"
            >
              Join Waitlist
            </Link>
          ) : dashboardHref ? (
            <Link
              className="inline-flex h-10 items-center rounded-control whitespace-nowrap bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
              href={dashboardHref}
            >
              Dashboard
            </Link>
          ) : (
            <>
              <Link
                className="hidden h-10 items-center rounded-control whitespace-nowrap px-4 text-sm font-medium text-foreground-muted transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background lg:inline-flex"
                href="/login"
              >
                Sign in
              </Link>
              <Link
                className="inline-flex h-10 items-center rounded-control whitespace-nowrap bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-90 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                href="/register"
              >
                Get started
              </Link>
            </>
          )}

          {/* Below `lg` the primary links collapse here. Native disclosure — no client JS. */}
          <details className="group relative lg:hidden">
            <summary className="flex h-11 w-11 cursor-pointer list-none items-center justify-center rounded-control text-foreground-muted transition hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-background [&::-webkit-details-marker]:hidden">
              <HamburgerMenuIcon aria-hidden="true" className="h-5 w-5 group-open:hidden" />
              <Cross1Icon aria-hidden="true" className="hidden h-5 w-5 group-open:block" />
              <span className="sr-only">Menu</span>
            </summary>
            <nav className="absolute right-0 top-[calc(100%+0.75rem)] w-60 rounded-card border border-border-strong bg-surface-1 p-2 shadow-card">
              {activeLinks.map((link) => (
                <Link
                  className="flex min-h-11 items-center rounded-control px-3 text-sm font-medium text-foreground-muted transition hover:bg-surface-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
                  href={link.href}
                  key={link.href}
                >
                  {link.label}
                </Link>
              ))}
              {!isWaitlistMode && !dashboardHref && (
                <Link
                  className="flex min-h-11 items-center rounded-control px-3 text-sm font-medium text-foreground-muted transition hover:bg-surface-2 hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
                  href="/login"
                >
                  Sign in
                </Link>
              )}
            </nav>
          </details>
        </div>
      </div>
    </header>
  );
}

