import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listMyOrganizationsV1OrgsMineGet as listMyOrgs,
  getOrgNda,
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost as activateOperator,
} from "@/lib/generated/sdk.gen";
import { OrganizationShell } from "./organization-shell";
import { ATTESTOR_APPLICATION_CHANGED_EVENT } from "@/lib/organizations/org-events";
import { OrganizationCapabilities } from "./organization-capabilities";

let mockPathname = "/dashboard/organizations/org-1";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => mockPathname,
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
  getOrgNda: vi.fn(),
  activateOperatorCapabilityV1OrgsOrgIdOperatorCapabilityActivatePost: vi.fn(),
  activateContributorCapabilityV1OrgsOrgIdContributorCapabilityActivatePost: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}));

function mockOrg(capabilities: Record<string, string>) {
  vi.mocked(listMyOrgs).mockResolvedValue({
    response: { ok: true },
    data: {
      organizations: [
        {
          org: { id: "org-1", name: "Test Org" },
          role: "member",
          kyb_status: "verified",
          capabilities,
        },
      ],
    },
  } as never);
}

describe("OrganizationShell contributor Frameworks tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1";
    vi.mocked(getOrgNda).mockResolvedValue({
      data: {
        required: false,
        current_version: "1.0",
        signed_version: null,
        signed_at: null,
      },
    } as never);
  });

  it("shows Frameworks to a plain member with the contributor grant", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "member",
            kyb_status: "verified",
            capabilities: { contributor: "active" },
            grants: { contributor: true },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(
      await screen.findByRole("tab", { name: /^Frameworks$/i }),
    ).toBeInTheDocument();
  });

  it("hides Frameworks from an ungranted plain member", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "member",
            kyb_status: "verified",
            capabilities: { contributor: "active" },
            grants: { contributor: false },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    await screen.findByRole("tab", { name: /Members/i });
    expect(
      screen.queryByRole("tab", { name: /^Frameworks$/i }),
    ).not.toBeInTheDocument();
  });

  it("shows Frameworks to an admin when contributor is active", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "admin",
            kyb_status: "verified",
            capabilities: { contributor: "active" },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(
      await screen.findByRole("tab", { name: /^Frameworks$/i }),
    ).toBeInTheDocument();
  });
});

describe("OrganizationShell member Operator library access", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1";
    vi.mocked(getOrgNda).mockResolvedValue({
      data: {
        required: false,
        current_version: "1.0",
        signed_version: null,
        signed_at: null,
      },
    } as never);
  });

  it("shows Operator without admin-only Projects or Financials to a member", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "member",
            kyb_status: "verified",
            capabilities: { operator: "active" },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(
      await screen.findByRole("tab", { name: /^Operator$/i }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /^Projects$/i })).toBeNull();
    expect(screen.queryByRole("tab", { name: /^Financials$/i })).toBeNull();
  });
});

describe("OrganizationShell NDA tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the NDA tab when the NDA is required (live application, no capability)", async () => {
    mockOrg({});
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: true, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(await screen.findByRole("tab", { name: /NDA/i })).toBeTruthy();
  });

  it("hides the NDA tab when the NDA is not required", async () => {
    mockOrg({});
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: false, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    // Members tab always renders once loaded; wait for it, then assert no NDA tab.
    await screen.findByRole("tab", { name: /Members/i });
    expect(screen.queryByRole("tab", { name: /NDA/i })).toBeNull();
  });

  it("flags the NDA tab with a dot when required but unsigned", async () => {
    mockOrg({});
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: true, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    await screen.findByRole("tab", { name: /NDA/i });
    expect(screen.getByLabelText(/NDA signature required/i)).toBeInTheDocument();
  });

  it("clears the NDA dot on the nda-signed event without a manual refresh", async () => {
    mockOrg({});
    // First load: required + unsigned -> dot shows.
    vi.mocked(getOrgNda).mockResolvedValueOnce({
      data: { required: true, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);
    // After signing, the re-check reports it signed.
    vi.mocked(getOrgNda).mockResolvedValueOnce({
      data: {
        required: true,
        current_version: "1.0",
        signed_version: "1.0",
        signed_at: "2026-07-16T00:00:00Z",
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);
    expect(await screen.findByLabelText(/NDA signature required/i)).toBeInTheDocument();

    window.dispatchEvent(new Event("auracles:nda-signed"));

    await vi.waitFor(() => {
      expect(screen.queryByLabelText(/NDA signature required/i)).not.toBeInTheDocument();
    });
  });

  it("shows no NDA dot once the member has signed", async () => {
    mockOrg({});
    vi.mocked(getOrgNda).mockResolvedValue({
      data: {
        required: true,
        current_version: "1.0",
        signed_version: "1.0",
        signed_at: "2026-07-16T00:00:00Z",
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    await screen.findByRole("tab", { name: /NDA/i });
    expect(screen.queryByLabelText(/NDA signature required/i)).not.toBeInTheDocument();
  });
});

describe("OrganizationShell action-count badges", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1";
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: false, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);
  });

  it("keeps the Queue tab active on the attestation workspace sub-route", async () => {
    mockPathname = "/dashboard/organizations/org-1/attestations/att-9";
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
            kyb_status: "verified",
            capabilities: { attestor: "active" },
            counts: { offers: 0, queue: 1, invitations: 0 },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    const queueTab = await screen.findByRole("tab", { name: /Queue/i });
    expect(queueTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Profile/i })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("shows offer, queue, and invitation counts on the admin tabs", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
            kyb_status: "verified",
            capabilities: { attestor: "active" },
            counts: { offers: 2, queue: 3, invitations: 1 },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(await screen.findByRole("tab", { name: /Offers/i })).toHaveTextContent("2");
    expect(screen.getByRole("tab", { name: /Queue/i })).toHaveTextContent("3");
    expect(screen.getByRole("tab", { name: /Invitations/i })).toHaveTextContent("1");
  });

  it("refetches counts when the window regains focus", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
            kyb_status: "verified",
            capabilities: { attestor: "active" },
            counts: { offers: 0, queue: 0, invitations: 0 },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);
    await screen.findByRole("tab", { name: /Offers/i });
    const initialCalls = vi.mocked(listMyOrgs).mock.calls.length;

    window.dispatchEvent(new Event("focus"));

    await vi.waitFor(() => {
      expect(vi.mocked(listMyOrgs).mock.calls.length).toBeGreaterThan(initialCalls);
    });
  });

  it("shows the Queue tab to a plain member of an active attestor org", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "member",
            kyb_status: "verified",
            capabilities: { attestor: "active" },
            counts: { offers: 0, queue: 0, invitations: 0 },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(await screen.findByRole("tab", { name: /Queue/i })).toBeInTheDocument();
    // Admin-only tabs stay hidden for a plain member.
    expect(screen.queryByRole("tab", { name: /Offers/i })).toBeNull();
  });

  it("shows a member's own assigned-task count on the Queue tab", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "member",
            kyb_status: "verified",
            capabilities: { attestor: "active" },
            counts: { offers: 0, queue: 2, invitations: 0 },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(await screen.findByRole("tab", { name: /Queue/i })).toHaveTextContent("2");
  });

  it("renders no count badge when there is nothing to attend to", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
            kyb_status: "verified",
            capabilities: { attestor: "active" },
            counts: { offers: 0, queue: 0, invitations: 0 },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    const offersTab = await screen.findByRole("tab", { name: /Offers/i });
    expect(offersTab).toHaveTextContent(/^Offers$/);
  });
});

describe("OrganizationShell capability activation refresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1";
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: false, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);
  });

  it("shows the new Operator tab immediately after activating the operator capability", async () => {
    vi.mocked(listMyOrgs)
      .mockResolvedValueOnce({
        response: { ok: true },
        data: {
          organizations: [
            {
              org: { id: "org-1", name: "Test Org" },
              role: "owner",
              kyb_status: "verified",
              capabilities: {},
              counts: { offers: 0, queue: 0, invitations: 0 },
            },
          ],
        },
      } as never)
      .mockResolvedValueOnce({
        response: { ok: true },
        data: {
          organizations: [
            {
              org: { id: "org-1", name: "Test Org" },
              role: "owner",
              kyb_status: "verified",
              capabilities: { operator: "active" },
              counts: { offers: 0, queue: 0, invitations: 0 },
            },
          ],
        },
      } as never);
    vi.mocked(activateOperator).mockResolvedValue({
      response: { ok: true },
    } as never);

    render(
      <OrganizationShell orgId="org-1">
        <OrganizationCapabilities />
      </OrganizationShell>,
    );

    await screen.findByRole("tab", { name: /Profile/i });
    expect(screen.queryByRole("tab", { name: /^Operator$/i })).toBeNull();

    fireEvent.click(
      await screen.findByRole("button", { name: "Activate Operator capability" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Activate Operator" }));

    expect(await screen.findByRole("tab", { name: /^Operator$/i })).toBeInTheDocument();
  });
});


describe("OrganizationShell unverified organization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1";
    vi.mocked(getOrgNda).mockResolvedValue({
      data: {
        required: true,
        current_version: "1.0",
        signed_version: null,
        signed_at: null,
      },
    } as never);
  });

  it("keeps people tabs open and gates only capability tabs (Decision 2)", async () => {
    // Members, invitations and teams are open from day one; capability
    // surfaces (frameworks, operator, NDA, calibration) wait on verification.
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
            kyb_status: "unverified",
            capabilities: { contributor: "active", operator: "active" },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">{null}</OrganizationShell>);

    expect(await screen.findByText("Verification")).toBeInTheDocument();
    expect(screen.getByText("Profile")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Members$/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Teams$/ })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Invitations/ })).toBeInTheDocument();
    expect(screen.queryByText("Calibration Trial")).toBeNull();
    expect(screen.queryByText("Frameworks")).toBeNull();
    expect(screen.queryByText("Operator")).toBeNull();
    expect(screen.queryByText("NDA")).toBeNull();
    expect(
      screen.getByText(/not verified yet/i),
    ).toBeInTheDocument();
  });
});

describe("OrganizationShell status banners", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1";
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: false, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);
  });

  it("explains a platform suspension with the admin's reason, date, and a support link", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: {
              id: "org-1",
              name: "Test Org",
              suspended_at: "2026-09-13T10:00:00Z",
              suspension_reason: "Repeated chargebacks on operator purchases.",
            },
            role: "owner",
            kyb_status: "verified",
            capabilities: {},
            capability_reasons: {},
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(await screen.findByText(/organization suspended/i)).toBeInTheDocument();
    expect(
      screen.getByText("Repeated chargebacks on operator purchases."),
    ).toBeInTheDocument();
    expect(screen.getByText(/13 Sep(t)? 2026|Sep(t)? 13, 2026/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /contact support/i })).toHaveAttribute(
      "href",
      expect.stringMatching(/^mailto:/),
    );
  });

  it("shows a banner with the reason for each suspended or revoked capability", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org", suspended_at: null },
            role: "owner",
            kyb_status: "verified",
            capabilities: { contributor: "suspended", attestor: "revoked", operator: "active" },
            capability_reasons: {
              contributor: "Artifacts failed the malware scan twice.",
              attestor: "Calibration drift after two disputes.",
            },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(await screen.findByText(/contributor capability suspended/i)).toBeInTheDocument();
    expect(screen.getByText("Artifacts failed the malware scan twice.")).toBeInTheDocument();
    expect(screen.getByText(/attestor capability revoked/i)).toBeInTheDocument();
    expect(screen.getByText("Calibration drift after two disputes.")).toBeInTheDocument();
    expect(screen.queryByText(/operator capability/i)).not.toBeInTheDocument();
  });
});

describe("OrganizationShell header", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1";
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: false, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);
  });

  it("renders the caller's role as a status pill", async () => {
    mockOrg({});
    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    const pill = await screen.findByText("Member");
    expect(pill.className).toMatch(/rounded-badge/);
  });

  it("does not send an unverified org's members deep link to verification", async () => {
    mockPathname = "/dashboard/organizations/org-1/members";
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          { org: { id: "org-1", name: "Test Org" }, role: "owner", kyb_status: "unverified", capabilities: {} },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">members-page</OrganizationShell>);

    expect(await screen.findByText("members-page")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /^Members$/ })).toHaveAttribute("aria-selected", "true");
  });
});

describe("OrganizationShell Offers tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1";
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: false, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);
  });

  it("hides Offers from an owner until the attestor capability is active", async () => {
    // Offers are attestation requests sent to attestor organizations; before
    // approval the tab could only ever be empty. The Attestor tab, where the
    // application lives, stays visible.
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
            kyb_status: "verified",
            capabilities: { contributor: "active", operator: "active" },
            counts: { offers: 0, queue: 0, invitations: 0 },
          },
        ],
      },
    } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);

    expect(await screen.findByRole("tab", { name: /^Attestor$/i })).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /Offers/i })).toBeNull();
  });
});

describe("OrganizationShell NDA tab after an attestor application is saved", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPathname = "/dashboard/organizations/org-1/attestor";
  });

  it("shows the NDA tab as soon as the application changes, without a reload", async () => {
    // Saving the first draft makes the NDA required; the shell only re-read
    // NDA status on mount, focus, or signing, so the tab stayed hidden.
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
            kyb_status: "verified",
            capabilities: {},
            counts: { offers: 0, queue: 0, invitations: 0 },
          },
        ],
      },
    } as never);
    vi.mocked(getOrgNda)
      .mockResolvedValueOnce({
        data: { required: false, current_version: "1.0", signed_version: null, signed_at: null },
      } as never)
      .mockResolvedValue({
        data: { required: true, current_version: "1.0", signed_version: null, signed_at: null },
      } as never);

    render(<OrganizationShell orgId="org-1">child</OrganizationShell>);
    await screen.findByRole("tab", { name: /^Attestor$/i });
    expect(screen.queryByRole("tab", { name: /NDA/i })).toBeNull();

    act(() => {
      window.dispatchEvent(new Event(ATTESTOR_APPLICATION_CHANGED_EVENT));
    });

    expect(await screen.findByRole("tab", { name: /NDA/i })).toBeInTheDocument();
  });
});
