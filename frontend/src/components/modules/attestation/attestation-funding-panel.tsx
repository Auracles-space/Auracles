"use client";

/**
 * Stripe payment panel for funding an Attestation fee into escrow.
 *
 * The request/fund call returns a PaymentIntent client secret; this panel hands
 * it to Stripe Elements so the requestor can pay the attestation fee. Card data
 * stays inside Stripe-hosted fields. On success the fee is escrowed and the
 * backend advances the request into matching, dispatching offers to attestor
 * orgs.
 *
 * Maps to: FR-ATT (requestor funding), FR-FIN-005.
 */
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { useMemo, useState } from "react";

import { getStripeClient } from "@/lib/financials/stripe-client";

type AttestationFundingPanelProps = {
  /** PaymentIntent client secret from the request/fund response. */
  clientSecret: string;
  /** Attestation id being funded, echoed back on the payment return. */
  attestationId: string;
  /** Called after the fee is confirmed without a redirect. */
  onPaid: () => void;
  /** Dismiss the panel without paying; the request stays pending fee. */
  onCancel: () => void;
};

/**
 * Render the Stripe Elements wrapper for one attestation-fee payment session.
 *
 * @param props - Client secret, attestation id, and lifecycle callbacks.
 */
export function AttestationFundingPanel({
  clientSecret,
  attestationId,
  onPaid,
  onCancel,
}: AttestationFundingPanelProps) {
  const stripePromise = useMemo(() => getStripeClient(), []);
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <h2 className="font-heading text-xl font-bold text-foreground">
        Pay attestation fee
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        The fee is held in escrow and released to the attestor once your request
        is verified. Paying it sends your request to matching attestor
        organizations.
      </p>
      <div className="mt-4">
        <Elements options={{ clientSecret }} stripe={stripePromise}>
          <AttestationPaymentConfirmation
            attestationId={attestationId}
            onCancel={onCancel}
            onPaid={onPaid}
          />
        </Elements>
      </div>
    </div>
  );
}

type AttestationPaymentConfirmationProps = {
  attestationId: string;
  onPaid: () => void;
  onCancel: () => void;
};

/**
 * Confirm the mounted attestation-fee PaymentIntent.
 *
 * Uses `redirect: "if_required"` so card payments resolve inline; only payment
 * methods that mandate a redirect leave the page, returning to the request's
 * detail view.
 *
 * @param props - Attestation id and lifecycle callbacks.
 */
function AttestationPaymentConfirmation({
  attestationId,
  onPaid,
  onCancel,
}: AttestationPaymentConfirmationProps) {
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
        return_url: `${window.location.origin}/attestations/${attestationId}?funded=1`,
      },
      redirect: "if_required",
    });
    setSubmitting(false);
    if (result.error) {
      setError(result.error.message ?? "Payment could not be confirmed.");
      return;
    }
    onPaid();
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
          {submitting ? "Confirming payment" : "Pay fee"}
        </button>
        <button
          className="inline-flex min-h-12 items-center justify-center rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
          disabled={submitting}
          onClick={onCancel}
          type="button"
        >
          Pay later
        </button>
      </div>
    </div>
  );
}
