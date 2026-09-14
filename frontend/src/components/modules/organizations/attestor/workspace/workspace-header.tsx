/**
 * Header card for the attestor's review workspace.
 *
 * Answers the three questions a reviewer opens the page with: what is this,
 * what state is it in, and when is it due — plus the dispute window while the
 * report sits with the requestor.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */
import { CheckCircledIcon, ExclamationTriangleIcon } from "@radix-ui/react-icons";

import { StatusPill, attestationStatusKey } from "@/components/ui/status-pill";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

import { formatAttestationDate } from "../attestation-dates";

type WorkspaceHeaderProps = {
  /** The attestation being reviewed. */
  attestation: AttestationRequestResponse;
  /** Display name of what is under review. */
  title: string;
  /** Name of the staffed reviewing member. */
  reviewerLabel: string;
  /** Whether the viewer is the assigned reviewer. */
  canWrite: boolean;
  /** Completion deadline, when one is set. */
  dueAt: string | null;
  /** Whether that deadline has passed on a review still owed work. */
  overdue: boolean;
  /** Failure from the last workspace action. */
  actionError: string | null;
  /** Confirmation from the last workspace action. */
  actionSuccess: string | null;
};

/**
 * Render the workspace header card.
 *
 * @param props - Attestation, display labels, deadline state, action banners.
 */
export function WorkspaceHeader({
  attestation,
  title,
  reviewerLabel,
  canWrite,
  dueAt,
  overdue,
  actionError,
  actionSuccess,
}: WorkspaceHeaderProps) {
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="font-heading text-xl font-bold text-foreground">
            {title}
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            {attestation.review_type
              ? `${formatLabel(attestation.review_type)} review`
              : "Attestation"}
            {" · "}
            {formatLabel(attestation.target_type)}
          </p>
        </div>
        <StatusPill
          status={attestationStatusKey(attestation.status, "attestor")}
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        {dueAt ? (
          <span className={overdue ? "text-error" : "text-foreground-muted"}>
            Due {formatAttestationDate(dueAt)}
            {overdue ? " · Overdue" : ""}
          </span>
        ) : null}
        {attestation.status === "report_submitted" &&
        attestation.dispute_window_ends_at ? (
          <span className="text-foreground-muted">
            Dispute window ends{" "}
            {formatAttestationDate(attestation.dispute_window_ends_at)}
          </span>
        ) : null}
      </div>

      {actionError ? (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-error/50 bg-error/5 p-4 text-sm text-error">
          <ExclamationTriangleIcon className="h-4 w-4" />
          {actionError}
        </div>
      ) : null}
      {actionSuccess ? (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-success/50 bg-success/5 p-4 text-sm text-success">
          <CheckCircledIcon className="h-4 w-4" />
          {actionSuccess}
        </div>
      ) : null}

      <dl className="mt-5 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-xl bg-surface-2 p-4">
          <dt className="text-foreground-muted">Assigned member</dt>
          <dd className="mt-1 font-semibold text-foreground">{reviewerLabel}</dd>
        </div>
        <div className="rounded-xl bg-surface-2 p-4">
          <dt className="text-foreground-muted">Your access</dt>
          <dd className="mt-1 font-semibold text-foreground">
            {canWrite ? "Write" : "Read-only"}
          </dd>
        </div>
      </dl>
    </div>
  );
}
