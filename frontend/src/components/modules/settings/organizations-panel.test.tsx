import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { listMyOrganizationsV1OrgsMineGet as listMyOrgs } from "@/lib/generated/sdk.gen";
import { loadReceivedInvitations } from "@/lib/organizations/received-invitations";
import { OrganizationsPanel } from "./organizations-panel";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  listMyOrganizationsV1OrgsMineGet: vi.fn(),
  acceptReceivedInvitation: vi.fn(),
  declineReceivedInvitation: vi.fn(),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({ Authorization: "Bearer test" }),
  describeGeneratedError: () => "error",
}));

vi.mock("@/lib/organizations/received-invitations", () => ({
  loadReceivedInvitations: vi.fn(),
  invalidateReceivedInvitations: vi.fn(),
}));

function mockOrgs(counts: Record<string, number>) {
  vi.mocked(listMyOrgs).mockResolvedValue({
    response: { ok: true },
    data: {
      organizations: [
        {
          org: { id: "org-1", name: "Acme Advisory" },
          role: "owner",
          capabilities: {},
          counts,
        },
      ],
    },
  } as never);
  vi.mocked(loadReceivedInvitations).mockResolvedValue([]);
}

describe("OrganizationsPanel offer dot", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows an unread dot when the org has open offers", async () => {
    mockOrgs({ offers: 2, queue: 0, invitations: 0 });

    render(<OrganizationsPanel />);

    expect(
      await screen.findByLabelText(/2 attestation offers to review/i),
    ).toBeInTheDocument();
  });

  it("shows no dot when there are no open offers", async () => {
    mockOrgs({ offers: 0, queue: 0, invitations: 0 });

    render(<OrganizationsPanel />);

    await screen.findByText("Acme Advisory");
    expect(
      screen.queryByLabelText(/attestation offer/i),
    ).not.toBeInTheDocument();
  });
});
