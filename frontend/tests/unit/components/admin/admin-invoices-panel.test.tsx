/**
 * Admin invoices panel — money formatting.
 *
 * Invoice totals must read through the shared `formatMoney` helper in each
 * invoice's own currency, so the admin console never disagrees with the org
 * billing surfaces about how naira (or any other currency) is written.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AdminInvoicesPanel } from "@/components/modules/admin/admin-invoices-panel";
import { listAdminInvoicesV1AdminInvoicesGet } from "@/lib/generated/sdk.gen";
import { formatMoney } from "@/lib/marketplace/format";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminInvoicesV1AdminInvoicesGet: vi.fn(),
}));

describe("AdminInvoicesPanel", () => {
  it("formats each invoice total with formatMoney in the invoice's currency", async () => {
    vi.mocked(listAdminInvoicesV1AdminInvoicesGet).mockResolvedValue({
      response: { ok: true },
      data: {
        items: [
          {
            invoice_id: "inv-1",
            invoice_number: "AUR-INV-2026-000001",
            buyer_name: "Lagos Clearing House",
            buyer_email: "finance@lagosclearing.example",
            total: "30000.00",
            currency: "NGN",
            doc_type: "sales_invoice",
            issue_date: "2026-08-01T00:00:00Z",
          },
          {
            invoice_id: "inv-2",
            invoice_number: "AUR-INV-2026-000002",
            buyer_name: "Thames Advisory",
            buyer_email: "ap@thamesadvisory.example",
            total: "149.50",
            currency: "USD",
            doc_type: "sales_invoice",
            issue_date: "2026-08-02T00:00:00Z",
          },
        ],
        page: 1,
        page_size: 20,
        total: 2,
      },
    } as never);

    render(<AdminInvoicesPanel />);

    expect(await screen.findByText(formatMoney("30000.00", "NGN"))).toBeInTheDocument();
    expect(screen.getByText(formatMoney("149.50", "USD"))).toBeInTheDocument();
  });
});
