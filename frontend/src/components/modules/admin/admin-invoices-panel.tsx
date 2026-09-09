"use client";

/**
 * Admin invoice oversight panel.
 *
 * Read-only: administrators list and search issued invoices for financial
 * reconciliation. The internal PDF storage key is never returned by the API.
 * Renders as a table on desktop and stacked cards on mobile.
 *
 * Maps to: admin issued-invoice oversight.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { listAdminInvoicesV1AdminInvoicesGet } from "@/lib/generated/sdk.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import type { AdminInvoicesResponse } from "@/lib/generated/types.gen";
import { CURRENCY_DISPLAY } from "@/lib/marketplace/currency";

/**
 * Format an invoice date for compact admin copy.
 *
 * @param value - ISO timestamp string.
 */
function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(parsed);
}

/**
 * Format a decimal string as a currency amount.
 *
 * @param amount - Decimal string from the API.
 * @param currency - ISO 4217 currency code.
 */
function formatAmount(amount: string, currency: string): string {
  const value = Number(amount);
  if (Number.isNaN(value)) {
    return `${amount} ${currency}`;
  }
  try {
    return new Intl.NumberFormat(undefined, {
      currency,
      currencyDisplay: CURRENCY_DISPLAY,
      style: "currency",
    }).format(value);
  } catch {
    return `${amount} ${currency}`;
  }
}

/**
 * Render the read-only admin issued-invoice directory with search.
 */
export function AdminInvoicesPanel() {
  const [directory, setDirectory] = useState<AdminInvoicesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadInvoices(): Promise<void> {
      configureBrowserClient();
      const result = await listAdminInvoicesV1AdminInvoicesGet({
        headers: getAccessTokenHeaders(),
        query: {
          page: 1,
          page_size: 20,
          query: query.trim() || undefined,
        },
      });

      if (!mounted) {
        return;
      }
      setLoading(false);
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setError(null);
      setDirectory(result.data);
    }

    void loadInvoices();
    return () => {
      mounted = false;
    };
  }, [query]);

  if (loading) {
    return <TableSkeleton />;
  }

  const items = directory?.items ?? [];

  return (
    <section className="grid gap-6">
      <header className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
          Admin invoices
        </p>
        <h2 className="mt-2 font-heading text-3xl font-bold text-foreground">
          Issued invoices
        </h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
          Review issued invoices for reconciliation. Read-only — search by
          invoice number or buyer. Invoice PDFs are never exposed here.
          {directory ? ` ${directory.total} total.` : ""}
        </p>
      </header>

      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm md:max-w-md">
        <label className="grid gap-2 text-sm font-semibold text-foreground">
          Search
          <input
            className="min-h-12 rounded-xl border border-border-default bg-background px-4 text-sm text-foreground outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Invoice number or buyer"
            value={query}
          />
        </label>
      </section>

      {error ? (
        <div className="rounded-2xl border border-error/30 bg-error/10 p-4 text-sm text-error">
          {error}
        </div>
      ) : null}

      {items.length === 0 ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-8 text-center text-sm text-foreground-muted shadow-sm">
          No invoices match this search.
        </div>
      ) : (
        <div className="grid gap-4 md:gap-0 md:divide-y md:divide-border-default/40 md:rounded-2xl md:border md:border-border-default md:bg-surface-1 md:shadow-sm overflow-hidden">
          <div className="hidden md:grid md:grid-cols-[1.2fr_1.4fr_0.9fr_0.8fr_1fr] md:gap-4 md:bg-surface-2/40 md:p-4 md:pl-6 md:pr-6 text-xs font-semibold uppercase tracking-wider text-foreground-muted select-none">
            <div>Invoice</div>
            <div>Buyer</div>
            <div>Total</div>
            <div>Type</div>
            <div className="text-right">Issued</div>
          </div>

          {items.map((item) => (
            <article
              className="
                flex flex-col gap-3 rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm
                md:grid md:grid-cols-[1.2fr_1.4fr_0.9fr_0.8fr_1fr] md:items-center md:gap-4
                md:rounded-none md:border-none md:bg-transparent md:p-4 md:pl-6 md:pr-6 md:shadow-none
                md:hover:bg-surface-2/30 transition-colors
              "
              key={item.invoice_id}
              role="article"
            >
              <p className="font-mono text-sm font-semibold text-foreground md:text-xs">
                {item.invoice_number}
              </p>

              <div className="grid gap-0.5">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Buyer
                </span>
                <p className="text-sm text-foreground md:text-xs">{item.buyer_name}</p>
                <p className="text-xs text-foreground-muted break-all">
                  {item.buyer_email}
                </p>
              </div>

              <div className="text-sm text-foreground md:text-xs">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Total
                </span>
                <span className="font-semibold">
                  {formatAmount(item.total, item.currency)}
                </span>
              </div>

              <div>
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Type
                </span>
                <span className="inline-flex items-center rounded-md border border-border-default bg-surface-2 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-foreground-muted">
                  {item.doc_type}
                </span>
              </div>

              <div className="text-sm text-foreground md:text-right md:text-xs">
                <span className="md:hidden text-xs text-foreground-muted block mb-1 font-semibold uppercase tracking-wider">
                  Issued
                </span>
                {formatDate(item.issue_date)}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
