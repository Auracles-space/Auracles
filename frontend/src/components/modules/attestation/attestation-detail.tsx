"use client";

/**
 * Requestor-facing detail view for a single Attestation request.
 *
 * Shows the full submitted brief, the request lifecycle status, the attestor's
 * report when one has been submitted, and the accept / dispute actions that are
 * open within the dispute window. Read-only for every field except those two
 * decisions.
 */
import { useEffect, useState } from "react";

import {
  configureBrowserClient,
  describeGeneratedError,
  getAccessTokenHeaders,
} from "@/lib/auth/form-client";
import {
  acceptAttestationReport,
  createAttestationDispute,
  getAttestation,
  getAttestationFeePayment,
} from "@/lib/generated/sdk.gen";
import type { AttestationRequestResponse } from "@/lib/generated/types.gen";
import { TableSkeleton } from "@/components/ui/skeletons/table-skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  ErrorMessage,
  StatusTag,
} from "@/components/modules/attestation/attestation-status";
import { AttestationFundingPanel } from "@/components/modules/attestation/attestation-funding-panel";
import { RequestorClarificationsPanel } from "@/components/modules/attestation/requestor-clarifications-panel";

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
  const [disputeReason, setDisputeReason] = useState("");
  const [acting, setActing] = useState(false);
  const [clientSecret, setClientSecret] = useState<string | null>(null);

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

  /** Fetch the PaymentIntent secret to resume an unpaid fee, then show Stripe. */
  async function handleStartPayment() {
    setError(null);
    setActing(true);
    try {
      configureBrowserClient();
      const result = await getAttestationFeePayment({
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setClientSecret(result.data.client_secret);
    } finally {
      setActing(false);
    }
  }

  /** Accept the submitted report and release escrow to the attestor. */
  async function handleAccept() {
    setError(null);
    setActing(true);
    try {
      configureBrowserClient();
      const result = await acceptAttestationReport({
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok || !result.data) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setAttestation(result.data);
    } finally {
      setActing(false);
    }
  }

  /** Raise a dispute against the submitted report. */
  async function handleDispute() {
    setError(null);
    setActing(true);
    try {
      configureBrowserClient();
      const result = await createAttestationDispute({
        body: { reason: disputeReason, category: "scope_error" },
        headers: getAccessTokenHeaders(),
        path: { attestation_id: attestationId },
      });
      if (!result.response.ok) {
        setError(describeGeneratedError(result.error));
        return;
      }
      setDisputeReason("");
      await load();
    } finally {
      setActing(false);
    }
  }

  if (loading) {
    return <TableSkeleton />;
  }

  if (!attestation) {
    return <ErrorMessage message={error ?? "Attestation not found."} />;
  }

  const reportReady = attestation.status === "report_submitted";
  const hasReport = Boolean(attestation.summary || attestation.scope);
  const awaitingFee = attestation.status === "pending_fee";

  return (
    <section className="grid gap-6">
      <ErrorMessage message={error} />

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.05em] text-accent">
              {attestation.target_type} attestation
            </p>
            <h1 className="mt-1 font-heading text-2xl font-bold text-foreground">
              {attestation.review_type
                ? `${attestation.review_type} review`
                : "Attestation request"}
            </h1>
            <p className="mt-1 text-sm text-foreground-muted">
              Fee {attestation.currency} {attestation.fee_amount}
            </p>
          </div>
          <StatusTag value={attestation.status} />
        </div>
      </div>

      {awaitingFee &&
        (clientSecret ? (
          <AttestationFundingPanel
            attestationId={attestationId}
            clientSecret={clientSecret}
            onCancel={() => setClientSecret(null)}
            onPaid={() => {
              setClientSecret(null);
              void load();
            }}
          />
        ) : (
          <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
            <h2 className="font-heading text-xl font-bold text-foreground">
              Pay attestation fee
            </h2>
            <p className="mt-1 text-sm text-foreground-muted">
              This request is waiting for its fee. Pay it to send the request to
              matching attestor organizations.
            </p>
            <button
              className="mt-4 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
              disabled={acting}
              onClick={handleStartPayment}
              type="button"
            >
              {acting ? "Loading…" : "Pay fee"}
            </button>
          </div>
        ))}

      <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
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

      {hasReport && (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Attestor report
          </h2>
          {attestation.summary && (
            <div className="mt-4">
              <p className="text-sm font-semibold text-foreground">Summary</p>
              <p className="mt-1 text-sm text-foreground-muted">
                {attestation.summary}
              </p>
            </div>
          )}
          {attestation.scope && (
            <div className="mt-4">
              <p className="text-sm font-semibold text-foreground">Scope</p>
              <p className="mt-1 text-sm text-foreground-muted">
                {attestation.scope}
              </p>
            </div>
          )}
        </div>
      )}

      {reportReady && (
        <div className="rounded-2xl border border-border-default bg-surface-1 p-6 shadow-sm">
          <h2 className="font-heading text-xl font-bold text-foreground">
            Decision
          </h2>
          <p className="mt-1 text-sm text-foreground-muted">
            Accept the report to release the fee, or dispute it within the open
            window.
          </p>
          <button
            className="mt-4 min-h-12 rounded-xl bg-foreground px-6 text-sm font-semibold text-background shadow-sm outline-none transition hover:bg-foreground/90 focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-60"
            disabled={acting}
            onClick={handleAccept}
            type="button"
          >
            Accept report
          </button>
          <label className="mt-4 grid gap-2 text-sm font-semibold text-foreground">
            Dispute reason
            <Textarea
              onChange={(event) => setDisputeReason(event.target.value)}
              value={disputeReason}
            />
          </label>
          <button
            className="mt-3 min-h-12 rounded-xl border border-error px-6 text-sm font-semibold text-error outline-none transition hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error disabled:cursor-not-allowed disabled:opacity-60"
            disabled={acting || disputeReason.trim().length === 0}
            onClick={handleDispute}
            type="button"
          >
            Dispute report
          </button>
        </div>
      )}
    </section>
  );
}
