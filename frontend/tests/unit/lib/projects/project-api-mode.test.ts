import { describe, expect, it, vi } from "vitest";
import { projectApi } from "../../../../src/lib/projects/project-api-mode";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createProject: vi.fn(), createOrgProject: vi.fn(),
  getProject: vi.fn(), getOrgProject: vi.fn(),
  listProjectProposals: vi.fn(), listOrgProjectProposals: vi.fn(),
  cancelAcceptance: vi.fn(), cancelOrgAcceptance: vi.fn(),
  deleteProject: vi.fn(), deleteOrgProject: vi.fn(),
  acceptProposal: vi.fn(), acceptOrgProposal: vi.fn(),
  fundMilestone: vi.fn(), fundOrgMilestone: vi.fn(),
  approveDeliverable: vi.fn(), approveOrgDeliverable: vi.fn(),
  requestDeliverableRevision: vi.fn(), requestOrgDeliverableRevision: vi.fn(),
  createDispute: vi.fn(), createOrgDispute: vi.fn(),
}));

describe("projectApi self mode", () => {
  it("createProject calls the self SDK with body only", async () => {
    await projectApi({ kind: "self" }).createProject({ title: "P" } as never);
    expect(sdk.createProject).toHaveBeenCalledWith(expect.objectContaining({ body: { title: "P" } }));
  });
});

describe("projectApi org mode", () => {
  it("createProject calls the org SDK with org_id path", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).createProject({ title: "P" } as never);
    expect(sdk.createOrgProject).toHaveBeenCalledWith(expect.objectContaining({ path: { org_id: "org-1" }, body: { title: "P" } }));
  });

  it("getProject binds org_id and project_id", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).getProject("proj-1");
    expect(sdk.getOrgProject).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1", project_id: "proj-1" } }),
    );
  });

  it("listProjectProposals binds org_id and project_id", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).listProjectProposals("proj-1");
    expect(sdk.listOrgProjectProposals).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1", project_id: "proj-1" } }),
    );
  });

  it("cancelAcceptance binds org_id and project_id", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).cancelAcceptance("proj-1");
    expect(sdk.cancelOrgAcceptance).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1", project_id: "proj-1" } }),
    );
  });

  it("deleteProject binds org_id and project_id", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).deleteProject("proj-1");
    expect(sdk.deleteOrgProject).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1", project_id: "proj-1" } }),
    );
  });

  it("fundMilestone binds org_id, project_id, milestone_id", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).fundMilestone("proj-1", "ms-1", { payment_method_id: "pm1" } as never);
    expect(sdk.fundOrgMilestone).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1", project_id: "proj-1", milestone_id: "ms-1" }, body: { payment_method_id: "pm1" } }),
    );
  });

  it("approveDeliverable binds org_id, project_id, deliverable_id (omits milestone_id)", async () => {
    await projectApi({ kind: "org", orgId: "org-1" }).approveDeliverable("proj-1", "ms-1", "del-1");
    expect(sdk.approveOrgDeliverable).toHaveBeenCalledWith(
      expect.objectContaining({ path: { org_id: "org-1", project_id: "proj-1", deliverable_id: "del-1" } }),
    );
  });

  it("requestDeliverableRevision binds the full org workspace path", async () => {
    const body = { revision_notes: "Please revise." };
    await projectApi({ kind: "org", orgId: "org-1" }).requestDeliverableRevision(
      "proj-1",
      "ms-1",
      "del-1",
      body,
    );
    expect(sdk.requestOrgDeliverableRevision).toHaveBeenCalledWith(
      expect.objectContaining({
        path: {
          org_id: "org-1",
          project_id: "proj-1",
          milestone_id: "ms-1",
          deliverable_id: "del-1",
        },
        body,
      }),
    );
  });
});
