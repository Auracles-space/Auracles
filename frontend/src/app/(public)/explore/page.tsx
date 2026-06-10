/**
 * Public Explore catalog route.
 *
 * Server-rendered for SEO and fast public browsing. Authenticated action gates
 * are handled only when users attempt write/download actions.
 */
import { FilterSidebar } from "@/components/modules/explore/filter-sidebar";
import { FrameworkCard } from "@/components/modules/explore/framework-card";
import type {
  ExploreFrameworkCard,
  ExploreAttestationStatus,
  ExploreSort,
  FrameworkCategory,
  FrameworkFunction,
  FrameworkIndustry,
  FrameworkSector,
  ListExploreFrameworksData,
  OrgSize,
} from "@/lib/generated/types.gen";
import { loadExploreCatalog } from "@/lib/marketplace/explore-read-model";
import {
  FRAMEWORK_CATEGORY_OPTIONS,
  FUNCTION_OPTIONS,
  INDUSTRY_OPTIONS,
  ORG_SIZE_OPTIONS,
  SECTOR_OPTIONS,
  type MarketplaceOption,
} from "@/lib/marketplace/taxonomy";

type ExplorePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

/**
 * Read the first query string value for generated-client query params.
 *
 * @param value - Next.js search param value.
 * @returns First string value or undefined.
 */
function firstParam(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * Parse a positive integer query param.
 *
 * @param value - Query string value.
 * @param fallback - Value used when parsing fails.
 * @returns Positive integer query value.
 */
function numberParam(
  value: string | string[] | undefined,
  fallback: number,
): number {
  const parsed = Number(firstParam(value));
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

/**
 * Parse a taxonomy query param only when it is in the current vocabulary.
 *
 * @param value - Next.js search param value.
 * @param options - Allowed taxonomy options for the filter.
 * @returns Typed taxonomy value or null when absent/unknown.
 */
function taxonomyParam<TValue extends string>(
  value: string | string[] | undefined,
  options: readonly MarketplaceOption<TValue>[],
): TValue | null {
  const param = firstParam(value);
  const match = options.find((option) => option.value === param);
  return match?.value ?? null;
}

/**
 * Parse Explore sort, falling back to newest for unknown query strings.
 *
 * @param value - Next.js search param value.
 * @returns Supported sort value.
 */
function sortParam(value: string | string[] | undefined): ExploreSort {
  const param = firstParam(value);
  if (
    param === "top-rated" ||
    param === "most-purchased" ||
    param === "price_asc" ||
    param === "price_desc"
  ) {
    return param;
  }
  return "newest";
}

/**
 * Parse the public Attestation badge filter.
 *
 * @param value - Next.js search param value.
 * @returns Supported public Attestation status filter.
 */
function attestationStatusParam(
  value: string | string[] | undefined,
): ExploreAttestationStatus | null {
  const param = firstParam(value);
  if (
    param === "attested" ||
    param === "pending_acceptance" ||
    param === "none"
  ) {
    return param;
  }
  return null;
}

/**
 * Render the public marketplace catalog.
 *
 * @param props - Next.js query params.
 */
export default async function ExplorePage({ searchParams }: ExplorePageProps) {
  const params = (await searchParams) ?? {};
  const query: NonNullable<ListExploreFrameworksData["query"]> = {
    category: taxonomyParam<FrameworkCategory>(
      params.category,
      FRAMEWORK_CATEGORY_OPTIONS,
    ),
    complexity: firstParam(params.complexity)
      ? Number(firstParam(params.complexity))
      : null,
    function: taxonomyParam<FrameworkFunction>(params.function, FUNCTION_OPTIONS),
    industry: taxonomyParam<FrameworkIndustry>(params.industry, INDUSTRY_OPTIONS),
    jurisdiction: firstParam(params.jurisdiction) ?? null,
    license_type: firstParam(params.license_type) ?? null,
    lifecycle_stage: firstParam(params.lifecycle_stage) ?? null,
    org_size: taxonomyParam<OrgSize>(params.org_size, ORG_SIZE_OPTIONS),
    page: numberParam(params.page, 1),
    page_size: 12,
    price_max: firstParam(params.price_max) ?? null,
    price_min: firstParam(params.price_min) ?? null,
    q: firstParam(params.q) ?? null,
    sector: taxonomyParam<FrameworkSector>(params.sector, SECTOR_OPTIONS),
    sort: sortParam(params.sort),
    attestation_status: attestationStatusParam(params.attestation_status),
  };

  const { catalog, unavailable } = await loadExploreCatalog(query);

  return (
    <main className="min-h-[calc(100vh-4rem)] bg-background p-6 text-foreground">
      <div className="mx-auto w-full max-w-[1600px]">
        <div className="flex flex-col gap-8 lg:flex-row">
          <div className="w-full lg:w-64 lg:shrink-0">
            {/* Mobile Filters Accordion */}
            <div className="block lg:hidden mb-4">
              <details className="group rounded-xl border border-border-default bg-surface-1 overflow-hidden">
                <summary className="flex cursor-pointer items-center justify-between p-4 font-medium text-foreground outline-none hover:bg-surface-2 transition-colors">
                  <div className="flex items-center gap-2">
                    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                    </svg>
                    Filters
                  </div>
                  <svg className="h-5 w-5 text-foreground-muted transition-transform group-open:rotate-180" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </summary>
                <div className="border-t border-border-default p-4 bg-background">
                  <FilterSidebar
                    active={{
                      category: query.category ?? undefined,
                      attestation_status: query.attestation_status ?? undefined,
                      function: query.function ?? undefined,
                      industry: query.industry ?? undefined,
                      license_type: query.license_type ?? undefined,
                      org_size: query.org_size ?? undefined,
                      q: query.q ?? undefined,
                      sector: query.sector ?? undefined,
                      sort: query.sort,
                    }}
                  />
                </div>
              </details>
            </div>
            
            {/* Desktop Filters Sidebar */}
            <div className="hidden lg:block">
              <FilterSidebar
                active={{
                  category: query.category ?? undefined,
                  attestation_status: query.attestation_status ?? undefined,
                  function: query.function ?? undefined,
                  industry: query.industry ?? undefined,
                  license_type: query.license_type ?? undefined,
                  org_size: query.org_size ?? undefined,
                  q: query.q ?? undefined,
                  sector: query.sector ?? undefined,
                  sort: query.sort,
                }}
              />
            </div>
          </div>
          <section className="flex-1 min-w-0">
            <div className="mb-6 flex items-center justify-between border-b border-border-default pb-4">
              <p className="text-sm font-medium text-foreground-muted">{catalog?.total ?? 0} frameworks</p>
              
              <div className="flex items-center gap-3">
                <button className="flex items-center gap-2 rounded-lg border border-border-default px-3 py-1.5 text-sm font-medium text-foreground-muted hover:bg-surface-2 transition-colors">
                  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                  </svg>
                  Sort: Newest
                  <svg className="h-3 w-3 ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
              </div>
            </div>
            
            {unavailable ? (
              <div className="rounded-xl border border-warning/30 bg-warning/10 p-8 text-center">
                <h2 className="font-heading text-xl font-bold text-foreground">
                  Catalog is temporarily unavailable
                </h2>
                <p className="mt-2 text-sm text-foreground-muted">
                  Framework browsing will return when the API is reachable.
                </p>
              </div>
            ) : catalog && catalog.items.length > 0 ? (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {catalog.items.map((framework: ExploreFrameworkCard) => (
                  <FrameworkCard framework={framework} key={framework.id} />
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-border-default bg-surface-2 p-12 text-center">
                <h2 className="font-heading text-xl font-bold text-foreground">
                  No frameworks match these filters
                </h2>
                <p className="mt-2 text-sm text-foreground-muted">
                  Clear filters or search a broader operational term.
                </p>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
