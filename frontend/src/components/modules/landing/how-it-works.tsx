/**
 * "How it works" — bento grid covering the Auracles loop.
 *
 * Maps to the three platform roles: Contributor publishes, Operator licenses,
 * Attestor verifies.
 */
type StepItem = {
  eyebrow?: string;
  title: string;
  body: string;
  colSpan: string;
};

const waitlistSteps: StepItem[] = [
  {
    title: "Package your playbook",
    body: "Upload the frameworks, templates, and operating systems you've developed. Auracles reviews submissions for originality, rarity, and compliance before publication.",
    colSpan: "md:col-span-2",
  },
  {
    title: "Build a reputation",
    body: "As your work is discovered and licensed, your reputation grows.",
    colSpan: "md:col-span-1",
  },
  {
    title: "Earn every time it's licensed",
    body: "Publish once, improve over time, and earn whenever organizations license your Frameworks.",
    colSpan: "md:col-span-3",
  },
];

/**
 * Render the three-step explainer block.
 */
export function HowItWorks() {
  const steps = waitlistSteps;

  return (
    <section className="px-5 py-16 md:px-10 md:py-24" id="how-it-works">
      <div className="mx-auto w-full max-w-[1280px]">
        <div className="max-w-2xl text-center md:mx-auto md:text-center mb-16">
          <h2 className="font-heading text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
            A marketplace built for people who ship.
          </h2>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {steps.map((step) => (
            <article
              className={`relative overflow-hidden rounded-card border border-border-default bg-surface-1 p-6 shadow-bento transition hover:border-accent/30 md:p-8 ${step.colSpan}`}
              key={step.title}
            >
              <div className="relative z-10 flex h-full flex-col justify-between">
                <div>
                  {step.eyebrow && (
                    <p className="inline-block rounded-badge bg-surface-2 px-3 py-1 text-xs font-medium tracking-[0.08em] text-foreground-subtle">
                      {step.eyebrow}
                    </p>
                  )}
                  <h3 className="mt-4 font-heading text-2xl font-semibold text-foreground md:text-3xl">
                    {step.title}
                  </h3>
                  <p className="mt-3 max-w-lg text-base leading-7 text-foreground-muted">
                    {step.body}
                  </p>
                </div>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
