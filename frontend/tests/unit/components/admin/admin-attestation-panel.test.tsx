import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminAttestationPanel } from "@/components/modules/admin/admin-attestation-panel";
import { adminAssignAttestation, listOrgAttestorApplicationsForAdmin } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgAttestorApplicationsForAdmin: vi.fn(),
  adminAssignAttestation: vi.fn(),
  adminRefundAttestation: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data, error: undefined,
  request: new Request("http://t"), response: new Response(null, { status: 200 }),
});

describe("AdminAttestationPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("posts attestor_org_id and reviewing_member_id when assigning", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(
      ok({ applications: [] }) as never,
    );
    vi.mocked(adminAssignAttestation).mockResolvedValue(ok({ id: "att-1" }) as never);
    render(<AdminAttestationPanel />);
    await waitFor(() => screen.getByText(/Admin attestation/));
    
    // Fill out the required 2FA code and reason to enable the assign button
    fireEvent.change(screen.getByPlaceholderText(/Enter 6-digit code/), { target: { value: "123456" } });
    fireEvent.change(screen.getByPlaceholderText(/Explain this action/), { target: { value: "reason" } });
    
    // Fill out attestation ID, org ID, and member ID
    fireEvent.change(screen.getByLabelText(/Attestation ID/i), { target: { value: "att-1" } });
    fireEvent.change(screen.getByLabelText(/Target Attestor Org ID/i), { target: { value: "org-2" } });
    fireEvent.change(screen.getByLabelText(/Target Reviewing Member ID/i), { target: { value: "mem-3" } });
    
    fireEvent.click(screen.getByRole("button", { name: /Manual assign/i }));
    await waitFor(() =>
      expect(vi.mocked(adminAssignAttestation)).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { attestor_org_id: "org-2", reviewing_member_id: "mem-3", reason: "reason", totp_code: "123456" },
        }),
      ),
    );
  });
});
