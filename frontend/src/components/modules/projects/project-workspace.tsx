"use client";

/**
 * Project workspace shell.
 *
 * This component intentionally keeps the Project flow in one operational screen:
 * brief, proposals, milestones, workspace messages, and deliverable actions.
 */
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DeliverableSubmitForm } from "@/components/modules/projects/deliverable-submit-form";
import { MilestoneFundingPanel } from "@/components/modules/projects/milestone-funding-panel";
import { PublishAsFrameworkButton } from "@/components/modules/projects/publish-as-framework-button";
import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { loadCurrentUserSession } from "@/lib/auth/current-user-session";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { authTokenStore } from "@/lib/auth/token-store";
import {
  acceptProposal,
  approveDeliverable,
  cancelAcceptance,
  createMilestone,
  createWorkspaceMessage,
  deleteMilestone,
  finalizeMilestonePlan,
  fundMilestone,
  getProject,
  reopenMilestonePlan,
  updateMilestone,
  listMilestones,
  listMyProjectProposals,
  listProjectProposals,
  listWorkspaceMessages,
  submitProposal,
} from "@/lib/generated/sdk.gen";
import type {
  DeliverableResponse,
  MilestoneResponse,
  CurrentUserResponse,
  ProjectResponse,
  ProposalResponse,
  WorkspaceMessageResponse,
} from "@/lib/generated/types.gen";
import { allValid, isNonEmpty, isPositiveNumber } from "@/lib/forms/validators";
import { useProjectRealtime } from "@/lib/projects/realtime";

type ProjectWorkspaceProps = {
  projectId: string;
};

type MilestoneFormState = {
  budget: string;
  description: string;
  name: string;
  sequence: string;
};

const initialMilestoneForm: MilestoneFormState = {
  budget: "",
  description: "",
  name: "",
  sequence: "",
};

/**
 * Return IDs from a workspace system payload when present.
 */
function payloadIds(message: WorkspaceMessageResponse): {
  deliverableId?: string;
  milestoneId?: string;
} {
  const payload = message.system_payload ?? {};
  return {
    deliverableId:
      typeof payload.deliverable_id === "string"
        ? payload.deliverable_id
        : undefined,
    milestoneId:
      typeof payload.milestone_id === "string" ? payload.milestone_id : undefined,
  };
}

/**
 * Render a small status badge.
 */
function StatusBadge({ status }: { status: string }) {
  return (
    <span className="rounded-md border border-[#2563EB]/30 bg-[#2563EB]/10 px-2 py-1 text-xs font-semibold uppercase tracking-[0.05em] text-[#2563EB]">
      {status.replaceAll("_", " ")}
    </span>
  );
}

/**
 * Render the Project workspace.
 */
export function ProjectWorkspace({ projectId }: ProjectWorkspaceProps) {
  const [currentUser, setCurrentUser] = useState<CurrentUserResponse | null>(null);
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [operatorProposals, setOperatorProposals] = useState<ProposalResponse[]>([]);
  const [myProposals, setMyProposals] = useState<ProposalResponse[]>([]);
  const [milestones, setMilestones] = useState<MilestoneResponse[]>([]);
  const [messages, setMessages] = useState<WorkspaceMessageResponse[]>([]);
  const [lastDeliverable, setLastDeliverable] = useState<DeliverableResponse | null>(() => {
    if (typeof window !== "undefined") {
      const saved = window.sessionStorage.getItem(`last_deliverable:${projectId}`);
      if (saved) {
        try {
          return JSON.parse(saved) as DeliverableResponse;
        } catch {
          return null;
        }
      }
    }
    return null;
  });

  const updateLastDeliverable = useCallback((deliverable: DeliverableResponse | null) => {
    setLastDeliverable(deliverable);
    if (typeof window !== "undefined") {
      if (deliverable) {
        window.sessionStorage.setItem(`last_deliverable:${projectId}`, JSON.stringify(deliverable));
      } else {
        window.sessionStorage.removeItem(`last_deliverable:${projectId}`);
      }
    }
  }, [projectId]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [proposalScope, setProposalScope] = useState("");
  const [proposalBudget, setProposalBudget] = useState("");
  const [milestoneForm, setMilestoneForm] =
    useState<MilestoneFormState>(initialMilestoneForm);
  const [editingMilestoneId, setEditingMilestoneId] = useState<string | null>(null);
  const [editMilestoneForm, setEditMilestoneForm] = useState<{
    budget: string;
    description: string;
    name: string;
  }>({ budget: "", description: "", name: "" });
  const [fundingInFlight, setFundingInFlight] = useState(false);
  const [fundingSession, setFundingSession] = useState<{
    milestoneId: string;
    clientSecret: string;
    transactionId: string;
  } | null>(null);
  const [deliverableFormMilestoneId, setDeliverableFormMilestoneId] = useState<
    string | null
  >(null);
  const [messageBody, setMessageBody] = useState("");
  const realtime = useProjectRealtime(projectId);

  const headers = useMemo(() => getAccessTokenHeaders(), []);

  const currentUserId = currentUser?.id ?? authTokenStore.getState().userId;
  const userRoles = currentUser?.roles ?? authTokenStore.getState().roles;
  const isOperator = userRoles.includes("operator");
  const isContributor = userRoles.includes("contributor");

  // Project-specific roles and ownership
  const isProjectOwner = project !== null && project.operator_id === currentUserId;
  const isAssignedContributor = myProposals.some((p) => p.status === "accepted");

  // Gating visibility of forms and actions
  // Re-bidding is allowed after a rejected/withdrawn proposal: gate on having no
  // *active* (pending/accepted) proposal, not on never having proposed before.
  const hasActiveProposal = myProposals.some(
    (proposal) => proposal.status === "pending" || proposal.status === "accepted",
  );
  const showProposalForm =
    isContributor &&
    project !== null &&
    !isProjectOwner &&
    project.status === "open" &&
    !hasActiveProposal;
  const showAcceptButton = isProjectOwner && project?.status === "open";
  const showMilestoneForm = isAssignedContributor && project?.milestone_plan_status === "draft";
  // Either member may reopen a finalized plan to renegotiate the split, but only
  // before any milestone is funded (escrow stays untouched).
  const canReopenPlan =
    (isProjectOwner || isAssignedContributor) &&
    project?.milestone_plan_status === "finalized" &&
    milestones.length > 0 &&
    milestones.every((milestone) => milestone.status === "pending");
  // Either member may unwind an acceptance while it is still unfunded
  // (project assigned, no escrow). After funding, disputes are the exit.
  const canCancelAcceptance =
    (isProjectOwner || isAssignedContributor) && project?.status === "assigned";

  // Finalize requires a balanced plan: at least one milestone whose budgets sum
  // exactly to the accepted Proposal budget. Compared in integer cents to avoid
  // float drift; mirrors the backend's strict SUM == proposal.budget gate.
  const acceptedProposalBudget =
    myProposals.find((proposal) => proposal.status === "accepted")?.budget ?? null;
  const milestoneTotalCents = milestones.reduce(
    (sum, milestone) => sum + Math.round(Number(milestone.budget) * 100),
    0,
  );
  const proposalBudgetCents =
    acceptedProposalBudget !== null
      ? Math.round(Number(acceptedProposalBudget) * 100)
      : null;
  const milestoneRemainingCents =
    proposalBudgetCents !== null ? proposalBudgetCents - milestoneTotalCents : null;
  const canFinalizePlan =
    milestones.length > 0 && milestoneRemainingCents === 0;

  const loadWorkspace = useCallback(async () => {
    configureBrowserClient();
    setError(null);

    const sessionUser = await loadCurrentUserSession();
    if (sessionUser === null) {
      setError("Please sign in again.");
      return;
    }
    setCurrentUser(sessionUser);

    const activeHeaders = getAccessTokenHeaders();
    const activeRoles = sessionUser.roles;
    const activeUserId = sessionUser.id;
    const isOperatorRole = activeRoles.includes("operator");
    const isContributorRole = activeRoles.includes("contributor");

    const projectResult = await getProject({
      headers: activeHeaders,
      path: { project_id: projectId },
    });
    if (!projectResult.response.ok || !projectResult.data) {
      setError(describeGeneratedError(projectResult.error));
      return;
    }

    const currentProject = projectResult.data;
    setProject(currentProject);

    const hasAcceptedProposal = currentProject.accepted_proposal_id !== null;

    const [
      operatorProposalResult,
      myProposalResult,
    ] = await Promise.all([
      isOperatorRole
        ? listProjectProposals({
            headers: activeHeaders,
            path: { project_id: projectId },
          })
        : Promise.resolve({ response: new Response(), data: { proposals: [] }, error: undefined }),
      isContributorRole
        ? listMyProjectProposals({
            headers: activeHeaders,
            path: { project_id: projectId },
          })
        : Promise.resolve({ response: new Response(), data: { proposals: [] }, error: undefined }),
    ]);

    let activeOperatorProposals: ProposalResponse[] = [];
    let activeMyProposals: ProposalResponse[] = [];

    if (operatorProposalResult.response.ok && operatorProposalResult.data) {
      activeOperatorProposals = operatorProposalResult.data.proposals;
      setOperatorProposals(activeOperatorProposals);
    }
    if (myProposalResult.response.ok && myProposalResult.data) {
      activeMyProposals = myProposalResult.data.proposals;
      setMyProposals(activeMyProposals);
    }

    const activeProjectOwner = currentProject.operator_id === activeUserId;
    const activeAssignedContributor = activeMyProposals.some((p) => p.status === "accepted");
    const activeProjectMember = activeProjectOwner || activeAssignedContributor;

    const [
      milestonesResult,
      messagesResult,
    ] = await Promise.all([
      hasAcceptedProposal
        ? listMilestones({
            headers: activeHeaders,
            path: { project_id: projectId },
          })
        : Promise.resolve({ response: new Response(), data: { milestones: [] }, error: undefined }),
      activeProjectMember
        ? listWorkspaceMessages({
            headers: activeHeaders,
            path: { project_id: projectId },
          })
        : Promise.resolve({ response: new Response(), data: { messages: [] }, error: undefined }),
    ]);

    if (milestonesResult.response.ok && milestonesResult.data) {
      setMilestones(milestonesResult.data.milestones);
    }
    if (messagesResult.response.ok && messagesResult.data) {
      setMessages(messagesResult.data.messages);
    }
  }, [projectId]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace, realtime.lastEvent]);

  async function submitProjectProposal(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await submitProposal({
      body: {
        budget: proposalBudget,
        currency: "USD",
        deliverables: [
          {
            description: "Implementation playbook and rollout plan.",
            name: "Implementation playbook",
          },
        ],
        scope: proposalScope,
        timeline_days: 30,
      },
      headers,
      path: { project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setNotice("Proposal submitted.");
    setMyProposals([result.data]);
    setProposalScope("");
    setProposalBudget("");
  }

  async function acceptProjectProposal(proposalId: string) {
    const result = await acceptProposal({
      headers,
      path: { project_id: projectId, proposal_id: proposalId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setProject(result.data);
    setNotice("Proposal accepted.");
    void loadWorkspace();
  }

  async function addMilestone(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await createMilestone({
      body: {
        budget: milestoneForm.budget,
        currency: "USD",
        description: milestoneForm.description,
        name: milestoneForm.name,
        sequence: Number(milestoneForm.sequence),
      },
      headers,
      path: { project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setMilestones((current) => [...current, result.data]);
    setNotice("Milestone added.");
    setMilestoneForm(initialMilestoneForm);
    void loadWorkspace();
  }

  async function finalizePlan() {
    const result = await finalizeMilestonePlan({
      headers,
      path: { project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setProject(result.data);
    setNotice("Milestone plan finalized.");
    void loadWorkspace();
  }

  async function reopenPlan() {
    const result = await reopenMilestonePlan({
      headers,
      path: { project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setProject(result.data);
    setNotice("Milestone plan reopened for changes.");
    void loadWorkspace();
  }

  async function cancelAcceptanceAction() {
    const result = await cancelAcceptance({
      headers,
      path: { project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setProject(result.data);
    setNotice(
      isProjectOwner
        ? "Acceptance cancelled. The project is open for new proposals."
        : "You have withdrawn from this project.",
    );
    void loadWorkspace();
  }

  function startEditMilestone(milestone: MilestoneResponse) {
    setEditingMilestoneId(milestone.id);
    setEditMilestoneForm({
      budget: String(milestone.budget),
      description: milestone.description,
      name: milestone.name,
    });
    setError(null);
  }

  function cancelEditMilestone() {
    setEditingMilestoneId(null);
  }

  async function saveMilestoneEdit(milestoneId: string) {
    const result = await updateMilestone({
      body: {
        budget: editMilestoneForm.budget,
        description: editMilestoneForm.description,
        name: editMilestoneForm.name,
      },
      headers,
      path: { milestone_id: milestoneId, project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    const updated = result.data;
    setMilestones((current) =>
      current.map((milestone) =>
        milestone.id === milestoneId ? updated : milestone,
      ),
    );
    setEditingMilestoneId(null);
    setNotice("Milestone updated.");
    void loadWorkspace();
  }

  async function deleteProjectMilestone(milestoneId: string) {
    const result = await deleteMilestone({
      headers,
      path: { milestone_id: milestoneId, project_id: projectId },
    });
    if (!result.response.ok) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setMilestones((current) =>
      current.filter((milestone) => milestone.id !== milestoneId),
    );
    if (editingMilestoneId === milestoneId) {
      setEditingMilestoneId(null);
    }
    setNotice("Milestone removed.");
    void loadWorkspace();
  }

  async function fundProjectMilestone(milestoneId: string) {
    setError(null);
    setFundingInFlight(true);
    const result = await fundMilestone({
      headers,
      path: { milestone_id: milestoneId, project_id: projectId },
    });
    setFundingInFlight(false);
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    // Open the Stripe payment panel with the returned PaymentIntent secret;
    // escrow funds only after the Operator completes payment.
    setFundingSession({
      milestoneId,
      clientSecret: result.data.client_secret,
      transactionId: result.data.transaction_id,
    });
  }

  function onDeliverableSubmitted(deliverable: DeliverableResponse) {
    updateLastDeliverable(deliverable);
    setMessages((current) => [
      {
        body: null,
        created_at: deliverable.created_at,
        file_keys: null,
        id: `deliverable:${deliverable.id}`,
        project_id: projectId,
        scan_status: "visible",
        sender_id: null,
        system_event: "deliverable_submitted",
        system_payload: {
          deliverable_id: deliverable.id,
          milestone_id: deliverable.milestone_id,
        },
      },
      ...current,
    ]);
    setNotice(
      "Deliverable submitted. Files are scanned for viruses before the operator can approve.",
    );
    setDeliverableFormMilestoneId(null);
    void loadWorkspace();
  }

  async function approveMilestoneDeliverable(
    milestoneId: string,
    deliverableId: string,
  ) {
    const result = await approveDeliverable({
      headers,
      path: {
        deliverable_id: deliverableId,
        milestone_id: milestoneId,
        project_id: projectId,
      },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    updateLastDeliverable(result.data);
    setNotice("Deliverable approved.");
    void loadWorkspace();
  }

  async function postWorkspaceMessage(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = await createWorkspaceMessage({
      body: { body: messageBody },
      headers,
      path: { project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setMessages((current) => [result.data, ...current]);
    setMessageBody("");
  }

  const deliverableApprovalActions = messages
    .filter((message) => message.system_event === "deliverable_submitted")
    .map((message) => ({ ...payloadIds(message), messageId: message.id }))
    .filter((ids) => ids.deliverableId && ids.milestoneId);

  const canSubmitProposal = allValid(
    isNonEmpty(proposalScope),
    isPositiveNumber(proposalBudget),
  );
  const canAddMilestone = allValid(
    isNonEmpty(milestoneForm.name),
    isPositiveNumber(milestoneForm.budget),
    isPositiveNumber(milestoneForm.sequence),
  );
  const canPostMessage = isNonEmpty(messageBody);

  return (
    <section className="mx-auto grid max-w-7xl gap-6 px-4 py-8 md:px-8">
      <div className="flex items-center">
        <Link
          className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold text-accent hover:underline"
          href="/projects"
        >
          <svg
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M10 19l-7-7m0 0l7-7m-7 7h18"
            />
          </svg>
          Back to projects
        </Link>
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              Project workspace
            </p>
            <h1 className="mt-2 flex items-center font-heading text-3xl font-bold text-foreground">
              {project ? project.title : <Skeleton className="h-9 w-64 rounded-xl" />}
            </h1>
            <div className="mt-3 max-w-3xl text-sm leading-6 text-foreground-muted">
              {project ? project.description : (
                <div className="space-y-2">
                  <Skeleton className="h-5 w-full rounded-md" />
                  <Skeleton className="h-5 w-3/4 rounded-md" />
                </div>
              )}
            </div>
          </div>
          <div className="grid justify-items-end gap-2 text-right">
            {project ? <StatusBadge status={project.status} /> : null}
            {project?.operator_reputation ? (
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] font-medium uppercase tracking-[0.05em] text-foreground-subtle">
                  Operator
                </span>
                <ReputationBadge
                  score={project.operator_reputation.score ?? null}
                  isProvisional={
                    project.operator_reputation.is_provisional ?? true
                  }
                  factors={project.operator_reputation.factors ?? []}
                />
              </div>
            ) : null}
            <span className="text-xs text-foreground-muted">
              Realtime {realtime.connected ? "connected" : "offline"}
            </span>
          </div>
        </div>
      </div>

      {canCancelAcceptance ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#DC2626]/30 bg-[#DC2626]/5 p-4">
          <p className="text-sm text-foreground-muted">
            {isProjectOwner
              ? "No milestone is funded yet. You can cancel and reopen this project for new proposals."
              : "No milestone is funded yet. You can withdraw from this project."}
          </p>
          <button
            className="min-h-12 rounded-xl border border-[#DC2626]/40 px-6 text-sm font-semibold text-[#DC2626] transition-all hover:bg-[#DC2626]/10 focus-visible:ring-2 focus-visible:ring-[#DC2626]"
            onClick={() => void cancelAcceptanceAction()}
            type="button"
          >
            {isProjectOwner ? "Cancel acceptance" : "Withdraw from project"}
          </button>
        </div>
      ) : null}

      {error ? (
        <p className="rounded-xl border border-[#DC2626]/30 bg-[#DC2626]/10 p-3 text-sm text-[#DC2626]">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="rounded-xl border border-[#16A34A]/30 bg-[#16A34A]/10 p-3 text-sm text-[#16A34A]">
          {notice}
        </p>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <section className="grid content-start gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <h2 className="font-heading text-xl font-semibold text-foreground">
            Proposals
          </h2>
          {showProposalForm ? (
            <form className="grid gap-3" onSubmit={submitProjectProposal}>
              <label className="grid gap-1 text-sm font-semibold text-foreground">
                Proposal scope
                <textarea
                  className="min-h-24 rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm font-normal outline-none transition-all focus:border-accent focus:ring-0"
                  onChange={(event) => setProposalScope(event.target.value)}
                  placeholder="Describe your approach, scope, and deliverables..."
                  value={proposalScope}
                />
              </label>
              <label className="grid gap-1 text-sm font-semibold text-foreground">
                Budget
                <input
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm font-normal outline-none transition-all focus:border-accent focus:ring-0"
                  inputMode="decimal"
                  onChange={(event) => {
                    const cleaned = event.target.value.replace(/[^0-9.]/g, "");
                    const parts = cleaned.split(".");
                    if (parts.length > 2) return;
                    setProposalBudget(cleaned);
                  }}
                  pattern="[0-9]*[.]?[0-9]*"
                  placeholder="e.g. 1500.00"
                  type="text"
                  value={proposalBudget}
                />
              </label>
              <button
                className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                disabled={!canSubmitProposal}
                type="submit"
              >
                Submit proposal
              </button>
            </form>
          ) : null}

          <div className="grid gap-2">
            {operatorProposals.length === 0 && myProposals.length === 0 ? (
              <p className="text-sm text-foreground-muted italic">
                {isOperator
                  ? "No proposals submitted yet."
                  : "Submit a proposal below to bid on this project."}
              </p>
            ) : (
              [...operatorProposals, ...myProposals].map((proposal) => (
                <div
                  className="rounded-xl border border-border-default bg-surface-2 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
                  key={proposal.id}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-foreground">
                        {proposal.contributor_name ?? "Contributor"}
                      </p>
                      <p className="text-xs text-foreground-muted">
                        ${proposal.budget} · {proposal.timeline_days} days
                      </p>
                    </div>
                    <StatusBadge status={proposal.status} />
                  </div>
                  <p className="mt-2 text-sm text-foreground-muted">{proposal.scope}</p>
                  {showAcceptButton && proposal.status === "pending" ? (
                    <button
                      className="mt-3 min-h-12 rounded-xl bg-accent px-6 text-sm font-semibold text-white shadow-sm transition-all hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-accent"
                      onClick={() => void acceptProjectProposal(proposal.id)}
                      type="button"
                    >
                      Accept proposal
                    </button>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </section>

        <section className={`grid content-start gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm ${project?.status === "open" ? "opacity-60 select-none pointer-events-none" : ""}`}>
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-heading text-xl font-semibold text-foreground">
              Milestones
            </h2>
            {project?.status === "open" ? (
              <span className="rounded-badge border border-border-default bg-surface-2 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.05em] text-foreground-subtle">
                Inactive
              </span>
            ) : null}
          </div>
          {showMilestoneForm ? (
            <form className="grid gap-3" onSubmit={addMilestone}>
              <div className="grid gap-3 md:grid-cols-3">
                <input
                  aria-label="Milestone sequence"
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm outline-none transition-all focus:border-accent focus:ring-0"
                  inputMode="numeric"
                  onChange={(event) => {
                    const cleaned = event.target.value.replace(/[^0-9]/g, "");
                    setMilestoneForm((current) => ({
                      ...current,
                      sequence: cleaned,
                    }));
                  }}
                  pattern="[0-9]*"
                  placeholder="Sequence (e.g. 1)"
                  type="text"
                  value={milestoneForm.sequence}
                />
                <input
                  aria-label="Milestone name"
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm outline-none transition-all focus:border-accent focus:ring-0"
                  onChange={(event) =>
                    setMilestoneForm((current) => ({
                      ...current,
                      name: event.target.value,
                    }))
                  }
                  placeholder="Milestone name (e.g. Design)"
                  type="text"
                  value={milestoneForm.name}
                />
                <input
                  aria-label="Milestone budget"
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm outline-none transition-all focus:border-accent focus:ring-0"
                  inputMode="decimal"
                  onChange={(event) => {
                    const cleaned = event.target.value.replace(/[^0-9.]/g, "");
                    const parts = cleaned.split(".");
                    if (parts.length > 2) return;
                    setMilestoneForm((current) => ({
                      ...current,
                      budget: cleaned,
                    }));
                  }}
                  pattern="[0-9]*[.]?[0-9]*"
                  placeholder="Budget (e.g. 1500.00)"
                  type="text"
                  value={milestoneForm.budget}
                />
              </div>
              <textarea
                aria-label="Milestone description"
                className="min-h-20 rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm outline-none transition-all focus:border-accent focus:ring-0"
                onChange={(event) =>
                  setMilestoneForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
                placeholder="Describe milestone deliverables..."
                value={milestoneForm.description}
              />
              {milestoneRemainingCents !== null ? (
                <p className="text-xs text-foreground-muted">
                  {milestones.length === 0
                    ? `Add milestones totaling $${(
                        (proposalBudgetCents ?? 0) / 100
                      ).toFixed(2)} to finalize.`
                    : milestoneRemainingCents > 0
                      ? `Remaining to allocate: $${(
                          milestoneRemainingCents / 100
                        ).toFixed(2)} before you can finalize.`
                      : milestoneRemainingCents < 0
                        ? `Over budget by $${(
                            -milestoneRemainingCents / 100
                          ).toFixed(2)} — lower or remove a milestone.`
                        : "Balanced — ready to finalize."}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-3">
                <button
                  className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!canAddMilestone}
                  type="submit"
                >
                  Add milestone
                </button>
                <button
                  className="min-h-12 rounded-xl bg-[#16A34A] px-6 text-sm font-semibold text-white shadow-sm transition-all hover:bg-[#16A34A]/90 focus-visible:ring-2 focus-visible:ring-[#16A34A] disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!canFinalizePlan}
                  onClick={() => void finalizePlan()}
                  type="button"
                >
                  Finalize plan
                </button>
              </div>
            </form>
          ) : null}

          {canReopenPlan ? (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border-default bg-surface-2 p-4">
              <p className="text-sm text-foreground-muted">
                Plan finalized. Reopen to change the milestone breakdown before
                funding begins.
              </p>
              <button
                className="min-h-12 rounded-xl border border-accent/40 bg-accent/5 px-6 text-sm font-semibold text-accent transition-all hover:bg-accent/10 focus-visible:ring-2 focus-visible:ring-accent"
                onClick={() => void reopenPlan()}
                type="button"
              >
                Reopen plan
              </button>
            </div>
          ) : null}

          <div className="grid gap-2">
            {milestones.length === 0 ? (
              <p className="text-sm text-foreground-muted italic">
                {project?.status === "open"
                  ? "Milestones will be defined by the contributor after a proposal is accepted."
                  : "No milestones defined yet."}
              </p>
            ) : (
              milestones.map((milestone) => {
                const canManage =
                  isAssignedContributor &&
                  milestone.status === "pending" &&
                  project?.milestone_plan_status === "draft";
                const isEditing = editingMilestoneId === milestone.id;
                return (
                  <div
                    className="rounded-xl border border-border-default bg-surface-2 p-4 shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
                    key={milestone.id}
                  >
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <p className="font-semibold text-foreground">
                        {milestone.sequence}. {milestone.name} · ${milestone.budget}
                      </p>
                      <StatusBadge status={milestone.status} />
                    </div>
                    {isEditing ? (
                      <div className="mt-3 grid gap-3">
                        <label className="grid gap-1 text-sm">
                          <span className="font-medium text-foreground">Name</span>
                          <input
                            className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
                            onChange={(event) =>
                              setEditMilestoneForm((form) => ({
                                ...form,
                                name: event.target.value,
                              }))
                            }
                            value={editMilestoneForm.name}
                          />
                        </label>
                        <label className="grid gap-1 text-sm">
                          <span className="font-medium text-foreground">
                            Budget (USD)
                          </span>
                          <input
                            className="min-h-12 rounded-xl border border-border-default bg-surface-1 px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
                            inputMode="decimal"
                            onChange={(event) =>
                              setEditMilestoneForm((form) => ({
                                ...form,
                                budget: event.target.value,
                              }))
                            }
                            value={editMilestoneForm.budget}
                          />
                        </label>
                        <label className="grid gap-1 text-sm">
                          <span className="font-medium text-foreground">
                            Description
                          </span>
                          <textarea
                            className="min-h-20 rounded-xl border border-border-default bg-surface-1 px-3 py-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent"
                            onChange={(event) =>
                              setEditMilestoneForm((form) => ({
                                ...form,
                                description: event.target.value,
                              }))
                            }
                            value={editMilestoneForm.description}
                          />
                        </label>
                      </div>
                    ) : (
                      <p className="mt-2 text-sm text-foreground-muted">
                        {milestone.description}
                      </p>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {isProjectOwner &&
                      milestone.status === "pending" &&
                      project?.milestone_plan_status === "finalized" &&
                      fundingSession?.milestoneId !== milestone.id ? (
                        <button
                          className="min-h-12 rounded-xl bg-accent px-6 text-sm font-semibold text-white shadow-sm transition-all hover:bg-accent/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                          disabled={fundingInFlight || fundingSession !== null}
                          onClick={() => void fundProjectMilestone(milestone.id)}
                          type="button"
                        >
                          {fundingInFlight ? "Preparing payment" : "Fund milestone"}
                        </button>
                      ) : null}
                      {isAssignedContributor &&
                      (milestone.status === "funded" ||
                        milestone.status === "revision_requested") &&
                      deliverableFormMilestoneId !== milestone.id ? (
                        <button
                          className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
                          onClick={() => setDeliverableFormMilestoneId(milestone.id)}
                          type="button"
                        >
                          Submit deliverable
                        </button>
                      ) : null}
                      {canManage && isEditing ? (
                        <>
                          <button
                            className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
                            onClick={() => void saveMilestoneEdit(milestone.id)}
                            type="button"
                          >
                            Save
                          </button>
                          <button
                            className="min-h-12 rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
                            onClick={cancelEditMilestone}
                            type="button"
                          >
                            Cancel
                          </button>
                        </>
                      ) : null}
                      {canManage && !isEditing ? (
                        <>
                          <button
                            className="min-h-12 rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
                            onClick={() => startEditMilestone(milestone)}
                            type="button"
                          >
                            Edit
                          </button>
                          <button
                            className="min-h-12 rounded-xl border border-[#DC2626]/40 px-6 text-sm font-semibold text-[#DC2626] transition-all hover:bg-[#DC2626]/10 focus-visible:ring-2 focus-visible:ring-[#DC2626]"
                            onClick={() => void deleteProjectMilestone(milestone.id)}
                            type="button"
                          >
                            Delete
                          </button>
                        </>
                      ) : null}
                    </div>
                    {fundingSession?.milestoneId === milestone.id ? (
                      <MilestoneFundingPanel
                        clientSecret={fundingSession.clientSecret}
                        onCancel={() => setFundingSession(null)}
                        projectId={projectId}
                        transactionId={fundingSession.transactionId}
                      />
                    ) : null}
                    {deliverableFormMilestoneId === milestone.id ? (
                      <DeliverableSubmitForm
                        milestoneId={milestone.id}
                        onCancel={() => setDeliverableFormMilestoneId(null)}
                        onSubmitted={onDeliverableSubmitted}
                        projectId={projectId}
                      />
                    ) : null}
                  </div>
                );
              })
            )}
          </div>
        </section>
      </div>

      {isProjectOwner || isAssignedContributor ? (
        <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-heading text-xl font-semibold text-foreground">
              Workspace
            </h2>
            {isAssignedContributor && lastDeliverable ? (
              <PublishAsFrameworkButton
                deliverableId={lastDeliverable.id}
                description={lastDeliverable.description}
                fileKeys={lastDeliverable.file_keys}
                projectId={projectId}
                status={lastDeliverable.status}
                title={lastDeliverable.name}
              />
            ) : null}
          </div>
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={postWorkspaceMessage}>
            <input
              aria-label="Workspace message"
              className="min-h-12 flex-1 rounded-xl border border-border-default bg-surface-2 px-4 text-sm outline-none transition-all focus:border-accent focus:ring-0"
              onChange={(event) => setMessageBody(event.target.value)}
              placeholder="Type a message..."
              value={messageBody}
            />
            <button
              className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
              disabled={!canPostMessage}
              type="submit"
            >
              Post message
            </button>
          </form>

          {isProjectOwner && deliverableApprovalActions.map((action) => (
            <button
              className="min-h-12 rounded-xl border border-[#16A34A]/30 bg-[#16A34A]/10 px-6 text-sm font-semibold text-[#16A34A] transition-all hover:bg-[#16A34A]/20 outline-none focus-visible:ring-2 focus-visible:ring-accent"
              key={action.messageId}
              onClick={() =>
                void approveMilestoneDeliverable(
                  action.milestoneId ?? "",
                  action.deliverableId ?? "",
                )
              }
              type="button"
            >
              Approve deliverable
            </button>
          ))}

          <div className="grid gap-2">
            {messages.map((message) => (
              <article
                className="rounded-xl border border-border-default bg-surface-2 p-4 text-sm shadow-[0_1px_2px_rgba(0,0,0,0.02)]"
                key={message.id}
              >
                <p className="font-semibold text-foreground">
                  {message.system_event ?? "Message"}
                </p>
                <p className="mt-1 text-foreground-muted">
                  {message.body ?? JSON.stringify(message.system_payload ?? {})}
                </p>
              </article>
            ))}
          </div>
        </section>
      ) : null}
    </section>
  );
}
