import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AdminAttestorsConsole } from "@/components/modules/admin/attestors/admin-attestors-console";

const nav = vi.hoisted(() => ({
  replace: vi.fn(),
  params: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => "/admin/attestors",
  useSearchParams: () => nav.params,
}));

const sdk = vi.hoisted(() => ({
  listApplications: vi.fn(),
  listFixtures: vi.fn(),
  listDocuments: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listOrgAttestorApplicationsForAdmin: sdk.listApplications,
  adminListCalibrationFixturesV1AdminOrgAttestorApplicationsCalibrationFixturesGet:
    sdk.listFixtures,
  listOrgAttestorDocumentsForAdmin: sdk.listDocuments,
  approveOrgAttestor: vi.fn(),
  orgAttestorNeedsInfo: vi.fn(),
  rejectOrgAttestor: vi.fn(),
  startOrgAttestorTrial: vi.fn(),
  // The grader loads on mount; give it a settled response so the test run
  // never sees an unhandled rejection from an undefined result.
  adminGetTrialGradeV1AdminOrgAttestorApplicationsApplicationIdTrialGet: vi.fn(
    async () => ({ data: undefined, error: { detail: "none" }, response: { ok: false } }),
  ),
  adminDecideTrialV1AdminOrgAttestorApplicationsApplicationIdTrialDecidePost: vi.fn(),
  suspendOrgAttestorCapability: vi.fn(),
  reinstateOrgAttestorCapability: vi.fn(),
  revokeOrgAttestorCapability: vi.fn(),
}));

vi.mock("@/components/modules/admin/admin-calibration-fixtures-panel", () => ({
  AdminCalibrationFixturesPanel: () => <div>Fixtures panel</div>,
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer admin" })),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

function row(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    org_id: `org-${id}`,
    org_name: `Org ${id}`,
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

describe("AdminAttestorsConsole", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nav.params = new URLSearchParams();
    sdk.listFixtures.mockResolvedValue(ok({ fixtures: [] }));
    sdk.listDocuments.mockResolvedValue(ok({ documents: [] }));
    sdk.listApplications.mockImplementation(async ({ query }: { query: { status: string } }) => {
      if (query.status === "submitted") {
        return ok({ applications: [row("a"), row("b")], total: 2, page: 1, page_size: 10 });
      }
      if (query.status === "trial") {
        return ok({
          applications: [row("t", { trial_status: "submitted" })],
          total: 1,
          page: 1,
          page_size: 10,
        });
      }
      return ok({ applications: [], total: 0, page: 1, page_size: 10 });
    });
  });

  it("opens on Applications with counts on the Applications and Trials tabs", async () => {
    render(<AdminAttestorsConsole />);

    expect(await screen.findByRole("heading", { name: "Org a" })).toBeInTheDocument();
    const applications = screen.getByRole("tab", { name: /Applications/ });
    expect(applications).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(applications).toHaveTextContent("2"));
    expect(screen.getByRole("tab", { name: /Trials/ })).toHaveTextContent("1");
  });

  it("switches to Trials, writes the tab to the URL, and opens the trial cards", async () => {
    render(<AdminAttestorsConsole />);
    await screen.findByRole("heading", { name: "Org a" });

    fireEvent.click(screen.getByRole("tab", { name: /Trials/ }));

    expect(await screen.findByRole("heading", { name: "Org t" })).toBeInTheDocument();
    expect(nav.replace).toHaveBeenCalledWith("/admin/attestors?tab=trials", { scroll: false });
    expect(screen.getByText(/Trials assigned, awaiting a grade/)).toBeInTheDocument();
  });

  it("lands on the tab named in the URL", async () => {
    nav.params = new URLSearchParams("tab=fixtures");
    render(<AdminAttestorsConsole />);

    expect(await screen.findByText("Fixtures panel")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Fixtures" })).toHaveAttribute("aria-selected", "true");
  });

  it("filters the application queue by status", async () => {
    render(<AdminAttestorsConsole />);
    await screen.findByRole("heading", { name: "Org a" });

    fireEvent.click(screen.getByRole("button", { name: "Rejected" }));

    expect(await screen.findByText("No applications in this status.")).toBeInTheDocument();
    expect(sdk.listApplications).toHaveBeenCalledWith(
      expect.objectContaining({ query: { status: "rejected" } }),
    );
  });
});
