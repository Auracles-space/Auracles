/**
 * Contributor Framework creation route.
 */
import {
  CreateFrameworkPanel,
  type ProjectDeliverablePrefill,
} from "@/components/modules/frameworks/create-framework-panel";

type NewFrameworkPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

/**
 * Return all values for a query key regardless of single or repeated encoding.
 *
 * @param value - Next.js search param value.
 */
function toArray(value: string | string[] | undefined): string[] {
  if (Array.isArray(value)) {
    return value.filter(Boolean);
  }
  return value ? [value] : [];
}

/**
 * Decode Project deliverable query params for the client create panel.
 *
 * @param params - Resolved route search params.
 */
function buildPrefill(
  params: Record<string, string | string[] | undefined>,
): ProjectDeliverablePrefill {
  const tags = toArray(params.tags);
  return {
    description:
      typeof params.description === "string" ? params.description : undefined,
    fileKeys: toArray(params.file_keys),
    sourceProjectId:
      typeof params.source_project_id === "string"
        ? params.source_project_id
        : undefined,
    tags: tags.length ? tags : ["project-deliverable"],
    title: typeof params.title === "string" ? params.title : undefined,
  };
}

/**
 * Render the new Framework wizard.
 *
 * @param props - Next.js route props including optional prefill params.
 */
export default async function NewFrameworkPage({
  searchParams,
}: NewFrameworkPageProps) {
  const prefill = buildPrefill((await searchParams) ?? {});

  return (
    <main className="px-4 py-12 text-foreground md:px-8">
      <div className="mx-auto max-w-5xl">
        <div className="grid gap-12 lg:grid-cols-[1fr_2fr]">
          <div className="lg:sticky lg:top-24 lg:self-start">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              New framework
            </p>
            <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
              Create a draft
            </h1>
            <p className="mt-4 text-sm leading-6 text-foreground-muted">
              Complete the initial metadata to create your draft. You&apos;ll be able to upload your artifacts, configure the pricing model in detail, and submit it to the processing pipeline in the next steps.
            </p>
            
            <div className="mt-8 rounded-xl bg-surface-2 p-5 border border-border-default shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
              <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <svg className="h-4 w-4 text-accent" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Pro Tip
              </h3>
              <p className="mt-2 text-xs text-foreground-muted leading-relaxed">
                Frameworks with highly descriptive titles and specific tags (e.g., &quot;SOC2 Compliance&quot;, &quot;Enterprise Django&quot;) sell up to 3x faster on the marketplace.
              </p>
            </div>
          </div>
          
          <div>
            <section className="rounded-2xl border border-border-default bg-surface-1 p-6 sm:p-8 shadow-sm">
              <CreateFrameworkPanel prefill={prefill} />
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
