import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  listAdminAttestations,
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
  listOrgAttestorApplicationsForAdmin: vi.fn(),
  rejectOrgAttestor: vi.fn(),
  resolveAttestationDispute: vi.fn(),
}));

describe("AdminAttestationPanel needs-admin queue", () => {
  it("lists the needs-admin queue and loads a row into the controls", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue({
      response: { ok: true },
      data: { applications: [] },
    } as never);
    vi.mocked(listAdminAttestations).mockResolvedValue({
      response: { ok: true },
      data: {
        attestations: [
          {
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
          },
        ],
      },
    } as never);

    render(<AdminAttestationPanel />);

    expect(await screen.findByText(/Needs admin \(1\)/)).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: /Load into controls/i }),
    );

    await waitFor(() => {
      expect(
        (screen.getByPlaceholderText(/att-93f8e/i) as HTMLInputElement).value,
      ).toBe("att-1");
    });
  });
});
