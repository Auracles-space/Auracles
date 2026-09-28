/**
 * Public demand map.
 *
 * What Operators searched for on Explore and did not find. Public by decision:
 * a visitor who can see proven unmet demand has a concrete reason to join and
 * serve it, which a gated page can never give them.
 *
 * Every number here is a count of distinct searchers that already cleared the
 * aggregation floor in its own month. No raw query is ever shown — only terms
 * and filter combinations — so the page describes a market, never a person.
 *
 * Maps to: FR-SRCH (search), FR-EXP (discovery).
 */
import type { DemandMapResponse } from "@/lib/generated/types.gen";
import { formatLabel, formatShortDate } from "@/lib/marketplace/format";

type DemandMapProps = {
  /** Loaded demand, or null when the API could not be reached. */
  demand: DemandMapResponse | null;
};

/**
 * Render one filter combination the way an Operator would say it.
 *
 * @param filters - Raw filter keys and values from the API.
 */
function describeFilters(filters: Record<string, string>): string {
  return Object.entries(filters)
    .map(([, value]) => formatLabel(value))
    .join(" · ");
}

/**
 * A single demand row: what was wanted, and how many people wanted it.
 */
function DemandRow({ label, count }: { label: string; count: number }) {
  return (
    <li className="flex items-center justify-between gap-4 rounded-xl border border-border-default bg-surface-2 px-4 py-3">
      <span className="min-w-0 break-words text-sm font-medium text-foreground">
        {label}
      </span>
      <span className="shrink-0 font-heading text-lg font-bold tabular-nums text-accent">
        {count}
      </span>
    </li>
  );
}

/**
 * Render unmet marketplace demand for a public page.
 *
 * @param demand - Loaded demand, or null when the API was unavailable.
 */
export function DemandMap({ demand }: DemandMapProps) {
  if (demand === null) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
        <p className="text-sm text-foreground-muted">
          Demand could not be loaded right now. Please try again shortly.
        </p>
      </div>
    );
  }

  const isEmpty = demand.terms.length === 0 && demand.filters.length === 0;

  return (
    <div className="space-y-4 md:space-y-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
        <h1 className="font-heading text-2xl font-semibold tracking-[-0.02em] text-foreground md:text-3xl">
          What the market is asking for
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-foreground-muted">
          Searches on Auracles that returned nothing, since{" "}
          {formatShortDate(demand.period_from)}. Each number counts the distinct
          people who looked. Only what at least {demand.min_searchers} people
          searched for is shown, so quieter demand is not listed here.
        </p>
      </header>

      {isEmpty ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
          <h2 className="font-heading text-base font-semibold text-foreground">
            Nothing to report yet
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-foreground-muted">
            Either the catalogue is answering what people search for, or not
            enough people have searched for the same thing yet.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 md:gap-6">
          {demand.terms.length > 0 ? (
            <section className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
              <h2 className="font-heading text-base font-semibold text-foreground">
                Most searched terms
              </h2>
              <p className="mt-1 text-xs text-foreground-subtle">
                Words people used when nothing came back
              </p>
              <ul className="mt-4 space-y-2">
                {demand.terms.map((row) => (
                  <DemandRow
                    count={row.searcher_count}
                    key={row.term}
                    label={row.term}
                  />
                ))}
              </ul>
            </section>
          ) : null}

          {demand.filters.length > 0 ? (
            <section className="rounded-2xl border border-border-default bg-surface-1 p-4 shadow-sm md:p-6">
              <h2 className="font-heading text-base font-semibold text-foreground">
                Unserved segments
              </h2>
              <p className="mt-1 text-xs text-foreground-subtle">
                Combinations of sector, industry and jurisdiction with no match
              </p>
              <ul className="mt-4 space-y-2">
                {demand.filters.map((row) => (
                  <DemandRow
                    count={row.searcher_count}
                    key={JSON.stringify(row.filters)}
                    label={describeFilters(row.filters)}
                  />
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      )}
    </div>
  );
}
