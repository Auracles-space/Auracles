"use client";

/**
 * Organization operator billing section.
 *
 * Starts Stripe SetupIntents for org payment methods and renders invoices.
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
  createOrgPaymentMethodSetup,
  deleteOrgPaymentMethod,
  getOrgPurchaseInvoice,
  listOrgInvoices,
  listOrgPaymentMethods,
} from "@/lib/generated/sdk.gen";
import type { OrgPaymentMethodResponse, OrgInvoiceListItem } from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";
import { useOrganization } from "@/components/modules/organizations/organization-context";

type SetupSession = {
  clientSecret: string;
  setupIntentId: string;
};



/**
 * Render saved payment methods and invoices for Organization operators.
 */
export function OrgBillingSection() {
  const { orgId } = useOrganization();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [methods, setMethods] = useState<OrgPaymentMethodResponse[]>([]);
  const [invoices, setInvoices] = useState<OrgInvoiceListItem[]>([]);
  const [removalTotpCode, setRemovalTotpCode] = useState("");
  const [setupSession, setSetupSession] = useState<SetupSession | null>(null);
  const [setupTotpCode, setSetupTotpCode] = useState("");
  const [submittingSetup, setSubmittingSetup] = useState(false);
  const stripePromise = useMemo(() => getStripeClient(), []);

  useEffect(() => {
    async function load() {
      configureBrowserClient();
      const headers = getAccessTokenHeaders();
      const [methodsResult, invoicesResult] = await Promise.all([
        listOrgPaymentMethods({ headers, path: { org_id: orgId } }),
        listOrgInvoices({ headers, path: { org_id: orgId } }),
      ]);

      if (!methodsResult.response.ok || !methodsResult.data) {
        setError(describeGeneratedError(methodsResult.error));
        setLoading(false);
        return;
      }
      if (!invoicesResult.response.ok || !invoicesResult.data) {
        setError(describeGeneratedError(invoicesResult.error));
        setLoading(false);
        return;
      }

      setMethods(methodsResult.data.payment_methods);
      setInvoices(invoicesResult.data.invoices || []);
      setLoading(false);
    }

    void load();
  }, [orgId]);

  /**
   * Fetch the org purchase invoice URL, then navigate the browser to it.
   *
   * The route lazily issues the PDF and returns a short-lived presigned S3
   * URL. Fetching it with the Authorization header and navigating to the
   * result keeps the access token out of the address bar.
   *
   * @param invoice - The invoice row whose source purchase to bill against.
   */
  async function downloadPurchaseInvoice(invoice: OrgInvoiceListItem) {
    setError(null);
    configureBrowserClient();
    const result = await getOrgPurchaseInvoice({
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, transaction_id: invoice.source_ref_id },
    });

    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    if (result.data?.download_url) {
      window.location.assign(result.data.download_url);
      return;
    }
    // 202: the PDF is still rendering.
    setError("The invoice is being prepared. Try again shortly.");
  }

  async function handleStartSetup() {
    setError(null);
    setSubmittingSetup(true);
    configureBrowserClient();
    const result = await createOrgPaymentMethodSetup({
      body: { totp_code: setupTotpCode },
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId },
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
    const result = await deleteOrgPaymentMethod({
      body: { totp_code: removalTotpCode },
      headers: getAccessTokenHeaders(),
      path: { org_id: orgId, payment_method_id: methodId },
    });

    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }

    setMethods((current) => current.filter((method) => method.id !== methodId));
  }


  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading billing information.</p>;
  }

  return (
    <div className="grid gap-6 p-4 md:p-6">
      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Add payment method
        </h2>
        {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}
        {!setupSession ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <label className="grid gap-2 text-sm font-semibold text-foreground">
              Setup 2FA code
              <input
                className="min-h-[44px] rounded-xl border border-border-default bg-background px-3 text-sm font-medium text-foreground outline-none transition-all focus:border-accent focus:ring-0"
                inputMode="numeric"
                onChange={(event) => setSetupTotpCode(event.target.value)}
                type="text"
                value={setupTotpCode}
                aria-label="Authentication code"
              />
            </label>
            <button
              className="min-h-[44px] self-end rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
              disabled={submittingSetup || setupTotpCode.length < 6}
              onClick={handleStartSetup}
              type="button"
            >
              {submittingSetup ? "Starting setup" : "Add payment method"}
            </button>
          </div>
        ) : (
          <Elements
            options={{ clientSecret: setupSession.clientSecret }}
            stripe={stripePromise}
          >
            <SetupConfirmation setupIntentId={setupSession.setupIntentId} orgId={orgId} />
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
              className="min-h-[44px] rounded-xl border border-border-default bg-background px-3 text-sm font-medium text-foreground outline-none transition-all focus:border-accent focus:ring-0"
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
                    {formatLabel(method.type || "card")} expires{" "}
                    {method.exp_month && method.exp_year
                      ? `${method.exp_month}/${method.exp_year}`
                      : "not available"}
                  </p>
                </div>
                <button
                  aria-label={`Remove card ending ${method.last4 ?? "unknown"}`}
                  className="min-h-[44px] rounded-xl border border-error px-4 text-sm font-semibold text-error outline-none transition-all hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-50"
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

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Invoices
        </h2>
        <div className="mt-5 grid gap-3">
          {invoices.length === 0 ? (
            <p className="text-sm text-foreground-muted">
              No invoices yet.
            </p>
          ) : (
            invoices.map((invoice) => (
              <article
                className="grid gap-3 rounded-xl border border-border-default bg-surface-1 p-5 shadow-[0_1px_2px_rgba(0,0,0,0.02)] transition-colors hover:border-border-strong sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
                key={invoice.id}
              >
                <div>
                  <p className="text-sm font-semibold text-foreground">
                    {invoice.invoice_number}
                  </p>
                  <p className="text-xs text-foreground-muted">
                    {new Date(invoice.issue_date).toLocaleDateString()}
                  </p>
                </div>
                <div className="flex items-center justify-end gap-4">
                  <div className="text-right">
                    <p className="text-sm font-semibold text-foreground">
                      {formatMoney(invoice.total, invoice.currency.toUpperCase())}
                    </p>
                    <p className="text-xs text-foreground-muted capitalize">
                      {invoice.doc_type}
                    </p>
                  </div>
                  {invoice.direction === "purchase" &&
                  invoice.source_ref_type === "transaction" ? (
                    <button
                      aria-label={`Download invoice ${invoice.invoice_number}`}
                      className="inline-flex min-h-11 items-center rounded-control border border-border-strong bg-surface-1 px-4 text-xs font-semibold text-foreground transition hover:bg-surface-2 focus-visible:ring-2 focus-visible:ring-accent"
                      onClick={() => downloadPurchaseInvoice(invoice)}
                      type="button"
                    >
                      Download
                    </button>
                  ) : null}
                </div>
              </article>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

type SetupConfirmationProps = {
  setupIntentId: string;
  orgId: string;
};

/**
 * Confirm a Stripe SetupIntent from mounted Elements.
 *
 * @param props - Provider setup intent id used only for return routing.
 */
function SetupConfirmation({ setupIntentId, orgId }: SetupConfirmationProps) {
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
        return_url: `${window.location.origin}/dashboard/organizations/${orgId}/financials?setup=${setupIntentId}`,
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
        className="min-h-[44px] rounded-xl bg-foreground px-4 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
        disabled={submitting}
        onClick={handleConfirmSetup}
        type="button"
      >
        {submitting ? "Saving card" : "Save payment method"}
      </button>
    </div>
  );
}
