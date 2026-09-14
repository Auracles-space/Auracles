/**
 * One Attestation request as it appears in the requestor's list.
 *
 * The card is a summary, not a workspace: it answers "which framework, who is
 * reviewing it, what happens next, and by when", and sends every decision —
 * accept, dispute, withdraw — to the detail page where the report and the
 * refund copy sit beside the buttons.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import Link from "next/link";

import { StatusPill, attestationStatusKey } from "@/components/ui/status-pill";
import {
  formatAttestationDate,
  requestorNextStep,
} from "@/components/modules/attestation/requestor-next-step";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import { formatMoney } from "@/lib/marketplace/format";

/**
 * Render a single requestor-facing Attestation summary card.
 *
 * @param props - The attestation to summarise.
 */
export function RequestorAttestationCard({
  attestation,
}: {
  attestation: AttestationRequestResponse;
}) {
  const nextStep = requestorNextStep(attestation);
  const dateLabel = formatAttestationDate(nextStep.date);
  const detailHref = `/attestations/${attestation.id}`;

  return (
    <article className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="flex items-center gap-2 font-heading text-lg font-bold text-foreground">
            {attestation.open_clarification ? (
              <span
                aria-label="Question awaiting your answer"
                className="h-2.5 w-2.5 flex-shrink-0 rounded-full bg-error"
                role="img"
              />
            ) : null}
            {attestation.target_title || "Framework"}
          </h3>
          {attestation.attestor_org_name ? (
            <p className="mt-1 text-sm text-foreground-muted">
              Reviewed by {attestation.attestor_org_name}
            </p>
          ) : null}
        </div>
        <StatusPill
          status={attestationStatusKey(attestation.status, "requestor")}
        />
      </div>

      <p className="mt-3 text-sm leading-6 text-foreground">{nextStep.text}</p>
      <p className="mt-2 text-sm text-foreground-muted">
        Fee {formatMoney(attestation.fee_amount, attestation.currency)}
        {dateLabel ? ` · ${dateLabel}` : ""}
      </p>

      {attestation.open_clarification ? (
        <p className="mt-4 inline-flex items-center gap-2 rounded-full border border-error/40 bg-error/5 px-3 py-1.5 text-sm font-semibold text-error">
          The attestor asked a question — open details to answer.
        </p>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {attestation.status === "pending_fee" ? (
          <Link
            className="inline-flex min-h-12 items-center justify-center rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent"
            href={detailHref}
          >
            Pay fee
          </Link>
        ) : null}
        <Link
          className="inline-flex min-h-11 items-center text-sm font-semibold text-accent hover:underline"
          href={detailHref}
        >
          View details
        </Link>
      </div>
    </article>
  );
}
