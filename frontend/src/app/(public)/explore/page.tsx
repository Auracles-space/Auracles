/**
 * Public Explore catalog route.
 *
 * Server-rendered for SEO and fast public browsing. Authenticated action gates
 * are handled only when users attempt write/download actions.
 */
import { FilterSidebar } from "@/components/modules/explore/filter-sidebar";
import {
  CollectionCard,
  FrameworkCard,
} from "@/components/modules/explore/framework-card";
import { ExploreSaveSearchAction } from "@/components/modules/explore/save-search-action";
import { SortMenu } from "@/components/modules/explore/sort-menu";
import type {
  ExploreAttestationStatus,
  ExploreCatalogResponse,
  ExploreSearchFilters,
  ExploreSort,
  FrameworkCategory,
  FrameworkFunction,
  FrameworkIndustry,
  FrameworkSector,
  ListMixedCatalogV1ExploreCatalogGetData,
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
import { filtersFromExploreSearchParams } from "@/lib/marketplace/saved-search-filters";
import { getVerifiedSessionHintFromCookies } from "@/lib/auth/server-session";

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
    param === "conditionally_attested" ||
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
  // Validated taxonomy filters drive both the API query and the sidebar's active
  // state, so a filter link narrows the catalog instead of only restyling the UI.
  const category =
    taxonomyParam<FrameworkCategory>(
      params.category,
      FRAMEWORK_CATEGORY_OPTIONS,
    ) ?? undefined;
  const attestation_status =
    attestationStatusParam(params.attestation_status) ?? undefined;
  const frameworkFunction =
    taxonomyParam<FrameworkFunction>(params.function, FUNCTION_OPTIONS) ??
    undefined;
  const industry =
    taxonomyParam<FrameworkIndustry>(params.industry, INDUSTRY_OPTIONS) ??
    undefined;
  const license_type = firstParam(params.license_type) ?? undefined;
  const org_size =
    taxonomyParam<OrgSize>(params.org_size, ORG_SIZE_OPTIONS) ?? undefined;
  const sector =
    taxonomyParam<FrameworkSector>(params.sector, SECTOR_OPTIONS) ?? undefined;

  const query: NonNullable<ListMixedCatalogV1ExploreCatalogGetData["query"]> = {
    page: numberParam(params.page, 1),
    page_size: 12,
    q: firstParam(params.q) ?? null,
    sort: sortParam(params.sort),
    category: category ?? null,
    attestation_status: attestation_status ?? null,
    function: frameworkFunction ?? null,
    industry: industry ?? null,
    license_type: license_type ?? null,
    org_size: org_size ?? null,
    sector: sector ?? null,
  };
  const filterActive = {
    category,
    attestation_status,
    function: frameworkFunction,
    industry,
    license_type,
    org_size,
    q: query.q ?? undefined,
    sector,
    sort: query.sort,
  };
  const savedSearchFilters: ExploreSearchFilters = {
    sort: query.sort,
    ...filtersFromExploreSearchParams(params),
  };

  // Saving a search persists per-user state, so only offer it to authenticated
  // viewers. Backend RBAC stays authoritative on the write itself.
  const isAuthenticated = (await getVerifiedSessionHintFromCookies()) !== null;

  const { catalog, unavailable } = await loadExploreCatalog(query);

  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto w-full max-w-[1600px]">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
          <div className="w-full lg:sticky lg:top-20 lg:w-auto lg:shrink-0 lg:self-start lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto">
            {/* Mobile Filters Accordion */}
            <FilterSidebar 
              active={filterActive} 
              defaultOpen={false} 
              className="block lg:hidden mb-4" 
            />
            
            {/* Desktop Filters Sidebar */}
            <FilterSidebar 
              active={filterActive} 
              defaultOpen={true} 
              className="hidden lg:block lg:w-[5.5rem] open:lg:w-64" 
            />
          </div>
          <section className="flex-1 min-w-0">
            <div className="mb-6 flex items-center justify-between border-b border-border-default pb-4">
              <p className="text-sm font-medium text-foreground-muted">{catalog?.total ?? 0} marketplace items</p>
              
              <div className="flex items-center gap-3">
                <SortMenu active={filterActive} current={query.sort ?? "newest"} />
              </div>
            </div>
            {isAuthenticated ? (
              <div className="mb-6">
                <ExploreSaveSearchAction filters={savedSearchFilters} />
              </div>
            ) : null}

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
                {catalog.items.map((item: ExploreCatalogResponse["items"][number]) =>
                  "bundle_price" in item ? (
                    <CollectionCard collection={item} key={item.id} />
                  ) : (
                    <FrameworkCard framework={item} key={item.id} />
                  ),
                )}
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
