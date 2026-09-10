import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminOrgAttestorReviewPanel } from "@/components/modules/admin/admin-org-attestor-review-panel";
import {
  adminDecideTrialV1AdminOrgAttestorApplicationsApplicationIdTrialDecidePost as adminDecideTrial,
  adminGetTrialGradeV1AdminOrgAttestorApplicationsApplicationIdTrialGet as adminGetTrialGrade,
  adminListCalibrationFixturesV1AdminOrgAttestorApplicationsCalibrationFixturesGet as adminListCalibrationFixtures,
  approveOrgAttestor,
  listOrgAttestorApplicationsForAdmin,
  listOrgAttestorDocumentsForAdmin,
  orgAttestorNeedsInfo,
  startOrgAttestorTrial,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
  configureBrowserClient: vi.fn(),
}));
vi.mock("@/lib/auth/current-user-session", () => ({ loadCurrentUserSession: vi.fn(async () => ({ isSuperAdmin: true })) }));
vi.mock("@/lib/generated/sdk.gen", () => ({
  adminDecideTrialV1AdminOrgAttestorApplicationsApplicationIdTrialDecidePost: vi.fn(),
  adminGetTrialGradeV1AdminOrgAttestorApplicationsApplicationIdTrialGet: vi.fn(),
  adminListCalibrationFixturesV1AdminOrgAttestorApplicationsCalibrationFixturesGet: vi.fn(),
  listOrgAttestorApplicationsForAdmin: vi.fn(),
  listOrgAttestorDocumentsForAdmin: vi.fn(),
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
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(adminListCalibrationFixtures).mockResolvedValue(
      ok({
        fixtures: [
          { id: "fixture-1", title: "Quality Fixture", review_type: "quality" },
          { id: "fixture-2", title: "Compliance Fixture", review_type: "compliance" },
        ],
      }) as never,
    );
  });

  it("loads and renders document links on view", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", org_name: "Audit Ltd", status: "submitted", kyb_status: "unverified", created_at: "2026-07-07T12:00:00Z", reviewed_at: null }],
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
        { id: "app-1", org_id: "org-1", org_name: "Kyb Stage", status: "submitted", kyb_status: "unverified", trial_status: null, created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
        // Stage 2: KYB done, no trial → only Start Trial active.
        { id: "app-2", org_id: "org-2", org_name: "Trial Stage", status: "submitted", kyb_status: "verified", trial_status: null, created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
        // Stage 3: KYB done, trial passed → only Approve active.
        { id: "app-3", org_id: "org-3", org_name: "Approve Stage", status: "submitted", kyb_status: "verified", trial_status: "passed", created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
      ],
      total: 3,
      page: 1,
      page_size: 10
    }));
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Kyb Stage/));

    const start = screen.getAllByRole("button", { name: /start trial/i });
    const approve = screen.getAllByRole("button", { name: /^approve$/i });

    // app-1: unverified, so this queue offers no action at all — the verdict
    // is recorded on the organizations queue and only linked to from here.
    expect(
      screen.getAllByRole("link", { name: /verify in organizations/i }),
    ).toHaveLength(1);
    expect(start[0]).toBeDisabled();
    expect(approve[0]).toBeDisabled();
    // app-2: verified, no trial → Start Trial is the live step.
    expect(start[1]).toBeDisabled();
    expect(approve[1]).toBeDisabled();
    // app-3: verified and trial passed → Approve.
    expect(start[2]).toBeDisabled();
    expect(approve[2]).not.toBeDisabled();
  });

  it("holds Start Trial after assigning it, without a page reload", async () => {
    // Start Trial returns the application response (no trial_status). If the
    // panel does not reflect the freshly-assigned trial locally, the button
    // re-enables and the admin can re-assign — the reported flicker.
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [
        { id: "app-1", org_id: "org-1", org_name: "Ready Org", status: "submitted", kyb_status: "verified", trial_status: null, created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
      ],
      total: 1,
      page: 1,
      page_size: 10
    }));
    vi.mocked(startOrgAttestorTrial).mockResolvedValue(
      ok({ id: "app-1", status: "submitted", kyb_status: "verified" }) as never,
    );
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: /Ready Org/i }),
      ).toBeInTheDocument(),
    );

    fireEvent.change(screen.getByLabelText(/Calibration fixture for Ready Org/i), {
      target: { value: "fixture-1" },
    });
    const start = screen.getByRole("button", { name: /start trial/i });
    expect(start).not.toBeDisabled();
    fireEvent.click(start);
    await screen.findByText(/Trial assigned/i);
    await waitFor(() =>
      expect(vi.mocked(startOrgAttestorTrial)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { application_id: "app-1" },
          body: { framework_id: "fixture-1" },
        }),
      ),
    );
    // The gate must advance: Start Trial locks and the next-step copy flips.
    expect(screen.getByRole("button", { name: /start trial/i })).toBeDisabled();
    expect(screen.getByText(/Waiting on the nominee/i)).toBeTruthy();
  });

  it("holds Start Trial while a trial is pending and offers a retry after a failure", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [
        // Trial assigned but not decided → Start Trial held.
        { id: "app-1", org_id: "org-1", org_name: "Pending Trial", status: "submitted", kyb_status: "verified", trial_status: "assigned", created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
        // Trial failed → Start Trial live again for a retry, Approve still blocked.
        { id: "app-2", org_id: "org-2", org_name: "Failed Trial", status: "submitted", kyb_status: "verified", trial_status: "failed", created_at: "2026-07-07T12:00:00Z", reviewed_at: null },
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
    expect(start[1]).toBeDisabled();
    expect(approve[0]).toBeDisabled();
    expect(approve[1]).toBeDisabled();
    expect(screen.getByText(/Waiting on the nominee/i)).toBeTruthy();
  });

  it("fills the needs-info feedback from a preset and sends it", async () => {
    // The preset must save the admin retyping the same send-back guidance and
    // reach the endpoint verbatim as the feedback body.
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", org_name: "Audit Ltd", status: "submitted", kyb_status: "unverified", created_at: "2026-07-07T12:00:00Z", reviewed_at: null }],
      total: 1,
      page: 1,
      page_size: 10,
    }));
    vi.mocked(orgAttestorNeedsInfo).mockResolvedValue(
      ok({ id: "app-1", status: "needs_info" }) as never,
    );
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Audit Ltd/));

    // "Needs Info" matches both the status filter tab and the card action, so
    // scope to the card action via its sibling Approve button.
    const approve = screen.getByRole("button", { name: /^approve$/i });
    const actionRow = within(approve.parentElement as HTMLElement);
    fireEvent.click(actionRow.getByRole("button", { name: /^needs info$/i }));
    fireEvent.click(screen.getByRole("button", { name: /payout account/i }));

    const textarea = screen.getByRole("textbox");
    expect((textarea as HTMLTextAreaElement).value).toMatch(/connect a payout account/i);

    fireEvent.click(screen.getByRole("button", { name: /confirm needs info/i }));
    await waitFor(() =>
      expect(vi.mocked(orgAttestorNeedsInfo)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { application_id: "app-1" },
          body: { feedback: expect.stringMatching(/connect a payout account/i) },
        }),
      ),
    );
  });

  it("loads the submitted trial grade view and lets the admin pass it", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(
      ok({
        applications: [
          {
            id: "app-1",
            org_id: "org-1",
            org_name: "Review Org",
            status: "submitted",
            kyb_status: "verified",
            trial_status: "submitted",
            created_at: "2026-07-07T12:00:00Z",
            reviewed_at: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
      }),
    );
    vi.mocked(adminGetTrialGrade).mockResolvedValue(
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
      }) as never,
    );
    vi.mocked(adminDecideTrial).mockResolvedValue(
      ok({
        id: "app-1",
        status: "submitted",
        kyb_status: "verified",
      }) as never,
    );

    render(<AdminOrgAttestorReviewPanel />);

    await waitFor(() => screen.getByText(/Review Org/));
    expect(await screen.findByText(/84.50%/i)).toBeInTheDocument();
    expect(
      screen.getByText((_, element) =>
        element?.textContent === "Suggested result: pass",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Pass Trial/i }));

    await waitFor(() =>
      expect(vi.mocked(adminDecideTrial)).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { application_id: "app-1" },
          body: { result: "pass", feedback: undefined },
        }),
      ),
    );
    expect(
      await screen.findByText((_, element) =>
        element?.textContent === "Trial Status: passed",
      ),
    ).toBeInTheDocument();
  });

  it("enables only the valid capability transitions for an active capability", async () => {
    // Active capability: suspend and revoke apply; reinstate does not. All three
    // must never be live at once.
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", org_name: "Active Org", status: "approved", kyb_status: "verified", trial_status: "passed", capability_status: "active", created_at: "2026-07-07T12:00:00Z", reviewed_at: "2026-07-07T12:00:00Z" }],
      total: 1, page: 1, page_size: 10,
    }) as never);
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Active Org/));

    expect(screen.getByRole("button", { name: /^suspend$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^reinstate$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^revoke$/i })).toBeEnabled();
  });

  it("enables reinstate and revoke, not suspend, for a suspended capability", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", org_name: "Suspended Org", status: "approved", kyb_status: "verified", trial_status: "passed", capability_status: "suspended", created_at: "2026-07-07T12:00:00Z", reviewed_at: "2026-07-07T12:00:00Z" }],
      total: 1, page: 1, page_size: 10,
    }) as never);
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Suspended Org/));

    expect(screen.getByRole("button", { name: /^suspend$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^reinstate$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^revoke$/i })).toBeEnabled();
  });

  it("enables the capability controls right after an in-place approve, without a refetch", async () => {
    // Approving from the queue activates the capability server-side. The row's
    // stale capability_status ("pending") must flip to "active" locally, or all
    // three controls stay disabled until the admin manually refetches.
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", org_name: "Fresh Org", status: "submitted", kyb_status: "verified", trial_status: "passed", capability_status: "pending", created_at: "2026-07-07T12:00:00Z", reviewed_at: null }],
      total: 1, page: 1, page_size: 10,
    }) as never);
    vi.mocked(approveOrgAttestor).mockResolvedValue(
      ok({ id: "app-1", status: "approved" }) as never,
    );
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Fresh Org/));

    fireEvent.click(screen.getByRole("button", { name: /^approve$/i }));
    await screen.findByText(/capability activated/i);

    expect(screen.getByRole("button", { name: /^suspend$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^revoke$/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /^reinstate$/i })).toBeDisabled();
  });

  it("disables every capability control once the capability is revoked", async () => {
    vi.mocked(listOrgAttestorApplicationsForAdmin).mockResolvedValue(ok({
      applications: [{ id: "app-1", org_id: "org-1", org_name: "Revoked Org", status: "approved", kyb_status: "verified", trial_status: "passed", capability_status: "revoked", created_at: "2026-07-07T12:00:00Z", reviewed_at: "2026-07-07T12:00:00Z" }],
      total: 1, page: 1, page_size: 10,
    }) as never);
    render(<AdminOrgAttestorReviewPanel />);
    await waitFor(() => screen.getByText(/Revoked Org/));

    expect(screen.getByRole("button", { name: /^suspend$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^reinstate$/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^revoke$/i })).toBeDisabled();
  });
});
