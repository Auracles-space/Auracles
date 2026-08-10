/**
 * Pricing strip — three license-type comparison cards.
 *
 * Mirrors Phase 2's license model: single, team, enterprise. Pricing is
 * per-Framework (set by Contributors); the cards illustrate license shape,
 * not specific dollar values.
 */
import Link from "next/link";

const isWaitlistMode = process.env.NEXT_PUBLIC_WAITLIST_MODE !== "false";

const tiers = [
  {
    name: "Single",
    summary: "One named operator.",
    body: "Best for individual practitioners. Lifetime access to the licensed version.",
    bullets: ["1 seat", "Lifetime access", "Audit-logged downloads"],
    // Pre-launch the catalog is empty, so waitlist mode routes to the signup
    // instead of dropping visitors onto a filtered page with no results.
    cta: isWaitlistMode
      ? { label: "Join the waitlist", href: "#waitlist-form" }
      : { label: "Browse single-seat", href: "/explore?license_type=single_user" },
    featured: false,
  },
  {
    name: "Team",
    summary: "Up to 10 named seats.",
    body: "For teams running the same playbook. Add or remove seats anytime.",
    bullets: ["Up to 10 seats", "Lifetime access", "Audit per seat"],
    cta: isWaitlistMode
      ? { label: "Join the waitlist", href: "#waitlist-form" }
      : { label: "Browse team", href: "/explore?license_type=team" },
    featured: true,
  },
  {
    name: "Enterprise",
    summary: "Custom seat ceiling, invoiced.",
    body: "Procurement-friendly. Custom MSA, manual invoicing, dedicated onboarding.",
    bullets: ["Unlimited seats", "Custom invoice", "MSA on request"],
    cta: { label: "Contact sales", href: "mailto:sales@auracles.space" },
    featured: false,
  },
];

/**
 * Render the three license tiers side by side.
 */
export function PricingStrip() {
  return (
    <section className="px-5 pb-16 md:px-10 md:pb-24" id="pricing">
      <div className="mx-auto w-full max-w-[1280px]">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="font-heading text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
            Contributors set the price. You pick the license.
          </h2>
          <p className="mt-4 max-w-xl mx-auto text-base leading-7 text-foreground-muted">
            Every Framework is priced by the person who built it. These are the
            three license shapes you can buy it under.
          </p>
        </div>

        <div className="mt-12 grid gap-6 md:mt-16 md:grid-cols-3 md:items-start">
          {tiers.map((tier) => (
            <article
              className={`relative flex h-full flex-col rounded-hero border bg-surface-1 p-8 ${
                tier.featured
                  ? "z-10 border-accent shadow-bento md:-mt-4 md:pb-12"
                  : "border-border-default shadow-card"
              }`}
              key={tier.name}
            >
              {tier.featured && (
                <div className="absolute -top-4 left-1/2 -translate-x-1/2 rounded-full bg-accent px-3 py-1 text-xs font-bold uppercase tracking-widest text-white shadow-sm">
                  Popular
                </div>
              )}
              
              <div className="text-center">
                <h3 className="font-heading text-2xl font-bold text-foreground">
                  {tier.name}
                </h3>
                <p className="mt-2 text-sm font-medium text-foreground-muted">
                  {tier.summary}
                </p>
              </div>

              <div className="my-8 h-px w-full bg-border-default" />

              <ul className="flex-1 space-y-4 text-sm text-foreground">
                {tier.bullets.map((bullet) => (
                  <li className="flex items-center gap-3" key={bullet}>
                    <div className="flex h-5 w-5 items-center justify-center rounded-full bg-accent text-white shadow-sm">
                      <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    </div>
                    {bullet}
                  </li>
                ))}
              </ul>

              <Link
                className={`mt-8 inline-flex h-12 items-center justify-center rounded-control px-5 text-sm font-bold transition focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 ${
                  tier.featured
                    ? "bg-foreground text-background shadow-md hover:bg-foreground/90"
                    : "border-2 border-foreground bg-transparent text-foreground hover:bg-foreground hover:text-background"
                }`}
                href={tier.cta.href}
              >
                {tier.cta.label}
              </Link>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
