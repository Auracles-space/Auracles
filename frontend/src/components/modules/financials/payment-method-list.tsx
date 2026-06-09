"use client";

/**
 * Operator saved payment methods UI.
 *
 * Starts Stripe SetupIntents and renders Stripe Elements for card collection.
 * Existing card metadata is provider-held; Auracles displays only brand,
 * last-four, and expiry values returned by the backend.
 */
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { useEffect, useMemo, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getStripeClient } from "@/lib/financials/stripe-client";
import {
  createPaymentMethodSetup,
  deletePaymentMethod,
  listPaymentMethods,
} from "@/lib/generated/sdk.gen";
import type { PaymentMethodResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

type SetupSession = {
  clientSecret: string;
  setupIntentId: string;
};

/**
 * Render saved payment methods and setup controls for Operators.
 */
export function PaymentMethodList() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [methods, setMethods] = useState<PaymentMethodResponse[]>([]);
  const [removalTotpCode, setRemovalTotpCode] = useState("");
  const [setupSession, setSetupSession] = useState<SetupSession | null>(null);
  const [setupTotpCode, setSetupTotpCode] = useState("");
  const [submittingSetup, setSubmittingSetup] = useState(false);
  const stripePromise = useMemo(() => getStripeClient(), []);

  useEffect(() => {
    async function loadMethods() {
      configureBrowserClient();
      const result = await listPaymentMethods({
        headers: getAccessTokenHeaders(),
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setMethods(result.data.payment_methods);
      setLoading(false);
    }

    void loadMethods();
  }, []);

  async function handleStartSetup() {
    setError(null);
    setSubmittingSetup(true);
    configureBrowserClient();
    const result = await createPaymentMethodSetup({
      body: { totp_code: setupTotpCode },
      headers: getAccessTokenHeaders(),
    });
    setSubmittingSetup(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSetupSession({
      clientSecret: result.data.client_secret,
      setupIntentId: result.data.setup_intent_id,
    });
  }

  async function handleRemove(methodId: string) {
    setError(null);
    configureBrowserClient();
    const result = await deletePaymentMethod({
      body: { totp_code: removalTotpCode },
      headers: getAccessTokenHeaders(),
      path: { payment_method_id: methodId },
    });

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setMethods((current) => current.filter((method) => method.id !== methodId));
  }

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading payment methods.</p>;
  }

  return (
    <section className="grid gap-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Stripe payment methods
        </p>
        <h1 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Payment methods
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-foreground-muted">
          Add or remove provider-held cards. Changes require two-factor
          confirmation before Stripe setup begins.
        </p>
        {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Add payment method
        </h2>
        {!setupSession ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <label className="grid gap-2 text-sm font-semibold text-foreground">
              Setup 2FA code
              <input
                className="min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm font-medium text-foreground outline-none transition-all focus:border-accent focus:ring-0"
                inputMode="numeric"
                onChange={(event) => setSetupTotpCode(event.target.value)}
                type="text"
                value={setupTotpCode}
              />
            </label>
            <button
              className="min-h-11 self-end rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
              disabled={submittingSetup || setupTotpCode.length < 6}
              onClick={handleStartSetup}
              type="button"
            >
              {submittingSetup ? "Starting setup" : "Start secure setup"}
            </button>
          </div>
        ) : (
          <Elements
            options={{ clientSecret: setupSession.clientSecret }}
            stripe={stripePromise}
          >
            <SetupConfirmation setupIntentId={setupSession.setupIntentId} />
          </Elements>
        )}
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="font-heading text-xl font-bold text-foreground">
              Saved cards
            </h2>
            <p className="mt-1 text-sm text-foreground-muted">
              Only safe card metadata is returned by the backend.
            </p>
          </div>
          <label className="grid gap-2 text-sm font-semibold text-foreground md:w-56">
            Removal 2FA code
            <input
              className="min-h-11 rounded-xl border border-border-default bg-background px-3 text-sm font-medium text-foreground outline-none transition-all focus:border-accent focus:ring-0"
              inputMode="numeric"
              onChange={(event) => setRemovalTotpCode(event.target.value)}
              type="text"
              value={removalTotpCode}
            />
          </label>
        </div>

        <div className="mt-5 grid gap-3">
          {methods.length === 0 ? (
            <p className="text-sm text-foreground-muted">
              No saved payment methods yet.
            </p>
          ) : (
            methods.map((method) => (
              <article
                className="grid gap-3 rounded-xl border border-border-default bg-surface-1 p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-colors hover:border-border-strong sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                key={method.id}
              >
                <div>
                  <h3 className="font-heading text-base font-bold text-foreground">
                    {formatLabel(method.brand)} ending {method.last4 ?? "unknown"}
                  </h3>
                  <p className="mt-1 text-sm text-foreground-muted">
                    {formatLabel(method.type)} expires{" "}
                    {method.exp_month && method.exp_year
                      ? `${method.exp_month}/${method.exp_year}`
                      : "not available"}
                  </p>
                </div>
                <button
                  aria-label={`Remove card ending ${method.last4 ?? "unknown"}`}
                  className="min-h-11 rounded-xl border border-error px-4 text-sm font-semibold text-error outline-none transition-all hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={removalTotpCode.length < 6}
                  onClick={() => handleRemove(method.id)}
                  type="button"
                >
                  Remove
                </button>
              </article>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

type SetupConfirmationProps = {
  setupIntentId: string;
};

/**
 * Confirm a Stripe SetupIntent from mounted Elements.
 *
 * @param props - Provider setup intent id used only for return routing.
 */
function SetupConfirmation({ setupIntentId }: SetupConfirmationProps) {
  const elements = useElements();
  const stripe = useStripe();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleConfirmSetup() {
    if (!stripe || !elements) {
      setError("Payment setup form is still loading.");
      return;
    }
    setError(null);
    setSubmitting(true);
    const result = await stripe.confirmSetup({
      elements,
      confirmParams: {
        return_url: `${window.location.origin}/settings/payment-methods?setup=${setupIntentId}`,
      },
    });
    setSubmitting(false);
    if (result.error) {
      setError(result.error.message ?? "Payment method could not be saved.");
    }
  }

  return (
    <div className="mt-4 grid gap-4">
      <PaymentElement />
      {error ? <p className="text-sm text-error">{error}</p> : null}
      <button
        className="min-h-11 rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
        disabled={submitting}
        onClick={handleConfirmSetup}
        type="button"
      >
        {submitting ? "Saving card" : "Save payment method"}
      </button>
    </div>
  );
}
