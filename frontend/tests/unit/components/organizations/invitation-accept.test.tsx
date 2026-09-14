/**
 * Token-link invitation screen: accept and decline both hit the API.
 *
 * Declining used to be a plain link home, which left the invitation pending
 * for the org and let the same link be accepted later. Both buttons must
 * call their endpoint, and a failed decline must show the server message.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InvitationAccept } from "@/components/modules/organizations/invitation-accept";
import {
  acceptInvitationV1OrgInvitationsTokenAcceptPost,
  declineInvitationV1OrgInvitationsTokenDeclinePost,
  previewInvitationV1OrgInvitationsTokenGet,
} from "@/lib/generated/sdk.gen";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/auth/form-client", () => ({
  describeGeneratedError: vi.fn(() => "described server error"),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test-token" }),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  acceptInvitationV1OrgInvitationsTokenAcceptPost: vi.fn(),
  declineInvitationV1OrgInvitationsTokenDeclinePost: vi.fn(),
  getOrgNda: vi.fn(),
  previewInvitationV1OrgInvitationsTokenGet: vi.fn(),
  signOrgNda: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

const failed = (status: number, error: unknown) => ({
  data: undefined,
  error,
  request: new Request("http://t"),
  response: new Response(null, { status }),
});

const PREVIEW = {
  expires_at: "2026-10-01T00:00:00Z",
  org_name: "Lagos Audit Collective",
  org_slug: "lagos-audit",
  role: "member",
};

describe("InvitationAccept", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(previewInvitationV1OrgInvitationsTokenGet).mockResolvedValue(ok(PREVIEW) as never);
  });

  it("accepts the invitation by token and sends the member to their organizations", async () => {
    vi.mocked(acceptInvitationV1OrgInvitationsTokenAcceptPost).mockResolvedValue(
      ok({ nda_required: false, org: { id: "org-1", name: "Lagos Audit Collective" } }) as never,
    );

    render(<InvitationAccept token="tok-123" />);

    fireEvent.click(await screen.findByRole("button", { name: /accept invitation/i }));

    await waitFor(() =>
      expect(acceptInvitationV1OrgInvitationsTokenAcceptPost).toHaveBeenCalledWith(
        expect.objectContaining({ path: { token: "tok-123" } }),
      ),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/dashboard/organizations"));
  });

  it("declines the invitation by token before returning home", async () => {
    vi.mocked(declineInvitationV1OrgInvitationsTokenDeclinePost).mockResolvedValue(
      ok(undefined) as never,
    );

    render(<InvitationAccept token="tok-123" />);

    fireEvent.click(await screen.findByRole("button", { name: /decline/i }));

    await waitFor(() =>
      expect(declineInvitationV1OrgInvitationsTokenDeclinePost).toHaveBeenCalledWith(
        expect.objectContaining({ path: { token: "tok-123" } }),
      ),
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/"));
  });

  it("shows the server message when the decline fails and stays on the page", async () => {
    vi.mocked(declineInvitationV1OrgInvitationsTokenDeclinePost).mockResolvedValue(
      failed(410, { detail: { error_code: "invitation_expired" } }) as never,
    );

    render(<InvitationAccept token="tok-123" />);

    fireEvent.click(await screen.findByRole("button", { name: /decline/i }));

    expect(await screen.findByText("described server error")).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });
});
