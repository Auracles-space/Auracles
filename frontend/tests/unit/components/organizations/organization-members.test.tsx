/**
 * Organization members tab.
 *
 * Covers the role vocabulary, the confirm-gated removal, the invite CTA, and
 * how a server refusal is surfaced.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationMembers } from "@/components/modules/organizations/organization-members";
import { OrganizationProvider } from "@/components/modules/organizations/organization-context";
import {
  changeMemberRoleV1OrgsOrgIdMembersMemberIdPatch,
  listMembersV1OrgsOrgIdMembersGet,
  removeMemberV1OrgsOrgIdMembersMemberIdDelete,
} from "@/lib/generated/sdk.gen";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: { message?: string } } | undefined) =>
    error?.detail?.message ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test-token" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  changeMemberRoleV1OrgsOrgIdMembersMemberIdPatch: vi.fn(),
  listMembersV1OrgsOrgIdMembersGet: vi.fn(),
  removeMemberV1OrgsOrgIdMembersMemberIdDelete: vi.fn(),
}));

function ok<T>(data: T, status = 200) {
  return {
    data,
    error: undefined,
    request: new Request("http://test.local"),
    response: new Response(null, { status }),
  };
}

function refused(message: string, status = 409) {
  return {
    data: undefined,
    error: { detail: { error_code: "refused", message } },
    request: new Request("http://test.local"),
    response: new Response(null, { status }),
  };
}

const members = [
  {
    id: "m-owner",
    user_id: "u-1",
    display_name: "Ada Okafor",
    email: "ada@meridian.example",
    role: "owner",
    joined_at: "2026-07-01T00:00:00Z",
  },
  {
    id: "m-2",
    user_id: "u-2",
    display_name: "Grace Bello",
    email: "grace@meridian.example",
    role: "member",
    joined_at: "2026-08-01T00:00:00Z",
  },
];

const org = {
  id: "org-1",
  slug: "meridian",
  name: "Meridian",
  logo_key: null,
  logo_url: null,
  country: "NG",
  website: null,
  description: null,
  created_at: "2026-07-01T00:00:00Z",
};

function renderMembers(role = "owner") {
  return render(
    <OrganizationProvider capabilities={{}} org={org} orgId="org-1" role={role}>
      <OrganizationMembers />
    </OrganizationProvider>,
  );
}

describe("OrganizationMembers", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listMembersV1OrgsOrgIdMembersGet).mockResolvedValue(
      ok({ members }) as never,
    );
  });

  it("renders each member's role as a pill and links to the invitations tab", async () => {
    renderMembers("admin");

    expect(await screen.findByText("Ada Okafor")).toBeInTheDocument();
    const ownerPill = screen.getByText("Owner");
    expect(ownerPill.className).toContain("rounded-badge");
    expect(screen.getByText("Member").className).toContain("rounded-badge");

    expect(screen.getByRole("link", { name: /invite a member/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/invitations",
    );
  });

  it("removes a member only after confirmation", async () => {
    vi.mocked(removeMemberV1OrgsOrgIdMembersMemberIdDelete).mockResolvedValue(
      ok(undefined, 204) as never,
    );
    renderMembers("owner");

    await screen.findByText("Grace Bello");
    fireEvent.click(screen.getByRole("button", { name: /remove grace bello/i }));
    expect(removeMemberV1OrgsOrgIdMembersMemberIdDelete).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Remove Member" }));

    await waitFor(() =>
      expect(removeMemberV1OrgsOrgIdMembersMemberIdDelete).toHaveBeenCalledWith(
        expect.objectContaining({ path: { org_id: "org-1", member_id: "m-2" } }),
      ),
    );
  });

  it("shows the server's message when a role change is refused", async () => {
    vi.mocked(changeMemberRoleV1OrgsOrgIdMembersMemberIdPatch).mockResolvedValue(
      refused("Only the owner can promote administrators.", 403) as never,
    );
    renderMembers("owner");

    await screen.findByText("Grace Bello");
    fireEvent.change(screen.getByLabelText(/role for grace bello/i), {
      target: { value: "admin" },
    });

    expect(
      await screen.findByText("Only the owner can promote administrators."),
    ).toBeInTheDocument();
  });
});
