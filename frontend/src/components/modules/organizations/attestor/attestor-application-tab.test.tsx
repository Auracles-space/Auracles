import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  createOrgAttestorApplication,
  getOrgAttestorApplication,
  listMyOrganizationsV1OrgsMineGet as listMyOrganizations,
  submitOrgAttestorApplication,
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
vi.mock("./apply-gate", () => ({
  ApplyGate: ({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) => (
    <button onClick={() => onDirtyChange?.(true)} type="button">
      edit-details
    </button>
  ),
}));
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

    it("marks every review stage done, Activation included, once active", async () => {
      context.capabilities = { attestor: "active" };
      render(<AttestorApplicationTab />);

      await screen.findByText("Active");
      for (const label of ["Submit", "Review and trial", "Approval", "Activation"]) {
        const stage = screen.getByText(label, { selector: "li" });
        expect(stage.className).toContain("text-success");
        expect(stage).not.toHaveAttribute("aria-current");
      }
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
        data: application({ trial_member_id: "member-1", trial_status: "assigned" }),
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

describe("AttestorApplicationTab stepper", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    context.capabilities = {};
    vi.mocked(listMyOrganizations).mockResolvedValue({
      data: { organizations: [] },
    } as never);
  });

  /** Every owner step done, still a draft. */
  const readyDraft = () =>
    application({
      status: "draft",
      coi_signed_at: "2026-09-15T00:00:00Z",
      confidentiality_signed_at: "2026-09-15T00:00:00Z",
      tax_document_key: "tax/doc.pdf",
      trial_member_id: "member-1",
    });

  it("lists the owner's steps in order and opens on the first incomplete one", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: application({ status: "draft" }),
    } as never);
    render(<AttestorApplicationTab />);

    expect(await screen.findByRole("heading", { level: 3, name: "Sign undertakings" })).toBeInTheDocument();
    const steps = screen.getAllByRole("button", { name: /^Step \d/ });
    expect(steps.map((step) => step.getAttribute("aria-label"))).toEqual([
      "Step 1: Details, complete",
      "Step 2: Undertakings",
      "Step 3: Tax document",
      "Step 4: Payout account, complete",
      "Step 5: Trial member",
      "Step 6: Submit",
    ]);
    expect(steps[1]).toHaveAttribute("aria-current", "step");
  });

  it("keeps Next disabled until the open step is complete, and blocks skipping ahead", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: application({ status: "draft" }),
    } as never);
    render(<AttestorApplicationTab />);
    await screen.findByRole("heading", { level: 3, name: "Sign undertakings" });

    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByText("Complete this step to continue.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Step 3: Tax document/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Step 6: Submit/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("heading", { level: 3, name: "Application details" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { level: 3, name: "Sign undertakings" })).toBeInTheDocument();
  });

  it("blocks Next while the details have unsaved changes", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: application({ status: "draft" }),
    } as never);
    render(<AttestorApplicationTab />);
    await screen.findByRole("heading", { level: 3, name: "Sign undertakings" });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "edit-details" }));

    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
    expect(screen.getByText("Save this step to continue.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Step 2: Undertakings/ })).toBeDisabled();
  });

  it("submits a draft once every owner step is done", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({ data: readyDraft() } as never);
    vi.mocked(submitOrgAttestorApplication).mockResolvedValue({ data: {} } as never);
    render(<AttestorApplicationTab />);

    const submit = await screen.findByRole("button", { name: "Submit for review" });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() => expect(submitOrgAttestorApplication).toHaveBeenCalled());
  });

  it("pins the review stage above the steps once submitted", async () => {
    vi.mocked(getOrgAttestorApplication).mockResolvedValue({
      data: { ...readyDraft(), status: "submitted" },
    } as never);
    render(<AttestorApplicationTab />);

    expect(await screen.findByRole("heading", { level: 3, name: "Application in review" })).toBeInTheDocument();
    expect(screen.getByText(/will start the calibration trial/i)).toBeInTheDocument();
    expect(screen.getByText("Review and trial").closest("li")).toHaveAttribute("aria-current", "step");
    expect(screen.queryByRole("button", { name: "Submit for review" })).toBeNull();
  });
});
