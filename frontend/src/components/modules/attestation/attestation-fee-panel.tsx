"use client";

/**
 * Fee payment block for an Attestation request that is still unpaid.
 *
 * The stored transaction's rail decides the screen: Stripe returns a client
 * secret for the in-page PaymentElement, Paystack re-issues a hosted checkout
 * the browser navigates to.
 */
import { useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getAttestationFeePayment } from "@/lib/generated/sdk.gen";
import { AttestationFundingPanel } from "@/components/modules/attestation/attestation-funding-panel";

type AttestationFeePanelProps = {
  /** Attestation whose fee is outstanding. */
  attestationId: string;
  /** Called once the fee is paid, to reload the request. */
  onPaid: () => void;
};

/**
 * Render the pay-the-fee prompt and, on Stripe, the inline payment panel.
 *
 * @param props - Attestation id and the paid callback.
 */
export function AttestationFeePanel({
  attestationId,
  onPaid,
}: AttestationFeePanelProps) {
  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Resume an unpaid fee on its rail: in-page Stripe, or Paystack redirect. */
  async function handleStartPayment() {
    setError(null);
    setBusy(true);
    let redirecting = false;
    try {
      configureBrowserClient();
      const result = await getAttestationFeePayment({
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      if (result.data.provider === "paystack") {
        if (!result.data.authorization_url) {
          setError("Payment could not be started.");
          return;
        }
        redirecting = true;
        window.location.assign(result.data.authorization_url);
        return;
      }
      setClientSecret(result.data.client_secret ?? null);
    } finally {
      // Stay in the busy state through a Paystack navigation so the button
      // cannot be pressed twice into two charges.
      if (!redirecting) {
        setBusy(false);
      }
    }
  }

  if (clientSecret) {
    return (
      <AttestationFundingPanel
        attestationId={attestationId}
        clientSecret={clientSecret}
        onCancel={() => setClientSecret(null)}
        onPaid={() => {
          setClientSecret(null);
          onPaid();
        }}
      />
    );
  }

  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h2 className="font-heading text-xl font-bold text-foreground">
        Pay attestation fee
      </h2>
      <p className="mt-1 text-sm text-foreground-muted">
        This request is waiting for its fee. Pay it to send the request to
        matching attestor organizations.
      </p>
      <button
        className="mt-4 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
        disabled={busy}
        onClick={handleStartPayment}
        type="button"
      >
        {busy ? "Loading…" : "Pay fee"}
      </button>
      {error ? <p className="mt-3 text-sm text-error">{error}</p> : null}
    </div>
  );
}
