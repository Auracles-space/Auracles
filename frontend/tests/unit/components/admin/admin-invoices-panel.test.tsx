/**
 * Admin invoices panel — money formatting.
 *
 * Invoice totals must read through the shared `formatMoney` helper in each
 * invoice's own currency, so the admin console never disagrees with the org
 * billing surfaces about how naira (or any other currency) is written.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

  const PAYER_ORG = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
  
  function respond(items: unknown[]) {
    vi.mocked(listAdminInvoicesV1AdminInvoicesGet).mockResolvedValue({
      response: { ok: true },
      data: { items, page: 1, page_size: 20, total: items.length },
    } as never);
  }

  const invoice = {
    invoice_id: "inv-3",
    invoice_number: "AUR-INV-2026-000003",
    buyer_name: "Ada Okafor",
    buyer_email: "ada@example.ng",
    total: "12000.00",
    currency: "NGN",
    doc_type: "sales_invoice",
    issue_date: "2026-08-03T00:00:00Z",
  };

  it("names the invoice organization and links it to the org detail page", async () => {
    respond([{ ...invoice, organization_id: PAYER_ORG, organization_name: "Lagos Clearing House" }]);
    render(<AdminInvoicesPanel />);

    const link = await screen.findByRole("link", { name: "Lagos Clearing House" });
    expect(link).toHaveAttribute("href", `/admin/organizations/${PAYER_ORG}`);
  });

  it("shows a dash when the invoice has no organization", async () => {
    respond([{ ...invoice, organization_id: null, organization_name: null }]);
    render(<AdminInvoicesPanel />);

    await screen.findByText("AUR-INV-2026-000003");
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("passes the organization ID filter as org_id", async () => {
    respond([]);
    render(<AdminInvoicesPanel />);

    fireEvent.change(await screen.findByLabelText("Organization ID"), {
      target: { value: PAYER_ORG },
    });

    await waitFor(() =>
      expect(listAdminInvoicesV1AdminInvoicesGet).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: expect.objectContaining({ org_id: PAYER_ORG }) }),
      ),
    );
  });
});
