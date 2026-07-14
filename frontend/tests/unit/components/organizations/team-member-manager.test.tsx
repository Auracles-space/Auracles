import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TeamMemberManager } from "@/components/modules/organizations/team-member-manager";
import {
  addTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdPut,
  listMembersV1OrgsOrgIdMembersGet,
  listTeamMembersV1OrgsOrgIdTeamsTeamIdMembersGet,
  removeTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdDelete,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listTeamMembersV1OrgsOrgIdTeamsTeamIdMembersGet: vi.fn(),
  listMembersV1OrgsOrgIdMembersGet: vi.fn(),
  addTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdPut: vi.fn(),
  removeTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdDelete: vi.fn(),
}));

function ok<T>(data: T) {
  return {
    data,
    error: undefined,
    request: new Request("http://test.local"),
    response: new Response(null, { status: 200 }),
  };
}

function noContent() {
  return {
    data: undefined,
    error: undefined,
    request: new Request("http://test.local"),
    response: new Response(null, { status: 204 }),
  };
}

function member(id: string, name: string) {
  return {
    id,
    user_id: `user-${id}`,
    display_name: name,
    email: `${name.toLowerCase()}@example.com`,
    role: "member",
    joined_at: "2026-07-14T00:00:00Z",
  };
}

describe("TeamMemberManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listTeamMembersV1OrgsOrgIdTeamsTeamIdMembersGet).mockResolvedValue(
      ok({ members: [member("m1", "Ada")] }) as never,
    );
    vi.mocked(listMembersV1OrgsOrgIdMembersGet).mockResolvedValue(
      ok({ members: [member("m1", "Ada"), member("m2", "Grace")] }) as never,
    );
    vi.mocked(
      addTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdPut,
    ).mockResolvedValue(noContent() as never);
    vi.mocked(
      removeTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdDelete,
    ).mockResolvedValue(noContent() as never);
  });

  it("renders the current roster", async () => {
    render(
      <TeamMemberManager
        orgId="org-1"
        teamId="team-1"
        isAdmin
        isSuspended={false}
      />,
    );
    expect(await screen.findByText("Ada")).toBeInTheDocument();
  });

  it("offers only org members not already on the team", async () => {
    render(
      <TeamMemberManager
        orgId="org-1"
        teamId="team-1"
        isAdmin
        isSuspended={false}
      />,
    );
    await screen.findByText("Ada");
    // Ada is on the team already; only Grace is offered as an add candidate.
    expect(screen.getByRole("option", { name: "Grace" })).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "Ada" }),
    ).not.toBeInTheDocument();
  });

  it("adds the selected member to the team", async () => {
    render(
      <TeamMemberManager
        orgId="org-1"
        teamId="team-1"
        isAdmin
        isSuspended={false}
      />,
    );
    await screen.findByText("Ada");
    fireEvent.change(screen.getByLabelText(/add member to team/i), {
      target: { value: "m2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add member/i }));

    await waitFor(() => {
      expect(
        addTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdPut,
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1", team_id: "team-1", member_id: "m2" },
        }),
      );
    });
  });

  it("removes a member from the team", async () => {
    render(
      <TeamMemberManager
        orgId="org-1"
        teamId="team-1"
        isAdmin
        isSuspended={false}
      />,
    );
    await screen.findByText("Ada");
    fireEvent.click(screen.getByTitle(/remove ada from team/i));

    await waitFor(() => {
      expect(
        removeTeamMemberV1OrgsOrgIdTeamsTeamIdMembersMemberIdDelete,
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1", team_id: "team-1", member_id: "m1" },
        }),
      );
    });
  });
});
