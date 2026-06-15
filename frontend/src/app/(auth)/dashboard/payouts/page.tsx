/**
 * Contributor payout history route.
 */
import { PayoutHistoryTable } from "@/components/modules/financials/payout-history-table";

/**
 * Render Contributor payout requests and provider transfer statuses.
 */
export default function ContributorPayoutsPage() {
  return (
    <main className="px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Contributor dashboard
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Payouts
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Request Stripe transfers after earnings clear the refund window.
          </p>
        </header>
        <PayoutHistoryTable />
      </div>
    </main>
  );
}
