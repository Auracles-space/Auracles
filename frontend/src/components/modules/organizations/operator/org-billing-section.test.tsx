/**
 * Org billing section — invoice list behavior.
 *
 * Pins the download affordance on purchase invoices: settlement issues org
 * purchase invoices automatically, and an org admin must be able to fetch
 * the PDF from the billing list via the browser-navigable, token-authed
 * org invoice route.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listOrgInvoices, listOrgPaymentMethods } from "@/lib/generated/sdk.gen";
import { OrgBillingSection } from "./org-billing-section";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessToken: vi.fn(() => "test-access-token"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve(null)),
}));

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createOrgPaymentMethodSetup: vi.fn(),
  deleteOrgPaymentMethod: vi.fn(),
  listOrgInvoices: vi.fn(),
  listOrgPaymentMethods: vi.fn(),
}));

describe("OrgBillingSection invoices", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.mocked(listOrgPaymentMethods).mockResolvedValue({
      response: { ok: true },
      data: { payment_methods: [] },
    } as never);
    vi.mocked(listOrgInvoices).mockResolvedValue({
      response: { ok: true },
      data: {
        invoices: [
          {
            id: "inv-1",
            invoice_number: "AUR-INV-2026-000001",
            doc_type: "sales_invoice",
            issue_date: "2026-08-01T00:00:00Z",
            currency: "USD",
            total: "149.00",
            source_ref_type: "transaction",
            source_ref_id: "txn-1",
            direction: "purchase",
          },
          {
            id: "inv-2",
            invoice_number: "AUR-ERN-2026-000001",
            doc_type: "earnings_statement",
            issue_date: "2026-08-02T00:00:00Z",
            currency: "USD",
            total: "300.00",
            source_ref_type: "attestation",
            source_ref_id: "att-1",
            direction: "sales",
          },
        ],
      },
    } as never);
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { assign: vi.fn(), origin: "http://localhost:3000" },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
    vi.clearAllMocks();
  });

  it("downloads a purchase invoice through the token-authed org route", async () => {
    render(<OrgBillingSection />);

    const download = await screen.findByRole("button", {
      name: /download invoice AUR-INV-2026-000001/i,
    });
    fireEvent.click(download);

    await waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith(
        expect.stringContaining(
          "/v1/orgs/org-1/financials/purchases/txn-1/invoice?token=",
        ),
      );
    });
  });

  it("offers no purchase-invoice download on sales-direction rows", async () => {
    render(<OrgBillingSection />);

    await screen.findByText("AUR-ERN-2026-000001");
    expect(
      screen.queryByRole("button", {
        name: /download invoice AUR-ERN-2026-000001/i,
      }),
    ).toBeNull();
  });
});
