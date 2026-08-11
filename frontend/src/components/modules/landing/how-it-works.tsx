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
  gradient: string;
  blob: string;
};

const waitlistSteps: StepItem[] = [
  {
    title: "Package your playbook",
    body: "Upload the frameworks, templates, and operating systems you've developed. Auracles reviews submissions for originality, rarity, and compliance before publication.",
    colSpan: "md:col-span-2",
    gradient: "bg-brand-peach/10",
    blob: "bg-brand-coral/20",
  },
  {
    title: "Build a reputation",
    body: "As your work is discovered and licensed, your reputation grows.",
    colSpan: "md:col-span-1",
    gradient: "bg-brand-coral/10",
    blob: "bg-brand-magenta/20",
  },
  {
    title: "Earn every time it's licensed",
    body: "Publish once, improve over time, and earn whenever organizations license your Frameworks.",
    colSpan: "md:col-span-3",
    gradient: "bg-brand-violet/10",
    blob: "bg-brand-indigo/20",
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
              className={`group relative overflow-hidden rounded-[32px] border border-border-default ${step.gradient} p-8 shadow-bento transition hover:shadow-hero ${step.colSpan}`}
              key={step.title}
            >
              <div
                className={`absolute -right-16 -top-16 h-64 w-64 rounded-full blur-3xl transition duration-700 group-hover:scale-125 ${step.blob}`}
              />
              <div className="relative z-10 flex h-full flex-col justify-between">
                <div>
                  {step.eyebrow && (
                    <p className="inline-block rounded-full bg-surface-1/60 px-3 py-1 text-xs font-medium tracking-[0.08em] text-foreground-subtle backdrop-blur-md">
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
