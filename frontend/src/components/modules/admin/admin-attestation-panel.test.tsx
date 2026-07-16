import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  adminAssignAttestation,
  listAdminAttestations,
  listAttestorOrgs,
  listOrgAttestorApplicationsForAdmin,
} from "@/lib/generated/sdk.gen";
import { AdminAttestationPanel } from "./admin-attestation-panel";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "error"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminAssignAttestation: vi.fn(),
  adminRefundAttestation: vi.fn(),
  listAdminAttestations: vi.fn(),
  listAttestorOrgs: vi.fn(),
  listOrgAttestorApplicationsForAdmin: vi.fn(),
  rejectOrgAttestor: vi.fn(),
  resolveAttestationDispute: vi.fn(),
}));

/** One needs-admin attestation used across assign tests. */
function needsAdminItem() {
  return {
    id: "att-1",
    target_type: "framework",
    target_id: "fw-1",
    requestor_id: "user-1",
    attestor_org_id: null,
    status: "needs_admin",
    outcome: null,
    review_type: "quality",
    requested_specializations: [],
    requested_jurisdictions: [],
    fee_amount: "500.00",
    currency: "USD",
    escrow_id: "esc-1",
    created_at: "2026-07-16T00:00:00Z",
    updated_at: "2026-07-16T00:00:00Z",
  };
}

describe("AdminAttestationPanel needs-admin queue", () => {
  it("lists the needs-admin queue and loads a row into the controls", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue({
      response: { ok: true },
      data: { applications: [] },
    } as never);
    vi.mocked(listAttestorOrgs).mockResolvedValue({
      response: { ok: true },
      data: { attestors: [] },
    } as never);
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [needsAdminItem()] },
    } as never);

    render(<AdminAttestationPanel />);

    expect(await screen.findByText(/Needs admin \(1\)/)).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /Load into controls/i }),
    );

    await waitFor(() => {
      expect(
        (screen.getByPlaceholderText(/Load one from the queue/i) as HTMLInputElement)
          .value,
      ).toBe("att-1");
    });
  });

  it("assigns an org only (no reviewing member) via the org picker", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue({
      response: { ok: true },
      data: { applications: [] },
    } as never);
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [needsAdminItem()] },
    } as never);
    vi.mocked(listAttestorOrgs).mockResolvedValue({
      response: { ok: true },
      data: { attestors: [{ org_id: "org-1", name: "Acme Advisory" }] },
    } as never);
    vi.mocked(adminAssignAttestation).mockResolvedValue({
      response: { ok: true },
      data: {},
    } as never);

    render(<AdminAttestationPanel />);
    await screen.findByText(/Needs admin \(1\)/);
    fireEvent.click(
      screen.getByRole("button", { name: /Load into controls/i }),
    );
    await screen.findByRole("option", { name: "Acme Advisory" });

    fireEvent.change(
      screen.getByPlaceholderText(/Enter 6-digit code/i),
      { target: { value: "123456" } },
    );
    fireEvent.change(
      screen.getByPlaceholderText(/Explain this action/i),
      { target: { value: "Manual dispatch." } },
    );
    fireEvent.change(screen.getByLabelText(/Attestor org/i), {
      target: { value: "org-1" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Manual assign/i }));

    await waitFor(() => {
      expect(adminAssignAttestation).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { attestation_id: "att-1" },
          body: expect.objectContaining({ attestor_org_id: "org-1" }),
        }),
      );
    });
    const assignBody = vi.mocked(adminAssignAttestation).mock.calls[0][0].body;
    expect(assignBody).not.toHaveProperty("reviewing_member_id");
  });
});
