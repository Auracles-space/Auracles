/**
 * Dispute and revision notices for the attestor's review workspace.
 *
 * On `disputed` and `revision_requested` the reviewer previously saw a locked
 * report form and nothing else — not what was challenged, not what an admin
 * asked for, not by when. This card carries that, and renders nothing in every
 * other state.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2
 * (Attestor org).
 */
import type { AttestationDisputeSummary } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

import { formatAttestationDate } from "../attestation-dates";

type DisputeNoticeProps = {
  /** Current attestation status. */
  status: string;
  /** Latest dispute on the attestation, when there is one. */
  dispute?: AttestationDisputeSummary | null;
  /** Completion deadline, re-set by an admin when a revision is requested. */
  dueAt?: string | null;
};

/**
 * Render the dispute or revision card for the current status.
 *
 * @param props - Status, latest dispute, and the current completion deadline.
 */
export function DisputeNotice({ status, dispute, dueAt }: DisputeNoticeProps) {
  if (!dispute) {
    return null;
  }

  if (status === "disputed") {
    return (
      <section className="rounded-2xl border border-error/50 bg-surface-1 p-5 shadow-sm">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-heading text-base font-bold text-error">
            Dispute
          </h3>
          <span className="rounded-badge border border-error/30 bg-error/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.05em] text-error">
            {formatLabel(dispute.category)}
          </span>
        </div>
        <p className="mt-3 text-sm leading-6 text-foreground">
          {dispute.reason}
        </p>
        {dispute.resolution_due_at ? (
          <div className="mt-3 rounded-xl bg-surface-2 p-4 text-sm text-foreground-muted">
            <p className="font-semibold text-foreground">
              Decision due {formatAttestationDate(dispute.resolution_due_at)}
            </p>
            <p className="mt-1">
              An admin is reviewing this dispute. You do not need to do
              anything until they decide.
            </p>
          </div>
        ) : null}
      </section>
    );
  }

  if (status === "revision_requested") {
    return (
      <section className="rounded-2xl border border-warning/50 bg-surface-1 p-5 shadow-sm">
        <h3 className="font-heading text-base font-bold text-warning">
          Revision requested
        </h3>
        <p className="mt-3 text-sm leading-6 text-foreground">
          {dispute.resolution_notes ??
            "An admin upheld the dispute and asked for a revised report."}
        </p>
        {dueAt ? (
          <p className="mt-3 rounded-xl bg-surface-2 p-4 text-sm text-foreground-muted">
            New due date {formatAttestationDate(dueAt)}
          </p>
        ) : null}
      </section>
    );
  }

  return null;
}
