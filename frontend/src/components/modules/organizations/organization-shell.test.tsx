import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  listMyOrganizationsV1OrgsMineGet as listMyOrgs,
  getOrgNda,
} from "@/lib/generated/sdk.gen";
import { OrganizationShell } from "./organization-shell";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/dashboard/organizations/org-1",
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
  getOrgNda: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));

function mockOrg(capabilities: Record<string, string>) {
  vi.mocked(listMyOrgs).mockResolvedValue({
    response: { ok: true },
    data: {
      organizations: [
        {
          org: { id: "org-1", name: "Test Org" },
          role: "member",
          capabilities,
        },
      ],
    },
  } as never);
}

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
    vi.mocked(getOrgNda).mockResolvedValue({
      data: { required: false, current_version: "1.0", signed_version: null, signed_at: null },
    } as never);
  });

  it("shows offer, queue, and invitation counts on the admin tabs", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
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

  it("renders no count badge when there is nothing to attend to", async () => {
    vi.mocked(listMyOrgs).mockResolvedValue({
      response: { ok: true },
      data: {
        organizations: [
          {
            org: { id: "org-1", name: "Test Org" },
            role: "owner",
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
