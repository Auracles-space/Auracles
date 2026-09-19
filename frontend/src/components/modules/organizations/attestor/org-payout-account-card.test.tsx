import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";

import {
  listOrgPayoutAccounts,
  replaceOrgPayoutAccount,
  resolveOrgPayoutAccountName,
} from "@/lib/generated/sdk.gen";

import { OrgPayoutAccountCard } from "./org-payout-account-card";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listPayoutBanks: vi.fn(async () => ({
    data: { banks: [{ code: "044", name: "Access Bank" }] },
    error: undefined,
    response: { ok: true },
  })),
  listOrgPayoutAccounts: vi.fn(),
  replaceOrgPayoutAccount: vi.fn(),
  resolveOrgPayoutAccountName: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/form-client")>()),
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

/** One verified Paystack destination, as the list endpoint returns it. */
function connectedAccount(): never {
  return {
    data: {
      payout_accounts: [
        {
          id: "account-1",
          provider: "paystack",
          account_type: "nuban",
          provider_account_ref: "****4321",
          verified_at: "2026-09-19T10:00:00Z",
          is_default: true,
        },
      ],
    },
    error: undefined,
    response: { ok: true },
  } as never;
}

describe("OrgPayoutAccountCard", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names the bank account the organization's earnings are sent to", async () => {
    // Registering was write-only, so an owner who mistyped an account number
    // had nothing anywhere to check it against.
    vi.mocked(listOrgPayoutAccounts).mockResolvedValue(connectedAccount());

    render(<OrgPayoutAccountCard orgId="org-1" isOwner onChange={vi.fn()} />);

    expect(await screen.findByText("****4321")).toBeInTheDocument();
    expect(screen.getByText(/verified/i)).toBeInTheDocument();
  });

  it("replaces the account in one action rather than removing it", async () => {
    // Removal on its own would leave an approved org pointing at an account
    // that no longer exists, so the replacement is registered in the same call.
    vi.mocked(listOrgPayoutAccounts).mockResolvedValue(connectedAccount());
    vi.mocked(replaceOrgPayoutAccount).mockResolvedValue({
      data: {
        provider: "paystack",
        onboarding_url: null,
        account_name: "ATTESTOR ORG LLC",
        payout_account: { id: "account-2" },
      },
      error: undefined,
      response: { ok: true },
    } as never);

    vi.mocked(resolveOrgPayoutAccountName).mockResolvedValue({
      data: { account_name: "ATTESTOR ORG LLC" },
      error: undefined,
      response: { ok: true },
    } as never);
    const onChange = vi.fn();

    render(<OrgPayoutAccountCard orgId="org-1" isOwner onChange={onChange} />);
    fireEvent.click(
      await screen.findByRole("button", { name: /replace this account/i }),
    );
    fireEvent.change(await screen.findByLabelText(/bank/i), {
      target: { value: "044" },
    });
    fireEvent.change(screen.getByLabelText(/account number/i), {
      target: { value: "9876543210" },
    });
    // The holder is named and accepted before the swap is sent.
    fireEvent.click(screen.getByRole("button", { name: /check account/i }));
    fireEvent.click(
      await screen.findByRole("button", { name: /replace bank account/i }),
    );

    await waitFor(() =>
      expect(replaceOrgPayoutAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1", payout_account_id: "account-1" },
          body: {
            account_number: "9876543210",
            bank_code: "044",
            provider: "paystack",
          },
        }),
      ),
    );
    await waitFor(() => expect(onChange).toHaveBeenCalled());
  });

  it("does not offer replacement to a member who does not own the org", async () => {
    // Changing where money lands is an owner action, matching the API.
    vi.mocked(listOrgPayoutAccounts).mockResolvedValue(connectedAccount());

    render(
      <OrgPayoutAccountCard orgId="org-1" isOwner={false} onChange={vi.fn()} />,
    );

    expect(await screen.findByText("****4321")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /replace/i }),
    ).not.toBeInTheDocument();
  });
});
