/**
 * Terminal-state cards for an Attestation request: an open or decided dispute,
 * and the two ways a request can end without the fee reaching the attestor.
 *
 * Release and refund used to be written as the same `closed` status, so the
 * requestor could not tell a completed review from a refunded one. These cards
 * state which happened and, for a dispute, where it stands.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import { StatusPill } from "@/components/ui/status-pill";
import { describeDisputeCategory } from "@/components/modules/attestation/attestation-status";
import { formatAttestationDate } from "@/components/modules/attestation/requestor-next-step";
import type { AttestationDisputeSummary } from "@/lib/generated/types.gen";
import { formatLabel } from "@/lib/marketplace/format";

/**
 * Render the dispute raised against one Attestation.
 *
 * @param props - The dispute summary returned to the two parties.
 */
export function AttestationDisputeCard({
  dispute,
}: {
  dispute: AttestationDisputeSummary;
}) {
  const decisionDue = formatAttestationDate(dispute.resolution_due_at);
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Dispute
        </h2>
        <StatusPill status={dispute.status} />
      </div>
      <dl className="mt-4 grid gap-4">
        <div>
          <dt className="text-sm font-semibold text-foreground">Category</dt>
          <dd className="mt-1 text-sm text-foreground-muted">
            {describeDisputeCategory(dispute.category)}
          </dd>
        </div>
        <div>
          <dt className="text-sm font-semibold text-foreground">Your reason</dt>
          <dd className="mt-1 text-sm leading-6 text-foreground-muted">
            {dispute.reason}
          </dd>
        </div>
        {dispute.outcome ? (
          <div>
            <dt className="text-sm font-semibold text-foreground">Outcome</dt>
            <dd className="mt-1 text-sm text-foreground-muted">
              {formatLabel(dispute.outcome)}
            </dd>
          </div>
        ) : null}
        {dispute.resolution_notes ? (
          <div>
            <dt className="text-sm font-semibold text-foreground">
              Trust team notes
            </dt>
            <dd className="mt-1 text-sm leading-6 text-foreground-muted">
              {dispute.resolution_notes}
            </dd>
          </div>
        ) : null}
      </dl>
      {!dispute.outcome && decisionDue ? (
        <p className="mt-4 text-sm font-semibold text-warning">
          Decision due {decisionDue}
        </p>
      ) : null}
    </div>
  );
}

/** Copy for each way a request can end without paying the attestor. */
const SETTLEMENT_COPY: Record<string, { title: string; body: string }> = {
  refunded: {
    title: "Refunded",
    body: "The fee was refunded to your original payment method.",
  },
  cancelled: {
    title: "Withdrawn",
    body: "You withdrew this request. Any fee you paid has been refunded.",
  },
};

/**
 * Render the closing note for a refunded or withdrawn request.
 *
 * @param props - The terminal status of the request.
 * @returns The card, or null for a status that did not end this way.
 */
export function AttestationSettlementCard({ status }: { status: string }) {
  const copy = SETTLEMENT_COPY[status];
  if (!copy) {
    return null;
  }
  return (
    <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <h2 className="font-heading text-xl font-bold text-foreground">
        {copy.title}
      </h2>
      <p className="mt-1 text-sm leading-6 text-foreground-muted">
        {copy.body}
      </p>
    </div>
  );
}
