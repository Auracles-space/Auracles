import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttestorApplicationCard } from "@/components/modules/admin/attestors/attestor-application-card";
import type { OrgAttestorAdminListItem } from "@/lib/generated/types.gen";

const sdk = vi.hoisted(() => ({
  approveOrgAttestor: vi.fn(),
  orgAttestorNeedsInfo: vi.fn(),
  rejectOrgAttestor: vi.fn(),
  startOrgAttestorTrial: vi.fn(),
  listOrgAttestorDocumentsForAdmin: vi.fn(),
  adminGetTrialGrade: vi.fn(),
  adminDecideTrial: vi.fn(),
  suspendOrgAttestorCapability: vi.fn(),
  reinstateOrgAttestorCapability: vi.fn(),
  revokeOrgAttestorCapability: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  approveOrgAttestor: sdk.approveOrgAttestor,
  orgAttestorNeedsInfo: sdk.orgAttestorNeedsInfo,
  rejectOrgAttestor: sdk.rejectOrgAttestor,
  startOrgAttestorTrial: sdk.startOrgAttestorTrial,
  listOrgAttestorDocumentsForAdmin: sdk.listOrgAttestorDocumentsForAdmin,
  adminGetTrialGradeV1AdminOrgAttestorApplicationsApplicationIdTrialGet: sdk.adminGetTrialGrade,
  adminDecideTrialV1AdminOrgAttestorApplicationsApplicationIdTrialDecidePost: sdk.adminDecideTrial,
  suspendOrgAttestorCapability: sdk.suspendOrgAttestorCapability,
  reinstateOrgAttestorCapability: sdk.reinstateOrgAttestorCapability,
  revokeOrgAttestorCapability: sdk.revokeOrgAttestorCapability,
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "The request failed."),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

function app(overrides: Partial<OrgAttestorAdminListItem> = {}): OrgAttestorAdminListItem {
  return {
    id: "app-1",
    org_id: "org-1",
    org_name: "Audit Ltd",
    status: "submitted",
    kyb_status: "verified",
    trial_status: null,
    capability_status: null,
    admin_feedback: null,
    created_at: "2026-07-07T12:00:00Z",
    reviewed_at: null,
    ...overrides,
  };
}

const fixtures = [
  { id: "fixture-1", title: "Quality Fixture", review_type: "quality" },
] as never;

function renderCard(item: OrgAttestorAdminListItem, open = true) {
  const onUpdate = vi.fn();
  const onNotice = vi.fn();
  const onError = vi.fn();
  render(
    <AttestorApplicationCard
      app={item}
      defaultOpen={open}
      fixtures={fixtures}
      onError={onError}
      onNotice={onNotice}
      onUpdate={onUpdate}
    />,
  );
  return { onUpdate, onNotice, onError };
}

describe("AttestorApplicationCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sdk.listOrgAttestorDocumentsForAdmin.mockResolvedValue(
      ok({ documents: [{ label: "Incorporation document 1", filename: "cert.pdf", url: "https://signed/cert.pdf" }] }),
    );
  });

  it("shows the organization, every gate pill, and the next step when collapsed", () => {
    renderCard(app({ kyb_status: "unverified" }), false);

    expect(screen.getByRole("heading", { name: "Audit Ltd" })).toBeInTheDocument();
    expect(screen.getByText("Not verified")).toBeInTheDocument();
    expect(screen.getByText("No trial")).toBeInTheDocument();
    expect(screen.getByText(/Verify the organization first/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("lists the review documents as external links once expanded", async () => {
    renderCard(app());

    const link = await screen.findByRole("link", { name: /cert\.pdf/ });
    expect(link).toHaveAttribute("href", "https://signed/cert.pdf");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("starts the trial with the chosen fixture and advances the gate locally", async () => {
    sdk.startOrgAttestorTrial.mockResolvedValue(ok({ id: "app-1", status: "submitted" }));
    const { onUpdate, onNotice } = renderCard(app());

    fireEvent.change(screen.getByLabelText("Calibration fixture for Audit Ltd"), {
      target: { value: "fixture-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start trial" }));

    await waitFor(() =>
      expect(sdk.startOrgAttestorTrial).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { application_id: "app-1" },
          body: { framework_id: "fixture-1" },
        }),
      ),
    );
    expect(onUpdate).toHaveBeenCalledWith("app-1", { status: "submitted", trial_status: "assigned" });
    expect(onNotice).toHaveBeenCalledWith("Trial assigned to the nominated member.");
  });

  it("grades a submitted trial and reports the decision", async () => {
    sdk.adminGetTrialGrade.mockResolvedValue(
      ok({
        trial_id: "trial-1",
        status: "submitted",
        score_pct: "84.50",
        auto_result: "pass",
        rows: [
          {
            dimension_id: "dim-1",
            label: "Governance",
            weight: "1.0",
            nominee_score: 4,
            nominee_comment: "Matches the evidence.",
            expected_score: 4,
            tolerance: 0,
          },
        ],
      }),
    );
    sdk.adminDecideTrial.mockResolvedValue(ok({ id: "app-1", status: "submitted" }));
    const { onUpdate } = renderCard(app({ trial_status: "submitted" }));

    expect(await screen.findByText("84.50%")).toBeInTheDocument();
    expect(screen.getByText("Suggested: pass")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pass trial" }));

    await waitFor(() =>
      expect(sdk.adminDecideTrial).toHaveBeenCalledWith(
        expect.objectContaining({ body: { result: "pass", feedback: undefined } }),
      ),
    );
    expect(onUpdate).toHaveBeenCalledWith("app-1", { status: "submitted", trial_status: "passed" });
  });

  it("sends needs-info feedback from a preset", async () => {
    sdk.orgAttestorNeedsInfo.mockResolvedValue(ok({ id: "app-1", status: "needs_info" }));
    const { onUpdate } = renderCard(app());

    fireEvent.click(screen.getByRole("button", { name: "Needs info" }));
    fireEvent.click(screen.getByRole("button", { name: "Payout account" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm needs info" }));

    await waitFor(() =>
      expect(sdk.orgAttestorNeedsInfo).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { feedback: expect.stringMatching(/connect a payout account/i) },
        }),
      ),
    );
    expect(onUpdate).toHaveBeenCalledWith(
      "app-1",
      expect.objectContaining({ status: "needs_info" }),
    );
  });

  it("approves once every gate is met and enables the capability controls", async () => {
    sdk.approveOrgAttestor.mockResolvedValue(ok({ id: "app-1", status: "approved" }));
    const { onUpdate } = renderCard(app({ trial_status: "passed" }));

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(onUpdate).toHaveBeenCalledWith("app-1", {
        status: "approved",
        capability_status: "active",
      }),
    );
  });

  it("confirms before suspending an active capability, requiring a reason, and reports the new status", async () => {
    sdk.suspendOrgAttestorCapability.mockResolvedValue(ok({}));
    const { onUpdate } = renderCard(app({ status: "approved", capability_status: "active" }));

    expect(screen.getByRole("button", { name: "Reinstate" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Suspend" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Suspend attestor capability?");
    // The dialog's confirm button shares its label with the trigger; pick the
    // one inside the dialog.
    const confirm = within(dialog).getByRole("button", { name: "Suspend" });
    expect(confirm).toBeDisabled();

    const reason = within(dialog).getByLabelText(
      /reason \(shown to the organization's owner\)/i,
    );
    fireEvent.change(reason, { target: { value: "abc" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(reason, { target: { value: "Two reports were withdrawn after review" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() =>
      expect(sdk.suspendOrgAttestorCapability).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { reason: "Two reports were withdrawn after review" },
          path: { org_id: "org-1" },
        }),
      ),
    );
    expect(onUpdate).toHaveBeenCalledWith("app-1", { capability_status: "suspended" });
  });

  it("requires a reason to revoke and sends it in the body", async () => {
    sdk.revokeOrgAttestorCapability.mockResolvedValue(ok({}));
    const { onUpdate } = renderCard(app({ status: "approved", capability_status: "active" }));

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    const dialog = await screen.findByRole("dialog");
    const confirm = within(dialog).getByRole("button", { name: "Revoke" });
    expect(confirm).toBeDisabled();

    fireEvent.change(within(dialog).getByLabelText(/reason/i), {
      target: { value: "Falsified attestation evidence" },
    });
    fireEvent.click(confirm);

    await waitFor(() =>
      expect(sdk.revokeOrgAttestorCapability).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { reason: "Falsified attestation evidence" },
          path: { org_id: "org-1" },
        }),
      ),
    );
    expect(onUpdate).toHaveBeenCalledWith("app-1", { capability_status: "revoked" });
  });

  it("reinstates without asking for a reason and sends no body", async () => {
    sdk.reinstateOrgAttestorCapability.mockResolvedValue(ok({}));
    const { onUpdate } = renderCard(app({ status: "approved", capability_status: "suspended" }));

    fireEvent.click(screen.getByRole("button", { name: "Reinstate" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText(/reason/i)).not.toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Reinstate" });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(sdk.reinstateOrgAttestorCapability).toHaveBeenCalledTimes(1));
    expect(sdk.reinstateOrgAttestorCapability.mock.calls[0][0]).not.toHaveProperty("body");
    expect(onUpdate).toHaveBeenCalledWith("app-1", { capability_status: "active" });
  });

  it("surfaces an API failure through onError without changing state", async () => {
    sdk.approveOrgAttestor.mockResolvedValue({
      data: undefined,
      error: { detail: "Nope" },
      request: new Request("http://t"),
      response: new Response(null, { status: 422 }),
    });
    const { onUpdate, onError } = renderCard(app({ trial_status: "passed" }));

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(onError).toHaveBeenCalledWith("The request failed."));
    expect(onUpdate).not.toHaveBeenCalled();
  });
});
