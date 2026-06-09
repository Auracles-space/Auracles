/**
 * Contributor earnings route.
 */
import { EarningsSummary } from "@/components/modules/financials/earnings-summary";

/**
 * Render refund-safe Contributor revenue and payout availability.
 */
export default function ContributorEarningsPage() {
  return (
    <main className="min-h-screen bg-background px-4 py-8 text-foreground md:px-8">
      <div className="mx-auto max-w-[1280px]">
        <header className="mb-8">
          <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
            Contributor dashboard
          </p>
          <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
            Earnings
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-foreground-muted">
            Track refund-safe balances, pending clearance, and payout thresholds.
          </p>
        </header>
        <EarningsSummary />
      </div>
    </main>
  );
}
