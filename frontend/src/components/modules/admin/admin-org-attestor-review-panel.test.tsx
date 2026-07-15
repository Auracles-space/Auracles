import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminOrgAttestorReviewPanel } from "@/components/modules/admin/admin-org-attestor-review-panel";
import {
  listOrgAttestorApplicationsForAdmin,
  listOrgAttestorDocumentsForAdmin,
  verifyOrgAttestorKyb,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
  configureBrowserClient: vi.fn(),
}));
vi.mock("@/lib/auth/current-user-session", () => ({ loadCurrentUserSession: vi.fn(async () => ({ isSuperAdmin: true })) }));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgAttestorApplicationsForAdmin: vi.fn(),
  listOrgAttestorDocumentsForAdmin: vi.fn(),
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

  it("verifies KYB and reflects the stamp plus a success notice", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", legal_name: "Audit Ltd", status: "submitted", kyb_verified_at: null, created_at: "2026-07-07T12:00:00Z", reviewed_at: null }],
      total: 1,
      page: 1,
      page_size: 10
    }));
    // verify_kyb leaves status put but stamps kyb_verified_at; the row and a
    // notice must both reflect it, or the click looks like it did nothing.
    vi.mocked(verifyOrgAttestorKyb).mockResolvedValue(
      ok({ id: "app-1", status: "submitted", kyb_verified_at: "2026-07-15T09:00:00Z" }) as never,
    );
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Audit Ltd/));
    const kybLine = () => screen.getByText(/KYB Verified:/i).closest("p");
    expect(kybLine()?.textContent).toMatch(/Pending/i);
    fireEvent.click(screen.getByRole("button", { name: /verify kyb/i }));
    await waitFor(() => expect(vi.mocked(verifyOrgAttestorKyb)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { application_id: "app-1" } }),
    ));
    await screen.findByText(/KYB verified\./i);
    expect(kybLine()?.textContent).not.toMatch(/Pending/i);
  });

  it("loads and renders document links on view", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", legal_name: "Audit Ltd", status: "submitted", kyb_verified_at: null, created_at: "2026-07-07T12:00:00Z", reviewed_at: null }],
      total: 1,
      page: 1,
      page_size: 10
    }));
    vi.mocked(listOrgAttestorDocumentsForAdmin).mockResolvedValue(ok({
      documents: [{ label: "Incorporation document 1", filename: "cert.pdf", url: "https://signed/cert.pdf" }],
    }) as never);
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Audit Ltd/));
    fireEvent.click(screen.getByRole("button", { name: /view kyb \/ tax documents/i }));
    await waitFor(() => expect(vi.mocked(listOrgAttestorDocumentsForAdmin)).toHaveBeenCalledWith(
      expect.objectContaining({ path: { application_id: "app-1" } }),
    ));
    const link = await screen.findByRole("link", { name: /cert\.pdf/i });
    expect(link).toHaveAttribute("href", "https://signed/cert.pdf");
  });

  it("activates the gate buttons in sequence: KYB then trial then approve", async () => {
    // Three apps at successive stages. Only the next undone step is live per
    // app; predecessors done and successors not-yet-reachable stay disabled.
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [
        // Stage 1: nothing done → only Verify KYB active.
        { id: "app-1", org_id: "org-1", legal_name: "Kyb Stage", status: "submitted", kyb_verified_at: null, trial_status: null, created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
        // Stage 2: KYB done, no trial → only Start Trial active.
        { id: "app-2", org_id: "org-2", legal_name: "Trial Stage", status: "submitted", kyb_verified_at: "2026-07-07T12:00:00Z", trial_status: null, created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
        // Stage 3: KYB done, trial passed → only Approve active.
        { id: "app-3", org_id: "org-3", legal_name: "Approve Stage", status: "submitted", kyb_verified_at: "2026-07-07T12:00:00Z", trial_status: "passed", created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
      ],
      total: 3,
      page: 1,
      page_size: 10
    }));
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Kyb Stage/));

    const verify = screen.getAllByRole("button", { name: /verify kyb/i });
    const start = screen.getAllByRole("button", { name: /start trial/i });
    const approve = screen.getAllByRole("button", { name: /^approve$/i });

    // app-1: KYB only.
    expect(verify[0]).not.toBeDisabled();
    expect(start[0]).toBeDisabled();
    expect(approve[0]).toBeDisabled();
    // app-2: Trial only.
    expect(verify[1]).toBeDisabled();
    expect(start[1]).not.toBeDisabled();
    expect(approve[1]).toBeDisabled();
    // app-3: Approve only.
    expect(verify[2]).toBeDisabled();
    expect(start[2]).toBeDisabled();
    expect(approve[2]).not.toBeDisabled();
  });

  it("holds Start Trial while a trial is pending and offers a retry after a failure", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [
        // Trial assigned but not decided → Start Trial held.
        { id: "app-1", org_id: "org-1", legal_name: "Pending Trial", status: "submitted", kyb_verified_at: "2026-07-07T12:00:00Z", trial_status: "assigned", created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
        // Trial failed → Start Trial live again for a retry, Approve still blocked.
        { id: "app-2", org_id: "org-2", legal_name: "Failed Trial", status: "submitted", kyb_verified_at: "2026-07-07T12:00:00Z", trial_status: "failed", created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
      ],
      total: 2,
      page: 1,
      page_size: 10
    }));
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Pending Trial/));

    const start = screen.getAllByRole("button", { name: /start trial/i });
    const approve = screen.getAllByRole("button", { name: /^approve$/i });
    expect(start[0]).toBeDisabled();
    expect(start[1]).not.toBeDisabled();
    expect(approve[0]).toBeDisabled();
    expect(approve[1]).toBeDisabled();
    expect(screen.getByText(/Waiting on the nominee/i)).toBeTruthy();
  });
});
