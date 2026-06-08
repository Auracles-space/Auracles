/**
 * Explore filter sidebar.
 *
 * Generates normal links so public catalog filtering remains SSR-friendly and
 * crawlable while preserving existing search params.
 */
import Link from "next/link";

import { formatLabel } from "@/lib/marketplace/format";

type FilterSidebarProps = {
  active: Record<string, string | undefined>;
};

const filterGroups = [
  {
    key: "category",
    label: "Category",
    values: ["governance", "risk", "operations", "finance"],
  },
  {
    key: "license_type",
    label: "License",
    values: ["single_user", "team", "enterprise"],
  },
  {
    key: "org_size",
    label: "Organization",
    values: ["startup", "sme", "mid_market", "enterprise"],
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
    <aside className="rounded-[8px] border border-border-default bg-surface-2 p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="font-heading text-base font-bold text-foreground">
          Filters
        </h2>
        <Link className="text-sm font-semibold text-accent" href="/explore">
          Clear
        </Link>
      </div>
      <div className="space-y-5">
        {filterGroups.map((group) => (
          <section key={group.key}>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
              {group.label}
            </h3>
            <div className="grid gap-2">
              {group.values.map((value) => {
                const selected = active[group.key] === value;
                return (
                  <Link
                    className={[
                      "rounded-[6px] border px-3 py-2 text-sm transition",
                      selected
                        ? "border-accent bg-accent/10 text-accent"
                        : "border-border-default text-foreground hover:border-border-strong hover:bg-surface-3",
                    ].join(" ")}
                    href={buildExploreFilterHref(active, group.key, value)}
                    key={value}
                  >
                    {formatLabel(value)}
                  </Link>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </aside>
  );
}
