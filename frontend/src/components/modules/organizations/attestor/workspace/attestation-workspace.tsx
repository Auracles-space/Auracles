"use client";

/**
 * Review workspace for one attestation, seen by the attestor organization.
 *
 * Frames the review: what is being reviewed and in what state, when it is due,
 * what the requestor asked for, and — on a dispute or a revision request —
 * what is being challenged and by when it must be answered. The review tools
 * themselves (files, rubric, annotations, clarifications, report) hang off it.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeftIcon, ExclamationTriangleIcon } from "@radix-ui/react-icons";

import { getAttestation, listOrgAttestations } from "@/lib/generated/sdk.gen";
import type {
  AttestationRequestResponse,
  OrgAttestationItem,
} from "@/lib/generated/types.gen";
import { getAccessTokenHeaders, describeGeneratedError } from "@/lib/auth/form-client";
import { Spinner } from "@/components/ui/spinner";
import { formatLabel } from "@/lib/marketplace/format";
import { isOverdue } from "../attestation-dates";
import { FrameworkFilesPanel } from "./framework-files-panel";
import { RubricPanel } from "./rubric-panel";
import { AnnotationsPanel } from "./annotations-panel";
import { ClarificationsPanel } from "./clarifications-panel";
import { ReportPanel } from "./report-panel";
import { ReviewBriefCard } from "./review-brief-card";
import { DisputeNotice } from "./dispute-notice";
import { StartReviewCard } from "./start-review-card";
import { WorkspaceHeader } from "./workspace-header";

// Statuses where a missed completion deadline still matters: past these the
// work is done or out of the org's hands, so no overdue tone.
const ACTIVE_REVIEW_STATUSES = [
  "accepted",
  "in_review",
  "revision_requested",
];

type AttestationWorkspaceProps = {
  orgId: string;
  attestationId: string;
};

/**
 * Render the attestor-side review workspace for one attestation.
 *
 * @param props - Organization and attestation ids from the route.
 */
export function AttestationWorkspace({ orgId, attestationId }: AttestationWorkspaceProps) {
  const router = useRouter();
  const [attestation, setAttestation] = useState<AttestationRequestResponse | null>(null);
  const [queueItem, setQueueItem] = useState<OrgAttestationItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    try {
      const [res, queueRes] = await Promise.all([
        getAttestation({
          path: { attestation_id: attestationId },
          headers: getAccessTokenHeaders(),
        }),
        listOrgAttestations({
          path: { org_id: orgId },
          headers: getAccessTokenHeaders(),
        }),
      ]);

      if (res.error) throw new Error(describeGeneratedError(res.error));
      if (queueRes.error) throw new Error(describeGeneratedError(queueRes.error));

      const foundQueueItem = queueRes.data.attestations.find(
        (item: OrgAttestationItem) => item.id === attestationId,
      );

      setAttestation(res.data);
      setQueueItem(foundQueueItem || null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load attestation.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attestationId, orgId]);

  if (loading) {
    return <div className="p-8 flex justify-center"><Spinner className="h-8 w-8 text-accent" /></div>;
  }

  if (error || !attestation) {
    return (
      <div className="p-8 flex items-center justify-center gap-2 text-error">
        <ExclamationTriangleIcon className="h-5 w-5" />
        {error || "Attestation not found."}
      </div>
    );
  }

  // Write access is decided server-side: the queue item is flagged when the
  // caller is the assigned reviewing member.
  const canWrite = Boolean(queueItem?.assigned_to_me);
  // The review is "started" once it moves past the freshly-accepted state.
  const isStarted = attestation.status !== "accepted";
  // Scores, annotations and questions are accepted by the server only while
  // the review is in progress; afterwards the workspace is a read-only record.
  const reviewInProgress = attestation.status === "in_review";
  const canEditReview = canWrite && reviewInProgress;
  const frameworkLabel =
    queueItem?.target_title ??
    attestation.target_title ??
    formatLabel(attestation.target_type);
  const reviewerLabel = queueItem?.reviewing_member_name ?? "Unassigned";
  const dueAt = attestation.completion_due_at ?? queueItem?.completion_due_at ?? null;
  const overdue =
    ACTIVE_REVIEW_STATUSES.includes(attestation.status) && isOverdue(dueAt);

  return (
    <div className="space-y-6">
      <button
        className="inline-flex min-h-12 items-center gap-2 text-sm font-semibold text-foreground-muted outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent"
        onClick={() => router.push(`/dashboard/organizations/${orgId}/attestor/queue`)}
        type="button"
      >
        <ArrowLeftIcon className="h-4 w-4" /> Back to queue
      </button>

      <WorkspaceHeader
        actionError={actionError}
        actionSuccess={actionSuccess}
        attestation={attestation}
        canWrite={canWrite}
        dueAt={dueAt}
        overdue={overdue}
        reviewerLabel={reviewerLabel}
        title={frameworkLabel}
      />

      <DisputeNotice
        dispute={attestation.dispute}
        dueAt={dueAt}
        status={attestation.status}
      />

      <ReviewBriefCard brief={attestation.brief} />

      {canWrite && !isStarted && (
        <StartReviewCard
          attestationId={attestationId}
          onError={setActionError}
          onStarted={async () => {
            setActionError(null);
            setActionSuccess("Review started.");
            await load();
          }}
        />
      )}

      {isStarted && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Document order follows the work, so a phone reads files ->
              scoring -> annotations -> questions -> report; the report is
              written last because it draws on the scores. On desktop the
              questions and report sit in the right-hand column. */}
          <div className="space-y-6 lg:col-span-2 lg:col-start-1 lg:row-start-1">
            <FrameworkFilesPanel attestationId={attestationId} />
            <RubricPanel
              attestationId={attestationId}
              reviewType={attestation.review_type || ""}
              canWrite={canEditReview}
            />
            <AnnotationsPanel attestationId={attestationId} canWrite={canEditReview} />
          </div>
          <div className="space-y-6 lg:col-start-3 lg:row-start-1">
            <ClarificationsPanel
              attestationId={attestationId}
              canWrite={canEditReview}
              lockedReason={
                canWrite && !reviewInProgress
                  ? "Questions can only be sent while the review is in progress."
                  : undefined
              }
            />
            <ReportPanel
              attestationId={attestationId}
              canWrite={canWrite}
              orgId={orgId}
              status={attestation.status}
            />
          </div>
        </div>
      )}
    </div>
  );
}
