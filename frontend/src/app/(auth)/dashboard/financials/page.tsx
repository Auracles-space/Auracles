/**
 * Contributor financials dashboard route.
 *
 * Combines earnings metrics and payout request/history tables into a single view.
 */
import { EarningsSummary } from "@/components/modules/financials/earnings-summary";
import { PayoutHistoryTable } from "@/components/modules/financials/payout-history-table";

/**
 * Render Contributor revenue, clearing balances, and payout history.
 */
export default function ContributorFinancialsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Contributor dashboard
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Financials
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Track your earnings, check clearance schedules, and manage payout transfers.
          </p>
        </header>
        <div className="grid gap-8">
          <EarningsSummary />
          <PayoutHistoryTable />
        </div>
      </div>
    </main>
  );
}
