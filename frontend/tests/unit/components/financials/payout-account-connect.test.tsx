import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PayoutAccountConnect } from "@/components/modules/financials/payout-account-connect";
import {
  listPayoutAccounts,
  listPayoutBanks,
  onboardPayoutAccount,
  resolvePayoutAccountName,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listPayoutAccounts: vi.fn(),
  listPayoutBanks: vi.fn(),
  onboardPayoutAccount: vi.fn(),
  resolvePayoutAccountName: vi.fn(),
}));

const originalLocation = window.location;

describe("PayoutAccountConnect", () => {
  beforeEach(() => {
    vi.mocked(listPayoutAccounts).mockReset();
    vi.mocked(listPayoutBanks).mockReset();
    vi.mocked(onboardPayoutAccount).mockReset();
    vi.mocked(resolvePayoutAccountName).mockReset();
    vi.mocked(resolvePayoutAccountName).mockResolvedValue({
      data: { account_name: "ADA LOVELACE" },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    } as never);
    vi.mocked(listPayoutBanks).mockResolvedValue({
      data: {
        banks: [
          { code: "044", name: "Access Bank" },
          { code: "50211", name: "Kuda Bank" },
        ],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    } as never);
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        assign: vi.fn(),
        origin: "http://localhost:3000",
      },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      value: originalLocation,
    });
  });

  it("lists payout accounts and starts Stripe Connect onboarding", async () => {
    vi.mocked(listPayoutAccounts).mockResolvedValue({
      data: {
        payout_accounts: [
          {
            account_type: "express",
            created_at: "2026-06-09T00:00:00Z",
            id: "00000000-0000-4000-8000-000000000020",
            is_default: true,
            provider: "stripe",
            provider_account_ref: "****acct",
            verified_at: null,
          },
        ],
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(onboardPayoutAccount).mockResolvedValue({
      data: {
        onboarding_url: "https://connect.stripe.test/onboard",
        payout_account: {
          account_type: "express",
          created_at: "2026-06-09T00:00:00Z",
          id: "00000000-0000-4000-8000-000000000021",
          is_default: true,
          provider: "stripe",
          provider_account_ref: "****next",
          verified_at: null,
        },
        provider: "stripe",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<PayoutAccountConnect />);

    expect(await screen.findByText("Stripe Express")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Connect Stripe" }));

    await waitFor(() => {
      expect(onboardPayoutAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            country: "US",
            provider: "stripe",
          }),
        }),
      );
    });
    expect(window.location.assign).toHaveBeenCalledWith(
      "https://connect.stripe.test/onboard",
    );
  });

  it("onboards with the selected country instead of a hardcoded US", async () => {
    vi.mocked(listPayoutAccounts).mockResolvedValue({
      data: { payout_accounts: [] },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(onboardPayoutAccount).mockResolvedValue({
      data: {
        onboarding_url: "https://connect.stripe.test/onboard",
        payout_account: {
          account_type: "express",
          created_at: "2026-06-09T00:00:00Z",
          id: "00000000-0000-4000-8000-000000000022",
          is_default: true,
          provider: "stripe",
          provider_account_ref: "****gb",
          verified_at: null,
        },
        provider: "stripe",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<PayoutAccountConnect />);

    const country = (await screen.findByLabelText(
      /Country/i,
    )) as HTMLSelectElement;
    fireEvent.change(country, { target: { value: "GB" } });

    fireEvent.click(screen.getByRole("button", { name: "Connect Stripe" }));

    await waitFor(() => {
      expect(onboardPayoutAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            country: "GB",
            provider: "stripe",
          }),
        }),
      );
    });
  });

  it("collects bank details and onboards a Nigerian account via Paystack", async () => {
    // Paystack has no hosted onboarding, so the NUBAN details are collected
    // here instead of at the provider. Bank codes come from the API because a
    // hardcoded list goes stale and misaddresses money.
    vi.mocked(listPayoutAccounts).mockResolvedValue({
      data: { payout_accounts: [] },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(onboardPayoutAccount).mockResolvedValue({
      data: {
        account_name: "ADA LOVELACE",
        onboarding_url: null,
        payout_account: {
          account_type: "nuban",
          created_at: "2026-06-09T00:00:00Z",
          id: "00000000-0000-4000-8000-000000000030",
          is_default: true,
          provider: "paystack",
          provider_account_ref: "****9876",
          verified_at: "2026-06-09T00:00:00Z",
        },
        provider: "paystack",
      },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    } as never);

    render(<PayoutAccountConnect />);

    fireEvent.change(await screen.findByLabelText(/Country/i), {
      target: { value: "NG" },
    });

    fireEvent.change(await screen.findByLabelText(/Bank/i), {
      target: { value: "044" },
    });
    fireEvent.change(screen.getByLabelText(/Account number/i), {
      target: { value: "0123456789" },
    });
    // The holder is named and accepted before anything is registered.
    fireEvent.click(screen.getByRole("button", { name: /Check account/i }));
    fireEvent.click(
      await screen.findByRole("button", { name: /Yes, connect this account/i }),
    );

    await waitFor(() => {
      expect(onboardPayoutAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          body: {
            account_number: "0123456789",
            bank_code: "044",
            country: "NG",
            provider: "paystack",
          },
        }),
      );
    });
    // There is no redirect on this rail, so the bank-confirmed name is the
    // only chance to catch a mistyped account number.
    expect(await screen.findByText(/ADA LOVELACE/)).toBeInTheDocument();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("does not ask a Nigerian contributor for Stripe redirect URLs", async () => {
    vi.mocked(listPayoutAccounts).mockResolvedValue({
      data: { payout_accounts: [] },
      error: undefined,
      request: new Request("http://testserver"),
      response: new Response(null, { status: 200 }),
    });

    render(<PayoutAccountConnect />);

    fireEvent.change(await screen.findByLabelText(/Country/i), {
      target: { value: "NG" },
    });

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Connect Stripe" })).toBeNull();
    });
    expect(listPayoutBanks).toHaveBeenCalled();
  });
});
