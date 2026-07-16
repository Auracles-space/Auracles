import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  onboardOrgPayoutAccount,
  updateOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import { PayoutAccountGate } from "./payout-account-gate";

vi.mock("@/lib/generated/sdk.gen", () => ({
  onboardOrgPayoutAccount: vi.fn(),
  updateOrgAttestorApplication: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
}));

/** A draft application with no payout account linked yet. */
function draftApp(): never {
  return { status: "draft", payout_account_id: null } as never;
}

describe("PayoutAccountGate", () => {
  beforeEach(() => vi.clearAllMocks());

  it("onboards, links the returned account, then redirects to the provider", async () => {
    // The linked account satisfies the approval gate even if the applicant
    // abandons Stripe, so linking must happen before the redirect navigates away.
    vi.mocked(onboardOrgPayoutAccount).mockResolvedValue({
      data: {
        provider: "stripe",
        onboarding_url: "https://connect.stripe.com/setup/abc",
        payout_account: { id: "acct-uuid-1" },
      },
    } as never);
    vi.mocked(updateOrgAttestorApplication).mockResolvedValue({
      data: { payout_account_id: "acct-uuid-1" },
    } as never);
    const assignMock = vi.fn();
    vi.stubGlobal("location", { href: "http://localhost/", assign: assignMock });
    const onChange = vi.fn();

    render(
      <PayoutAccountGate orgId="org-1" application={draftApp()} onChange={onChange} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /set up payout account/i }));

    await waitFor(() => expect(onboardOrgPayoutAccount).toHaveBeenCalled());
    await waitFor(() =>
      expect(updateOrgAttestorApplication).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: { payout_account_id: "acct-uuid-1" },
        }),
      ),
    );
    await waitFor(() =>
      expect(assignMock).toHaveBeenCalledWith("https://connect.stripe.com/setup/abc"),
    );
    vi.unstubAllGlobals();
  });

  it("lets a linked account be managed on the provider without dead-ending", async () => {
    // The gate is satisfied by a linked account; verification is a payout-time
    // concern. The linked state confirms completion but still offers a way back
    // to the hosted flow. Re-onboarding reuses the same account and redirects.
    vi.mocked(onboardOrgPayoutAccount).mockResolvedValue({
      data: {
        provider: "stripe",
        onboarding_url: "https://connect.stripe.com/setup/resume",
        payout_account: { id: "acct-uuid-1" },
      },
    } as never);
    vi.mocked(updateOrgAttestorApplication).mockResolvedValue({
      data: { payout_account_id: "acct-uuid-1" },
    } as never);
    const assignMock = vi.fn();
    vi.stubGlobal("location", { href: "http://localhost/", assign: assignMock });

    render(
      <PayoutAccountGate
        orgId="org-1"
        application={{ status: "draft", payout_account_id: "acct-uuid-1" } as never}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getByText(/payout account linked/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /manage on stripe/i }));

    await waitFor(() => expect(onboardOrgPayoutAccount).toHaveBeenCalled());
    await waitFor(() =>
      expect(assignMock).toHaveBeenCalledWith(
        "https://connect.stripe.com/setup/resume",
      ),
    );
    vi.unstubAllGlobals();
  });

  it("locks the gate once the application is submitted", () => {
    render(
      <PayoutAccountGate
        orgId="org-1"
        application={{ status: "submitted", payout_account_id: null } as never}
        onChange={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /set up payout account/i }),
    ).not.toBeInTheDocument();
  });
});
