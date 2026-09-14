import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgBillingSection } from "@/components/modules/organizations/operator/org-billing-section";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/financials/stripe-client", () => ({
  getStripeClient: vi.fn(() => Promise.resolve(null)),
}));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: "admin" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgPaymentMethods: vi.fn(),
  createOrgPaymentMethodSetup: vi.fn(),
  deleteOrgPaymentMethod: vi.fn(),
  listOrgInvoices: vi.fn(),
  getOrgPurchaseInvoice: vi.fn(),
}));
const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("OrgBillingSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("lists payment methods and invoices for the org", async () => {
    vi.mocked(sdk.listOrgPaymentMethods).mockResolvedValue(ok({ payment_methods: [{ id: "pm1", brand: "visa", last4: "4242" }] }) as never);
    vi.mocked(sdk.listOrgInvoices).mockResolvedValue(ok({ invoices: [{ id: "inv1", invoice_number: "INV-tx1", issue_date: "2026-07-01T00:00:00Z", currency: "usd", doc_type: "invoice", total: "1250.00" }] }) as never);
    render(<OrgBillingSection />);
    await waitFor(() => expect(sdk.listOrgPaymentMethods).toHaveBeenCalledWith(expect.objectContaining({ path: { org_id: "org-1" } })));
    expect(screen.getByText(/4242/)).toBeInTheDocument();
    expect(screen.getByText(/INV-tx1/i)).toBeInTheDocument();
    // The amount column shows the formatted total, not a bare currency code.
    expect(screen.getByText("$1,250")).toBeInTheDocument();
    expect(screen.queryByText("USD")).toBeNull();
  });

  it("requires a TOTP code to start payment-method setup", async () => {
    vi.mocked(sdk.listOrgPaymentMethods).mockResolvedValue(ok({ payment_methods: [] }) as never);
    vi.mocked(sdk.listOrgInvoices).mockResolvedValue(ok({ invoices: [] }) as never);
    vi.mocked(sdk.createOrgPaymentMethodSetup).mockResolvedValue(ok({ client_secret: "seti_cs" }) as never);
    render(<OrgBillingSection />);
    await waitFor(() => expect(sdk.listOrgPaymentMethods).toHaveBeenCalled());
    fireEvent.change(screen.getAllByLabelText(/totp|authentication code|2fa/i)[0], { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: /add payment method/i }));
    await waitFor(() =>
      expect(sdk.createOrgPaymentMethodSetup).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1" }, body: expect.objectContaining({ totp_code: "123456" }) }),
      ),
    );
  });
});
