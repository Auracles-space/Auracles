/**
 * Saved-search filter helpers.
 *
 * Converts public Explore URL params into the backend's saved-search filter
 * shape while excluding transient pagination controls.
 */
import type { ExploreSearchFilters } from "@/lib/generated/types.gen";

type ExploreSearchParamValue = string | string[] | undefined;

const savedSearchFilterKeys = [
  "q",
  "category",
  "sector",
  "industry",
  "function",
  "jurisdiction",
  "complexity",
  "org_size",
  "lifecycle_stage",
  "license_type",
  "price_min",
  "price_max",
  "attestation_status",
  "sort",
] as const;

const numericFilterKeys = new Set(["complexity", "price_min", "price_max"]);

/**
 * Return the first query-string value from a Next.js search-param field.
 *
 * @param value - Search-param value from Next.js.
 * @returns First string value or undefined.
 */
function firstParam(value: ExploreSearchParamValue): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/**
 * Convert current Explore URL params into a persisted saved-search filter blob.
 *
 * @param params - Next.js searchParams object for `/explore`.
 * @returns Saved-search filters excluding page/page_size.
 */
export function filtersFromExploreSearchParams(
  params: Record<string, ExploreSearchParamValue>,
): ExploreSearchFilters {
  const filters: ExploreSearchFilters = {};

  for (const key of savedSearchFilterKeys) {
    const value = firstParam(params[key]);
    if (!value) {
      continue;
    }
    if (numericFilterKeys.has(key)) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) {
        filters[key] = parsed as never;
      }
      continue;
    }
    filters[key] = value as never;
  }

  return filters;
}

/**
 * Convert saved-search filters back into a stable Explore URL.
 *
 * @param filters - Saved-search filter blob returned by the API.
 * @returns Explore route preserving only meaningful filter params.
 */
export function savedSearchFiltersToHref(
  filters: Record<string, unknown>,
): string {
  const params = new URLSearchParams();

  for (const key of savedSearchFilterKeys) {
    const value = filters[key];
    if (value === null || value === undefined || value === "") {
      continue;
    }
    params.set(key, String(value));
  }

  const query = params.toString();
  return query ? `/explore?${query}` : "/explore";
}
