import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminOrgAttestorReviewPanel } from "@/components/modules/admin/admin-org-attestor-review-panel";
import { listOrgAttestorApplicationsForAdmin, verifyOrgAttestorKyb } from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
  configureBrowserClient: vi.fn(),
}));
vi.mock("@/lib/auth/current-user-session", () => ({ loadCurrentUserSession: vi.fn(async () => ({ isSuperAdmin: true })) }));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgAttestorApplicationsForAdmin: vi.fn(),
  verifyOrgAttestorKyb: vi.fn(), 
  orgAttestorNeedsInfo: vi.fn(),
  startOrgAttestorTrial: vi.fn(), 
  approveOrgAttestor: vi.fn(), 
  rejectOrgAttestor: vi.fn(),
  suspendOrgAttestorCapability: vi.fn(), 
  reinstateOrgAttestorCapability: vi.fn(), 
  revokeOrgAttestorCapability: vi.fn(),
}));

const ok = <T,>(d: T) => ({ data: d, error: undefined, request: new Request("http://t"), response: new Response(null, { status: 200 }) });

describe("AdminOrgAttestorReviewPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("verifies KYB for an application", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", legal_name: "Audit Ltd", status: "submitted", kyb_verified_at: null, created_at: "2026-07-07T12:00:00Z", reviewed_at: null }],
      total: 1,
      page: 1,
      page_size: 10
    }));vi.mocked(verifyOrgAttestorKyb).mockResolvedValue(ok({ id: "app-1" }) as any);
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Audit Ltd/));
    fireEvent.click(screen.getByRole("button", { name: /verify kyb/i }));
    await waitFor(() => expect(vi.mocked(verifyOrgAttestorKyb)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { application_id: "app-1" } }),
    ));
  });
});
