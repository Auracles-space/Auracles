/**
 * Payout request controls for an attestor organization with a linked account.
 *
 * Shows the payout eligibility checklist, the owner-only Request Payout button,
 * the Manage payout account button (Stripe rail only), and the copy explaining
 * why a request is unavailable: not the owner, no balance, or below the minimum
 * payout. The minimum is the same threshold the API enforces, checked here so
 * the org learns why the button is off instead of meeting a refusal after a
 * step-up prompt.
 *
 * Maps to: FR-FIN-* (organization payouts).
 */
import type { OrgEarningsResponse } from "@/lib/generated/types.gen";
import { Button } from "@/components/ui/button";
import { formatMoney } from "@/lib/marketplace/format";

import { PayoutEligibilityChecklist } from "./payout-eligibility-checklist";

interface OrgPayoutRequestControlsProps {
  /** Earnings response, or null when it failed to load. */
  earnings: OrgEarningsResponse | null;
  /** Whether the viewer owns the organization (only owners request payouts). */
  isOwner: boolean;
  /** Whether payouts run on the Paystack (NGN) rail. */
  isPaystackRail: boolean;
  /** Whether a payout action is in flight. */
  isActionLoading: boolean;
  /** Request a payout of the available balance. */
  onRequestPayout: () => void;
  /** Re-open payout account onboarding. */
  onManageAccount: () => void;
}

/**
 * Render eligibility gating and payout request actions.
 *
 * @param props - Earnings, viewer role, rail, and action handlers.
 */
export function OrgPayoutRequestControls({
  earnings,
  isOwner,
  isPaystackRail,
  isActionLoading,
  onRequestPayout,
  onManageAccount,
}: OrgPayoutRequestControlsProps) {
  const availableAmount = Number(earnings?.available_balance ?? "0");
  const minimumAmount = Number(earnings?.minimum_payout ?? "0");
  const hasNoBalance = !(availableAmount > 0);
  const belowMinimum = !hasNoBalance && availableAmount < minimumAmount;
  const eligibility = earnings?.payout_eligibility;
  const notEligible = eligibility ? !eligibility.eligible : false;

  return (
    <div className="grid gap-4">
      {eligibility ? <PayoutEligibilityChecklist eligibility={eligibility} /> : null}
      <div className="flex flex-wrap gap-2">
        {isOwner ? (
          <Button
            onClick={onRequestPayout}
            disabled={isActionLoading || hasNoBalance || belowMinimum || notEligible}
          >
            Request Payout
          </Button>
        ) : null}
        <Button
          className={isPaystackRail ? "hidden" : undefined}
          variant="secondary"
          onClick={onManageAccount}
          disabled={isActionLoading}
        >
          Manage payout account
        </Button>
      </div>
      {!isOwner && (
        <p className="text-sm text-foreground-subtle">
          Only the organization owner can request payouts.
        </p>
      )}
      {hasNoBalance && (
        <p className="text-sm text-foreground-subtle">
          No available balance to payout.
        </p>
      )}
      {belowMinimum && earnings && (
        <p className="text-sm text-foreground-subtle">
          Your available balance is below the minimum payout of{" "}
          {formatMoney(earnings.minimum_payout, earnings.currency)}.
        </p>
      )}
    </div>
  );
}
