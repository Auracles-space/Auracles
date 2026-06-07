/**
 * FAQ list — uses native <details> for accessibility-first disclosure.
 *
 * No client JS required. Each item collapses by default and expands on click
 * or Enter/Space. Mobile-first stacking is automatic.
 */

const faqs = [
  {
    q: "What is a Framework?",
    a: "A licensable knowledge product — a set of documents (PDF, DOCX, XLSX, PPTX, ZIP) packaged with metadata, pricing, and a license type. Operators license, download, and run them.",
  },
  {
    q: "How does originality scoring work?",
    a: "Every uploaded artifact runs through a MinHash + LSH pipeline (internal duplicate detection) and a quoted-phrase web search (external rarity). Both signals plus metadata blend into a single rarity score, and the audit row is explainable.",
  },
  {
    q: "Why is KYC required to download?",
    a: "Auracles is a high-trust marketplace. KYC on both sides — Contributors verify before publishing, Operators verify before downloading — keeps the floor consistent and protects sellers.",
  },
  {
    q: "Who reviews submitted Frameworks?",
    a: "The pipeline reviews them. Virus scan, PII detection, originality, and rarity must all pass before the Publish button enables. Admins moderate after publish, on abuse reports or spot-checks.",
  },
  {
    q: "Can I version a published Framework?",
    a: "Yes. Pick a change type — fix, improvement, or major — and the platform auto-computes the semver. Prior version stays accessible to existing licensees.",
  },
  {
    q: "What about my data?",
    a: "Artifact text never leaves your own infrastructure for PII or originality checks. The only external call is a gated, quoted-phrase web search for external rarity, with phrase-level caching to minimize calls.",
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
            Frequently asked
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
