/**
 * Public Explore catalog route.
 *
 * Server-rendered for SEO and fast public browsing. Authenticated action gates
 * are handled only when users attempt write/download actions.
 */
import Link from "next/link";

import { FilterSidebar } from "@/components/modules/explore/filter-sidebar";
import { FrameworkCard } from "@/components/modules/explore/framework-card";
import { SearchPanel } from "@/components/modules/explore/search-panel";
import type {
  ExploreFrameworkCard,
  ExploreSort,
  ListExploreFrameworksData,
} from "@/lib/generated/types.gen";
import { loadExploreCatalog } from "@/lib/marketplace/explore-read-model";

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
 * Render the public marketplace catalog.
 *
 * @param props - Next.js query params.
 */
export default async function ExplorePage({ searchParams }: ExplorePageProps) {
  const params = (await searchParams) ?? {};
  const query: ListExploreFrameworksData["query"] = {
    category: firstParam(params.category) ?? null,
    complexity: firstParam(params.complexity)
      ? Number(firstParam(params.complexity))
      : null,
    function: firstParam(params.function) ?? null,
    industry: firstParam(params.industry) ?? null,
    jurisdiction: firstParam(params.jurisdiction) ?? null,
    license_type: firstParam(params.license_type) ?? null,
    lifecycle_stage: firstParam(params.lifecycle_stage) ?? null,
    org_size: firstParam(params.org_size) ?? null,
    page: numberParam(params.page, 1),
    page_size: 12,
    price_max: firstParam(params.price_max) ?? null,
    price_min: firstParam(params.price_min) ?? null,
    q: firstParam(params.q) ?? null,
    sector: firstParam(params.sector) ?? null,
    sort: (firstParam(params.sort) as ExploreSort | undefined) ?? "newest",
  };

  const { catalog, unavailable } = await loadExploreCatalog(query);

  return (
    <main className="min-h-[calc(100vh-4rem)] bg-background p-6 text-foreground">
      <div className="mx-auto w-full max-w-[1600px]">
        <div className="flex flex-col gap-8 lg:flex-row">
          <div className="w-full lg:w-64 lg:shrink-0">
            <FilterSidebar
              active={{
                category: query.category ?? undefined,
                license_type: query.license_type ?? undefined,
                org_size: query.org_size ?? undefined,
                q: query.q ?? undefined,
                sort: query.sort,
              }}
            />
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
