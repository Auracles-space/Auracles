/**
 * Received-invitations inbox on the organizations list page.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReceivedInvitationsInbox } from "@/components/modules/organizations/received-invitations-inbox";
import {
  acceptReceivedInvitation,
  declineReceivedInvitation,
} from "@/lib/generated/sdk.gen";
import { loadReceivedInvitations } from "@/lib/organizations/received-invitations";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({}),
}));
vi.mock("@/lib/generated/sdk.gen", () => ({
  acceptReceivedInvitation: vi.fn(),
  declineReceivedInvitation: vi.fn(),
}));
vi.mock("@/lib/organizations/received-invitations", () => ({
  loadReceivedInvitations: vi.fn(),
  invalidateReceivedInvitations: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

const invitation = {
  created_at: "2026-09-13T00:00:00Z",
  id: "inv-1",
  invited_by_name: "Ada",
  org: { id: "o1", logo_url: null, name: "Meridian", slug: "meridian" },
  role: "member",
};

describe("ReceivedInvitationsInbox", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders nothing when there are no invitations", async () => {
    vi.mocked(loadReceivedInvitations).mockResolvedValue([]);
    const { container } = render(<ReceivedInvitationsInbox />);
    await waitFor(() => expect(loadReceivedInvitations).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("lists an invitation and accepts it into the organization", async () => {
    vi.mocked(loadReceivedInvitations).mockResolvedValue([invitation] as never);
    vi.mocked(acceptReceivedInvitation).mockResolvedValue(ok({ role: "member" }) as never);
    const onResolved = vi.fn();

    render(<ReceivedInvitationsInbox onResolved={onResolved} />);

    await waitFor(() => expect(screen.getByText("Meridian")).toBeInTheDocument());
    expect(screen.getByText(/invited by ada/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /accept/i }));

    await waitFor(() =>
      expect(acceptReceivedInvitation).toHaveBeenCalledWith(
        expect.objectContaining({ path: { invitation_id: "inv-1" } }),
      ),
    );
    expect(onResolved).toHaveBeenCalled();
    expect(push).toHaveBeenCalledWith("/dashboard/organizations/o1");
  });

  it("declines an invitation and drops it from the list", async () => {
    vi.mocked(loadReceivedInvitations).mockResolvedValue([invitation] as never);
    vi.mocked(declineReceivedInvitation).mockResolvedValue(ok(undefined) as never);

    render(<ReceivedInvitationsInbox />);

    await waitFor(() => expect(screen.getByText("Meridian")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /decline/i }));

    await waitFor(() => expect(screen.queryByText("Meridian")).not.toBeInTheDocument());
  });
});
