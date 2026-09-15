/**
 * Behaviour of the admin organization detail page: the header and lifecycle
 * banner, lazy per-tab loading, and what each tab surfaces to an admin.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AdminOrganizationDetailPage from "@/app/(auth)/admin/organizations/[orgId]/page";
import {
  adminOrgAttestationsV1AdminOrgsOrgIdAttestationsGet as getAttestations,
  adminOrgAuditV1AdminOrgsOrgIdAuditGet as getAudit,
  adminOrgFinancialsV1AdminOrgsOrgIdFinancialsGet as getFinancials,
  adminOrgFrameworksV1AdminOrgsOrgIdFrameworksGet as getFrameworks,
  adminOrgMembersV1AdminOrgsOrgIdMembersGet as getMembers,
  adminOrgOverviewV1AdminOrgsOrgIdDetailGet as getOverview,
  adminOrgVerificationV1AdminOrgsOrgIdVerificationGet as getVerification,
} from "@/lib/generated/sdk.gen";

import {
  ATTESTATIONS,
  FINANCIALS,
  FRAMEWORKS,
  MEMBERS,
  VERIFICATION,
  auditPage,
  fail,
  ok,
  overview,
} from "./fixtures";

const nav = vi.hoisted(() => ({
  replace: vi.fn(),
  params: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace, push: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/organizations/org-1",
  useSearchParams: () => nav.params,
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  adminOrgOverviewV1AdminOrgsOrgIdDetailGet: vi.fn(),
  adminOrgMembersV1AdminOrgsOrgIdMembersGet: vi.fn(),
  adminOrgVerificationV1AdminOrgsOrgIdVerificationGet: vi.fn(),
  adminOrgFinancialsV1AdminOrgsOrgIdFinancialsGet: vi.fn(),
  adminOrgFrameworksV1AdminOrgsOrgIdFrameworksGet: vi.fn(),
  adminOrgAttestationsV1AdminOrgsOrgIdAttestationsGet: vi.fn(),
  adminOrgAuditV1AdminOrgsOrgIdAuditGet: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "Request failed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer admin" }),
}));

// The real dialog drives step-up capability transitions; here it only needs
// to report one change so the overview can be seen to update.
vi.mock("@/components/modules/admin/org-capabilities-dialog", () => ({
  OrgCapabilitiesDialog: ({
    onChanged,
    onClose,
  }: {
    onChanged: (capability: string, status: string, reason: string | null) => void;
    onClose: () => void;
  }) => (
    <div role="dialog">
      <button onClick={() => onChanged("contributor", "suspended", "Malware found.")} type="button">
        Suspend contributor
      </button>
      <button onClick={onClose} type="button">
        Close dialog
      </button>
    </div>
  ),
}));

async function renderPage() {
  render(await AdminOrganizationDetailPage({ params: Promise.resolve({ orgId: "org-1" }) }));
  await screen.findByRole("heading", { level: 1, name: "Kano Audit Partners" });
}

function openTab(name: string) {
  fireEvent.click(screen.getByRole("tab", { name }));
}

describe("AdminOrganizationDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nav.params = new URLSearchParams();
    vi.mocked(getOverview).mockResolvedValue(ok(overview()));
    vi.mocked(getMembers).mockResolvedValue(ok(MEMBERS));
    vi.mocked(getVerification).mockResolvedValue(ok(VERIFICATION));
    vi.mocked(getFinancials).mockResolvedValue(ok(FINANCIALS));
    vi.mocked(getFrameworks).mockResolvedValue(ok(FRAMEWORKS));
    vi.mocked(getAttestations).mockResolvedValue(ok(ATTESTATIONS));
    vi.mocked(getAudit).mockImplementation((options) =>
      Promise.resolve(ok(auditPage(options.query?.page ?? 1))),
    );
  });

  it("renders the header with back link, public profile link and pills", async () => {
    await renderPage();

    expect(getOverview).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" } }),
    );
    expect(screen.getByRole("link", { name: /organizations/i })).toHaveAttribute(
      "href",
      "/admin/organizations",
    );
    expect(screen.getByRole("link", { name: "@kano-audit" })).toHaveAttribute(
      "href",
      "/orgs/kano-audit",
    );
    const header = screen.getByRole("banner");
    expect(within(header).getByText("Active")).toBeInTheDocument();
    expect(within(header).getByText("Verified")).toBeInTheDocument();
    expect(within(header).getByText(/1 Sep 2026/)).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: /suspended/i })).not.toBeInTheDocument();
  });

  it("shows a suspension banner with the date, reason and acting admin", async () => {
    vi.mocked(getOverview).mockResolvedValue(
      ok(
        overview({
          suspended_at: "2026-09-12T08:00:00Z",
          suspended_by: { id: "u-9", display_name: "Grace Admin" },
          suspension_reason: "Chargeback pattern under investigation.",
        }),
      ),
    );
    await renderPage();

    const banner = screen.getByRole("status", { name: /suspended/i });
    expect(banner).toHaveTextContent("12 Sep 2026");
    expect(banner).toHaveTextContent("Chargeback pattern under investigation.");
    expect(banner).toHaveTextContent("Grace Admin");
    expect(within(screen.getByRole("banner")).getByText("Suspended")).toBeInTheDocument();
  });

  it("shows owners, capabilities with reasons and member count on Overview", async () => {
    await renderPage();

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("Amina Bello");
    expect(panel).toHaveTextContent("amina@kano.example");
    expect(panel).toHaveTextContent("Two chargebacks this month.");
    expect(panel).toHaveTextContent("4 members");
    expect(within(panel).getByText("Operator suspended")).toBeInTheDocument();
  });

  it("updates the overview after a capability change in the dialog", async () => {
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "Manage capabilities" }));
    fireEvent.click(screen.getByRole("button", { name: "Suspend contributor" }));

    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("Contributor suspended")).toBeInTheDocument();
    expect(panel).toHaveTextContent("Malware found.");
    expect(getOverview).toHaveBeenCalledTimes(1);
  });

  it("opens the tab named in ?tab= and records tab changes in the URL", async () => {
    nav.params = new URLSearchParams("tab=members");
    await renderPage();

    expect(screen.getByRole("tab", { name: "Members" })).toHaveAttribute("aria-selected", "true");
    await screen.findByText("Tunde Okafor");

    openTab("Frameworks");
    expect(nav.replace).toHaveBeenCalledWith("/admin/organizations/org-1?tab=frameworks", {
      scroll: false,
    });
  });

  it("loads Members once on first open and shows role, teams and invitations", async () => {
    await renderPage();
    expect(getMembers).not.toHaveBeenCalled();

    openTab("Members");
    const panel = await screen.findByRole("tabpanel");
    await within(panel).findByText("Tunde Okafor");
    expect(panel).toHaveTextContent("tunde@kano.example");
    expect(within(panel).getByText("Admin")).toBeInTheDocument();
    expect(panel).toHaveTextContent("Assurance");
    expect(panel).toHaveTextContent("4 Sep 2026");
    expect(panel).toHaveTextContent("2 pending invitations");

    openTab("Overview");
    openTab("Members");
    expect(getMembers).toHaveBeenCalledTimes(1);
  });

  it("links verification documents with the expiry and audit note", async () => {
    await renderPage();
    openTab("Verification");

    const open = await screen.findByRole("link", { name: /open cac\.pdf/i });
    expect(open).toHaveAttribute("href", "https://s3.example/cac.pdf?sig=1");
    expect(open).toHaveAttribute("target", "_blank");
    expect(open).toHaveAttribute("rel", "noopener noreferrer");
    expect(open.className).toMatch(/min-h-11/);
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent(
      "Links expire after 5 minutes. Opening documents is recorded in the audit log.",
    );
    expect(panel).toHaveTextContent("Not uploaded");
    expect(panel).toHaveTextContent("RC-778812");
    expect(panel).toHaveTextContent("12 Bompai Road");
    expect(panel).toHaveTextContent("Tax document was blurry on first submission.");
    expect(panel).toHaveTextContent("Tax Clearance Certificate (TCC)");
    expect(getVerification).toHaveBeenCalledTimes(1);
  });

  it("formats financials in the response currency", async () => {
    await renderPage();
    openTab("Financials");

    const panel = await screen.findByRole("tabpanel");
    await within(panel).findByText("₦150,000");
    expect(panel).toHaveTextContent("₦25,000");
    expect(panel).toHaveTextContent("₦900,000");
    expect(panel).toHaveTextContent("₦420,000");
    expect(panel).not.toHaveTextContent("$");
    expect(within(panel).getByText("Paid")).toBeInTheDocument();
    expect(panel).toHaveTextContent("Framework Purchase");
    expect(getFinancials).toHaveBeenCalledTimes(1);
  });

  it("lists frameworks with explore links only when published, and licenses", async () => {
    await renderPage();
    openTab("Frameworks");

    const link = await screen.findByRole("link", { name: "Supplier Risk Playbook" });
    expect(link).toHaveAttribute("href", "/explore/fw-1");
    expect(screen.queryByRole("link", { name: "Draft Controls Map" })).not.toBeInTheDocument();
    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveTextContent("Draft Controls Map");
    expect(panel).toHaveTextContent("Payroll Audit Kit");
    expect(panel).toHaveTextContent("3 grants");
    expect(getFrameworks).toHaveBeenCalledTimes(1);
  });

  it("lists attestations in flight with admin status, reviewer and due date", async () => {
    await renderPage();
    openTab("Attestations");

    const panel = await screen.findByRole("tabpanel");
    await within(panel).findByText("Supplier Risk Playbook");
    expect(within(panel).getByText("Submitted")).toBeInTheDocument();
    expect(panel).toHaveTextContent("Tunde Okafor");
    expect(panel).toHaveTextContent("20 Sep 2026");
    expect(panel).toHaveTextContent("1 in flight");
    expect(panel).toHaveTextContent("5 completed");
    expect(getAttestations).toHaveBeenCalledTimes(1);
  });

  it("shows audit entries and requests page 2 on Next", async () => {
    await renderPage();
    openTab("Audit");

    const panel = await screen.findByRole("tabpanel");
    await within(panel).findByText("Grace Admin");
    expect(panel).toHaveTextContent("Org kyb document viewed");
    expect(within(panel).getByText("Details")).toBeInTheDocument();
    expect(getAudit).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1" }, query: { page: 1, page_size: 20 } }),
    );

    fireEvent.click(within(panel).getByRole("button", { name: "Next" }));
    await within(panel).findByText("System");
    expect(getAudit).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: { page: 2, page_size: 20 } }),
    );
    expect(within(panel).getByRole("button", { name: "Next" })).toBeDisabled();
  });

  it("describes a failed tab load and refetches on Retry", async () => {
    vi.mocked(getMembers).mockResolvedValueOnce(fail());
    await renderPage();
    openTab("Members");

    const panel = await screen.findByRole("tabpanel");
    await within(panel).findByText("Server unavailable.");
    fireEvent.click(within(panel).getByRole("button", { name: "Retry" }));

    await within(panel).findByText("Tunde Okafor");
    await waitFor(() => expect(getMembers).toHaveBeenCalledTimes(2));
  });
});
