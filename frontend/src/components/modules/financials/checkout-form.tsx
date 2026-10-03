"use client";

/**
 * Operator checkout form for self-serve Framework purchases.
 *
 * The form starts a backend purchase transaction, then continues however the
 * chosen rail requires: Stripe hands back a PaymentIntent client secret for
 * in-page Elements, Paystack hands back a hosted URL the browser is sent to.
 * Card data stays inside the provider's own fields in both cases and is never
 * handled by Auracles components.
 *
 * The billing country drives that choice, so it is always sent — an omitted
 * country silently settles on Stripe, which fails for Nigerian cards.
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
  getExploreCollectionDetail,
  listMyOrganizationsV1OrgsMineGet,
} from "@/lib/generated/sdk.gen";
import type {
  ExploreCollectionDetail,
  ExploreFrameworkDetail,
  PurchaseRequest,
} from "@/lib/generated/types.gen";
import { CHECKOUT_COUNTRIES, defaultBillingCountry } from "@/lib/marketplace/countries";
import { ListingPrice } from "@/components/ui/listing-price";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";
import {
  type BuyerOption,
  type PurchaseSession,
  buyerOptions,
  startCollectionPurchase,
  startPurchase,
} from "@/lib/marketplace/purchase-context";
import { BuyerContextSelector } from "./buyer-context-selector";

type CheckoutFormProps = {
  framework: ExploreFrameworkDetail;
};

type CollectionCheckoutFormProps = {
  collection: ExploreCollectionDetail;
};

/**
 * A checkout in progress that this component still renders.
 *
 * Only the Stripe rail is ever held in state: a Paystack purchase navigates
 * away instead of mounting anything, so there is no Paystack session to keep.
 */
type StripeCheckoutSession = Extract<PurchaseSession, { kind: "stripe" }>;

const licenseDescriptions: Record<PurchaseRequest["license_type"], string> = {
  organizational: "For company-wide implementation and shared operating use.",
  single_user: "For one named Operator implementing the Framework.",
  team: "For a delivery team coordinating implementation together.",
};

const defaultCheckoutCountry = defaultBillingCountry();

/**
 * Render an Operator checkout flow for one published Framework.
 *
 * @param props - Framework detail from the marketplace API.
 */
export function CheckoutForm({ framework }: CheckoutFormProps) {
  const [session, setSession] = useState<StripeCheckoutSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [country, setCountry] = useState(defaultCheckoutCountry);
  const stripePromise = useMemo(() => getStripeClient(), []);
  const offersOrgTier = framework.license_types.includes("organizational");
  const [buyers, setBuyers] = useState<BuyerOption[]>([{ kind: "self", label: "Myself" }]);
  const [buyer, setBuyer] = useState<BuyerOption>({ kind: "self", label: "Myself" });
  const licenseType: PurchaseRequest["license_type"] =
    buyer.kind === "org" ? "organizational" : "single_user";
  const displayPrice =
    buyer.kind === "org" && framework.org_price != null
      ? framework.org_price
      : framework.price;
  const priceHint =
    buyer.kind === "org" && framework.org_price == null
      ? "Same as single user"
      : null;
  // Decided from the resolved tier price, not from `framework.price`, so a
  // Framework that is free for individuals and paid for Organizations shows
  // the right screen to each buyer.
  const isFree = Number(displayPrice) === 0;

  useEffect(() => {
    async function fetchBuyers() {
      configureBrowserClient();
      const result = await listMyOrganizationsV1OrgsMineGet({ headers: getAccessTokenHeaders() });
      if (result.response.ok && result.data) {
        const opts = buyerOptions(result.data.organizations, offersOrgTier);
        setBuyers(opts);
        setBuyer(opts[0]);
      }
    }
    void fetchBuyers();
  }, [offersOrgTier]);

  // Where this buyer's licence lands, shared by the paid confirmation step and
  // the free grant, which has no confirmation step to route from.
  const libraryPath =
    buyer.kind === "org"
      ? `/dashboard/organizations/${buyer.orgId}/operator/library`
      : "/library";

  async function handleStartCheckout() {
    setError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await startPurchase({
      buyer,
      frameworkId: framework.id,
      licenseType,
      headers: getAccessTokenHeaders(),
      country,
    });

    if ("error" in result) {
      setSubmitting(false);
      setError(describeGeneratedError(result.error));
      return;
    }

    if (result.kind === "paystack") {
      // Paystack owns the next screen. Stay in the submitting state through
      // navigation so the button cannot be pressed twice into two charges.
      window.location.assign(result.authorizationUrl);
      return;
    }

    if (result.kind === "free") {
      // Nothing to pay and nothing to confirm: the licence was granted by the
      // time this responded. Go straight to the Library, staying in the
      // submitting state through navigation so the button cannot be pressed
      // again into an "already licensed" conflict.
      window.location.assign(libraryPath);
      return;
    }

    setSubmitting(false);
    setSession(result);
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          {isFree ? "No charge" : "Secure checkout"}
        </p>
        <h2 className="mt-2 font-heading text-2xl font-bold text-foreground">
          License this Framework
        </h2>
        <p className="mt-2 text-sm leading-6 text-foreground-muted">
          {isFree
            ? "This Framework is offered at no charge. Add it to your library to download the artifacts."
            : "Choose who is purchasing, then complete payment through your provider\u2019s secure hosted fields."}
        </p>
      </div>

      {buyers.length > 1 ? (
        <BuyerContextSelector options={buyers} value={buyer} onChange={setBuyer} />
      ) : null}

      <div className="mt-6 rounded-xl border border-border-default bg-surface-2 p-5">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-foreground">
              {formatLabel(licenseType)}
            </p>
            <p className="mt-1 text-sm leading-6 text-foreground-muted">
              {licenseDescriptions[licenseType]}
            </p>
          </div>
          <div className="text-right">
            <ListingPrice
              className="block text-sm"
              currency={framework.currency}
              price={displayPrice}
            />
            {priceHint ? (
              <p className="mt-1 text-xs uppercase tracking-[0.05em] text-foreground-muted">
                {priceHint}
              </p>
            ) : null}
          </div>
        </div>
      </div>

      {!session && !isFree ? (
        <label className="mt-6 grid gap-2 text-sm font-semibold text-foreground">
          Billing country
          <select
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            disabled={submitting}
            onChange={(event) => setCountry(event.target.value)}
            value={country}
          >
            {CHECKOUT_COUNTRIES.map((option) => (
              <option key={option.code} value={option.code}>
                {option.name}
              </option>
            ))}
          </select>
          <span className="text-xs font-normal leading-5 text-foreground-muted">
            Determines how your payment is processed.
          </span>
        </label>
      ) : null}

      {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}

      {!session ? (
        <button
          className="mt-6 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting}
          onClick={handleStartCheckout}
          type="button"
        >
          {isFree
            ? submitting
              ? "Adding to library"
              : "Add to library"
            : submitting
              ? "Preparing checkout"
              : "Start checkout"}
        </button>
      ) : (
        <div className="mt-6">
          <Elements
            options={{ clientSecret: session.clientSecret }}
            stripe={stripePromise}
          >
            <CheckoutPaymentConfirmation
              successPath={libraryPath}
              transactionId={session.transactionId}
            />
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
  const [session, setSession] = useState<StripeCheckoutSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [country, setCountry] = useState(defaultCheckoutCountry);
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

    const result = await startCollectionPurchase({
      collectionId: displayCollection.id,
      licenseType,
      headers: getAccessTokenHeaders(),
      country,
    });

    if ("error" in result) {
      setSubmitting(false);
      setError(describeGeneratedError(result.error));
      return;
    }

    if (result.kind === "paystack") {
      // Paystack owns the next screen. Stay in the submitting state through
      // navigation so the button cannot be pressed twice into two charges.
      window.location.assign(result.authorizationUrl);
      return;
    }

    if (result.kind === "free") {
      // Nothing to pay and nothing to confirm: the licence was granted by the
      // time this responded. Go straight to the Library, staying in the
      // submitting state through navigation so the button cannot be pressed
      // again into an "already licensed" conflict.
      window.location.assign("/library");
      return;
    }

    setSubmitting(false);
    setSession(result);
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

      {!session ? (
        <label className="mt-6 grid gap-2 text-sm font-semibold text-foreground">
          Billing country
          <select
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            disabled={submitting}
            onChange={(event) => setCountry(event.target.value)}
            value={country}
          >
            {CHECKOUT_COUNTRIES.map((option) => (
              <option key={option.code} value={option.code}>
                {option.name}
              </option>
            ))}
          </select>
          <span className="text-xs font-normal leading-5 text-foreground-muted">
            Determines how your payment is processed.
          </span>
        </label>
      ) : null}

      {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}

      {!session ? (
        <button
          className="mt-6 inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
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
            <CheckoutPaymentConfirmation
              successPath="/library"
              transactionId={session.transactionId}
            />
          </Elements>
        </div>
      )}
    </section>
  );
}

type CheckoutPaymentConfirmationProps = {
  successPath: string;
  transactionId: string;
};

/**
 * Confirm an initialized Stripe PaymentIntent from mounted Elements.
 *
 * @param props - Success redirect path (personal or org library) and the
 *   pending purchase transaction identifier for return routing.
 */
function CheckoutPaymentConfirmation({
  successPath,
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
        return_url: `${window.location.origin}${successPath}?purchase=${transactionId}`,
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
        className="inline-flex min-h-12 w-full items-center justify-center rounded-xl bg-foreground px-4 py-2 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
        disabled={submitting}
        onClick={handleConfirmPayment}
        type="button"
      >
        {submitting ? "Confirming payment" : "Confirm payment"}
      </button>
    </div>
  );
}
