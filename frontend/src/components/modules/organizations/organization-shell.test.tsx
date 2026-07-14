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
});
