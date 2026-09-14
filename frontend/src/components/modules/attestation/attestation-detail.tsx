"use client";

/**
 * Requestor-facing detail view for a single Attestation request.
 *
 * Composes the whole lifecycle on one page: where the request has got to, what
 * happens next, the submitted brief, the attestor's report, and whichever
 * action the current status allows — pay, withdraw, accept or dispute, rate
 * and invoice. Every decision lives here rather than on the list, because each
 * one needs the report or the refund copy beside it.
 *
 * Maps to: docs/superpowers/specs/2026-09-14-attestation-request-to-report-design.md §2.
 */
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getAttestation } from "@/lib/generated/sdk.gen";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { StatusPill, attestationStatusKey } from "@/components/ui/status-pill";
import { ErrorMessage } from "@/components/modules/attestation/attestation-status";
import { AttestationDecisionPanel } from "@/components/modules/attestation/attestation-decision-panel";
import { AttestationFeePanel } from "@/components/modules/attestation/attestation-fee-panel";
import {
  AttestationDisputeCard,
  AttestationSettlementCard,
} from "@/components/modules/attestation/attestation-outcome-cards";
import { AttestationProgress } from "@/components/modules/attestation/attestation-progress";
import { AttestationRatingCard } from "@/components/modules/attestation/attestation-rating-card";
import { AttestationWithdrawPanel } from "@/components/modules/attestation/attestation-withdraw-panel";
import { RequestorClarificationsPanel } from "@/components/modules/attestation/requestor-clarifications-panel";
import { ReportRubricPanel } from "@/components/modules/attestation/report-rubric-panel";
import { requestorNextStep } from "@/components/modules/attestation/requestor-next-step";
import { formatLabel, formatMoney } from "@/lib/marketplace/format";

type AttestationDetailProps = {
  /** Attestation id from the route. */
  attestationId: string;
};

/** The five known brief fields, in display order, with human labels. */
const BRIEF_FIELDS: ReadonlyArray<[key: string, label: string]> = [
  ["what_it_does", "What it does"],
  ["use_case", "Use case"],
  ["jurisdiction", "Jurisdiction"],
  ["focus_areas", "Focus areas"],
  ["desired_outcome", "Desired outcome"],
];

/** Statuses where the fee has settled with the attestor. */
const SETTLED_STATUSES = ["released", "closed"];

/**
 * Read a string field from the loosely-typed brief object.
 *
 * @param brief - The attestation brief, or null when none was captured.
 * @param key - Brief field key.
 * @returns The string value, or an empty string when absent.
 */
function briefValue(
  brief: AttestationRequestResponse["brief"],
  key: string,
): string {
  if (!brief || typeof brief !== "object") {
    return "";
  }
  const value = (brief as Record<string, unknown>)[key];
  return typeof value === "string" ? value : "";
}

/**
 * Render the requestor detail view for one Attestation.
 *
 * @param props - The attestation id to load.
 */
export function AttestationDetail({ attestationId }: AttestationDetailProps) {
  const [attestation, setAttestation] =
    useState<AttestationRequestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attestationId]);

  /** Load the attestation for the current viewer. */
  async function load() {
    configureBrowserClient();
    const result = await getAttestation({
      headers: getAccessTokenHeaders(),
      path: { attestation_id: attestationId },
    });
    if (!result.response.ok || !result.data) {
      setError(describeGeneratedError(result.error));
      setLoading(false);
      return;
    }
    setAttestation(result.data);
    setLoading(false);
  }

  if (loading) {
    return <TableSkeleton />;
  }

  if (!attestation) {
    return <ErrorMessage message={error ?? "Attestation not found."} />;
  }

  const nextStep = requestorNextStep(attestation);
  const hasReport = Boolean(attestation.summary || attestation.scope);

  return (
    <section className="grid gap-6">
      <ErrorMessage message={error} />

      <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              {attestation.review_type
                ? `${formatLabel(attestation.review_type)} review`
                : "Attestation"}
            </p>
            <h1 className="mt-1 font-heading text-2xl font-bold text-foreground">
              {attestation.target_title || "Attestation request"}
            </h1>
            <p className="mt-1 text-sm text-foreground-muted">
              Fee {formatMoney(attestation.fee_amount, attestation.currency)}
            </p>
            {attestation.attestor_org_name && attestation.attestor_org_id ? (
              <p className="mt-1 text-sm text-foreground-muted">
                Reviewed by{" "}
                <Link
                  className="font-semibold text-accent hover:underline"
                  href={`/attestors/${attestation.attestor_org_id}`}
                >
                  {attestation.attestor_org_name}
                </Link>
              </p>
            ) : null}
          </div>
          <StatusPill
            status={attestationStatusKey(attestation.status, "requestor")}
          />
        </div>
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Progress
        </h2>
        <div className="mt-4">
          <AttestationProgress attestation={attestation} />
        </div>
      </div>

      <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Next step
        </h2>
        <p className="mt-1 text-sm leading-6 text-foreground">
          {nextStep.text}
        </p>
        <AttestationWithdrawPanel
          attestationId={attestationId}
          feePaid={Boolean(attestation.escrow_id)}
          onWithdrawn={() => void load()}
          status={attestation.status}
        />
      </div>

      {attestation.status === "pending_fee" ? (
        <AttestationFeePanel
          attestationId={attestationId}
          onPaid={() => void load()}
        />
      ) : null}

      {attestation.status === "report_submitted" ? (
        <AttestationDecisionPanel
          attestationId={attestationId}
          disputeWindowEndsAt={attestation.dispute_window_ends_at}
          minEvidenceLength={attestation.dispute_evidence_min_length}
          onAccepted={setAttestation}
          onDisputed={() => void load()}
        />
      ) : null}

      {SETTLED_STATUSES.includes(attestation.status) ? (
        <AttestationRatingCard attestationId={attestationId} />
      ) : null}

      <AttestationSettlementCard status={attestation.status} />

      {attestation.dispute ? (
        <AttestationDisputeCard dispute={attestation.dispute} />
      ) : null}

      <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
        <h2 className="font-heading text-xl font-bold text-foreground">
          Review brief
        </h2>
        <dl className="mt-4 grid gap-4">
          {BRIEF_FIELDS.map(([key, label]) => (
            <div key={key}>
              <dt className="text-sm font-semibold text-foreground">{label}</dt>
              <dd className="mt-1 text-sm text-foreground-muted">
                {briefValue(attestation.brief, key) || "—"}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <RequestorClarificationsPanel attestationId={attestationId} />

      {hasReport ? (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-5 shadow-sm">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Attestor report
          </h2>
          {attestation.summary ? (
            <div className="mt-4">
              <p className="text-sm font-semibold text-foreground">Summary</p>
              <p className="mt-1 text-sm leading-6 text-foreground-muted">
                {attestation.summary}
              </p>
            </div>
          ) : null}
          {attestation.scope ? (
            <div className="mt-4">
              <p className="text-sm font-semibold text-foreground">Scope</p>
              <p className="mt-1 text-sm leading-6 text-foreground-muted">
                {attestation.scope}
              </p>
            </div>
          ) : null}
          <ReportRubricPanel attestationId={attestationId} />
        </div>
      ) : null}
    </section>
  );
}
