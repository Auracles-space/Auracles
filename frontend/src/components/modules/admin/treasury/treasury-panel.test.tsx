/**
 * Tests for the admin Treasury panel.
 *
 * Pins what an admin must be able to trust on this page: the platform's money
 * and users' money are shown apart, warnings surface when the balance does not
 * add up or money moved outside Auracles, and only the super-admin can move
 * money, change the bank account, or run the fee backfill.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { TreasuryPanel } from "@/components/modules/admin/treasury/treasury-panel";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import {
  adminAcknowledgeUnrecognizedTransferV1AdminTreasuryUnrecognizedTransfersTransferIdAcknowledgePost as acknowledgeTransfer,
  adminPlatformBankAccountV1AdminTreasuryBankAccountGet as getBankAccount,
  adminPlatformWithdrawalsV1AdminTreasuryWithdrawalsGet as listWithdrawals,
  adminRequestFeeBackfillV1AdminTreasuryFeeBackfillPost as requestFeeBackfill,
  adminRequestPlatformWithdrawalV1AdminTreasuryWithdrawalsPost as requestWithdrawal,
  adminTreasuryStatementV1AdminTreasuryStatementsMonthGet as downloadStatement,
  adminTreasurySummaryV1AdminTreasurySummaryGet as getSummary,
  adminTreasuryBanksV1AdminTreasuryBanksGet as listTreasuryBanks,
  adminUnrecognizedTransfersV1AdminTreasuryUnrecognizedTransfersGet as listTransfers,
  listPayoutBanks,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn((error: { detail?: { message?: string } }) =>
    error?.detail?.message ?? "Request failed.",
  ),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));

vi.mock("@/lib/auth/current-user-session", () => ({
  loadCurrentUserSession: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminTreasurySummaryV1AdminTreasurySummaryGet: vi.fn(),
  adminPlatformBankAccountV1AdminTreasuryBankAccountGet: vi.fn(),
  adminSetPlatformBankAccountV1AdminTreasuryBankAccountPut: vi.fn(),
  adminPlatformWithdrawalsV1AdminTreasuryWithdrawalsGet: vi.fn(),
  adminRequestPlatformWithdrawalV1AdminTreasuryWithdrawalsPost: vi.fn(),
  adminUnrecognizedTransfersV1AdminTreasuryUnrecognizedTransfersGet: vi.fn(),
  adminAcknowledgeUnrecognizedTransferV1AdminTreasuryUnrecognizedTransfersTransferIdAcknowledgePost:
    vi.fn(),
  adminTreasuryStatementV1AdminTreasuryStatementsMonthGet: vi.fn(),
  adminRequestFeeBackfillV1AdminTreasuryFeeBackfillPost: vi.fn(),
  listPayoutBanks: vi.fn(async () => ({
    data: undefined,
    error: { detail: { error_code: "role_required" } },
    response: new Response(null, { status: 403 }),
  })),
  adminTreasuryBanksV1AdminTreasuryBanksGet: vi.fn(async () => ({
    data: { banks: [{ name: "Guaranty Trust Bank", code: "058" }] },
    error: undefined,
    response: new Response(null, { status: 200 }),
  })),
}));

const ok = <T,>(data: T, status = 200) => ({
  data,
  error: undefined,
  request: new Request("http://test.local"),
  response: new Response(null, { status }),
});

const failed = (message: string, status: number) => ({
  data: undefined,
  error: { detail: { error_code: "x", message } },
  request: new Request("http://test.local"),
  response: new Response(null, { status }),
});

const NGN = {
  currency: "NGN",
  withdrawable_here: true,
  owed_to_users: {
    held_escrow: "100000.00",
    contributor_balances: "5500.00",
    org_balances: "135000.00",
    partner_commissions: "500.00",
    total: "241000.00",
  },
  our_money: {
    commission_framework_sales: "1500.00",
    commission_collections: "0.00",
    commission_project_milestones: "0.00",
    commission_attestation_fees: "15000.00",
    provider_fees: "250.00",
    partner_commissions: "500.00",
    platform_withdrawals: "0.00",
    total: "15750.00",
  },
  live_balance: "259000.00",
  withdrawable: "15750.00",
  balance_gap: "2250.00",
  balance_unavailable: false,
};

const USD = {
  ...NGN,
  currency: "USD",
  withdrawable_here: false,
  live_balance: null,
  withdrawable: null,
  balance_gap: null,
};

function summary(overrides: Record<string, unknown> = {}, unreviewed = 0) {
  return ok({
    currencies: [{ ...NGN, ...overrides }, USD],
    live_balance_fetched_at: "2026-09-16T11:00:00Z",
    unreviewed_unrecognized_transfers: unreviewed,
  });
}

const BANK_ACCOUNT = {
  id: "bank-1",
  bank_name: "Guaranty Trust Bank",
  bank_code: "058",
  account_last4: "6789",
  account_name: "AURACLES TECHNOLOGIES LTD",
  usable_from: "2026-09-01T10:00:00Z",
  created_at: "2026-08-31T10:00:00Z",
};

const TRANSFER = {
  id: "transfer-1",
  provider: "paystack",
  reference: "dash-1",
  event_type: "transfer.success",
  amount: "500000.00",
  currency: "NGN",
  recipient_name: "Chidi Okafor",
  recipient_bank: "Kuda Bank",
  recipient_last4: "4321",
  acknowledged_by: null,
  acknowledged_at: null,
  created_at: "2026-09-15T09:00:00Z",
};

function mockPage({
  superadmin = false,
  summaryResult = summary(),
  bankAccount = BANK_ACCOUNT as typeof BANK_ACCOUNT | null,
  transfers = [] as (typeof TRANSFER)[],
} = {}) {
  vi.mocked(loadCurrentUserSession).mockResolvedValue({
    is_superadmin: superadmin,
  } as never);
  vi.mocked(getSummary).mockResolvedValue(summaryResult as never);
  vi.mocked(getBankAccount).mockResolvedValue(ok({ bank_account: bankAccount }) as never);
  vi.mocked(listWithdrawals).mockResolvedValue(
    ok({ withdrawals: [], total: 0, page: 1, page_size: 20 }) as never,
  );
  vi.mocked(listTransfers).mockResolvedValue(
    ok({ transfers, total: transfers.length, page: 1, page_size: 20 }) as never,
  );
}

describe("TreasuryPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the platform's money apart from users' money", async () => {
    mockPage();

    render(<TreasuryPanel />);

    const available = await screen.findByTestId("treasury-withdrawable");
    expect(available).toHaveTextContent("15,750");
    expect(screen.getByTestId("treasury-our-money")).toHaveTextContent("15,750");
    expect(screen.getByTestId("treasury-owed-to-users")).toHaveTextContent("241,000");
    expect(screen.getByTestId("treasury-live-balance")).toHaveTextContent("259,000");
    expect(screen.getByText(/Not withdrawable here/i)).toBeInTheDocument();
  });

  it("keeps money actions away from ordinary admins", async () => {
    mockPage({ superadmin: false });

    render(<TreasuryPanel />);

    await screen.findByTestId("treasury-withdrawable");
    expect(screen.queryByRole("button", { name: /^Withdraw$/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Change account/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Backfill fees/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/Only the super-admin can move money/i)).toBeInTheDocument();
  });

  it("lets the super-admin withdraw no more than is available", async () => {
    mockPage({ superadmin: true });
    vi.mocked(requestWithdrawal).mockResolvedValue(ok({ id: "w-1" }, 202) as never);

    render(<TreasuryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /^Withdraw$/i }));
    const dialog = screen.getByRole("dialog");
    const amount = within(dialog).getByLabelText(/Amount/i);

    fireEvent.change(amount, { target: { value: "20000" } });
    expect(within(dialog).getByText(/more than is available/i)).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: /Withdraw ₦/i }),
    ).toBeDisabled();

    fireEvent.change(amount, { target: { value: "10000" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /Withdraw ₦/i }));

    await waitFor(() =>
      expect(vi.mocked(requestWithdrawal)).toHaveBeenCalledWith(
        expect.objectContaining({ body: { amount: "10000" } }),
      ),
    );
    await waitFor(() => expect(vi.mocked(getSummary)).toHaveBeenCalledTimes(2));
  });

  it("shows the API's reason when a withdrawal is refused", async () => {
    mockPage({ superadmin: true });
    vi.mocked(requestWithdrawal).mockResolvedValue(
      failed("The minimum withdrawal is 10000.00 NGN.", 422) as never,
    );

    render(<TreasuryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /^Withdraw$/i }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText(/Amount/i), {
      target: { value: "5000" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /Withdraw ₦/i }));

    expect(
      await within(dialog).findByText("The minimum withdrawal is 10000.00 NGN."),
    ).toBeInTheDocument();
  });

  it("warns when money is missing, moved outside Auracles, or the account is on hold", async () => {
    mockPage({
      summaryResult: summary({ balance_gap: "-6750.00" }, 1),
      bankAccount: { ...BANK_ACCOUNT, usable_from: "2999-01-01T00:00:00Z" },
    });

    render(<TreasuryPanel />);

    expect(await screen.findByText(/₦6,750 less than the ledger/i)).toBeInTheDocument();
    expect(screen.getByText(/1 transfer not started by Auracles/i)).toBeInTheDocument();
    expect(screen.getByText(/Withdrawals to this account open/i)).toBeInTheDocument();
  });

  it("says the live balance is unavailable instead of guessing", async () => {
    mockPage({
      summaryResult: summary({
        balance_unavailable: true,
        live_balance: null,
        withdrawable: null,
        balance_gap: null,
      }),
    });

    render(<TreasuryPanel />);

    expect(
      await screen.findByText(/Paystack balance is unavailable/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId("treasury-withdrawable")).toHaveTextContent("—");
  });

  it("lets the super-admin mark an unrecognized transfer reviewed", async () => {
    mockPage({ superadmin: true, transfers: [TRANSFER] });
    vi.mocked(acknowledgeTransfer).mockResolvedValue(
      ok({ ...TRANSFER, acknowledged_at: "2026-09-16T12:00:00Z" }) as never,
    );

    render(<TreasuryPanel />);
    expect(await screen.findByText(/Chidi Okafor/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Mark reviewed/i }));

    await waitFor(() =>
      expect(vi.mocked(acknowledgeTransfer)).toHaveBeenCalledWith(
        expect.objectContaining({ path: { transfer_id: "transfer-1" } }),
      ),
    );
  });

  it("downloads a month's statement and queues the fee backfill", async () => {
    mockPage({ superadmin: true });
    vi.mocked(downloadStatement).mockResolvedValue(
      ok(new Blob(["section,line\n"], { type: "text/csv" })) as never,
    );
    vi.mocked(requestFeeBackfill).mockResolvedValue(ok({ status: "queued" }, 202) as never);

    render(<TreasuryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /Download CSV/i }));
    await waitFor(() =>
      expect(vi.mocked(downloadStatement)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { month: expect.stringMatching(/^\d{4}-\d{2}$/) },
        }),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: /Backfill fees/i }));
    expect(await screen.findByText(/Fee backfill queued/i)).toBeInTheDocument();
  });

  it("lists banks from the Treasury API, not the Contributor one", async () => {
    // The Contributor list needs a role the super-admin need not hold; its
    // refusal used to send the super-admin to identity verification.
    mockPage({ superadmin: true });

    render(<TreasuryPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /Change account/i }));

    expect(
      await screen.findByRole("option", { name: "Guaranty Trust Bank" }),
    ).toBeInTheDocument();
    expect(vi.mocked(listTreasuryBanks)).toHaveBeenCalled();
    expect(vi.mocked(listPayoutBanks)).not.toHaveBeenCalled();
  });

  describe("while the bank account is on hold", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    it("counts down beside Withdraw and enables it when the hold ends", async () => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
      const now = Date.now();
      mockPage({
        superadmin: true,
        bankAccount: {
          ...BANK_ACCOUNT,
          usable_from: new Date(now + 90_000).toISOString(),
        },
      });

      render(<TreasuryPanel />);

      const withdraw = await screen.findByRole("button", { name: /^Withdraw$/i });
      expect(withdraw).toBeDisabled();
      expect(screen.getByText(/Withdrawals open in 1m (29|30)s/)).toBeInTheDocument();

      await act(async () => {
        vi.advanceTimersByTime(91_000);
      });

      expect(screen.getByRole("button", { name: /^Withdraw$/i })).toBeEnabled();
      expect(screen.queryByText(/Withdrawals open in/)).not.toBeInTheDocument();
    });
  });
});
