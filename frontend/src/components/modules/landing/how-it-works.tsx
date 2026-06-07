/**
 * "How it works" — bento grid covering the Auracles loop.
 *
 * Maps to the three platform roles: Contributor publishes, Operator licenses,
 * Attestor verifies.
 */

const steps = [
  {
    eyebrow: "01 — Contributor",
    title: "Package your playbook.",
    body: "Upload the document set you actually use. Auracles runs PII, originality, and rarity checks before it ever hits the catalog.",
    colSpan: "md:col-span-2",
    gradient: "bg-brand-peach/10",
    blob: "bg-brand-coral/20",
  },
  {
    eyebrow: "02 — Operator",
    title: "License what you need.",
    body: "Buy a Framework with a single, team, or enterprise license. Download artifacts only after KYC clears.",
    colSpan: "md:col-span-1",
    gradient: "bg-brand-pink/10",
    blob: "bg-brand-magenta/20",
  },
  {
    eyebrow: "03 — Attestor",
    title: "Verify the source.",
    body: "Independent domain experts review and attest. Every Framework carries its provenance and trust signal in plain sight.",
    colSpan: "md:col-span-3",
    gradient: "bg-brand-violet/10",
    blob: "bg-brand-indigo/20",
  },
];

/**
 * Render the three-step explainer block.
 */
export function HowItWorks() {
  return (
    <section className="px-5 py-16 md:px-10 md:py-24" id="how-it-works">
      <div className="mx-auto w-full max-w-[1280px]">
        <div className="max-w-2xl text-center md:mx-auto md:text-center">
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-accent">
            How it works
          </p>
          <h2 className="mt-3 font-heading text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
            A marketplace built around the people who ship.
          </h2>
        </div>

        <div className="mt-16 grid gap-6 md:grid-cols-3">
          {steps.map((step) => (
            <article
              className={`group relative overflow-hidden rounded-[32px] border border-border-default ${step.gradient} p-8 shadow-bento transition hover:shadow-hero ${step.colSpan}`}
              key={step.eyebrow}
            >
              <div
                className={`absolute -right-16 -top-16 h-64 w-64 rounded-full blur-3xl transition duration-700 group-hover:scale-125 ${step.blob}`}
              />
              <div className="relative z-10 flex h-full flex-col justify-between">
                <div>
                  <p className="inline-block rounded-full bg-surface-1/60 px-3 py-1 text-xs font-medium tracking-[0.08em] text-foreground-subtle backdrop-blur-md">
                    {step.eyebrow}
                  </p>
                  <h3 className="mt-6 font-heading text-2xl font-semibold text-foreground md:text-3xl">
                    {step.title}
                  </h3>
                  <p className="mt-3 max-w-lg text-base leading-7 text-foreground-muted">
                    {step.body}
                  </p>
                </div>
                
                {/* Visual Placeholder for Bento */}
                <div className="mt-8 h-32 w-full rounded-2xl bg-surface-1/40 backdrop-blur-sm border border-border-default" />
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
