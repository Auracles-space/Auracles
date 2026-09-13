import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrganizationsPanel } from "@/components/modules/settings/organizations-panel";
import {
  declineReceivedInvitation,
  listMyOrganizationsV1OrgsMineGet,
} from "@/lib/generated/sdk.gen";
import { loadReceivedInvitations } from "@/lib/organizations/received-invitations";

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

  it("points at the Organizations page when invitations are pending", async () => {
    vi.mocked(loadReceivedInvitations).mockResolvedValue([
      {
        created_at: "2026-07-13T00:00:00Z",
        id: "inv-1",
        invited_by_name: "Ada",
        org: { id: "o1", logo_url: null, name: "Meridian", slug: "meridian" },
        role: "member",
      },
    ] as never);

    render(<OrganizationsPanel />);

    await waitFor(() =>
      expect(screen.getByText(/1 pending invitation/i)).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /review invitations/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations",
    );
    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no invitations", async () => {
    vi.mocked(loadReceivedInvitations).mockResolvedValue([]);

    render(<OrganizationsPanel />);

    await waitFor(() =>
      expect(screen.getByText(/no pending invitations/i)).toBeInTheDocument(),
    );
  });
});
