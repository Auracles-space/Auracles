/**
 * FAQ list — uses native <details> for accessibility-first disclosure.
 *
 * No client JS required. Each item collapses by default and expands on click
 * or Enter/Space. Mobile-first stacking is automatic.
 */

const faqs = [
  {
    q: "What is a Framework?",
    a: "A Framework is a repeatable methodology, playbook, process, template, or operating model that helps solve a specific problem.",
  },
  {
    q: "Who can become a contributor?",
    a: "Operators, investors, consultants, analysts, compliance professionals, researchers, and domain experts with proven experience.",
  },
  {
    q: "How does framework scoring work?",
    a: "Auracles analyzes submissions for uniqueness and overlap before publication.",
  },
  {
    q: "Why is verification required?",
    a: "Verification helps ensure every Framework is connected to a real contributor.",
  },
  {
    q: "Can I update a published Framework?",
    a: "Yes. Frameworks are versioned so contributors can improve them over time.",
  },
  {
    q: "What happens to my data?",
    a: "Contributors retain ownership of their intellectual property while granting marketplace licensing rights under selected terms.",
  },
];

/**
 * Render the FAQ disclosure list.
 */
export function FaqList() {
  return (
    <section className="px-5 py-16 md:px-10 md:py-24" id="faq">
      <div className="mx-auto w-full max-w-[1280px]">
        <div className="max-w-2xl">
          <p className="text-xs font-medium uppercase tracking-[0.08em] text-foreground-subtle">
            Frequently asked questions
          </p>
          <h2 className="mt-3 font-heading text-3xl font-semibold leading-tight tracking-tight text-foreground md:text-5xl">
            Answers, before you ask.
          </h2>
        </div>

        <div className="mt-10 rounded-card border border-border-default bg-surface-1 p-2 md:p-3">
          <ul className="divide-y divide-border-default">
            {faqs.map((faq) => (
              <li key={faq.q}>
                <details className="group px-4 py-5 md:px-6">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-left text-base font-medium text-foreground md:text-lg">
                    <span>{faq.q}</span>
                    <span
                      aria-hidden="true"
                      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-badge border border-border-strong bg-surface-1 text-foreground-muted transition group-open:rotate-45"
                    >
                      +
                    </span>
                  </summary>
                  <p className="mt-3 text-sm leading-7 text-foreground-muted">
                    {faq.a}
                  </p>
                </details>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}


