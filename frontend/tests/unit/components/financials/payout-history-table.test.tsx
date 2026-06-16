import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PayoutHistoryTable } from "@/components/modules/financials/payout-history-table";
import {
  listPayoutAccounts,
  listPayouts,
  requestPayout,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listPayoutAccounts: vi.fn(),
  listPayouts: vi.fn(),
  requestPayout: vi.fn(),
}));

const account = {
  account_type: "express",
  created_at: "2026-06-09T00:00:00Z",
  id: "00000000-0000-4000-8000-000000000020",
  is_default: true,
  provider: "stripe" as const,
  provider_account_ref: "****acct",
  verified_at: "2026-06-09T00:00:00Z",
};

describe("PayoutHistoryTable", () => {
  beforeEach(() => {
    vi.mocked(listPayoutAccounts).mockReset();
    vi.mocked(listPayouts).mockReset();
    vi.mocked(requestPayout).mockReset();
    vi.mocked(listPayoutAccounts).mockResolvedValue({
      data: { payout_accounts: [account] },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(listPayouts).mockResolvedValue({
      data: {
        payouts: [
          {
            amount: "100.00",
            commission_deducted: "15.00",
            completed_at: null,
            currency: "USD",
            id: "00000000-0000-4000-8000-000000000030",
            initiated_at: "2026-06-09T00:00:00Z",
            net_amount: "85.00",
            payout_account_id: account.id,
            provider_ref: "****tr_1",
            status: "pending",
          },
        ],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
  });

  it("lists payouts and submits a TOTP-gated payout request", async () => {
    vi.mocked(requestPayout).mockResolvedValue({
      data: {
        amount: "200.00",
        commission_deducted: "30.00",
        completed_at: null,
        currency: "USD",
        id: "00000000-0000-4000-8000-000000000031",
        initiated_at: "2026-06-09T01:00:00Z",
        net_amount: "170.00",
        payout_account_id: account.id,
        provider_ref: null,
        status: "pending",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 201 }),
    });

    render(<PayoutHistoryTable />);

    expect(await screen.findByText("****tr_1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Request payout" }));
    fireEvent.change(screen.getByLabelText("Amount"), {
      target: { value: "200.00" },
    });
    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit payout request" }));

    await waitFor(() => {
      expect(requestPayout).toHaveBeenCalledWith(
        expect.objectContaining({
          body: {
            amount: "200.00",
            currency: "USD",
            payout_account_id: account.id,
            totp_code: "123456",
          },
        }),
      );
    });
    expect(await screen.findByText("$170")).toBeInTheDocument();
  });

  it("disables the payout submit until amount and a 6-digit code are valid", async () => {
    render(<PayoutHistoryTable />);

    expect(await screen.findByText("****tr_1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Request payout" }));
    const submit = screen.getByRole("button", {
      name: "Submit payout request",
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Amount"), {
      target: { value: "200.00" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123" },
    });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Authenticator code"), {
      target: { value: "123456" },
    });
    expect(submit).toBeEnabled();
  });
});
