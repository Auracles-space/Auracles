/**
 * Trust signal grid — four pillars the marketplace stands on.
 *
 * Mirrors the platform's enforcement seams: KYC at the boundary, pipeline
 * gates at submission, audit trail at every event, attestations on the
 * surface.
 */

const pillars = [
  {
    label: "KYC at the boundary",
    body: "Contributors verify before publishing. Operators verify before downloading. The trust floor is enforced at both sides, not just one.",
    icon: (
      <svg className="h-6 w-6 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
      </svg>
    ),
  },
  {
    label: "Pipeline as the gate",
    body: "Virus scan, PII redaction, originality, and rarity run before the Publish button enables. No admin bottleneck — but no skipped checks either.",
    icon: (
      <svg className="h-6 w-6 text-[#FF9A76]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
      </svg>
    ),
  },
  {
    label: "Provable provenance",
    body: "Every Framework carries its version history, change reasons, and attestation chain. You can audit the journey from draft to license.",
    icon: (
      <svg className="h-6 w-6 text-[#FFC2B4]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
  {
    label: "Auditable from day one",
    body: "Logins, downloads, payouts, role changes — every meaningful event lands in a queryable audit log. Compliance starts on day one.",
    icon: (
      <svg className="h-6 w-6 text-[#C74634]" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
      </svg>
    ),
  },
];

/**
 * Render the trust pillars grid.
 */
export function TrustGrid() {
  return (
    <section className="bg-surface-2 px-5 py-16 md:px-10 md:py-24" id="trust">
      <div className="mx-auto w-full max-w-[1280px]">
        <div className="flex flex-col items-start justify-between gap-8 md:flex-row md:items-end">
          <div className="max-w-2xl">
            <p className="text-xs font-medium uppercase tracking-[0.08em] text-accent">
              Trust by design
            </p>
            <h2 className="mt-3 font-heading text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
              Marketplaces fail when the trust floor leaks.
            </h2>
            <p className="mt-4 max-w-xl text-base leading-7 text-foreground-muted">
              Auracles bakes verification into the workflow. Not a badge, not a
              policy — a runtime gate at every transition.
            </p>
          </div>
        </div>

        <div className="mt-12 grid gap-6 md:grid-cols-2">
          {pillars.map((pillar) => (
            <article
              className="group relative overflow-hidden rounded-[32px] border border-border-default bg-surface-1 p-8 shadow-bento transition hover:-translate-y-1 hover:shadow-hero"
              key={pillar.label}
            >
              <div className="absolute -right-12 -top-12 h-32 w-32 rounded-full bg-brand-peach/5 blur-2xl transition duration-500 group-hover:bg-brand-peach/10" />
              <div className="relative z-10">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-2">
                  {pillar.icon}
                </div>
                <h3 className="mt-6 font-heading text-xl font-semibold text-foreground md:text-2xl">
                  {pillar.label}
                </h3>
                <p className="mt-3 text-sm leading-7 text-foreground-muted">
                  {pillar.body}
                </p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
