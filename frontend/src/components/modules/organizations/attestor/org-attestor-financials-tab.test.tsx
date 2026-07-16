import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getOrgAttestorEarnings,
  onboardOrgPayoutAccount,
  requestOrgPayout,
  listOrgInvoices,
  getOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import { OrgAttestorFinancialsTab } from "./org-attestor-financials-tab";

vi.mock("@/lib/generated/sdk.gen", () => ({
  getOrgAttestorEarnings: vi.fn(),
  onboardOrgPayoutAccount: vi.fn(),
  requestOrgPayout: vi.fn(),
  listOrgInvoices: vi.fn(),
  getOrgAttestorApplication: vi.fn(),
}));

describe("OrgAttestorFinancialsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        id: "app-id",
        org_id: "org-1",
        status: "approved",
        payout_account_id: null,
      },
    } as never);

    vi.mocked(getOrgAttestorEarnings).mockResolvedValue({
      data: {
        currency: "USD",
        gross_revenue: "450.00",
        pending_clearance: "0.00",
        available_balance: "450.00",
        commission_rate: "0.20",
        minimum_payout: "50.00",
      },
    } as never);

    vi.mocked(listOrgInvoices).mockResolvedValue({
      data: {
        invoices: [],
      },
    } as never);
  });

  it("shows onboard CTA when no payout account exists", async () => {
    render(<OrgAttestorFinancialsTab orgId="org-1" />);
    await waitFor(() => {
      expect(screen.getByText("Available Balance")).toBeInTheDocument();
    });

    expect(screen.getByText("Setup Payout Account")).toBeInTheDocument();
  });

  it("shows request payout CTA and handles TOTP flow when payout account exists", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        id: "app-id",
        org_id: "org-1",
        status: "approved",
        payout_account_id: "payout-acc-id",
      },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);
    await waitFor(() => {
      expect(screen.getByText("Request Payout")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Request Payout"));

    // Should show TOTP input
    await waitFor(() => {
      expect(screen.getByLabelText("Authenticator code")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByText("Confirm Payout"));

    await waitFor(() => {
      expect(requestOrgPayout).toHaveBeenCalledWith({
        path: { org_id: "org-1" },
        body: {
          amount: "450.00",
          currency: "USD",
          payout_account_id: "payout-acc-id",
          totp_code: "123456",
        },
      });
    });
  });

  it("lets an approved org re-open Stripe to manage an existing payout account", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        id: "app-id",
        org_id: "org-1",
        status: "approved",
        payout_account_id: "payout-acc-id",
      },
    } as never);
    // No onboarding_url in the response so the component skips the redirect
    // (jsdom cannot navigate) while we still assert the call is wired.
    vi.mocked(onboardOrgPayoutAccount).mockResolvedValue({
      data: {},
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);
    await waitFor(() => {
      expect(screen.getByText("Manage payout account")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Manage payout account"));

    await waitFor(() => {
      expect(onboardOrgPayoutAccount).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: expect.objectContaining({ provider: "stripe" }),
        }),
      );
    });
  });

  it("blocks payout if application is not approved", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        id: "app-id",
        org_id: "org-1",
        status: "pending",
        payout_account_id: "payout-acc-id",
      },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);
    await waitFor(() => {
      expect(screen.getByText("Account Pending")).toBeInTheDocument();
    });

    expect(screen.queryByText("Request Payout")).not.toBeInTheDocument();
  });
});
