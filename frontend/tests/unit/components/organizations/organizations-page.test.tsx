/**
 * Organizations list page: status pills and the invitation inbox.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import OrganizationsPage from "@/app/(auth)/dashboard/organizations/page";
import { listMyOrganizationsV1OrgsMineGet } from "@/lib/generated/sdk.gen";
import { loadReceivedInvitations } from "@/lib/organizations/received-invitations";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: () => ({}),
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

function entry(overrides: Record<string, unknown> = {}) {
  return {
    org: {
      id: "o1",
      name: "Meridian Audit",
      slug: "meridian",
      country: "NG",
      suspended_at: null,
      suspension_reason: null,
    },
    role: "owner",
    capabilities: {},
    capability_reasons: {},
    kyb_status: "verified",
    grants: {},
    counts: { offers: 0, queue: 0, invitations: 0 },
    ...overrides,
  };
}

describe("OrganizationsPage status", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(loadReceivedInvitations).mockResolvedValue([]);
  });

  it("shows In review while business verification is pending", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [entry({ kyb_status: "pending" })] }) as never,
    );
    render(<OrganizationsPage />);
    await waitFor(() => expect(screen.getByText("Meridian Audit")).toBeInTheDocument());
    expect(screen.getByText("In review")).toBeInTheDocument();
  });

  it("shows Not verified and Needs changes for the other unverified states", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({
        organizations: [
          entry({ kyb_status: "unverified" }),
          entry({ org: { ...entry().org, id: "o2", name: "Second" }, kyb_status: "rejected" }),
        ],
      }) as never,
    );
    render(<OrganizationsPage />);
    await waitFor(() => expect(screen.getByText("Second")).toBeInTheDocument());
    expect(screen.getByText("Not verified")).toBeInTheDocument();
    expect(screen.getByText("Needs changes")).toBeInTheDocument();
  });

  it("flags a suspended organization", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({
        organizations: [
          entry({
            org: { ...entry().org, suspended_at: "2026-09-13T10:00:00Z", suspension_reason: "Chargebacks" },
          }),
        ],
      }) as never,
    );
    render(<OrganizationsPage />);
    await waitFor(() => expect(screen.getByText("Suspended")).toBeInTheDocument());
  });

  it("renders capabilities with their real labels instead of raw keys", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({
        organizations: [entry({ capabilities: { contributor: "active", attestor: "revoked" } })],
      }) as never,
    );
    render(<OrganizationsPage />);
    await waitFor(() => expect(screen.getByText("Meridian Audit")).toBeInTheDocument());
    expect(screen.getByText("Contributor")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Attestor")).toBeInTheDocument();
    expect(screen.getByText("Revoked")).toBeInTheDocument();
    expect(screen.queryByText(/contributor: active/i)).not.toBeInTheDocument();
  });

  it("shows the invitation inbox above the organizations", async () => {
    vi.mocked(listMyOrganizationsV1OrgsMineGet).mockResolvedValue(
      ok({ organizations: [] }) as never,
    );
    vi.mocked(loadReceivedInvitations).mockResolvedValue([
      {
        created_at: "2026-09-13T00:00:00Z",
        id: "inv-1",
        invited_by_name: "Ada",
        org: { id: "o9", logo_url: null, name: "Invited Org", slug: "invited" },
        role: "member",
      },
    ] as never);
    render(<OrganizationsPage />);
    await waitFor(() => expect(screen.getByText("Invited Org")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: /invitations/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /accept/i })).toBeInTheDocument();
  });
});
