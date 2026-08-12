import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  onboardOrgPayoutAccount,
  updateOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import { PayoutAccountGate } from "./payout-account-gate";

vi.mock("@/lib/generated/sdk.gen", () => ({
  listPayoutBanks: vi.fn(async () => ({
    data: { banks: [{ code: "044", name: "Access Bank" }] },
    error: undefined,
    response: { ok: true },
  })),
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

  it("collects bank details and onboards a Nigerian org via Paystack", async () => {
    // On an NGN deployment Stripe Connect cannot pay out at all, so the gate
    // must register the org's bank account rather than redirect to a hosted
    // flow that would 422 on the routing check.
    vi.stubEnv("NEXT_PUBLIC_PLATFORM_CURRENCY", "NGN");
    vi.resetModules();
    const { PayoutAccountGate: NgnGate } = await import("./payout-account-gate");

    vi.mocked(onboardOrgPayoutAccount).mockResolvedValue({
      data: {
        account_name: "ATTESTOR ORG LLC",
        onboarding_url: null,
        payout_account: { id: "acct-uuid-ng" },
        provider: "paystack",
      },
      error: undefined,
    } as never);
    vi.mocked(updateOrgAttestorApplication).mockResolvedValue({
      data: {},
      error: undefined,
    } as never);
    const onChange = vi.fn();

    render(<NgnGate application={draftApp()} onChange={onChange} orgId="org-1" />);

    fireEvent.change(await screen.findByLabelText(/Bank/i), {
      target: { value: "044" },
    });
    fireEvent.change(screen.getByLabelText(/Account number/i), {
      target: { value: "0123456789" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Set up payout account/i }));

    await waitFor(() => {
      expect(onboardOrgPayoutAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          body: {
            account_number: "0123456789",
            bank_code: "044",
            provider: "paystack",
          },
        }),
      );
    });
    // No redirect exists on this rail, so the gate must refresh in place
    // rather than dead-ending on a null onboarding URL.
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    vi.unstubAllEnvs();
  });
});
