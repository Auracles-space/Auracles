import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createOrgAttestorApplication,
  getOrgAttestorApplication,
  listMyOrganizationsV1OrgsMineGet as listMyOrganizations,
} from "@/lib/generated/sdk.gen";
import { AttestorApplicationTab } from "./attestor-application-tab";

vi.mock("@/lib/generated/sdk.gen", () => ({
  createOrgAttestorApplication: vi.fn(),
  getOrgAttestorApplication: vi.fn(),
  submitOrgAttestorApplication: vi.fn(),
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
}));

// The tab reads the org's capability map from context; tests swap it per case.
const context = vi.hoisted(() => ({
  capabilities: {} as Record<string, string>,
}));
vi.mock("@/components/modules/organizations/organization-context", () => ({
  useOrganization: () => ({
    orgId: "org-1",
    role: "owner",
    capabilities: context.capabilities,
  }),
}));

// Child gates own their own tests; stub them so this file exercises tab logic only.
vi.mock("./apply-gate", () => ({ ApplyGate: () => <div>apply-gate</div> }));
vi.mock("./undertakings-gate", () => ({ UndertakingsGate: () => null }));
vi.mock("./payout-account-gate", () => ({ PayoutAccountGate: () => null }));
vi.mock("./tax-document-gate", () => ({ TaxDocumentGate: () => null }));
vi.mock("./trial-member-gate", () => ({ TrialMemberGate: () => null }));

/** A submitted-and-decided application shell for status assertions. */
function application(overrides: Record<string, unknown> = {}) {
  return {
    id: "app-1",
    org_id: "org-1",
    status: "submitted",
    credentials_summary: "Ten years of audit experience across sectors.",
    professional_references: "Jane Doe, jane@example.com",
    sample_work: { url: "https://example.com" },
    sectors: ["private_equity"],
    functions: ["compliance"],
    jurisdictions: ["united_states"],
    admin_feedback: null,
    payout_account_id: "pa-1",
    confidentiality_signed_at: null,
    tax_document_key: null,
    trial_member_id: null,
    gate_checklist: {
      credentials_reviewed: false,
      kyb_verified: true,
      payout_account_linked: true,
      tax_document_uploaded: false,
      trial_passed: false,
      undertakings_signed: false,
    },
    ...overrides,
  };
}

describe("AttestorApplicationTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    context.capabilities = {};
    vi.mocked(listMyOrganizations).mockResolvedValue({
      data: { organizations: [] },
    } as never);
  });

  describe("rejected application", () => {
    beforeEach(() => {
      vi.mocked(getOrgAttestorApplication).mockResolvedValue({
        data: application({
          status: "rejected",
          admin_feedback: "References could not be verified.",
        }),
      } as never);
      vi.mocked(createOrgAttestorApplication).mockResolvedValue({
        data: application({ id: "app-2", status: "draft", admin_feedback: null }),
      } as never);
    });

    it("shows a red Rejected status with the admin feedback, not Submitted", async () => {
      render(<AttestorApplicationTab />);

      const pill = await screen.findByText("Rejected");
      expect(pill.className).toContain("text-error");
      expect(screen.getByText("References could not be verified.")).toBeInTheDocument();
      expect(screen.queryByText("Submitted")).not.toBeInTheDocument();
    });

    it("does not offer Resubmit for a rejected application", async () => {
      render(<AttestorApplicationTab />);
      await screen.findByText("Rejected");

      expect(screen.queryByRole("button", { name: /resubmit/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /submit for review/i })).not.toBeInTheDocument();
    });

    it("starts a fresh draft from the rejected application and reloads", async () => {
      render(<AttestorApplicationTab />);
      await screen.findByText("Rejected");

      fireEvent.click(screen.getByRole("button", { name: /start a new application/i }));

      await waitFor(() => expect(createOrgAttestorApplication).toHaveBeenCalled());
      const call = vi.mocked(createOrgAttestorApplication).mock.calls[0][0];
      expect(call.path).toEqual({ org_id: "org-1" });
      // The new draft is seeded from the rejected answers so the owner edits
      // rather than retypes.
      expect(call.body.credentials_summary).toBe(
        "Ten years of audit experience across sectors.",
      );
      expect(call.body.sectors).toEqual(["private_equity"]);
      // The tab re-fetches so the fresh draft replaces the rejected view.
      await waitFor(() => expect(getOrgAttestorApplication).toHaveBeenCalledTimes(2));
    });
  });

  describe("status vocabulary", () => {
    it("shows a submitted application as In review, never Submitted", async () => {
      vi.mocked(getOrgAttestorApplication).mockResolvedValue({
        data: application({ status: "submitted" }),
      } as never);
      render(<AttestorApplicationTab />);

      expect((await screen.findAllByText("In review")).length).toBeGreaterThan(0);
      expect(screen.queryByText("Submitted")).not.toBeInTheDocument();
      expect(screen.queryByText("Pending review")).not.toBeInTheDocument();
    });
  });

  describe("activation gate", () => {
    beforeEach(() => {
      vi.mocked(getOrgAttestorApplication).mockResolvedValue({
        data: application({ status: "approved" }),
      } as never);
    });

    it("shows Active once the capability is active", async () => {
      context.capabilities = { attestor: "active" };
      render(<AttestorApplicationTab />);

      expect(await screen.findByText("Active")).toBeInTheDocument();
      expect(listMyOrganizations).not.toHaveBeenCalled();
    });

    it("shows Suspended with the admin's reason instead of Active", async () => {
      context.capabilities = { attestor: "suspended" };
      vi.mocked(listMyOrganizations).mockResolvedValue({
        data: {
          organizations: [
            {
              org: { id: "org-1" },
              role: "owner",
              capabilities: { attestor: "suspended" },
              capability_reasons: { attestor: "Repeated late reports." },
            },
          ],
        },
      } as never);
      render(<AttestorApplicationTab />);

      const pill = await screen.findByText("Suspended");
      expect(pill.className).toContain("text-error");
      expect(await screen.findByText(/Repeated late reports\./)).toBeInTheDocument();
      expect(screen.getByText(/Reason:/)).toBeInTheDocument();
      expect(screen.queryByText("Active")).not.toBeInTheDocument();
      expect(screen.queryByText(/contact support to appeal/i)).not.toBeInTheDocument();
    });

    it("shows Revoked with the reason and an appeal hint", async () => {
      context.capabilities = { attestor: "revoked" };
      vi.mocked(listMyOrganizations).mockResolvedValue({
        data: {
          organizations: [
            {
              org: { id: "org-1" },
              role: "owner",
              capabilities: { attestor: "revoked" },
              capability_reasons: { attestor: "Fabricated credentials." },
            },
          ],
        },
      } as never);
      render(<AttestorApplicationTab />);

      expect(await screen.findByText("Revoked")).toBeInTheDocument();
      expect(await screen.findByText(/Fabricated credentials\./)).toBeInTheDocument();
      expect(screen.getByText("Contact support to appeal.")).toBeInTheDocument();
      expect(screen.queryByText("Active")).not.toBeInTheDocument();
    });
  });

  describe("trial gate", () => {
    it("shows Pending while the nominee still holds the trial", async () => {
      vi.mocked(getOrgAttestorApplication).mockResolvedValue({
        data: application({ trial_member_id: "member-1" }),
      } as never);
      render(<AttestorApplicationTab />);

      expect(await screen.findByText("Pending")).toBeInTheDocument();
      expect(screen.getByText(/waiting for them to complete the trial/i)).toBeInTheDocument();
    });

    it("shows Passed with the admin feedback once the trial is decided", async () => {
      vi.mocked(getOrgAttestorApplication).mockResolvedValue({
        data: application({
          trial_member_id: "member-1",
          trial_status: "passed",
          trial_feedback: "Scores were within tolerance on every dimension.",
          gate_checklist: {
            credentials_reviewed: true,
            kyb_verified: true,
            payout_account_linked: true,
            tax_document_uploaded: true,
            trial_passed: true,
            undertakings_signed: true,
          },
        }),
      } as never);
      render(<AttestorApplicationTab />);

      const pill = await screen.findByText("Passed");
      expect(pill.className).toContain("text-success");
      expect(
        screen.getByText("Scores were within tolerance on every dimension."),
      ).toBeInTheDocument();
      expect(screen.queryByText("Pending")).not.toBeInTheDocument();
    });

    it("shows Failed with the admin feedback instead of Pending", async () => {
      vi.mocked(getOrgAttestorApplication).mockResolvedValue({
        data: application({
          trial_member_id: "member-1",
          trial_status: "failed",
          trial_feedback: "Scores diverged from the answer key on three dimensions.",
        }),
      } as never);
      render(<AttestorApplicationTab />);

      const pill = await screen.findByText("Failed");
      expect(pill.className).toContain("text-error");
      expect(
        screen.getByText("Scores diverged from the answer key on three dimensions."),
      ).toBeInTheDocument();
      expect(screen.queryByText("Pending")).not.toBeInTheDocument();
      expect(screen.queryByText(/waiting for them/i)).not.toBeInTheDocument();
    });
  });
});

describe("AttestorApplicationTab application review gate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    context.capabilities = {};
    vi.mocked(listMyOrganizations).mockResolvedValue({
      data: { organizations: [] },
    } as never);
  });

  it("places the admin review after the owner's own steps, apart from business verification", async () => {
    // Listed second as "Org credentials", the card read like the business
    // verification the org had already passed.
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: application({ status: "draft" }),
    } as never);
    render(<AttestorApplicationTab />);

    await screen.findByText("Application review");
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual([
      "Apply",
      "Sign Undertakings",
      "Tax Documents",
      "Payout Account",
      "Application review",
      "Trial Attestation",
      "Activation",
    ]);
    expect(screen.queryByText("Org credentials")).not.toBeInTheDocument();
    expect(screen.getByText(/separate from business verification/i)).toBeInTheDocument();
    expect(screen.getByText("Awaiting submission")).toBeInTheDocument();
  });
});
