import { describe, expect, it, vi } from "vitest";
import { projectApi } from "../../../src/lib/projects/project-api-mode";
import * as sdk from "@/lib/generated/sdk.gen";

vi.mock("@/lib/auth/form-client", () => ({
  configureBrowserClient: vi.fn(),
  getAccessTokenHeaders: vi.fn(() => ({ Authorization: "Bearer t" })),
}));

vi.mock("@/lib/generated/sdk.gen", () => ({
  createProject: vi.fn(), createOrgProject: vi.fn(),
  acceptProposal: vi.fn(), acceptOrgProposal: vi.fn(),
  fundMilestone: vi.fn(), fundOrgMilestone: vi.fn(),
  approveDeliverable: vi.fn(), approveOrgDeliverable: vi.fn(),
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
});
