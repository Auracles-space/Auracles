"use client";

/**
 * Admin detail modal for one attestation.
 *
 * Fetches the attestation plus its offer history and shows the current status,
 * key timestamps, which org each offer went to (or was accepted by), and why
 * an org declined — the decline reason is admin-only and is the main signal
 * for why a request is still unmatched. Read only: actioning a request happens
 * from the queue rows. Portal overlay, closes on Escape or backdrop click.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import { getAdminAttestationDetail } from "@/lib/generated/sdk.gen";
import { formatLabel } from "@/lib/marketplace/format";
import { ReportEvidenceFiles } from "@/components/modules/attestation/report-evidence-files";
import type {
  AdminAttestationDetailResponse,
  AdminAttestationReport,
} from "@/lib/generated/types.gen";
import { StatusPill, attestationStatusKey } from "@/components/ui/status-pill";

type AttestationDetailModalProps = {
  /** Attestation to show detail for. */
  attestationId: string;
  /** Close the modal. */
  onClose: () => void;
};

/** Format an ISO timestamp for display, or a dash when absent. */
function formatWhen(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "—";
}

/**
 * Render the read-only admin detail modal for one attestation.
 *
 * @param props - The attestation id and close callback.
 */
export function AttestationDetailModal({
  attestationId,
  onClose,
}: AttestationDetailModalProps) {
  const [detail, setDetail] = useState<AdminAttestationDetailResponse | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      configureBrowserClient();
      const result = await getAdminAttestationDetail({
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setDetail(result.data);
    }
    void load();
  }, [attestationId]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (typeof document === "undefined") {
    return null;
  }

  const attestation = detail?.attestation;

  return createPortal(
    <div
      aria-modal="true"
      className="fixed inset-0 z-50 grid place-items-end bg-black/40 p-0 sm:place-items-center sm:p-4"
      onClick={onClose}
      role="dialog"
    >
      <div
        className="max-h-[85vh] w-full overflow-y-auto rounded-t-2xl border border-border-default bg-surface-1 p-6 shadow-xl sm:max-w-2xl sm:rounded-2xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Attestation detail
          </h2>
          <button
            className="rounded-lg px-2 text-sm font-semibold text-foreground-muted hover:text-foreground"
            onClick={onClose}
            type="button"
          >
            Close
          </button>
        </div>

        {error ? <p className="mt-4 text-sm text-error">{error}</p> : null}
        {!attestation && !error ? (
          <p className="mt-4 text-sm text-foreground-muted">Loading…</p>
        ) : null}

        {attestation ? (
          <div className="mt-4 grid gap-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                {attestation.target_title ? (
                  <p className="font-heading text-base font-bold text-foreground">
                    {attestation.target_title}
                  </p>
                ) : null}
                <p className="font-heading text-sm font-semibold text-foreground">
                  {attestation.review_type
                    ? `${attestation.review_type} review`
                    : "Attestation request"}
                  {attestation.attestor_org_name
                    ? ` · ${attestation.attestor_org_name}`
                    : ""}
                </p>
                <p className="mt-1 text-xs text-foreground-muted">
                  {attestation.id} · {attestation.currency}{" "}
                  {attestation.fee_amount}
                </p>
              </div>
              <StatusPill
                status={attestationStatusKey(attestation.status, "admin")}
              />
            </div>

            <dl className="grid gap-2 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Created</dt>
                <dd className="text-foreground">
                  {formatWhen(attestation.created_at)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Accepted</dt>
                <dd className="text-foreground">
                  {formatWhen(attestation.accepted_at)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Completion due</dt>
                <dd className="text-foreground">
                  {formatWhen(attestation.completion_due_at)}
                </dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-foreground-muted">Closed</dt>
                <dd className="text-foreground">
                  {formatWhen(attestation.closed_at)}
                </dd>
              </div>
            </dl>

            <AttestationBriefSection brief={attestation.brief} />
            {detail?.report ? (
              <>
                <AttestationReportSection report={detail.report} />
                <ReportEvidenceFiles attestationId={attestation.id} />
              </>
            ) : null}

            <div>
              <p className="text-sm font-semibold text-foreground">
                Offers ({detail?.offers.length ?? 0})
              </p>
              <div className="mt-2 grid gap-2">
                {detail && detail.offers.length > 0 ? (
                  detail.offers.map((offer, index) => (
                    <div
                      className="rounded-xl border border-border-default bg-surface-1 p-3 text-sm"
                      key={`${offer.org_id ?? "org"}-${index}`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-semibold text-foreground">
                          {offer.org_name ?? "Unknown org"}
                        </span>
                        <StatusPill status={offer.status} />
                      </div>
                      <p className="mt-1 text-xs text-foreground-muted">
                        Offered {formatWhen(offer.offered_at)}
                        {offer.responded_at
                          ? ` · Responded ${formatWhen(offer.responded_at)}`
                          : ` · Expires ${formatWhen(offer.expires_at)}`}
                      </p>
                      {offer.decline_reason ? (
                        // Admin-only: the reason an org gave for declining is
                        // never shown to the requestor.
                        <p className="mt-2 rounded-xl bg-surface-2 p-3 text-xs text-foreground">
                          Reason: {offer.decline_reason}
                        </p>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <p className="text-sm text-foreground-muted">
                    No offers have been made yet.
                  </p>
                )}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

/** Human labels for the brief's free-text fields, in reading order. */
const BRIEF_FIELDS: [string, string][] = [
  ["what_it_does", "What it does"],
  ["use_case", "Use case"],
  ["jurisdiction", "Jurisdiction"],
  ["focus_areas", "Focus areas"],
  ["desired_outcome", "Desired outcome"],
];

/**
 * The requestor's brief: what they asked the attestor to judge.
 *
 * @param brief - Raw brief object from the attestation, if any.
 */
function AttestationBriefSection({
  brief,
}: {
  brief?: Record<string, unknown> | null;
}) {
  const entries = BRIEF_FIELDS.map(([key, label]) => [label, brief?.[key]] as const).filter(
    (entry): entry is readonly [string, string] =>
      typeof entry[1] === "string" && entry[1].trim() !== "",
  );
  if (entries.length === 0) return null;
  return (
    <section className="grid gap-2">
      <h3 className="text-sm font-semibold text-foreground">Brief</h3>
      <dl className="grid gap-2 text-sm">
        {entries.map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs font-semibold text-foreground-muted">{label}</dt>
            <dd className="whitespace-pre-wrap break-words text-foreground">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/**
 * The submitted report with everything behind it: outcome, summary, scope,
 * conditions, the rubric scorecard, the reviewer's annotations, and the
 * clarification thread. This is what an admin reads before ruling on a dispute.
 *
 * @param report - The report block from the admin detail endpoint.
 */
function AttestationReportSection({ report }: { report: AdminAttestationReport }) {
  return (
    <section className="grid gap-4 rounded-xl border border-border-default bg-surface-2 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">Report</h3>
        {report.outcome ? (
          <span className="text-xs font-semibold uppercase tracking-[0.05em] text-foreground-muted">
            {formatLabel(report.outcome)}
          </span>
        ) : null}
      </div>
      {[
        ["Summary", report.summary],
        ["Scope", report.scope],
        ["Conditions", report.conditions],
      ].map(([label, value]) =>
        value ? (
          <div key={label}>
            <p className="text-xs font-semibold text-foreground-muted">{label}</p>
            <p className="mt-1 whitespace-pre-wrap break-words text-sm text-foreground">{value}</p>
          </div>
        ) : null,
      )}

      {report.rubric.length > 0 ? (
        <div>
          <p className="text-xs font-semibold text-foreground-muted">Rubric</p>
          <ul className="mt-2 grid gap-2">
            {report.rubric.map((item) => (
              <li className="rounded-lg bg-surface-1 p-3 text-sm" key={item.dimension_key}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-foreground">{item.label}</span>
                  <span className="text-foreground-muted">
                    {item.score !== null && item.score !== undefined ? `${item.score} / 5` : "Not scored"}
                  </span>
                </div>
                {item.comment ? (
                  <p className="mt-1 whitespace-pre-wrap break-words text-foreground">{item.comment}</p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.annotations.length > 0 ? (
        <div>
          <p className="text-xs font-semibold text-foreground-muted">Annotations</p>
          <ul className="mt-2 grid gap-2">
            {report.annotations.map((annotation) => (
              <li className="rounded-lg bg-surface-1 p-3 text-sm" key={annotation.id}>
                <p className="font-semibold text-foreground">
                  {formatLabel(annotation.annotation_type)} · {annotation.location_label}
                </p>
                {annotation.quoted_excerpt ? (
                  <p className="mt-1 italic text-foreground-muted">“{annotation.quoted_excerpt}”</p>
                ) : null}
                <p className="mt-1 whitespace-pre-wrap break-words text-foreground">{annotation.comment}</p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.clarifications.length > 0 ? (
        <div>
          <p className="text-xs font-semibold text-foreground-muted">Clarifications</p>
          <ul className="mt-2 grid gap-2">
            {report.clarifications.map((clarification) => (
              <li className="rounded-lg bg-surface-1 p-3 text-sm" key={clarification.id}>
                <p className="font-semibold text-foreground">{clarification.question}</p>
                <p className="mt-1 whitespace-pre-wrap break-words text-foreground">
                  {clarification.response ?? "No answer yet."}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
