import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationInvitations } from "@/components/modules/organizations/organization-invitations";
import { OrganizationProvider } from "@/components/modules/organizations/organization-context";
import {
  createInvitationV1OrgsOrgIdInvitationsPost,
  listInvitationsV1OrgsOrgIdInvitationsGet,
  revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete,
  searchOrgMembers,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createInvitationV1OrgsOrgIdInvitationsPost: vi.fn(),
  listInvitationsV1OrgsOrgIdInvitationsGet: vi.fn(),
  revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete: vi.fn(),
  searchOrgMembers: vi.fn(),
}));

function ok<T>(data: T) {
  return {
    data,
    error: undefined,
    request: new Request("http://test.local"),
    response: new Response(null, { status: 200 }),
  };
}

function created<T>(data: T) {
  return {
    data,
    error: undefined,
    request: new Request("http://test.local"),
    response: new Response(null, { status: 201 }),
  };
}

describe("OrganizationInvitations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
    vi.mocked(listInvitationsV1OrgsOrgIdInvitationsGet).mockResolvedValue(
      ok({ invitations: [] }) as never,
    );
    vi.mocked(
      revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete,
    ).mockResolvedValue({
      data: undefined,
      error: undefined,
      request: new Request("http://test.local"),
      response: new Response(null, { status: 204 }),
    } as never);
  });

  it("sends a selected suggestion as user_id", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(searchOrgMembers).mockResolvedValue(
      ok({
        results: [
          {
            user_id: "user-1",
            display_name: "Joanna Reed",
            avatar_url: null,
            masked_email: "j•••@example.com",
          },
        ],
      }) as never,
    );
    vi.mocked(createInvitationV1OrgsOrgIdInvitationsPost).mockResolvedValue(
      created({
        id: "inv-1",
        email: "j•••@example.com",
        role: "member",
        status: "pending",
        expires_at: "2026-07-20T00:00:00Z",
        created_at: "2026-07-13T00:00:00Z",
      }) as never,
    );

    render(
      <OrganizationProvider
        capabilities={{}}
        org={{ id: "org-1", slug: "org-1", name: "Org One", logo_key: null, logo_url: null, country: "GB", website: null, description: null, created_at: "2026-07-13T00:00:00Z" }}
        orgId="org-1"
        role="owner"
      >
        <OrganizationInvitations />
      </OrganizationProvider>,
    );

    await screen.findByText("Invite Member");
    fireEvent.change(screen.getByLabelText(/invite by email/i), {
      target: { value: "joa" },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });

    await screen.findByText("Joanna Reed");
    fireEvent.click(screen.getByText("Joanna Reed"));
    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));

    await waitFor(() => {
      expect(createInvitationV1OrgsOrgIdInvitationsPost).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: { user_id: "user-1", role: "member" },
        }),
      );
    });

    vi.useRealTimers();
  });

  it("still sends a manual outsider email when nothing is selected", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(searchOrgMembers).mockResolvedValue(
      ok({ results: [] }) as never,
    );
    vi.mocked(createInvitationV1OrgsOrgIdInvitationsPost).mockResolvedValue(
      created({
        id: "inv-2",
        email: "outsider@example.com",
        role: "member",
        status: "pending",
        expires_at: "2026-07-20T00:00:00Z",
        created_at: "2026-07-13T00:00:00Z",
      }) as never,
    );

    render(
      <OrganizationProvider
        capabilities={{}}
        org={{ id: "org-1", slug: "org-1", name: "Org One", logo_key: null, logo_url: null, country: "GB", website: null, description: null, created_at: "2026-07-13T00:00:00Z" }}
        orgId="org-1"
        role="owner"
      >
        <OrganizationInvitations />
      </OrganizationProvider>,
    );

    await screen.findByText("Invite Member");
    fireEvent.change(screen.getByLabelText(/invite by email/i), {
      target: { value: "outsider@example.com" },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });

    fireEvent.click(screen.getByRole("button", { name: /send invite/i }));

    await waitFor(() => {
      expect(createInvitationV1OrgsOrgIdInvitationsPost).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          body: { email: "outsider@example.com", role: "member" },
        }),
      );
    });

    vi.useRealTimers();
  });
});
