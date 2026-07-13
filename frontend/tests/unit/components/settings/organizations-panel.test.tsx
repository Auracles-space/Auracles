import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationsPanel } from "@/components/modules/settings/organizations-panel";
import {
  acceptReceivedInvitation,
  declineReceivedInvitation,
  listMyOrganizationsV1OrgsMineGet,
  listReceivedInvitations,
} from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: vi.fn(() => "err"),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  acceptReceivedInvitation: vi.fn(),
  declineReceivedInvitation: vi.fn(),
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
  listReceivedInvitations: vi.fn(),
}));

const ok = <T,>(data: T) => ({
  data,
  error: undefined,
  request: new Request("http://t"),
  response: new Response(null, { status: 200 }),
});

describe("OrganizationsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [] }) as never,
    );
    vi.mocked(declineReceivedInvitation).mockResolvedValue(
      ok(undefined) as never,
    );
  });

  it("renders a pending invitation and accepts it", async () => {
    vi.mocked(listReceivedInvitations).mockResolvedValue(
      ok({
        invitations: [
          {
            created_at: "2026-07-13T00:00:00Z",
            id: "inv-1",
            invited_by_name: "Ada",
            org: {
              id: "o1",
              logo_url: null,
              name: "Meridian",
              slug: "meridian",
            },
            role: "member",
          },
        ],
      }) as never,
    );
    vi.mocked(acceptReceivedInvitation).mockResolvedValue(
      ok({ role: "member" }) as never,
    );

    render(<OrganizationsPanel />);

    await waitFor(() => expect(screen.getByText("Meridian")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /accept/i }));

    await waitFor(() =>
      expect(acceptReceivedInvitation).toHaveBeenCalledWith(
        expect.objectContaining({ path: { invitation_id: "inv-1" } }),
      ),
    );
  });

  it("shows an empty state when there are no invitations", async () => {
    vi.mocked(listReceivedInvitations).mockResolvedValue(
      ok({ invitations: [] }) as never,
    );

    render(<OrganizationsPanel />);

    await waitFor(() =>
      expect(screen.getByText(/no pending invitations/i)).toBeInTheDocument(),
    );
  });
});
