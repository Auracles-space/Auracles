/**
 * Organization earnings invoice list.
 *
 * Renders the org's issued invoices and earnings statements, each total in the
 * invoice's own currency. Extracted from the org financials tab so that tab
 * stays focused on balances and payouts.
 *
 * Maps to: FR-FIN-* (organization invoices).
 */
import type { OrgInvoiceListItem } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

type OrgInvoiceListProps = {
  /** Invoices returned by the org invoices endpoint. */
  invoices: OrgInvoiceListItem[];
};

/**
 * Render the invoices section, with an empty state when there are none.
 *
 * @param props.invoices - Invoices to list.
 */
export function OrgInvoiceList({ invoices }: OrgInvoiceListProps) {
  return (
    <div>
      <h3 className="text-lg font-medium mb-4">Invoices</h3>
      {invoices.length === 0 ? (
        <p className="text-sm text-foreground-subtle">No invoices found.</p>
      ) : (
        <div className="space-y-4">
          {invoices.map((invoice) => (
            <div
              key={invoice.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-strong bg-surface-2 p-4"
            >
              <div className="min-w-0">
                <p className="break-all font-medium">{invoice.invoice_number}</p>
                <p className="text-sm text-foreground-subtle">
                  {new Date(invoice.issue_date).toLocaleDateString()}
                </p>
              </div>
              <div className="text-right">
                <p className="font-bold">
                  {formatMoney(invoice.total, invoice.currency.toUpperCase())}
                </p>
                <p className="text-xs text-foreground-subtle uppercase">{invoice.doc_type}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
