"use client";

/**
 * Partner-side checkout demo.
 *
 * A self-contained reference of the buyer experience a Partner builds on their
 * own site using the Partner API. It calls the partner purchase endpoint with
 * an `X-API-Key` (no Auracles login), then mounts Stripe Elements with the
 * returned PaymentIntent client secret so a buyer can pay by card. This is a
 * sample/integration harness, not part of the authenticated app.
 */
import {
  Elements,
  PaymentElement,
  useElements,
  useStripe,
} from "@stripe/react-stripe-js";
import { useMemo, useState } from "react";

import { getStripeClient } from "@/lib/financials/stripe-client";
import { PLATFORM_CURRENCY } from "@/lib/marketplace/currency";
import { formatMoney } from "@/lib/marketplace/format";

const PARTNER_API_BASE = `${
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
}/v1/partner`;

type LicenseType = "single_user" | "team" | "organizational";

type FrameworkPreview = {
  title: string;
  price: string;
  currency: string;
};

type CheckoutSession = {
  clientSecret: string;
  transactionId: string;
};

/**
 * Render the buyer card form once a PaymentIntent client secret exists.
 *
 * @param props.transactionId - Pending purchase id, used for the return URL.
 */
function PartnerPaymentForm({ transactionId }: { transactionId: string }) {
  const stripe = useStripe();
  const elements = useElements();
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleConfirm() {
    if (!stripe || !elements) {
      setError("Payment form is still loading.");
      return;
    }
    setError(null);
    setSubmitting(true);
    const result = await stripe.confirmPayment({
      elements,
      confirmParams: {
        return_url: `${window.location.origin}/partner-demo?paid=${transactionId}`,
      },
    });
    setSubmitting(false);
    if (result.error) {
      setError(result.error.message ?? "Payment could not be confirmed.");
    }
  }

  return (
    <div className="grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4">
      <PaymentElement />
      {error ? <p className="text-sm text-error">{error}</p> : null}
      <button
        className="inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
        disabled={submitting}
        onClick={() => void handleConfirm()}
        type="button"
      >
        {submitting ? "Processing payment…" : "Pay now"}
      </button>
      <p className="text-center text-xs text-foreground-muted">
        Test card 4242 4242 4242 4242 · any future date · any CVC/ZIP
      </p>
    </div>
  );
}

/**
 * Render a mock Partner storefront that drives a Partner API purchase.
 */
export function PartnerCheckoutDemo() {
  const [apiKey, setApiKey] = useState("");
  const [frameworkId, setFrameworkId] = useState("");
  const [buyerEmail, setBuyerEmail] = useState("buyer@example.com");
  const [licenseType, setLicenseType] = useState<LicenseType>("single_user");
  const [preview, setPreview] = useState<FrameworkPreview | null>(null);
  const [session, setSession] = useState<CheckoutSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const stripePromise = useMemo(() => getStripeClient(), []);
  const paid = useMemo(() => {
    if (typeof window === "undefined") {
      return null;
    }
    return new URLSearchParams(window.location.search).get("paid");
  }, []);

  /** Headers for an unauthenticated Partner API call. */
  function partnerHeaders(): HeadersInit {
    return { "X-API-Key": apiKey.trim(), "Content-Type": "application/json" };
  }

  async function loadFramework() {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `${PARTNER_API_BASE}/catalog/${frameworkId.trim()}`,
        { headers: partnerHeaders() },
      );
      if (!res.ok) {
        setError(`Could not load framework (${res.status}).`);
        return;
      }
      const data = await res.json();
      setPreview({
        title: data.title,
        price: data.price,
        currency: data.currency ?? PLATFORM_CURRENCY,
      });
    } catch {
      setError("Network error loading the framework.");
    } finally {
      setBusy(false);
    }
  }

  async function startCheckout() {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch(
        `${PARTNER_API_BASE}/frameworks/${frameworkId.trim()}/purchase`,
        {
          method: "POST",
          headers: partnerHeaders(),
          body: JSON.stringify({
            buyer_email: buyerEmail.trim(),
            license_type: licenseType,
          }),
        },
      );
      if (!res.ok) {
        setError(`Purchase could not start (${res.status}).`);
        return;
      }
      const data = await res.json();
      setSession({
        clientSecret: data.client_secret,
        transactionId: data.transaction_id,
      });
    } catch {
      setError("Network error starting checkout.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex-1 px-5 py-10 md:px-10 md:py-16">
      <div className="mx-auto grid w-full max-w-[1180px] gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(420px,0.8fr)] lg:items-start">
        <section className="rounded-card border border-border-default bg-surface-1 p-5 shadow-bento md:p-8 lg:sticky lg:top-24">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-foreground text-sm font-bold text-background">
              AI
            </span>
            <div>
              <p className="font-heading text-lg font-bold text-foreground">
                Partner storefront
              </p>
              <p className="text-sm text-foreground-muted">
                Powered by Auracles
              </p>
            </div>
          </div>

          <h1 className="mt-8 max-w-xl text-balance font-heading text-3xl font-bold tracking-tight text-foreground md:text-4xl">
            Test a partner-hosted framework checkout.
          </h1>
          <p className="mt-4 max-w-xl text-sm leading-7 text-foreground-muted md:text-base">
            Use a Partner API key and a published framework id to preview the
            buyer flow without requiring an Auracles login.
          </p>

          <div className="mt-8 grid gap-3 border-t border-border-default pt-5 text-sm text-foreground-muted">
            <div className="rounded-xl bg-surface-2 p-3">
              Catalog lookup confirms the framework and price.
            </div>
            <div className="rounded-xl bg-surface-2 p-3">
              Checkout creates a transaction through the Partner API.
            </div>
            <div className="rounded-xl bg-surface-2 p-3">
              Stripe Elements handles card collection and confirmation.
            </div>
          </div>
        </section>

      {paid ? (
        <div className="rounded-card border border-success/30 bg-success/10 p-6 text-center shadow-bento md:p-8">
          <h2 className="font-heading text-2xl font-bold text-success">
            Payment complete
          </h2>
          <p className="mt-2 text-sm text-foreground-muted">
            Transaction <span className="font-mono">{paid}</span>. The buyer now
            has their license; your commission is recorded once the payment
            clears.
          </p>
        </div>
      ) : (
        <section className="rounded-card border border-border-default bg-surface-1 p-5 shadow-bento md:p-8">
          <h2 className="font-heading text-2xl font-bold text-foreground">
            Buy a framework
          </h2>
          <p className="mt-2 text-sm text-foreground-muted">
            Demo of the buyer flow on a Partner&apos;s own site. Enter your
            Partner API key and a framework id, then pay by card.
          </p>

          {!session ? (
            <div className="mt-6 grid gap-4">
              <label className="grid gap-2 text-sm font-semibold text-foreground">
                Partner API key
                <input
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  onChange={(event) => setApiKey(event.target.value)}
                  placeholder="ak_…"
                  value={apiKey}
                />
              </label>
              <label className="grid gap-2 text-sm font-semibold text-foreground">
                Framework id
                <input
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none focus-visible:ring-2 focus-visible:ring-accent"
                  onChange={(event) => setFrameworkId(event.target.value)}
                  placeholder="00000000-0000-0000-0000-000000000000"
                  value={frameworkId}
                />
              </label>

              {preview ? (
                <div className="grid gap-2 rounded-xl border border-border-default bg-surface-2 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                  <span className="font-semibold text-foreground">
                    {preview.title}
                  </span>
                  <span className="font-heading font-bold text-foreground">
                    {formatMoney(preview.price, preview.currency)}
                  </span>
                </div>
              ) : (
                <button
                  className="min-h-12 rounded-xl border border-border-default px-4 text-sm font-semibold text-foreground outline-none transition-colors hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
                  disabled={busy || !apiKey.trim() || !frameworkId.trim()}
                  onClick={() => void loadFramework()}
                  type="button"
                >
                  {busy ? "Loading…" : "Load framework"}
                </button>
              )}

              {preview ? (
                <>
                  <label className="grid gap-2 text-sm font-semibold text-foreground">
                    Buyer email
                    <input
                      className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      onChange={(event) => setBuyerEmail(event.target.value)}
                      type="email"
                      value={buyerEmail}
                    />
                  </label>
                  <label className="grid gap-2 text-sm font-semibold text-foreground">
                    License
                    <select
                      className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-3 font-normal outline-none focus-visible:ring-2 focus-visible:ring-accent"
                      onChange={(event) =>
                        setLicenseType(event.target.value as LicenseType)
                      }
                      value={licenseType}
                    >
                      <option value="single_user">Single user</option>
                      <option value="team">Team</option>
                      <option value="organizational">Organizational</option>
                    </select>
                  </label>
                  <button
                    className="min-h-12 rounded-xl bg-foreground px-4 text-sm font-semibold text-background outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-60"
                    disabled={busy || !buyerEmail.trim()}
                    onClick={() => void startCheckout()}
                    type="button"
                  >
                    {busy ? "Preparing…" : "Continue to payment"}
                  </button>
                </>
              ) : null}

              {error ? <p className="text-sm text-error">{error}</p> : null}
            </div>
          ) : (
            <div className="mt-6">
              <Elements
                options={{ clientSecret: session.clientSecret }}
                stripe={stripePromise}
              >
                <PartnerPaymentForm transactionId={session.transactionId} />
              </Elements>
            </div>
          )}
        </section>
      )}
      </div>
    </main>
  );
}
