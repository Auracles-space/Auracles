"use client";

/**
 * Operator purchase history, invoice, and refund controls.
 *
 * The component uses generated financial endpoints only; refunds and invoice
 * downloads remain backend-authorized and never expose storage keys.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessToken,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  getFrameworkPurchaseInvoice,
  listFrameworkPurchases,
  refundFrameworkPurchase,
} from "@/lib/generated/sdk.gen";
import type { PurchaseHistoryItem } from "@/lib/generated/types.gen";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

/**
 * Render Operator purchase history with refund and invoice actions.
 */
export function PurchaseHistoryTable() {
  const [error, setError] = useState<string | null>(null);
  const [invoiceMessage, setInvoiceMessage] = useState<string | null>(null);
  const [items, setItems] = useState<PurchaseHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [generatingInvoiceId, setGeneratingInvoiceId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    async function loadPurchases() {
      configureBrowserClient();
      const result = await listFrameworkPurchases({
        headers: getAccessTokenHeaders(),
        query: { page: 1, page_size: 25 },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        setLoading(false);
        return;
      }
      setItems(result.data.items);
      setLoading(false);
    }

    void loadPurchases();
  }, []);

  function handleRefunded(transactionId: string) {
    setItems((current) =>
      current.map((item) =>
        item.transaction_id === transactionId
          ? { ...item, status: "refunded" }
          : item,
      ),
    );
  }

  async function handleInvoice(transactionId: string) {
    setGeneratingInvoiceId(transactionId);
    setInvoiceMessage(null);
    setError(null);
    setActionError(null);
    configureBrowserClient();
    try {
      let isDone = false;
      let attempts = 0;
      const maxAttempts = 15; // 30 seconds max (15 * 2 seconds)

      while (!isDone && attempts < maxAttempts) {
        const result = await getFrameworkPurchaseInvoice({
          headers: {
            ...getAccessTokenHeaders(),
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
          },
          path: { transaction_id: transactionId },
          redirect: "manual",
        });

        if (
          result.response.status === 0 ||
          result.response.status === 302 ||
          result.response.type === "opaqueredirect" ||
          result.response.redirected
        ) {
          const token = getAccessToken();
          const invoiceUrl = `${
            process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
          }/v1/financials/purchases/${transactionId}/invoice?token=${encodeURIComponent(token ?? "")}`;
          window.location.assign(invoiceUrl);
          isDone = true;
          setInvoiceMessage(null);
          setGeneratingInvoiceId(null);
          return;
        }

        if (result.response.status === 202 || result.data?.status === "generating") {
          setInvoiceMessage("Invoice is being prepared.");
          await new Promise((resolve) => setTimeout(resolve, 2000));
          attempts += 1;
        } else {
          if (!result.response.ok) {
            setError(describeGeneratedError(result.error));
          }
          isDone = true;
          setGeneratingInvoiceId(null);
          setInvoiceMessage(null);
          return;
        }
      }

      if (attempts >= maxAttempts) {
        setError("Invoice generation timed out. Please try again.");
        setGeneratingInvoiceId(null);
        setInvoiceMessage(null);
      }
    } catch {
      setError("An unexpected error occurred while fetching the invoice.");
      setGeneratingInvoiceId(null);
      setInvoiceMessage(null);
    }
  }

  if (loading) {
    return <p className="text-sm text-foreground-muted">Loading purchases.</p>;
  }

  if (error) {
    return <p className="text-sm text-error">{error}</p>;
  }

  if (items.length === 0) {
    return (
      <div className="rounded-2xl border border-border-default bg-surface-1 p-12 text-center shadow-sm">
        <h2 className="font-heading text-lg font-bold text-foreground">
          No purchases yet
        </h2>
        <p className="mt-2 text-sm text-foreground-muted">
          Completed Framework purchases and invoice actions will appear here.
        </p>
      </div>
    );
  }

  return (
    <section className="rounded-2xl border border-border-default bg-surface-1 shadow-sm overflow-hidden">
      <div className="border-b border-border-default p-4 md:p-5">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Purchase history
        </h2>
        <p className="mt-1 text-sm text-foreground-muted">
          Review purchases, request eligible refunds, and open invoices.
        </p>
      </div>
      {invoiceMessage ? (
        <div className="mx-4 mt-4 flex items-center gap-3.5 rounded-xl border border-border-default bg-surface-2 p-4 text-sm text-foreground md:mx-5 transition-all animate-in fade-in slide-in-from-top-2 duration-300">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
            <svg className="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          </div>
          <div className="flex-1">
            <p className="font-semibold font-heading text-foreground">{invoiceMessage}</p>
            <p className="text-xs text-foreground-muted mt-0.5">We are generating your secure PDF invoice. It will download automatically once ready.</p>
          </div>
        </div>
      ) : null}
      {actionError ? (
        <div className="mx-4 mt-4 flex items-start gap-3.5 rounded-xl border border-error/20 bg-error/10 p-4 text-sm text-error md:mx-5 transition-all animate-in fade-in slide-in-from-top-2 duration-300">
          <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-error/10 text-error mt-0.5">
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" xmlns="http://www.w3.org/2000/svg">
              <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
              <line x1="12" y1="8" x2="12" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <line x1="12" y1="16" x2="12.01" y2="16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </div>
          <div className="flex-1">
            <p className="font-semibold font-heading text-error">Action failed</p>
            <p className="text-xs opacity-90 mt-0.5">{actionError}</p>
          </div>
          <button
            className="text-error opacity-60 hover:opacity-100 transition-opacity"
            onClick={() => setActionError(null)}
            type="button"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      ) : null}
      <div className="grid divide-y divide-border-default">
        {items.map((item) => (
          <article
            className="grid gap-4 p-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:p-5"
            key={item.transaction_id}
          >
            <div>
              <h3 className="font-heading text-base font-bold text-foreground">
                {item.framework_title}
              </h3>
              <p className="mt-1 text-sm text-foreground-muted">
                {formatLabel(item.license_type)} license purchased{" "}
                {new Date(item.purchased_at).toLocaleDateString()}
              </p>
              <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold uppercase tracking-[0.05em]">
                <span className="rounded-md bg-surface-2 border border-border-default px-2 py-1 text-foreground-muted">
                  {formatMoney(item.amount, item.currency)}
                </span>
                <span className="rounded-md bg-surface-2 border border-border-default px-2 py-1 text-foreground-muted">
                  {formatLabel(item.status)}
                </span>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 md:w-[180px]">
              <RefundButton
                item={item}
                onError={setActionError}
                onRefunded={handleRefunded}
              />
              <button
                className="min-h-12 rounded-xl border border-border-default px-3 text-sm font-semibold text-foreground outline-none transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50 flex items-center justify-center gap-2"
                disabled={generatingInvoiceId !== null}
                onClick={() => handleInvoice(item.transaction_id)}
                type="button"
              >
                {generatingInvoiceId === item.transaction_id ? (
                  <>
                    <svg className="animate-spin h-4 w-4 text-foreground" fill="none" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                    </svg>
                    <span>Generating...</span>
                  </>
                ) : (
                  "Invoice"
                )}
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

type RefundButtonProps = {
  item: PurchaseHistoryItem;
  onError: (msg: string | null) => void;
  onRefunded: (transactionId: string) => void;
};

/**
 * Request a self-serve refund for an eligible purchase.
 *
 * @param props - Purchase row and callback for local state update.
 */
export function RefundButton({ item, onRefunded, onError }: RefundButtonProps) {
  const [submitting, setSubmitting] = useState(false);
  const refundable = item.status === "completed";

  async function handleRefund() {
    if (!refundable) {
      return;
    }
    onError(null);
    setSubmitting(true);
    configureBrowserClient();
    const result = await refundFrameworkPurchase({
      headers: getAccessTokenHeaders(),
      path: { transaction_id: item.transaction_id },
    });
    setSubmitting(false);

    if (!result.response.ok || !result.data) {
      onError(describeGeneratedError(result.error));
      return;
    }
    onRefunded(item.transaction_id);
  }

  return (
    <button
      className="min-h-12 w-full rounded-xl border border-border-default px-3 text-sm font-semibold text-foreground outline-none transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50"
      disabled={!refundable || submitting}
      onClick={handleRefund}
      type="button"
    >
      {submitting ? "Refunding" : "Refund"}
    </button>
  );
}
