"use client";

/**
 * Operator checkout form for self-serve Framework purchases.
 *
 * The form starts a backend purchase transaction, then hands the returned
 * PaymentIntent client secret to Stripe Elements. Card data remains inside
 * Stripe-hosted fields and is never handled by Auracles components.
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
  createCollectionPurchase,
  createFrameworkPurchase,
  getExploreCollectionDetail,
} from "@/lib/generated/sdk.gen";
import type {
  ExploreCollectionDetail,
  ExploreFrameworkDetail,
  PurchaseRequest,
} from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type CheckoutFormProps = {
  framework: ExploreFrameworkDetail;
};

type CollectionCheckoutFormProps = {
  collection: ExploreCollectionDetail;
};

type CheckoutSession = {
  clientSecret: string;
  transactionId: string;
};

const licenseDescriptions: Record<PurchaseRequest["license_type"], string> = {
  organizational: "For company-wide implementation and shared operating use.",
  single_user: "For one named Operator implementing the Framework.",
  team: "For a delivery team coordinating implementation together.",
};

/**
 * Render an Operator checkout flow for one published Framework.
 *
 * @param props - Framework detail from the marketplace API.
 */
export function CheckoutForm({ framework }: CheckoutFormProps) {
  const availableLicenses = framework.license_types.filter(
    (licenseType): licenseType is PurchaseRequest["license_type"] =>
      licenseType === "single_user" ||
      licenseType === "team" ||
      licenseType === "organizational",
  );
  const [licenseType, setLicenseType] = useState<PurchaseRequest["license_type"]>(
    availableLicenses[0] ?? "single_user",
  );
  const [session, setSession] = useState<CheckoutSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const stripePromise = useMemo(() => getStripeClient(), []);

  async function handleStartCheckout() {
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await createFrameworkPurchase({
      body: { license_type: licenseType },
      headers: getAccessTokenHeaders(),
      path: { framework_id: framework.id },
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSession({
      clientSecret: result.data.client_secret,
      transactionId: result.data.transaction_id,
    });
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Secure checkout
        </p>
        <h2 className="mt-2 font-heading text-2xl font-bold text-foreground">
          License this Framework
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Select a license, then complete payment through Stripe-hosted fields.
        </p>
      </div>

      <fieldset className="mt-6 grid gap-3" disabled={submitting || Boolean(session)}>
        <legend className="sr-only">License type</legend>
        {availableLicenses.map((option) => (
          <label
            className={[
              "block cursor-pointer rounded-xl border p-5 transition-all duration-200",
              licenseType === option
                ? "border-accent bg-accent/5 ring-1 ring-accent shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
                : "border-border-default bg-surface-1 hover:border-border-strong hover:bg-surface-2",
            ].join(" ")}
            key={option}
          >
            <input
              aria-label={formatLabel(option)}
              checked={licenseType === option}
              className="sr-only"
              name="license_type"
              onChange={() => setLicenseType(option)}
              type="radio"
              value={option}
            />
            <span className="flex items-start justify-between gap-4">
              <span>
                <span className="block text-sm font-semibold text-foreground">
                  {formatLabel(option)}
                </span>
                <span className="mt-1 block text-sm leading-6 text-foreground-muted">
                  {licenseDescriptions[option]}
                </span>
              </span>
              <span className="text-sm font-semibold text-foreground">
                {formatMoney(framework.price, framework.currency)}
              </span>
            </span>
          </label>
        ))}
      </fieldset>

      {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}

      {!session ? (
        <button
          className="mt-6 inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting || availableLicenses.length === 0}
          onClick={handleStartCheckout}
          type="button"
        >
          {submitting ? "Preparing checkout" : "Start checkout"}
        </button>
      ) : (
        <div className="mt-6">
          <Elements
            options={{ clientSecret: session.clientSecret }}
            stripe={stripePromise}
          >
            <CheckoutPaymentConfirmation transactionId={session.transactionId} />
          </Elements>
        </div>
      )}
    </section>
  );
}

/**
 * Render an Operator checkout flow for one published Collection bundle.
 *
 * @param props - Collection detail from the marketplace API.
 */
export function CollectionCheckoutForm({
  collection,
}: CollectionCheckoutFormProps) {
  const [displayCollection, setDisplayCollection] = useState(collection);
  const availableLicenses: PurchaseRequest["license_type"][] = [
    "single_user",
    "team",
    "organizational",
  ];
  const [licenseType, setLicenseType] = useState<PurchaseRequest["license_type"]>(
    "single_user",
  );
  const [session, setSession] = useState<CheckoutSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const stripePromise = useMemo(() => getStripeClient(), []);
  const alreadyOwnedCount =
    displayCollection.already_owned_member_ids?.length ?? 0;

  useEffect(() => {
    async function refreshOwnedMembers() {
      configureBrowserClient();
      const result = await getExploreCollectionDetail({
        headers: getAccessTokenHeaders(),
        path: { collection_id: collection.id },
      });
      if (result.response.ok && result.data) {
        setDisplayCollection(result.data);
      }
    }

    void refreshOwnedMembers();
  }, [collection.id]);

  async function handleStartCheckout() {
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await createCollectionPurchase({
      body: { license_type: licenseType },
      headers: getAccessTokenHeaders(),
      path: { collection_id: displayCollection.id },
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setSession({
      clientSecret: result.data.client_secret,
      transactionId: result.data.transaction_id,
    });
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Secure checkout
        </p>
        <h2 className="mt-2 font-heading text-2xl font-bold text-foreground">
          License this Collection
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          Pay the bundle price once and receive licenses for the Frameworks you
          do not already own.
        </p>
      </div>

      <div className="mt-6 grid gap-3 text-sm text-foreground-muted sm:grid-cols-2">
        <div className="rounded-xl border border-border-default bg-surface-2 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-foreground-muted">Includes</p>
          <p className="mt-1 font-semibold text-foreground">{displayCollection.member_count} frameworks</p>
        </div>
        <div className="rounded-xl border border-border-default bg-surface-2 p-4">
          <p className="text-[11px] font-bold uppercase tracking-wider text-foreground-muted">Already own</p>
          <p className="mt-1 font-semibold text-foreground">{alreadyOwnedCount} member{alreadyOwnedCount === 1 ? "" : "s"}</p>
        </div>
        <div className="rounded-xl border border-success/30 bg-success/10 p-4 text-success">
          <p className="text-[11px] font-bold uppercase tracking-wider">Save</p>
          <p className="mt-1 font-bold">
            {formatMoney(
              displayCollection.savings_amount,
              displayCollection.currency,
            )}
          </p>
        </div>
        <div className="rounded-xl border border-accent/20 bg-accent/5 p-4 text-foreground">
          <p className="text-[11px] font-bold uppercase tracking-wider text-accent">Bundle Price</p>
          <p className="mt-1 font-heading text-xl font-bold">
            {formatMoney(
              displayCollection.bundle_price,
              displayCollection.currency,
            )}
          </p>
        </div>
      </div>

      <fieldset className="mt-6 grid gap-3" disabled={submitting || Boolean(session)}>
        <legend className="sr-only">License type</legend>
        {availableLicenses.map((option) => (
          <label
            className={[
              "block cursor-pointer rounded-xl border p-5 transition-all duration-200",
              licenseType === option
                ? "border-accent bg-accent/5 ring-1 ring-accent shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
                : "border-border-default bg-surface-1 hover:border-border-strong hover:bg-surface-2",
            ].join(" ")}
            key={option}
          >
            <input
              aria-label={formatLabel(option)}
              checked={licenseType === option}
              className="sr-only"
              name="license_type"
              onChange={() => setLicenseType(option)}
              type="radio"
              value={option}
            />
            <span className="flex items-start justify-between gap-4">
              <span>
                <span className="block text-sm font-semibold text-foreground">
                  {formatLabel(option)}
                </span>
                <span className="mt-1 block text-sm leading-6 text-foreground-muted">
                  {licenseDescriptions[option]}
                </span>
              </span>
              <span className="text-sm font-semibold text-foreground">
                {formatMoney(
                  displayCollection.bundle_price,
                  displayCollection.currency,
                )}
              </span>
            </span>
          </label>
        ))}
      </fieldset>

      {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}

      {!session ? (
        <button
          className="mt-6 inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting}
          onClick={handleStartCheckout}
          type="button"
        >
          {submitting ? "Preparing checkout" : "Start checkout"}
        </button>
      ) : (
        <div className="mt-6">
          <Elements
            options={{ clientSecret: session.clientSecret }}
            stripe={stripePromise}
          >
            <CheckoutPaymentConfirmation transactionId={session.transactionId} />
          </Elements>
        </div>
      )}
    </section>
  );
}

type CheckoutPaymentConfirmationProps = {
  transactionId: string;
};

/**
 * Confirm an initialized Stripe PaymentIntent from mounted Elements.
 *
 * @param props - Pending purchase transaction identifier for return routing.
 */
function CheckoutPaymentConfirmation({
  transactionId,
}: CheckoutPaymentConfirmationProps) {
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
        return_url: `${window.location.origin}/library?purchase=${transactionId}`,
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
      <button
        className="inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
        disabled={submitting}
        onClick={handleConfirmPayment}
        type="button"
      >
        {submitting ? "Confirming payment" : "Confirm payment"}
      </button>
    </div>
  );
}
