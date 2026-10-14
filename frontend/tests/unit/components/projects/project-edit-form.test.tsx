/**
 * Operator Project edit form tests.
 *
 * The backend has accepted PATCH /v1/projects/{id} since Phase 4a but nothing
 * in the product ever called it, so a posted Project was immutable in the UI.
 * These pin the two behaviours that make the form safe to use: it sends only
 * what changed, and it refuses to offer the bid-sensitive terms once a
 * Contributor has priced against them.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectEditForm } from "@/components/modules/projects/project-edit-form";
import {
  getProject,
  listProjectProposals,
  updateProject,
} from "@/lib/generated/sdk.gen";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  describeGeneratedError: (error: { detail?: string } | undefined) =>
    error?.detail ?? "The request could not be completed.",
  getAccessTokenHeaders: () => ({ Authorization: "Bearer access-token" }),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createProject: vi.fn(),
  createOrgProject: vi.fn(),
  getProject: vi.fn(),
  getOrgProject: vi.fn(),
  listProjectProposals: vi.fn(),
  listOrgProjectProposals: vi.fn(),
  cancelAcceptance: vi.fn(),
  cancelOrgAcceptance: vi.fn(),
  deleteProject: vi.fn(),
  deleteOrgProject: vi.fn(),
  acceptProposal: vi.fn(),
  acceptOrgProposal: vi.fn(),
  fundMilestone: vi.fn(),
  fundOrgMilestone: vi.fn(),
  approveDeliverable: vi.fn(),
  approveOrgDeliverable: vi.fn(),
  requestDeliverableRevision: vi.fn(),
  requestOrgDeliverableRevision: vi.fn(),
  createDispute: vi.fn(),
  createOrgDispute: vi.fn(),
  updateProject: vi.fn(),
  updateOrgProject: vi.fn(),
}));

const okResponse = () => new Response(null, { status: 200 });

function projectResponse(overrides: Record<string, unknown> = {}) {
  return {
    accepted_proposal_id: null,
    budget_max: "2000000.00",
    budget_min: "1000000.00",
    category: "operations",
    closed_at: null,
    created_at: "2026-06-20T10:00:00Z",
    currency: "NGN",
    deadline: "2026-12-01",
    delivered_at: null,
    description: "Build a procurement operating model.",
    expires_at: "2026-12-31T00:00:00Z",
    id: "project-1",
    milestone_plan_status: "draft",
    operator_id: "operator-1",
    required_deliverables: [
      { description: "Implementation guide", name: "Playbook" },
    ],
    status: "open",
    title: "Procurement Playbook",
    updated_at: "2026-06-20T10:00:00Z",
    ...overrides,
  };
}

function mockLoad(proposals: Array<Record<string, unknown>> = []) {
  vi.mocked(getProject).mockResolvedValue({
    data: projectResponse(),
    error: undefined,
    response: okResponse(),
  } as never);
  vi.mocked(listProjectProposals).mockResolvedValue({
    data: { proposals },
    error: undefined,
    response: okResponse(),
  } as never);
}

describe("ProjectEditForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    push.mockReset();
  });

  it("sends only the fields that changed", async () => {
    // A full-payload PATCH would resend the budget untouched, which the
    // backend refuses once a bid is pending — and would overwrite a field
    // another session had just changed. The diff keeps both from happening.
    mockLoad();
    vi.mocked(updateProject).mockResolvedValue({
      data: projectResponse({ title: "Procurement Playbook v2" }),
      error: undefined,
      response: okResponse(),
    } as never);

    render(<ProjectEditForm mode={{ kind: "self" }} projectId="project-1" />);

    const title = await screen.findByLabelText(/^title$/i);
    expect(title).toHaveValue("Procurement Playbook");
    fireEvent.change(title, { target: { value: "Procurement Playbook v2" } });
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(updateProject).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateProject).mock.calls[0][0]).toMatchObject({
      body: { title: "Procurement Playbook v2" },
      path: { project_id: "project-1" },
    });
    expect(
      Object.keys(vi.mocked(updateProject).mock.calls[0][0].body as object),
    ).toEqual(["title"]);
    expect(push).toHaveBeenCalledWith("/projects/project-1");
  });

  it("locks budget and deliverables once a Proposal is pending", async () => {
    // Contributors price against the posted budget and the deliverables asked
    // for. The backend refuses the edit; the form has to say so before the
    // Operator types a number it will reject.
    mockLoad([{ id: "proposal-1", status: "pending" }]);

    render(<ProjectEditForm mode={{ kind: "self" }} projectId="project-1" />);

    expect(await screen.findByLabelText(/minimum budget/i)).toBeDisabled();
    expect(screen.getByLabelText(/maximum budget/i)).toBeDisabled();
    expect(screen.getByLabelText(/deliverable name/i)).toBeDisabled();
    expect(screen.getByText(/while a proposal is pending/i)).toBeInTheDocument();
    // The descriptive fields carry no bid weight, so they stay open.
    expect(screen.getByLabelText(/^title$/i)).not.toBeDisabled();
  });

  it("keeps the budget editable when no Proposal is pending", async () => {
    mockLoad([{ id: "proposal-1", status: "withdrawn" }]);

    render(<ProjectEditForm mode={{ kind: "self" }} projectId="project-1" />);

    expect(await screen.findByLabelText(/minimum budget/i)).not.toBeDisabled();
    expect(
      screen.queryByText(/while a proposal is pending/i),
    ).not.toBeInTheDocument();
  });

  it("surfaces the backend's refusal rather than a generic failure", async () => {
    mockLoad();
    vi.mocked(updateProject).mockResolvedValue({
      data: undefined,
      error: { detail: "Only open Projects can be edited." },
      response: new Response(null, { status: 409 }),
    } as never);

    render(<ProjectEditForm mode={{ kind: "self" }} projectId="project-1" />);

    fireEvent.change(await screen.findByLabelText(/^title$/i), {
      target: { value: "Renamed" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    expect(
      await screen.findByText(/only open projects can be edited/i),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("returns an org Project to its organization workspace", async () => {
    mockLoad();
    const { getOrgProject, listOrgProjectProposals, updateOrgProject } =
      await import("@/lib/generated/sdk.gen");
    vi.mocked(getOrgProject).mockResolvedValue({
      data: projectResponse(),
      error: undefined,
      response: okResponse(),
    } as never);
    vi.mocked(listOrgProjectProposals).mockResolvedValue({
      data: { proposals: [] },
      error: undefined,
      response: okResponse(),
    } as never);
    vi.mocked(updateOrgProject).mockResolvedValue({
      data: projectResponse({ title: "Renamed" }),
      error: undefined,
      response: okResponse(),
    } as never);

    render(
      <ProjectEditForm
        mode={{ kind: "org", orgId: "org-1" }}
        projectId="project-1"
      />,
    );

    fireEvent.change(await screen.findByLabelText(/^title$/i), {
      target: { value: "Renamed" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(updateOrgProject).toHaveBeenCalledTimes(1));
    expect(vi.mocked(updateOrgProject).mock.calls[0][0]).toMatchObject({
      path: { org_id: "org-1", project_id: "project-1" },
    });
    expect(push).toHaveBeenCalledWith(
      "/dashboard/organizations/org-1/projects/project-1",
    );
  });
});
