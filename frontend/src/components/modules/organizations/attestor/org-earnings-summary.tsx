/**
 * Earnings summary cards for an attestor organization.
 *
 * Available balance (with the minimum payout), pending clearance, and gross
 * revenue, each formatted in the currency the earnings response carries.
 *
 * Maps to: FR-FIN-* (organization payouts).
 */
import type { OrgEarningsResponse } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

interface OrgEarningsSummaryProps {
  /** Earnings response whose balances are shown. */
  earnings: OrgEarningsResponse;
}

/**
 * Render the three earnings stat cards for one attestor organization.
 *
 * @param earnings - Earnings response whose balances are shown.
 */
export function OrgEarningsSummary({ earnings }: OrgEarningsSummaryProps) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
      <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
        <p className="text-sm text-foreground-subtle mb-1">Available Balance</p>
        <p className="text-2xl font-bold">
          {formatMoney(earnings.available_balance, earnings.currency)}
        </p>
        <p className="mt-1 text-xs text-foreground-subtle">
          Minimum payout {formatMoney(earnings.minimum_payout, earnings.currency)}
        </p>
      </div>
      <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
        <p className="text-sm text-foreground-subtle mb-1">Pending Clearance</p>
        <p className="text-2xl font-bold">
          {formatMoney(earnings.pending_clearance, earnings.currency)}
        </p>
      </div>
      <div className="p-4 rounded-lg bg-surface-2 border border-border-strong">
        <p className="text-sm text-foreground-subtle mb-1">Gross Revenue</p>
        <p className="text-2xl font-bold">
          {formatMoney(earnings.gross_revenue, earnings.currency)}
        </p>
      </div>
    </div>
  );
}
