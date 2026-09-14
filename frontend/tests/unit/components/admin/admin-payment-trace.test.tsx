/**
 * Unit coverage for the admin single-payment trace.
 *
 * Verifies the trace renders every ledger step in recorded order with its
 * cause attached — the reason the view exists, since the status column keeps
 * only the final value — and that a missing payment reports rather than
 * rendering an empty timeline as if nothing had happened.
 */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminPaymentTrace } from "@/components/modules/admin/admin-payment-trace";
import { getAdminTransactionDetailV1AdminTransactionsTransactionIdGet } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "Transaction not found."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getAdminTransactionDetailV1AdminTransactionsTransactionIdGet: vi.fn(),
}));

const TRANSACTION_ID = "11111111-1111-1111-1111-111111111111";

const detail = {
  transaction: {
    transaction_id: TRANSACTION_ID,
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
  },
  escrows: [],
  timeline: [
    {
      event_id: "44444444-4444-4444-4444-444444444444",
      entity_type: "transaction",
      entity_id: TRANSACTION_ID,
      event_type: "purchase_initiated",
      from_status: null,
      to_status: "pending",
      amount: "500.00",
      currency: "NGN",
      provider: "paystack",
      provider_ref: "ref_declined_1",
      reason_code: null,
      reason_message: null,
      actor_id: null,
      occurred_at: "2026-08-11T09:00:00Z",
      metadata: {},
    },
    {
      event_id: "55555555-5555-5555-5555-555555555555",
      entity_type: "transaction",
      entity_id: TRANSACTION_ID,
      event_type: "purchase_failed",
      from_status: "pending",
      to_status: "failed",
      amount: "500.00",
      currency: "NGN",
      provider: "paystack",
      provider_ref: "ref_declined_1",
      reason_code: "insufficient_funds",
      reason_message: "Declined by issuing bank.",
      actor_id: null,
      occurred_at: "2026-08-11T09:05:00Z",
      metadata: {},
    },
  ],
};

describe("AdminPaymentTrace", () => {
  beforeEach(() => {
    vi.mocked(
      getAdminTransactionDetailV1AdminTransactionsTransactionIdGet,
    ).mockResolvedValue({
      data: detail,
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    } as never);
  });

  it("renders every ledger step in recorded order", async () => {
    render(<AdminPaymentTrace transactionId={TRANSACTION_ID} />);

    const steps = await screen.findAllByRole("listitem");
    expect(steps[0]).toHaveTextContent("purchase_initiated");
    expect(steps[1]).toHaveTextContent("purchase_failed");
  });

  it("attaches the normalized cause and message to the failing step", async () => {
    render(<AdminPaymentTrace transactionId={TRANSACTION_ID} />);

    expect(await screen.findByText("Declined by issuing bank.")).toBeInTheDocument();
    expect(screen.getAllByText("insufficient_funds").length).toBeGreaterThan(0);
  });

  it("reports a missing payment instead of an empty timeline", async () => {
    vi.mocked(
      getAdminTransactionDetailV1AdminTransactionsTransactionIdGet,
    ).mockResolvedValue({
      data: undefined,
      error: { detail: "Transaction not found." },
      request: new Request("http://testserver"),
      response: new Response(null, { status: 404 }),
    } as never);

    render(<AdminPaymentTrace transactionId={TRANSACTION_ID} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Transaction not found.",
    );
  });

  const PAYER_ORG = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
  
  it("names the payer organization with a link and falls back to the payee user", async () => {
    vi.mocked(
      getAdminTransactionDetailV1AdminTransactionsTransactionIdGet,
    ).mockResolvedValue({
      data: {
        ...detail,
        transaction: {
          ...detail.transaction,
          payer_org_id: PAYER_ORG,
          payer_org_name: "Lagos Clearing House",
          payee_id: "66666666-6666-6666-6666-666666666666",
        },
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    } as never);

    render(<AdminPaymentTrace transactionId={TRANSACTION_ID} />);

    const payer = await screen.findByRole("link", { name: "Lagos Clearing House" });
    expect(payer).toHaveAttribute("href", `/admin/organizations/${PAYER_ORG}`);
    expect(screen.getByText("66666666")).toBeInTheDocument();
  });
});
