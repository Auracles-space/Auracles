import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PurchaseHistoryTable } from "@/components/modules/financials/purchase-history-table";
import {
  getFrameworkPurchaseInvoice,
  listFrameworkPurchases,
  refundFrameworkPurchase,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getFrameworkPurchaseInvoice: vi.fn(),
  listFrameworkPurchases: vi.fn(),
  refundFrameworkPurchase: vi.fn(),
}));

const purchase = {
  amount: "250.00",
  currency: "USD",
  framework_id: "00000000-0000-4000-8000-000000000013",
  framework_title: "Diligence Control Playbook",
  license_id: "00000000-0000-4000-8000-000000000014",
  license_type: "team",
  provider: "stripe" as const,
  purchased_at: "2026-06-09T00:00:00Z",
  status: "completed",
  transaction_id: "00000000-0000-4000-8000-000000000099",
};

describe("PurchaseHistoryTable", () => {
  beforeEach(() => {
    vi.mocked(getFrameworkPurchaseInvoice).mockReset();
    vi.mocked(listFrameworkPurchases).mockReset();
    vi.mocked(refundFrameworkPurchase).mockReset();
    vi.mocked(listFrameworkPurchases).mockResolvedValue({
      data: { items: [purchase], page: 1, page_size: 25, total: 1 },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
  });

  it("lists purchases and lets Operators request refunds and invoices", async () => {
    vi.mocked(refundFrameworkPurchase).mockResolvedValue({
      data: {
        provider: "stripe",
        refund_id: "re_test_123",
        status: "refunded",
        transaction_id: purchase.transaction_id,
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(getFrameworkPurchaseInvoice).mockResolvedValue({
      data: { status: "generating", transaction_id: purchase.transaction_id },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 202 }),
    });

    render(<PurchaseHistoryTable />);

    expect(await screen.findByText("Diligence Control Playbook")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Refund" }));
    await waitFor(() => {
      expect(refundFrameworkPurchase).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { transaction_id: purchase.transaction_id },
        }),
      );
    });
    expect(await screen.findByText("Refunded")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Invoice" }));
    expect(
      await screen.findByText("Invoice is being prepared."),
    ).toBeInTheDocument();
  });
});
