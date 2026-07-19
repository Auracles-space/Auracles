/**
 * Project API mode selector.
 *
 * Returns project operations bound to either the individual endpoints or the
 * organization endpoints (path prefixed with org_id), so shared project
 * components run in org-operator mode without duplication.
 */
import {
  createProject, createOrgProject,
  getProject, getOrgProject,
  listProjectProposals, listOrgProjectProposals,
  cancelAcceptance, cancelOrgAcceptance,
  deleteProject, deleteOrgProject,
  acceptProposal, acceptOrgProposal,
  fundMilestone, fundOrgMilestone,
  approveDeliverable, approveOrgDeliverable,
  requestDeliverableRevision, requestOrgDeliverableRevision,
  createDispute, createOrgDispute,
} from "@/lib/generated/sdk.gen";
import { configureBrowserClient, getAccessTokenHeaders } from "@/lib/auth/form-client";

export type ProjectApiMode = { kind: "self" } | { kind: "org"; orgId: string };

/** Build project operations bound to the given identity mode. */
export function projectApi(mode: ProjectApiMode) {
  const headers = () => {
    configureBrowserClient();
    return getAccessTokenHeaders();
  };
  const orgPath = (extra: Record<string, string>) =>
    mode.kind === "org" ? { org_id: mode.orgId, ...extra } : extra;

  return {
    createProject: (body: unknown) =>
      mode.kind === "org"
        ? createOrgProject({ body: body as never, headers: headers(), path: { org_id: mode.orgId } })
        : createProject({ body: body as never, headers: headers() }),
    getProject: (projectId: string) => {
      const path = orgPath({ project_id: projectId }) as never;
      return mode.kind === "org"
        ? getOrgProject({ headers: headers(), path })
        : getProject({ headers: headers(), path });
    },
    listProjectProposals: (projectId: string) => {
      const path = orgPath({ project_id: projectId }) as never;
      return mode.kind === "org"
        ? listOrgProjectProposals({ headers: headers(), path })
        : listProjectProposals({ headers: headers(), path });
    },
    cancelAcceptance: (projectId: string) => {
      const path = orgPath({ project_id: projectId }) as never;
      return mode.kind === "org"
        ? cancelOrgAcceptance({ headers: headers(), path })
        : cancelAcceptance({ headers: headers(), path });
    },
    deleteProject: (projectId: string) => {
      const path = orgPath({ project_id: projectId }) as never;
      return mode.kind === "org"
        ? deleteOrgProject({ headers: headers(), path })
        : deleteProject({ headers: headers(), path });
    },
    acceptProposal: (projectId: string, proposalId: string) => {
      const path = orgPath({ project_id: projectId, proposal_id: proposalId }) as never;
      return mode.kind === "org"
        ? acceptOrgProposal({ headers: headers(), path })
        : acceptProposal({ headers: headers(), path });
    },
    fundMilestone: (projectId: string, milestoneId: string, body: unknown) => {
      const path = orgPath({ project_id: projectId, milestone_id: milestoneId }) as never;
      return mode.kind === "org"
        ? fundOrgMilestone({ body: body as never, headers: headers(), path })
        : fundMilestone({ body: body as never, headers: headers(), path });
    },
    approveDeliverable: (projectId: string, milestoneId: string, deliverableId: string) => {
      // NOTE: org deliverable approve path omits milestone_id
      const path = mode.kind === "org"
        ? orgPath({ project_id: projectId, deliverable_id: deliverableId }) as never
        : orgPath({ project_id: projectId, milestone_id: milestoneId, deliverable_id: deliverableId }) as never;
      return mode.kind === "org"
        ? approveOrgDeliverable({ headers: headers(), path })
        : approveDeliverable({ headers: headers(), path });
    },
    requestDeliverableRevision: (
      projectId: string,
      milestoneId: string,
      deliverableId: string,
      body: unknown,
    ) => {
      const path = orgPath({
        project_id: projectId,
        milestone_id: milestoneId,
        deliverable_id: deliverableId,
      }) as never;
      return mode.kind === "org"
        ? requestOrgDeliverableRevision({ body: body as never, headers: headers(), path })
        : requestDeliverableRevision({ body: body as never, headers: headers(), path });
    },
    createDispute: (projectId: string, body: unknown) => {
      const path = orgPath({ project_id: projectId }) as never;
      return mode.kind === "org"
        ? createOrgDispute({ body: body as never, headers: headers(), path })
        : createDispute({ body: body as never, headers: headers(), path });
    },
  };
}
