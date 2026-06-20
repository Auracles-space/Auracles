"use client";

/**
 * Project workspace shell.
 *
 * This component intentionally keeps the Project flow in one operational screen:
 * brief, proposals, milestones, workspace messages, and deliverable actions.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { PublishAsFrameworkButton } from "@/components/modules/projects/publish-as-framework-button";
import { ReputationBadge } from "@/components/modules/reputation/reputation-badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { authTokenStore } from "@/lib/auth/token-store";
import {
  acceptProposal,
  approveDeliverable,
  createMilestone,
  createWorkspaceMessage,
  finalizeMilestonePlan,
  fundMilestone,
  getProject,
  listMilestones,
  listMyProjectProposals,
  listProjectProposals,
  listWorkspaceMessages,
  submitDeliverable,
  submitProposal,
} from "@/lib/generated/sdk.gen";
import type {
  DeliverableResponse,
  MilestoneResponse,
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
  budget: "1500.00",
  description: "Build the approved operating model.",
  name: "Implementation",
  sequence: "1",
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
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [operatorProposals, setOperatorProposals] = useState<ProposalResponse[]>([]);
  const [myProposals, setMyProposals] = useState<ProposalResponse[]>([]);
  const [milestones, setMilestones] = useState<MilestoneResponse[]>([]);
  const [messages, setMessages] = useState<WorkspaceMessageResponse[]>([]);
  const [lastDeliverable, setLastDeliverable] = useState<DeliverableResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [proposalScope, setProposalScope] = useState(
    "I will deliver the operating model and rollout plan.",
  );
  const [proposalBudget, setProposalBudget] = useState("1500.00");
  const [milestoneForm, setMilestoneForm] =
    useState<MilestoneFormState>(initialMilestoneForm);
  const deliverableName = "Final playbook";
  const deliverableDescription = "Approved implementation playbook and rollout guide.";
  const [messageBody, setMessageBody] = useState("Implementation update posted.");
  const realtime = useProjectRealtime(projectId);

  const headers = useMemo(() => getAccessTokenHeaders(), []);

  const userRoles = authTokenStore.getState().roles;
  const isOperator = userRoles.includes("operator");
  const isContributor = userRoles.includes("contributor");

  const loadWorkspace = useCallback(async () => {
    configureBrowserClient();
    setError(null);

    const [
      projectResult,
      operatorProposalResult,
      myProposalResult,
      milestonesResult,
      messagesResult,
    ] = await Promise.all([
      getProject({ headers, path: { project_id: projectId } }),
      isOperator
        ? listProjectProposals({ headers, path: { project_id: projectId } })
        : Promise.resolve({ response: new Response(), data: { proposals: [] }, error: undefined }),
      isContributor
        ? listMyProjectProposals({ headers, path: { project_id: projectId } })
        : Promise.resolve({ response: new Response(), data: { proposals: [] }, error: undefined }),
      listMilestones({ headers, path: { project_id: projectId } }),
      listWorkspaceMessages({ headers, path: { project_id: projectId } }),
    ]);

    if (projectResult.response.ok && projectResult.data) {
      setProject(projectResult.data);
    } else {
      setError(describeGeneratedError(projectResult.error));
    }
    if (operatorProposalResult.response.ok && operatorProposalResult.data) {
      setOperatorProposals(operatorProposalResult.data.proposals);
    }
    if (myProposalResult.response.ok && myProposalResult.data) {
      setMyProposals(myProposalResult.data.proposals);
    }
    if (milestonesResult.response.ok && milestonesResult.data) {
      setMilestones(milestonesResult.data.milestones);
    }
    if (messagesResult.response.ok && messagesResult.data) {
      setMessages(messagesResult.data.messages);
    }
  }, [headers, projectId, isOperator, isContributor]);

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

  async function fundProjectMilestone(milestoneId: string) {
    const result = await fundMilestone({
      headers,
      path: { milestone_id: milestoneId, project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setNotice("Milestone funding started.");
    void loadWorkspace();
  }

  async function submitMilestoneDeliverable(milestoneId: string) {
    const result = await submitDeliverable({
      body: {
        description: deliverableDescription,
        file_keys: ["workspace/project/final-playbook.pdf"],
        name: deliverableName,
      },
      headers,
      path: { milestone_id: milestoneId, project_id: projectId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      return;
    }
    setLastDeliverable(result.data);
    setMessages((current) => [
      {
        body: null,
        created_at: result.data.created_at,
        file_keys: null,
        id: `deliverable:${result.data.id}`,
        project_id: projectId,
        scan_status: "visible",
        sender_id: null,
        system_event: "deliverable_submitted",
        system_payload: {
          deliverable_id: result.data.id,
          milestone_id: result.data.milestone_id,
        },
      },
      ...current,
    ]);
    setNotice("Deliverable submitted.");
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
    setLastDeliverable(result.data);
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
          {isContributor ? (
            <form className="grid gap-3" onSubmit={submitProjectProposal}>
              <label className="grid gap-1 text-sm font-semibold text-foreground">
                Proposal scope
                <textarea
                  className="min-h-24 rounded-xl border border-border-default bg-surface-2 px-4 py-3 text-sm font-normal outline-none transition-all focus:border-accent focus:ring-0"
                  onChange={(event) => setProposalScope(event.target.value)}
                  value={proposalScope}
                />
              </label>
              <label className="grid gap-1 text-sm font-semibold text-foreground">
                Budget
                <input
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm font-normal outline-none transition-all focus:border-accent focus:ring-0"
                  onChange={(event) => setProposalBudget(event.target.value)}
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
                    <p className="text-sm font-semibold text-foreground">
                      ${proposal.budget} · {proposal.timeline_days} days
                    </p>
                    <StatusBadge status={proposal.status} />
                  </div>
                  <p className="mt-2 text-sm text-foreground-muted">{proposal.scope}</p>
                  {isOperator && proposal.status === "pending" && project?.status === "open" ? (
                    <button
                      className="mt-3 min-h-12 rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
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

        <section className="grid content-start gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <h2 className="font-heading text-xl font-semibold text-foreground">
            Milestones
          </h2>
          {isContributor ? (
            <form className="grid gap-3" onSubmit={addMilestone}>
              <div className="grid gap-3 md:grid-cols-3">
                <input
                  aria-label="Milestone sequence"
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm outline-none transition-all focus:border-accent focus:ring-0"
                  onChange={(event) =>
                    setMilestoneForm((current) => ({
                      ...current,
                      sequence: event.target.value,
                    }))
                  }
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
                  value={milestoneForm.name}
                />
                <input
                  aria-label="Milestone budget"
                  className="min-h-12 rounded-xl border border-border-default bg-surface-2 px-4 text-sm outline-none transition-all focus:border-accent focus:ring-0"
                  onChange={(event) =>
                    setMilestoneForm((current) => ({
                      ...current,
                      budget: event.target.value,
                    }))
                  }
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
                value={milestoneForm.description}
              />
              <div className="flex flex-wrap gap-3">
                <button
                  className="min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition-all hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
                  disabled={!canAddMilestone}
                  type="submit"
                >
                  Add milestone
                </button>
                <button
                  className="min-h-12 rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
                  onClick={() => void finalizePlan()}
                  type="button"
                >
                  Finalize plan
                </button>
              </div>
            </form>
          ) : null}

          <div className="grid gap-2">
            {milestones.length === 0 ? (
              <p className="text-sm text-foreground-muted italic">
                {project?.status === "open"
                  ? "Milestones will be defined by the contributor after a proposal is accepted."
                  : "No milestones defined yet."}
              </p>
            ) : (
              milestones.map((milestone) => (
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
                  <p className="mt-2 text-sm text-foreground-muted">
                    {milestone.description}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {isOperator && milestone.status === "pending" && project?.milestone_plan_status === "finalized" ? (
                      <button
                        className="min-h-12 rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={() => void fundProjectMilestone(milestone.id)}
                        type="button"
                      >
                        Fund milestone
                      </button>
                    ) : null}
                    {isContributor && milestone.status === "funded" ? (
                      <button
                        className="min-h-12 rounded-xl border border-border-default px-6 text-sm font-semibold text-foreground transition-all hover:bg-surface-3 focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={() => void submitMilestoneDeliverable(milestone.id)}
                        type="button"
                      >
                        Submit deliverable
                      </button>
                    ) : null}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      <section className="grid gap-4 rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-heading text-xl font-semibold text-foreground">
            Workspace
          </h2>
          {isContributor && lastDeliverable ? (
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

        {isOperator && deliverableApprovalActions.map((action) => (
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
    </section>
  );
}
