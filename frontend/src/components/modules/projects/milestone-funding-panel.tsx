"use client";

/**
 * Stripe payment panel for funding a Project Milestone into escrow.
 *
 * The backend `fund_milestone` call returns a PaymentIntent client secret; this
 * panel hands it to Stripe Elements so the Operator can complete payment. Card
 * data stays inside Stripe-hosted fields. On success Stripe redirects to the
 * project with `?funded=<txn>`, where the escrow webhook will have funded the
 * Milestone.
 *
 * Maps to: FR-PROJ-007, FR-FIN-005.
 */
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { useMemo, useState } from "react";

import { getStripeClient } from "@/lib/financials/stripe-client";

type MilestoneFundingPanelProps = {
  /** PaymentIntent client secret from the fund-milestone response. */
  clientSecret: string;
  /** Pending escrow transaction id, used for return routing. */
  transactionId: string;
  /** Project id the Milestone belongs to. */
  projectId: string;
  /** Milestone id being funded, echoed back so the return page can poll it. */
  milestoneId: string;
  /** Dismiss the panel without paying. */
  onCancel: () => void;
};

/**
 * Render the Stripe Elements wrapper for one Milestone funding session.
 */
export function MilestoneFundingPanel({
  clientSecret,
  transactionId,
  projectId,
  milestoneId,
  onCancel,
}: MilestoneFundingPanelProps) {
  const stripePromise = useMemo(() => getStripeClient(), []);
  return (
    <div className="mt-3 rounded-xl border border-border-default bg-surface-1 p-4">
      <p className="text-sm font-semibold text-foreground">Fund this milestone</p>
      <p className="mt-1 text-xs text-foreground-muted">
        Payment is held in escrow and released when you approve the deliverable.
      </p>
      <div className="mt-4">
        <Elements options={{ clientSecret }} stripe={stripePromise}>
          <MilestonePaymentConfirmation
            milestoneId={milestoneId}
            onCancel={onCancel}
            projectId={projectId}
            transactionId={transactionId}
          />
        </Elements>
      </div>
    </div>
  );
}

type MilestonePaymentConfirmationProps = {
  transactionId: string;
  projectId: string;
  milestoneId: string;
  onCancel: () => void;
};

/**
 * Confirm the mounted Milestone PaymentIntent and route back to the project.
 */
function MilestonePaymentConfirmation({
  transactionId,
  projectId,
  milestoneId,
  onCancel,
}: MilestonePaymentConfirmationProps) {
  const stripe = useStripe();
  const elements = useElements();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleConfirmPayment() {
    if (!stripe || !elements) {
      setError("Payment form is still loading.");
      return;
    }
    setError(null);
    setSubmitting(true);
    const result = await stripe.confirmPayment({
      elements,
      confirmParams: {
        return_url: `${window.location.origin}/projects/${projectId}?funded=${transactionId}&funded_milestone=${milestoneId}`,
      },
    });
    setSubmitting(false);
    if (result.error) {
      setError(result.error.message ?? "Payment could not be confirmed.");
    }
  }

  return (
    <div className="grid gap-4">
      <PaymentElement />
      {error ? <p className="text-sm text-error">{error}</p> : null}
      <div className="flex flex-wrap gap-3">
        <button
          className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting}
          onClick={() => void handleConfirmPayment()}
          type="button"
        >
          {submitting ? "Confirming payment" : "Pay and fund milestone"}
        </button>
        <button
          className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
          disabled={submitting}
          onClick={onCancel}
          type="button"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
