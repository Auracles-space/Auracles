/**
 * Tests for the organization teams management panel.
 *
 * Verifies owner/admin capability controls on team rows and the confirm-gated
 * capability assignment flow.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useOrganization } from "./organization-context";
import { OrganizationTeams } from "./organization-teams";
import {
  deleteTeamV1OrgsOrgIdTeamsTeamIdDelete,
  disableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityDelete,
  enableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityPut,
  listTeamsV1OrgsOrgIdTeamsGet,
  createTeamV1OrgsOrgIdTeamsPost,
  renameTeamV1OrgsOrgIdTeamsTeamIdPatch,
} from "@/lib/generated/sdk.gen";

const { refreshOrganization, toastSuccess, toastError } = vi.hoisted(() => ({
  refreshOrganization: vi.fn().mockResolvedValue(undefined),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError }),
}));
vi.mock("./organization-context", () => ({ useOrganization: vi.fn() }));
vi.mock("./team-member-manager", () => ({
  TeamMemberManager: () => <div data-testid="team-member-manager" />,
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  listTeamsV1OrgsOrgIdTeamsGet: vi.fn(),
  createTeamV1OrgsOrgIdTeamsPost: vi.fn(),
  renameTeamV1OrgsOrgIdTeamsTeamIdPatch: vi.fn(),
  deleteTeamV1OrgsOrgIdTeamsTeamIdDelete: vi.fn(),
  enableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityPut: vi.fn(),
  disableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityDelete: vi.fn(),
}));

/** Seed the organization context the panel reads. */
function setOrg(
  overrides: Partial<{
    role: string;
    capabilities: Record<string, string>;
    isSuspended: boolean;
  }> = {},
) {
  vi.mocked(useOrganization).mockReturnValue({
    orgId: "org-1",
    role: "owner",
    org: { suspended_at: null },
    capabilities: {},
    isSuspended: false,
    markSuspended: vi.fn(),
    refreshOrganization,
    ...overrides,
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  refreshOrganization.mockResolvedValue(undefined);
  vi.mocked(listTeamsV1OrgsOrgIdTeamsGet).mockResolvedValue({
    response: { ok: true },
    data: {
      teams: [
        {
          id: "team-1",
          name: "Sellers",
          member_count: 2,
          capabilities: [],
          created_at: "2026-07-17T00:00:00Z",
        },
      ],
    },
  } as never);
  vi.mocked(createTeamV1OrgsOrgIdTeamsPost).mockResolvedValue({} as never);
  vi.mocked(renameTeamV1OrgsOrgIdTeamsTeamIdPatch).mockResolvedValue({} as never);
  vi.mocked(deleteTeamV1OrgsOrgIdTeamsTeamIdDelete).mockResolvedValue({} as never);
  vi.mocked(
    enableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityPut,
  ).mockResolvedValue({ response: { ok: true } } as never);
  vi.mocked(
    disableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityDelete,
  ).mockResolvedValue({ response: { ok: true } } as never);
});

describe("OrganizationTeams", () => {
  it("disables the Operator toggle when the org capability is inactive", async () => {
    setOrg({ capabilities: {} });

    render(<OrganizationTeams />);

    const button = await screen.findByRole("button", {
      name: "Enable Operator on Sellers",
    });
    expect(button).toBeDisabled();
    expect(
      screen.getByText("Activate this capability for the organization first."),
    ).toBeTruthy();

    await waitFor(() =>
      expect(listTeamsV1OrgsOrgIdTeamsGet).toHaveBeenCalledWith({
        path: { org_id: "org-1" },
        headers: { Authorization: "Bearer test" },
      }),
    );
  });

  it("enables a team capability and refreshes the organization", async () => {
    setOrg({ capabilities: { operator: "active" } });

    render(<OrganizationTeams />);

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Enable Operator on Sellers",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Enable Operator" }));

    await waitFor(() =>
      expect(
        enableTeamCapabilityV1OrgsOrgIdTeamsTeamIdCapabilitiesCapabilityPut,
      ).toHaveBeenCalledWith({
        path: {
          org_id: "org-1",
          team_id: "team-1",
          capability: "operator",
        },
        headers: { Authorization: "Bearer test" },
      }),
    );
    expect(refreshOrganization).toHaveBeenCalledTimes(1);
  });
});
