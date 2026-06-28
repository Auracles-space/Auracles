/**
 * Top marketing navigation bar.
 *
 * Mobile-first: collapses primary links into a single right-aligned CTA on
 * small screens. Desktop reveals the full primary nav and a charcoal sign-in
 * pill. Anchors target landing-page sections.
 */
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
  { href: "#trust", label: "Trust" },
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
      <div className="mx-auto flex h-16 w-full max-w-[1280px] items-center justify-between px-5 md:px-10">
        <BrandLogo className="h-7 w-28 md:h-8 md:w-32 shrink-0" />
        <nav className="hidden items-center gap-8 md:flex">
          {activeLinks.map((link) => (
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
          {isWaitlistMode ? (
            <Link
              className="inline-flex h-10 items-center rounded-control bg-accent px-4 text-sm font-medium text-white transition hover:opacity-90"
              href="#waitlist-form"
            >
              Join Waitlist
            </Link>
          ) : dashboardHref ? (
            <Link
              className="inline-flex h-10 items-center rounded-control bg-foreground px-4 text-sm font-medium text-background transition hover:opacity-90"
              href={dashboardHref}
            >
              Dashboard
            </Link>
          ) : (
            <>
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
            </>
          )}
        </div>
      </div>
    </header>
  );
}

