import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectWorkspace } from "@/components/modules/projects/project-workspace";
import { clearAuthToken } from "@/lib/auth/token-store";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import {
  getProject,
  listMilestones,
  listMyProjectProposals,
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

vi.mock("next/navigation", () => ({
  usePathname: () => "/projects/test",
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
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
  getProject: vi.fn(),
  listMilestones: vi.fn(),
  listMyProjectProposals: vi.fn(),
  listProjectProposals: vi.fn(),
  listWorkspaceMessages: vi.fn(),
  submitDeliverable: vi.fn(),
  submitProposal: vi.fn(),
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

    render(<ProjectWorkspace projectId="project-1" />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /procurement playbook/i })).toBeInTheDocument();
    });

    expect(listProjectProposals).toHaveBeenCalledTimes(1);
    expect(listWorkspaceMessages).toHaveBeenCalledTimes(1);
  });
});
