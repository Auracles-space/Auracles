"use client";

/**
 * Project list filter bar.
 *
 * Two shapes, because the three tabs are not the same kind of list. The Open
 * feed is a marketplace a Contributor is searching for work in, so it gets
 * text search, a category, a budget floor and an order. Posted and My
 * engagements are one person's own Projects, bounded in active terms by
 * BR-PROJ-004 but accumulating `closed` ones forever — what those need is a way
 * to hide finished work, not a search box over a list they wrote themselves.
 *
 * State lives in the URL; this component only reports changes. It is a separate
 * file because `project-list-shell.tsx` is already the largest in the module.
 *
 * Maps to: FR-PROJ-002.
 */
import { SearchInput } from "@/components/ui/search-input";
import { currencySymbol } from "@/lib/marketplace/currency";
import { FUNCTION_OPTIONS } from "@/lib/marketplace/taxonomy";

/** Statuses a Project can hold, as `project_status_enum` defines them. */
export const PROJECT_STATUS_OPTIONS = [
  { label: "Open", value: "open" },
  { label: "Assigned", value: "assigned" },
  { label: "In progress", value: "in_progress" },
  { label: "Delivered", value: "delivered" },
  { label: "Disputed", value: "disputed" },
  { label: "Closed", value: "closed" },
] as const;

/** Orderings the feed offers. Mirrors the API's `sort` enum. */
export const PROJECT_SORT_OPTIONS = [
  { label: "Newest first", value: "newest" },
  { label: "Highest budget", value: "budget_desc" },
] as const;

/** Orderings the API accepts, narrowed from the options above. */
export type ProjectSort = (typeof PROJECT_SORT_OPTIONS)[number]["value"];

/**
 * Narrow a URL-supplied sort to one the API accepts.
 *
 * Query strings are user input: `?sort=cheapest` would otherwise travel to the
 * API and come back 422, breaking the page on a value someone typed by hand.
 *
 * @param value - Raw `sort` parameter, or null when absent.
 * @returns A valid sort, defaulting to `newest`.
 */
export function projectSortParam(value: string | null): ProjectSort {
  return PROJECT_SORT_OPTIONS.some((option) => option.value === value)
    ? (value as ProjectSort)
    : "newest";
}

/**
 * Narrow a URL-supplied budget floor to something numeric.
 *
 * The input is `type="number"`, but the URL is not, and a non-numeric
 * `budget_at_least` is a 422 rather than an empty result.
 *
 * @param value - Raw `budget_at_least` parameter, or null when absent.
 * @returns The value if it parses as a non-negative number, else undefined.
 */
export function projectBudgetParam(value: string | null): string | undefined {
  if (!value) {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? value : undefined;
}

/** The filter values a Projects listing understands, as URL strings. */
export type ProjectFilterValues = {
  budgetAtLeast: string;
  category: string;
  q: string;
  sort: string;
  status: string;
};

const selectClass =
  "min-h-12 w-full rounded-xl border border-border-default bg-surface-2 px-3 text-sm text-foreground outline-none transition-colors focus-visible:border-accent focus-visible:ring-1 focus-visible:ring-accent";

const labelClass =
  "mb-2 block text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted";

/**
 * Render the filter controls for one Projects tab.
 *
 * @param onChange - Reports one changed key; the parent owns the URL.
 * @param showFeedFilters - True for the Open marketplace feed, false for a
 *   person's own list, which gets the status filter instead.
 * @param values - Current filter values, read from the URL by the parent.
 */
export function ProjectListFilters({
  onChange,
  showFeedFilters,
  values,
}: {
  onChange: (next: Partial<ProjectFilterValues>) => void;
  showFeedFilters: boolean;
  values: ProjectFilterValues;
}) {
  if (!showFeedFilters) {
    return (
      <div className="grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4 sm:max-w-xs">
        <label className="block">
          <span className={labelClass}>Status</span>
          <select
            className={selectClass}
            onChange={(event) => onChange({ status: event.target.value })}
            value={values.status}
          >
            <option value="">Any status</option>
            {PROJECT_STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
    );
  }

  return (
    <div className="grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4 md:grid-cols-2 lg:grid-cols-4">
      <SearchInput
        initialValue={values.q}
        label="Search Projects"
        onSearch={(q) => onChange({ q })}
        placeholder="Procurement, payroll, operating model"
      />
      <label className="block">
        <span className={labelClass}>Category</span>
        <select
          className={selectClass}
          onChange={(event) => onChange({ category: event.target.value })}
          value={values.category}
        >
          <option value="">Any category</option>
          {FUNCTION_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className={labelClass}>Pays at least</span>
        <div className="relative">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-foreground-muted">
            {currencySymbol()}
          </span>
          {/* Reads against the top of a Project's posted range, so a 100–9000
              Project answers "pays at least 1000". */}
          <input
            className={`${selectClass} pl-8`}
            inputMode="decimal"
            min="0"
            onChange={(event) => onChange({ budgetAtLeast: event.target.value })}
            placeholder="Any budget"
            type="number"
            value={values.budgetAtLeast}
          />
        </div>
      </label>
      <label className="block">
        <span className={labelClass}>Sort</span>
        <select
          className={selectClass}
          onChange={(event) => onChange({ sort: event.target.value })}
          value={values.sort}
        >
          {PROJECT_SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
