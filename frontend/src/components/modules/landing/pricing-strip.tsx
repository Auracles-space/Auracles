/**
 * Pricing strip — three license-type comparison cards.
 *
 * Mirrors Phase 2's license model: single, team, enterprise. Pricing is
 * per-Framework (set by Contributors); the cards illustrate license shape,
 * not specific dollar values.
 */
import Link from "next/link";

const tiers = [
  {
    name: "Single",
    summary: "One named operator.",
    body: "Best for individual practitioners. Lifetime access to the licensed version.",
    bullets: ["1 seat", "Lifetime access", "Audit-logged downloads"],
    cta: { label: "Browse single-seat", href: "/explore?license_type=single_user" },
    featured: false,
  },
  {
    name: "Team",
    summary: "Up to 10 named seats.",
    body: "For teams running the same playbook. Add or remove seats anytime.",
    bullets: ["Up to 10 seats", "Lifetime access", "Audit per seat"],
    cta: { label: "Browse team", href: "/explore?license_type=team" },
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
        <div className="max-w-2xl text-center md:mx-auto md:text-center">
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-accent">
            License options
          </p>
          <h2 className="mt-3 font-heading text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
            Find the right plan for your team
          </h2>
          <p className="mt-4 max-w-xl mx-auto text-base leading-7 text-foreground-muted">
            Contributors set the price. You pick the license shape that fits your org.
          </p>
        </div>

        <div className="mt-12 grid gap-6 md:grid-cols-3">
          {tiers.map((tier) => (
            <article
              className={`relative flex flex-col rounded-[32px] border bg-surface-1 p-8 ${
                tier.featured
                  ? "border-accent shadow-bento scale-105 z-10"
                  : "border-border-default shadow-card mt-0 md:mt-4 md:mb-4"
              }`}
              key={tier.name}
            >
              {tier.featured && (
                <div className="absolute -top-4 left-1/2 -translate-x-1/2 rounded-full bg-accent px-3 py-1 text-[11px] font-bold uppercase tracking-widest text-white shadow-sm">
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
                className={`mt-8 inline-flex h-12 items-center justify-center rounded-control px-5 text-sm font-bold transition ${
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
