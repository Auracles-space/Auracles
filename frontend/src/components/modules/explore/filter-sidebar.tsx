/**
 * Explore filter sidebar.
 *
 * Generates normal links so public catalog filtering remains SSR-friendly and
 * crawlable while preserving existing search params.
 */
import Link from "next/link";

import {
  FRAMEWORK_CATEGORY_OPTIONS,
  FUNCTION_OPTIONS,
  INDUSTRY_OPTIONS,
  ORG_SIZE_OPTIONS,
  SECTOR_OPTIONS,
} from "@/lib/marketplace/taxonomy";

type FilterSidebarProps = {
  active: Record<string, string | undefined>;
};

const filterGroups = [
  {
    key: "sector",
    label: "Sector",
    values: SECTOR_OPTIONS,
  },
  {
    key: "industry",
    label: "Industry",
    values: INDUSTRY_OPTIONS,
  },
  {
    key: "function",
    label: "Function",
    values: FUNCTION_OPTIONS,
  },
  {
    key: "category",
    label: "Category",
    values: FRAMEWORK_CATEGORY_OPTIONS,
  },
  {
    key: "attestation_status",
    label: "Attestation",
    values: [
      { label: "Attested", value: "attested" },
      { label: "Conditionally Attested", value: "conditionally_attested" },
      { label: "Pending Acceptance", value: "pending_acceptance" },
      { label: "No Attestation", value: "none" },
    ],
  },
  {
    key: "license_type",
    label: "License",
    values: [
      { label: "Single User", value: "single_user" },
      { label: "Team", value: "team" },
      { label: "Enterprise", value: "enterprise" },
    ],
  },
  {
    key: "org_size",
    label: "Organization",
    values: ORG_SIZE_OPTIONS,
  },
] as const;

/**
 * Build an Explore URL for a single filter change.
 *
 * @param active - Current search params.
 * @param key - Filter key to set.
 * @param value - Filter value to apply.
 * @returns Explore href preserving all other active params.
 */
export function buildExploreFilterHref(
  active: Record<string, string | undefined>,
  key: string,
  value: string,
): string {
  const params = new URLSearchParams();
  for (const [paramKey, paramValue] of Object.entries(active)) {
    if (paramValue) {
      params.set(paramKey, paramValue);
    }
  }
  params.set(key, value);
  params.set("page", "1");
  return `/explore?${params.toString()}`;
}

/**
 * Render catalog filters as SSR links.
 *
 * @param props - Active query param map.
 */
export function FilterSidebar({ active }: FilterSidebarProps) {
  return (
    <aside className="rounded-2xl border border-border-default bg-surface-1 p-5 sm:p-6 shadow-sm">
      <div className="mb-6 flex items-center justify-between gap-3 border-b border-border-default pb-4">
        <h2 className="font-heading text-base font-bold text-foreground flex items-center gap-2">
          <svg className="h-5 w-5 text-foreground-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
          </svg>
          Filters
        </h2>
        {Object.keys(active).length > 0 && (
          <Link className="text-xs font-semibold text-accent transition-colors hover:text-accent/80" href="/explore">
            Clear all
          </Link>
        )}
      </div>
      <div className="flex flex-col gap-6">
        {filterGroups.map((group) => {
          const hasActiveFilter = active[group.key] !== undefined;
          return (
            <details 
              key={group.key} 
              className="group"
              open={hasActiveFilter}
            >
              <summary className="flex cursor-pointer list-none items-center justify-between outline-none [&::-webkit-details-marker]:hidden">
                <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted transition-colors group-hover:text-foreground">
                  {group.label}
                </span>
                <svg className="h-4 w-4 text-foreground-muted transition-transform duration-200 group-open:rotate-180" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </summary>
              <div className="mt-3 grid gap-2">
                {group.values.map((option) => {
                  const value = option.value;
                  const selected = active[group.key] === value;
                  return (
                    <Link
                      className={[
                        "rounded-xl border px-3 py-2 text-sm transition-all duration-200",
                        selected
                          ? "border-accent bg-accent/10 text-accent font-medium shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
                          : "border-transparent text-foreground hover:border-border-default hover:bg-surface-2",
                      ].join(" ")}
                      href={buildExploreFilterHref(active, group.key, value)}
                      key={value}
                    >
                      {option.label}
                    </Link>
                  );
                })}
              </div>
            </details>
          );
        })}
      </div>
    </aside>
  );
}
