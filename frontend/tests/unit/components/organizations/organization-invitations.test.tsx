import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationInvitations } from "@/components/modules/organizations/organization-invitations";
import { OrganizationProvider } from "@/components/modules/organizations/organization-context";
import {
  createInvitationV1OrgsOrgIdInvitationsPost,
  listInvitationsV1OrgsOrgIdInvitationsGet,
  resendInvitationV1OrgsOrgIdInvitationsInvitationIdResendPost,
  revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete,
  searchOrgMembers,
} from "@/lib/generated/sdk.gen";

const { toastSuccess, toastError } = vi.hoisted(() => ({
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: { message?: string } } | undefined) =>
    error?.detail?.message ?? "The request could not be completed.",
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer test-token" })),
}));
vi.mock("@/components/ui/toast", () => ({
  useToast: () => ({ success: toastSuccess, error: toastError }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createInvitationV1OrgsOrgIdInvitationsPost: vi.fn(),
  listInvitationsV1OrgsOrgIdInvitationsGet: vi.fn(),
  resendInvitationV1OrgsOrgIdInvitationsInvitationIdResendPost: vi.fn(),
  revokeInvitationV1OrgsOrgIdInvitationsInvitationIdDelete: vi.fn(),
  searchOrgMembers: vi.fn(),
}));

const org = {
  id: "org-1",
  slug: "org-1",
  name: "Org One",
  logo_key: null,
  logo_url: null,
  country: "GB",
  website: null,
  description: null,
  created_at: "2026-07-13T00:00:00Z",
};

function renderPanel() {
  return render(
    <OrganizationProvider capabilities={{}} org={org} orgId="org-1" role="owner">
      <OrganizationInvitations />
    </OrganizationProvider>,
  );
}

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

  it("loads pending invitations by default and refetches when the filter changes", async () => {
    renderPanel();

    await waitFor(() =>
      expect(listInvitationsV1OrgsOrgIdInvitationsGet).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1" },
          query: { status: "pending" },
        }),
      ),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Expired" }));

    await waitFor(() =>
      expect(listInvitationsV1OrgsOrgIdInvitationsGet).toHaveBeenCalledWith(
        expect.objectContaining({ query: { status: "expired" } }),
      ),
    );
  });

  it("shows an expired invitation with its pill, expiry date, and a resend action", async () => {
    vi.mocked(listInvitationsV1OrgsOrgIdInvitationsGet).mockResolvedValue(
      ok({
        invitations: [
          {
            id: "inv-9",
            email: "late@example.com",
            role: "member",
            status: "expired",
            expires_at: "2026-09-01T00:00:00Z",
            created_at: "2026-08-25T00:00:00Z",
          },
        ],
      }) as never,
    );
    vi.mocked(
      resendInvitationV1OrgsOrgIdInvitationsInvitationIdResendPost,
    ).mockResolvedValue(
      ok({
        id: "inv-9",
        email: "late@example.com",
        role: "member",
        status: "pending",
        expires_at: "2026-09-21T00:00:00Z",
        created_at: "2026-08-25T00:00:00Z",
      }) as never,
    );

    renderPanel();

    expect(await screen.findByText("late@example.com")).toBeInTheDocument();
    expect(screen.getByText("Expired", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Expired 1 Sep 2026")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /resend/i }));

    await waitFor(() =>
      expect(
        resendInvitationV1OrgsOrgIdInvitationsInvitationIdResendPost,
      ).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { org_id: "org-1", invitation_id: "inv-9" },
        }),
      ),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Invitation resent to late@example.com.");
  });

  it("shows the server's message when a resend is refused", async () => {
    vi.mocked(listInvitationsV1OrgsOrgIdInvitationsGet).mockResolvedValue(
      ok({
        invitations: [
          {
            id: "inv-2",
            email: "soon@example.com",
            role: "admin",
            status: "pending",
            expires_at: new Date(Date.now() + 3 * 86_400_000).toISOString(),
            created_at: "2026-09-10T00:00:00Z",
          },
        ],
      }) as never,
    );
    vi.mocked(
      resendInvitationV1OrgsOrgIdInvitationsInvitationIdResendPost,
    ).mockResolvedValue({
      data: undefined,
      error: { detail: { error_code: "rate_limited", message: "Try again in an hour." } },
      request: new Request("http://test.local"),
      response: new Response(null, { status: 429 }),
    } as never);

    renderPanel();

    expect(await screen.findByText("Expires in 3 days")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /resend/i }));

    expect(await screen.findByText("Try again in an hour.")).toBeInTheDocument();
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
