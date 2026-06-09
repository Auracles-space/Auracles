import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PayoutAccountConnect } from "@/components/modules/financials/payout-account-connect";
import {
  listPayoutAccounts,
  onboardPayoutAccount,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request could not be completed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listPayoutAccounts: vi.fn(),
  onboardPayoutAccount: vi.fn(),
}));

const originalLocation = window.location;

describe("PayoutAccountConnect", () => {
  beforeEach(() => {
    vi.mocked(listPayoutAccounts).mockReset();
    vi.mocked(onboardPayoutAccount).mockReset();
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
});
