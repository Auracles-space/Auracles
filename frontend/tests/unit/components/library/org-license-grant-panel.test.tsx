import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { OrgLicenseGrantPanel } from "@/components/modules/library/org-license-grant-panel";
import * as sdk from "@/lib/generated/sdk.gen";
import type { OrgLicenseGrantResponse } from "@/lib/generated/types.gen";

vi.mock("@/lib/generated/sdk.gen", () => ({
  addOrgLicenseGrant: vi.fn(),
  listOrgLicenseGrants: vi.fn(),
  revokeOrgLicenseGrant: vi.fn(),
  listOrgMembers: vi.fn(),
  listOrgTeams: vi.fn(),
  client: {
    setConfig: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  },
}));

describe("OrgLicenseGrantPanel", () => {
  const mockGrant: OrgLicenseGrantResponse = {
    id: "grant-1",
    license_id: "license-1",
    member_id: "m-1",
    team_id: null,
    created_at: "2026-07-12T00:00:00Z",
  };

  const mockMember = {
    id: "m-1",
    user_id: "user-1",
    display_name: "Alice",
    email: "alice@example.com",
    role: "member",
    joined_at: "2026-01-01T00:00:00Z",
  };

  const mockTeam = {
    id: "team-1",
    name: "Engineering",
    member_count: 5,
    created_at: "2026-01-01T00:00:00Z",
  };

  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(sdk.listOrgMembers).mockResolvedValue({
      response: { ok: true } as Response,
      data: { members: [mockMember] },
    });
    vi.mocked(sdk.listOrgTeams).mockResolvedValue({
      response: { ok: true } as Response,
      data: { teams: [mockTeam] },
    });
  });

  it("lists existing grants on load", async () => {
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: { grants: [mockGrant] },
    });

    render(<OrgLicenseGrantPanel orgId="org-1" licenseId="license-1" />);

    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(sdk.listOrgLicenseGrants).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1", license_id: "license-1" },
      }),
    );
  });

  it("allows adding a user grant", async () => {
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: { grants: [] },
    });

    render(<OrgLicenseGrantPanel orgId="org-1" licenseId="license-1" />);
    await screen.findByText(/No active grants/);

    const comboboxes = screen.getAllByRole("combobox");
    // [0] is the grantType select, [1] is the grantTargetId select
    const targetSelect = comboboxes[1];

    fireEvent.change(targetSelect, { target: { value: "m-1" } });

    vi.mocked(sdk.addOrgLicenseGrant).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: { ...mockGrant, id: "grant-2" },
    });
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: { grants: [{ ...mockGrant, id: "grant-2" }] },
    });

    const addButton = screen.getByRole("button", { name: "Add Grant" });
    fireEvent.click(addButton);

    expect(sdk.addOrgLicenseGrant).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { member_id: "m-1" },
      }),
    );
    expect(await screen.findByText("Alice")).toBeInTheDocument();
  });

  it("allows adding a team grant", async () => {
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: { grants: [] },
    });

    render(<OrgLicenseGrantPanel orgId="org-1" licenseId="license-1" />);
    await screen.findByText(/No active grants/);

    const comboboxes = screen.getAllByRole("combobox");
    const typeSelect = comboboxes[0];
    fireEvent.change(typeSelect, { target: { value: "team_id" } });

    const targetSelect = screen.getAllByRole("combobox")[1];
    fireEvent.change(targetSelect, { target: { value: "team-1" } });

    vi.mocked(sdk.addOrgLicenseGrant).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: { ...mockGrant, id: "grant-3", user_id: null, team_id: "team-1" },
    });
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: {
        grants: [{ ...mockGrant, id: "grant-3", user_id: null, team_id: "team-1" }],
      },
    });

    const addButton = screen.getByRole("button", { name: "Add Grant" });
    fireEvent.click(addButton);

    expect(sdk.addOrgLicenseGrant).toHaveBeenCalledWith(
      expect.objectContaining({
        body: { team_id: "team-1" },
      }),
    );
    expect(await screen.findByText("Engineering")).toBeInTheDocument();
  });

  it("allows revoking a grant", async () => {
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: { grants: [mockGrant] },
    });

    render(<OrgLicenseGrantPanel orgId="org-1" licenseId="license-1" />);
    await screen.findByText("Alice");

    vi.mocked(sdk.revokeOrgLicenseGrant).mockResolvedValueOnce({
      response: { ok: true } as Response,
    });
    vi.mocked(sdk.listOrgLicenseGrants).mockResolvedValueOnce({
      response: { ok: true } as Response,
      data: { grants: [] },
    });

    const revokeButton = screen.getByLabelText("Revoke grant");
    fireEvent.click(revokeButton);

    expect(sdk.revokeOrgLicenseGrant).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { org_id: "org-1", license_id: "license-1", grant_id: "grant-1" },
      }),
    );
    await waitFor(() => {
      expect(screen.getByText(/No active grants/)).toBeInTheDocument();
    });
  });
});
