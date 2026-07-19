import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectWorkspace } from "@/components/modules/projects/project-workspace";
import { clearAuthToken } from "@/lib/auth/token-store";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import {
  getOrgProject,
  getProject,
  listDisputes,
  listMilestones,
  listMyProjectProposals,
  listOrgProjectProposals,
  listProjectProposals,
  listWorkspaceMessages,
} from "@/lib/generated/sdk.gen";

vi.mock("@/components/modules/projects/publish-as-framework-button", () => ({
  PublishAsFrameworkButton: () => <div>Publish as framework</div>,
}));

vi.mock("@/components/modules/reputation/reputation-badge", () => ({
  ReputationBadge: () => <div>Reputation</div>,
}));

vi.mock("@/components/ui/skeleton", () => ({
  Skeleton: ({ className }: { className?: string }) => (
    <div className={className}>Loading</div>
  ),
}));

vi.mock("@/lib/projects/realtime", () => ({
  useProjectRealtime: () => ({ connected: false, lastEvent: null }),
}));

const nav = vi.hoisted(() => ({
  searchParams: new URLSearchParams(""),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/projects/test",
  useRouter: () => ({ replace: nav.replace }),
  useSearchParams: () => nav.searchParams,
}));

vi.mock("@/lib/auth/form-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/auth/form-client")>(
    "@/lib/auth/form-client",
  );
  return {
    ...actual,
    configureBrowserClient: vi.fn(),
    getAccessTokenHeaders: vi.fn(() => ({})),
  };
});

vi.mock("@/lib/auth/current-user-session", () => ({
  loadCurrentUserSession: vi.fn(),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  acceptProposal: vi.fn(),
  approveDeliverable: vi.fn(),
  createMilestone: vi.fn(),
  createWorkspaceMessage: vi.fn(),
  finalizeMilestonePlan: vi.fn(),
  fundMilestone: vi.fn(),
  getOrgProject: vi.fn(),
  getProject: vi.fn(),
  listDisputes: vi.fn(),
  listMilestones: vi.fn(),
  listMyProjectProposals: vi.fn(),
  listOrgProjectProposals: vi.fn(),
  listProjectProposals: vi.fn(),
  listWorkspaceMessages: vi.fn(),
  submitDeliverable: vi.fn(),
  submitProposal: vi.fn(),
  createProject: vi.fn(),
  createOrgProject: vi.fn(),
  acceptOrgProposal: vi.fn(),
  fundOrgMilestone: vi.fn(),
  approveOrgDeliverable: vi.fn(),
  requestDeliverableRevision: vi.fn(),
  requestOrgDeliverableRevision: vi.fn(),
  createDispute: vi.fn(),
  createOrgDispute: vi.fn(),
  cancelAcceptance: vi.fn(),
  cancelOrgAcceptance: vi.fn(),
  deleteProject: vi.fn(),
  deleteOrgProject: vi.fn(),
}));

const okResponse = new Response(null, { status: 200 });
const forbiddenResponse = new Response(null, { status: 403 });

function projectResponse() {
  return {
    accepted_proposal_id: "proposal-1",
    category: "operations",
    created_at: "2026-06-20T10:00:00Z",
    currency: "USD",
    deadline: "2026-07-01",
    description: "Build a procurement operating model.",
    id: "project-1",
    milestone_plan_status: "draft",
    operator_id: "operator-1",
    operator_reputation: null,
    required_deliverables: [
      { description: "Implementation guide", name: "Playbook" },
    ],
    status: "assigned",
    title: "Procurement Playbook",
    updated_at: "2026-06-20T10:00:00Z",
  };
}

describe("ProjectWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearAuthToken();
    nav.searchParams = new URLSearchParams("");
    nav.replace.mockReset();
  });

  it("loads owner workspace data even when roles are not hydrated yet", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue({
      avatar_url: null,
      deactivated_at: null,
      display_name: "Operator User",
      email: "operator@example.com",
      email_verified: true,
      id: "operator-1",
      kyc_status: "verified",
      pending_roles: [],
      roles: ["operator"],
    });
    vi.mocked(getProject).mockResolvedValue({
      data: projectResponse(),
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listProjectProposals).mockResolvedValue({
      data: {
        proposals: [
          {
            budget: "1500.00",
            contributor_id: "contributor-1",
            created_at: "2026-06-20T11:00:00Z",
            currency: "USD",
            deliverables: [],
            id: "proposal-1",
            project_id: "project-1",
            scope: "I will deliver the procurement model.",
            status: "pending",
            timeline_days: 21,
            withdrawn_at: null,
            accepted_at: null,
          },
        ],
      },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listMyProjectProposals).mockResolvedValue({
      data: undefined,
      error: { detail: "Forbidden" },
      response: forbiddenResponse,
    });
    vi.mocked(listMilestones).mockResolvedValue({
      data: { milestones: [] },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listWorkspaceMessages).mockResolvedValue({
      data: { messages: [] },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listDisputes).mockResolvedValue({
      data: { disputes: [] },
      error: undefined,
      response: okResponse,
    });

    render(<ProjectWorkspace projectId="project-1" />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /procurement playbook/i })).toBeInTheDocument();
    });

    expect(listProjectProposals).toHaveBeenCalledTimes(1);
    expect(listWorkspaceMessages).toHaveBeenCalledTimes(1);
  });

  it("loads an org-owned workspace and exposes operator controls to its admin", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue({
      avatar_url: null,
      deactivated_at: null,
      display_name: "Organization Admin",
      email: "admin@example.com",
      email_verified: true,
      id: "admin-1",
      kyc_status: "verified",
      pending_roles: [],
      roles: [],
    });
    vi.mocked(getOrgProject).mockResolvedValue({
      data: {
        ...projectResponse(),
        accepted_proposal_id: null,
        operator_id: null,
        operator_org_id: "org-1",
        status: "open",
      },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listOrgProjectProposals).mockResolvedValue({
      data: {
        proposals: [
          {
            budget: "1500.00",
            contributor_id: "contributor-1",
            created_at: "2026-06-20T11:00:00Z",
            currency: "USD",
            deliverables: [],
            id: "proposal-1",
            project_id: "project-1",
            scope: "I will deliver the procurement model.",
            status: "pending",
            timeline_days: 21,
            withdrawn_at: null,
            accepted_at: null,
          },
        ],
      },
      error: undefined,
      response: okResponse,
    });

    render(
      <ProjectWorkspace
        mode={{ kind: "org", orgId: "org-1" }}
        projectId="project-1"
      />,
    );

    expect(
      await screen.findByRole("button", { name: /accept proposal/i }),
    ).toBeInTheDocument();
    expect(getOrgProject).toHaveBeenCalledTimes(1);
    expect(listOrgProjectProposals).toHaveBeenCalledTimes(1);
    expect(getProject).not.toHaveBeenCalled();
    expect(listMyProjectProposals).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /back to projects/i })).toHaveAttribute(
      "href",
      "/dashboard/organizations/org-1/projects",
    );
  });

  it("hides the Messages tab on an open org project before any proposal is accepted", async () => {
    vi.mocked(loadCurrentUserSession).mockResolvedValue({
      avatar_url: null,
      deactivated_at: null,
      display_name: "Organization Admin",
      email: "admin@example.com",
      email_verified: true,
      id: "admin-1",
      kyc_status: "verified",
      pending_roles: [],
      roles: [],
    });
    vi.mocked(getOrgProject).mockResolvedValue({
      data: {
        ...projectResponse(),
        accepted_proposal_id: null,
        operator_id: null,
        operator_org_id: "org-1",
        status: "open",
      },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listOrgProjectProposals).mockResolvedValue({
      data: { proposals: [] },
      error: undefined,
      response: okResponse,
    });

    render(
      <ProjectWorkspace
        mode={{ kind: "org", orgId: "org-1" }}
        projectId="project-1"
      />,
    );

    await screen.findByRole("tab", { name: /overview/i });
    expect(screen.queryByRole("tab", { name: /messages/i })).not.toBeInTheDocument();
    expect(listWorkspaceMessages).not.toHaveBeenCalled();
  });

  it("deletes an uncommenced org project from its detail page", async () => {
    const { deleteOrgProject } = await import("@/lib/generated/sdk.gen");
    vi.mocked(loadCurrentUserSession).mockResolvedValue({
      avatar_url: null,
      deactivated_at: null,
      display_name: "Organization Admin",
      email: "admin@example.com",
      email_verified: true,
      id: "admin-1",
      kyc_status: "verified",
      pending_roles: [],
      roles: [],
    });
    vi.mocked(getOrgProject).mockResolvedValue({
      data: {
        ...projectResponse(),
        accepted_proposal_id: null,
        operator_id: null,
        operator_org_id: "org-1",
        status: "open",
      },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listOrgProjectProposals).mockResolvedValue({
      data: { proposals: [] },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listWorkspaceMessages).mockResolvedValue({
      data: { messages: [] },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(deleteOrgProject).mockResolvedValue({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    } as never);
    render(
      <ProjectWorkspace
        mode={{ kind: "org", orgId: "org-1" }}
        projectId="project-1"
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /^delete project$/i }));
    const dialog = screen.getByRole("dialog", { name: /delete this project/i });
    fireEvent.click(within(dialog).getByRole("button", { name: /^delete project$/i }));

    await waitFor(() => expect(deleteOrgProject).toHaveBeenCalledTimes(1));
    expect(nav.replace).toHaveBeenCalledWith(
      "/dashboard/organizations/org-1/projects",
    );
  });

  it("clears the funding query params after returning funded from Stripe", async () => {
    // Reproduces the stale-button bug: Stripe redirects back with
    // `?funded_milestone=<id>` and the page must poll until the Milestone reads
    // funded, then strip the params — without a second manual refresh.
    nav.searchParams = new URLSearchParams(
      "funded=txn-1&funded_milestone=milestone-1",
    );
    vi.mocked(loadCurrentUserSession).mockResolvedValue({
      avatar_url: null,
      deactivated_at: null,
      display_name: "Operator User",
      email: "operator@example.com",
      email_verified: true,
      id: "operator-1",
      kyc_status: "verified",
      pending_roles: [],
      roles: ["operator"],
    });
    vi.mocked(getProject).mockResolvedValue({
      data: { ...projectResponse(), milestone_plan_status: "finalized" },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listProjectProposals).mockResolvedValue({
      data: { proposals: [] },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listMyProjectProposals).mockResolvedValue({
      data: undefined,
      error: { detail: "Forbidden" },
      response: forbiddenResponse,
    });
    vi.mocked(listMilestones).mockResolvedValue({
      data: {
        milestones: [
          {
            approved_at: null,
            budget: "1500.00",
            created_at: "2026-06-20T11:00:00Z",
            currency: "USD",
            description: "Build the model.",
            due_date: null,
            escrow_id: "escrow-1",
            funded_at: "2026-06-21T09:00:00Z",
            id: "milestone-1",
            name: "Implementation",
            project_id: "project-1",
            sequence: 1,
            status: "funded",
            submitted_at: null,
          },
        ],
      },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listWorkspaceMessages).mockResolvedValue({
      data: { messages: [] },
      error: undefined,
      response: okResponse,
    });
    vi.mocked(listDisputes).mockResolvedValue({
      data: { disputes: [] },
      error: undefined,
      response: okResponse,
    });

    render(<ProjectWorkspace projectId="project-1" />);

    await waitFor(() => {
      expect(nav.replace).toHaveBeenCalled();
    });
    // The funding params are gone from the URL it navigated to...
    const target = nav.replace.mock.calls[0][0] as string;
    expect(target).not.toContain("funded_milestone");
    expect(target).not.toContain("funded=");
    // ...and no stale "Fund milestone" button lingers for the funded Milestone.
    expect(
      screen.queryByRole("button", { name: /fund milestone/i }),
    ).not.toBeInTheDocument();
  });
});
