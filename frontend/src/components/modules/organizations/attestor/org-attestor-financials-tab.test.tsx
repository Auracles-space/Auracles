import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  getOrgAttestorEarnings,
  onboardOrgPayoutAccount,
  requestOrgPayout,
  listOrgInvoices,
  getOrgAttestorApplication,
} from "@/lib/generated/sdk.gen";
import { formatMoney } from "@/lib/marketplace/format";
import { OrgAttestorFinancialsTab } from "./org-attestor-financials-tab";

const orgContext = vi.hoisted(() => ({ role: "owner" }));

vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({ orgId: "org-1", role: orgContext.role }),
}));

// Payout history fetches on its own; its behaviour is pinned in its own test.
vi.mock("./org-payout-history", () => ({
  OrgPayoutHistory: () => <div>Payout history</div>,
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  getOrgAttestorEarnings: vi.fn(),
  onboardOrgPayoutAccount: vi.fn(),
  requestOrgPayout: vi.fn(),
  listOrgInvoices: vi.fn(),
  getOrgAttestorApplication: vi.fn(),
  // The connected-account card loads on mount; these tests assert on the
  // surrounding tab, so it resolves empty rather than being asserted here.
  listOrgPayoutAccounts: vi.fn(async () => ({
    data: { payout_accounts: [] },
    error: undefined,
    response: { ok: true },
  })),
  replaceOrgPayoutAccount: vi.fn(),
}));

// Keep the real getAccessTokenHeaders/describeGeneratedError; only stub
// configureBrowserClient, which touches the (mocked-away) transport client.
vi.mock("@/lib/auth/form-client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/form-client")>()),
  configureBrowserClient: vi.fn(),
}));

describe("OrgAttestorFinancialsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    orgContext.role = "owner";

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
        payout_eligibility: { eligible: true, reasons: [] },
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

  it("does not render a duplicate earnings section heading inside the org tab", async () => {
    render(<OrgAttestorFinancialsTab orgId="org-1" />);

    await waitFor(() => {
      expect(screen.getByText("Available Balance")).toBeInTheDocument();
    });

    expect(screen.queryByRole("heading", { name: "Earnings Overview" })).toBeNull();
  });

  it("shows request payout CTA and submits the payout when a payout account exists", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        id: "app-id",
        org_id: "org-1",
        status: "approved",
        payout_account_id: "payout-acc-id",
      },
    } as never);

    vi.mocked(requestOrgPayout).mockResolvedValue({
      data: { id: "payout-1", status: "pending" },
      response: { ok: true, status: 201 },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);
    await waitFor(() => {
      expect(screen.getByText("Request Payout")).toBeInTheDocument();
    });

    // No code field: the API requires a step-up window and the global prompt
    // handles a refusal, so one click submits.
    expect(screen.queryByLabelText("Authenticator code")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Request Payout"));

    await waitFor(() => {
      expect(requestOrgPayout).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: {
            amount: "450.00",
            currency: "USD",
            payout_account_id: "payout-acc-id",
          },
        }),
      );
    });
  });

  it("confirms a requested payout instead of only listing why another cannot be made", async () => {
    // After a successful request the refreshed checklist said "Before you can
    // request a payout ... a payout is already in progress", which read as a
    // refusal of the payout that had just gone through.
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        id: "app-id",
        org_id: "org-1",
        status: "approved",
        payout_account_id: "payout-acc-id",
      },
    } as never);
    vi.mocked(requestOrgPayout).mockResolvedValue({
      data: { id: "payout-1", status: "processing", net_amount: "450.00", currency: "USD" },
      response: { ok: true, status: 201 },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);
    fireEvent.click(await screen.findByRole("button", { name: "Request Payout" }));

    const confirmation = await screen.findByRole("status");
    expect(confirmation).toHaveTextContent(
      `Payout of ${formatMoney("450.00", "USD")} requested`,
    );
    expect(confirmation).toHaveTextContent(/on its way to your payout account/i);
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

  it("surfaces the backend error when re-opening Stripe fails", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        id: "app-id",
        org_id: "org-1",
        status: "approved",
        payout_account_id: "payout-acc-id",
      },
    } as never);
    vi.mocked(onboardOrgPayoutAccount).mockResolvedValue({
      error: { detail: "Payout provider is unavailable." },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);
    await waitFor(() => {
      expect(screen.getByText("Manage payout account")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Manage payout account"));

    expect(
      await screen.findByText("Payout provider is unavailable."),
    ).toBeInTheDocument();
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
    // The shared status vocabulary, not a bespoke "Account Pending" label.
    expect(await screen.findByText("Pending")).toBeInTheDocument();
    expect(screen.queryByText("Account Pending")).not.toBeInTheDocument();
    expect(screen.queryByText("Request Payout")).not.toBeInTheDocument();
  });

  it("formats every amount in the response's own currency", async () => {
    // Naira is the primary rail: amounts must never fall back to a dollar
    // sign or a bare "NGN 450.00" string concatenation.
    vi.mocked(getOrgAttestorEarnings).mockResolvedValue({
      data: {
        currency: "NGN",
        gross_revenue: "125000.50",
        pending_clearance: "2500.00",
        available_balance: "98000.00",
        commission_rate: "0.20",
        minimum_payout: "5000.00",
      },
    } as never);
    vi.mocked(listOrgInvoices).mockResolvedValue({
      data: {
        invoices: [
          {
            id: "inv-1",
            invoice_number: "AUR-ERN-2026-000123456789",
            doc_type: "earnings_statement",
            issue_date: "2026-08-02T00:00:00Z",
            currency: "NGN",
            total: "30000.00",
            source_ref_type: "attestation",
            source_ref_id: "att-1",
            direction: "sales",
          },
        ],
      },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);

    expect(await screen.findByText(formatMoney("98000.00", "NGN"))).toBeInTheDocument();
    expect(screen.getByText(formatMoney("2500.00", "NGN"))).toBeInTheDocument();
    expect(screen.getByText(formatMoney("125000.50", "NGN"))).toBeInTheDocument();
    expect(screen.getByText(formatMoney("30000.00", "NGN"))).toBeInTheDocument();
    expect(
      screen.getByText(`Minimum payout ${formatMoney("5000.00", "NGN")}`),
    ).toBeInTheDocument();
    expect(screen.queryByText(/NGN 98000/)).not.toBeInTheDocument();
  });

  it("disables Request Payout with an explanation when below the minimum", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: {
        id: "app-id",
        org_id: "org-1",
        status: "approved",
        payout_account_id: "payout-acc-id",
      },
    } as never);
    vi.mocked(getOrgAttestorEarnings).mockResolvedValue({
      data: {
        currency: "NGN",
        gross_revenue: "3000.00",
        pending_clearance: "0.00",
        available_balance: "3000.00",
        commission_rate: "0.20",
        minimum_payout: "5000.00",
      },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);

    const button = await screen.findByRole("button", { name: "Request Payout" });
    expect(button).toBeDisabled();
    expect(
      screen.getByText(
        `Your available balance is below the minimum payout of ${formatMoney("5000.00", "NGN")}.`,
      ),
    ).toBeInTheDocument();
  });

  it("shows the described error when earnings fail to load", async () => {
    vi.mocked(getOrgAttestorEarnings).mockResolvedValue({
      data: undefined,
      error: { detail: "Organization earnings are unavailable." },
      response: { ok: false, status: 403 },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Organization earnings are unavailable.");
  });

  const approvedWithAccount = {
    data: {
      id: "app-id",
      org_id: "org-1",
      status: "approved",
      payout_account_id: "payout-acc-id",
    },
  };

  it("lists unmet payout conditions and keeps Request Payout disabled", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue(approvedWithAccount as never);
    vi.mocked(getOrgAttestorEarnings).mockResolvedValue({
      data: {
        currency: "NGN",
        gross_revenue: "90000.00",
        pending_clearance: "0.00",
        available_balance: "90000.00",
        commission_rate: "0.20",
        minimum_payout: "5000.00",
        payout_eligibility: {
          eligible: false,
          reasons: [
            {
              code: "tax_document_missing",
              message: "Upload your tax document.",
              action_path: "/dashboard/organizations/org-1/settings",
            },
          ],
        },
      },
    } as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);

    expect(
      await screen.findByRole("heading", { name: "Before you can request a payout" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Upload your tax document.")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/settings",
    );
    expect(screen.getByRole("button", { name: "Request Payout" })).toBeDisabled();
  });

  it("hides the checklist when the organization is eligible", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue(approvedWithAccount as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);

    expect(await screen.findByRole("button", { name: "Request Payout" })).toBeEnabled();
    expect(
      screen.queryByRole("heading", { name: "Before you can request a payout" }),
    ).toBeNull();
  });

  it("tells a non-owner that only the owner can request payouts", async () => {
    orgContext.role = "admin";
    vi.mocked(getOrgAttestorApplication).mockResolvedValue(approvedWithAccount as never);

    render(<OrgAttestorFinancialsTab orgId="org-1" />);

    expect(
      await screen.findByText("Only the organization owner can request payouts."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Request Payout" })).toBeNull();
  });

  it("shows the payout history under earnings", async () => {
    render(<OrgAttestorFinancialsTab orgId="org-1" />);

    expect(await screen.findByText("Payout history")).toBeInTheDocument();
  });
});
