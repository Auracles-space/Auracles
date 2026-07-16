import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
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

/** One needs-admin attestation used across queue tests. */
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
  it("renders each needs-admin request as an inline row with a count", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue({
      response: { ok: true },
      data: { applications: [] },
    } as never);
    vi.mocked(listAttestorOrgs).mockResolvedValue({
      response: { ok: true },
      data: { attestors: [{ org_id: "org-1", name: "Acme Advisory" }] },
    } as never);
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: { attestations: [needsAdminItem()] },
    } as never);

    render(<AdminAttestationPanel />);

    expect(await screen.findByText(/Needs admin \(1\)/)).toBeInTheDocument();
    // Inline row exposes its own action, no shared "load into controls" step.
    expect(
      await screen.findByRole("button", { name: /Assign to org/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("quality review")).toBeInTheDocument();
  });
});
