/**
 * Unit coverage for the admin money-movement oversight panel.
 *
 * Verifies the behaviour the surface exists for: a failed payment shows its
 * normalized cause in the list, switching tabs queries the matching view, the
 * ledger cause filter reaches the API, and stored webhook errors are rendered.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminMoneyPanel } from "@/components/modules/admin/admin-money-panel";
import {
  listAdminAuditLogsV1AdminAuditLogsGet,
  listAdminEscrowsV1AdminEscrowsGet,
  listAdminFinancialEventsV1AdminFinancialEventsGet,
  listAdminTransactionsV1AdminTransactionsGet,
  listAdminWebhookEventsV1AdminWebhookEventsGet,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listAdminTransactionsV1AdminTransactionsGet: vi.fn(),
  listAdminFinancialEventsV1AdminFinancialEventsGet: vi.fn(),
  listAdminEscrowsV1AdminEscrowsGet: vi.fn(),
  listAdminWebhookEventsV1AdminWebhookEventsGet: vi.fn(),
  listAdminAuditLogsV1AdminAuditLogsGet: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://testserver"),
  response: new Response(null, { status: 200 }),
});

const page = <T,>(items: T[]) => ({ items, total: items.length, page: 1, page_size: 20 });

const failedPayment = {
  transaction_id: "11111111-1111-1111-1111-111111111111",
  transaction_type: "purchase",
  status: "failed",
  amount: "500.00",
  currency: "NGN",
  platform_commission: "50.00",
  net_amount: "450.00",
  provider: "paystack",
  provider_ref: "ref_declined_1",
  payer_id: "22222222-2222-2222-2222-222222222222",
  payer_org_id: null,
  payee_id: null,
  payee_org_id: null,
  ref_type: "framework",
  ref_id: null,
  failure_reason_code: "insufficient_funds",
  created_at: "2026-08-11T09:00:00Z",
  updated_at: "2026-08-11T09:05:00Z",
};

describe("AdminMoneyPanel", () => {
  beforeEach(() => {
    vi.mocked(listAdminTransactionsV1AdminTransactionsGet).mockResolvedValue(
      ok(page([failedPayment])) as never,
    );
    vi.mocked(listAdminFinancialEventsV1AdminFinancialEventsGet).mockResolvedValue(
      ok(page([])) as never,
    );
    vi.mocked(listAdminEscrowsV1AdminEscrowsGet).mockResolvedValue(
      ok(page([])) as never,
    );
    vi.mocked(listAdminWebhookEventsV1AdminWebhookEventsGet).mockResolvedValue(
      ok(page([])) as never,
    );
    vi.mocked(listAdminAuditLogsV1AdminAuditLogsGet).mockResolvedValue(
      ok(page([])) as never,
    );
  });

  it("shows why a failed payment failed, not only that it did", async () => {
    render(<AdminMoneyPanel />);

    expect(await screen.findByText("insufficient_funds")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
  });

  it("links each payment to its ledger timeline", async () => {
    render(<AdminMoneyPanel />);

    const link = await screen.findByRole("link");
    expect(link).toHaveAttribute(
      "href",
      "/admin/money/11111111-1111-1111-1111-111111111111",
    );
  });

  it("queries the webhook log and renders its stored delivery error", async () => {
    vi.mocked(listAdminWebhookEventsV1AdminWebhookEventsGet).mockResolvedValue(
      ok(
        page([
          {
            event_id: "33333333-3333-3333-3333-333333333333",
            provider: "stripe",
            provider_event_id: "evt_broken_1",
            event_type: "payment_intent.succeeded",
            status: "failed",
            error: "purchase event missing transaction_id",
            received_at: "2026-08-11T09:00:00Z",
            processed_at: null,
          },
        ]),
      ) as never,
    );
    render(<AdminMoneyPanel />);
    await screen.findByText("insufficient_funds");

    fireEvent.click(screen.getByRole("button", { name: "Webhooks" }));

    expect(
      await screen.findByText("purchase event missing transaction_id"),
    ).toBeInTheDocument();
  });

  it("passes the normalized failure cause to the ledger query", async () => {
    render(<AdminMoneyPanel />);
    await screen.findByText("insufficient_funds");

    fireEvent.click(screen.getByRole("button", { name: "Ledger" }));
    fireEvent.change(await screen.findByPlaceholderText("insufficient_funds"), {
      target: { value: "expired_card" },
    });

    await waitFor(() => {
      expect(
        vi.mocked(listAdminFinancialEventsV1AdminFinancialEventsGet),
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          query: expect.objectContaining({ reason_code: "expired_card" }),
        }),
      );
    });
  });

  it("surfaces a request failure instead of rendering an empty directory", async () => {
    vi.mocked(listAdminTransactionsV1AdminTransactionsGet).mockResolvedValue({
      data: undefined,
      error: { detail: "nope" },
      request: new Request("http://testserver"),
      response: new Response(null, { status: 500 }),
    } as never);

    render(<AdminMoneyPanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The request could not be completed.",
    );
  });
});
